import numpy as np
import pytest

from backend.pipeline import classify
from backend.pipeline.estimate import estimate_candidate
from backend.tests.test_estimate import fixture


@pytest.mark.parametrize("kind", ["bpsk", "qpsk", "fm"])
@pytest.mark.parametrize("snr", [20, 10, 0, -5])
def test_coarse_family_acceptance(kind, snr):
    c, d, _ = fixture(kind, snr)
    e = estimate_candidate(c, d)
    out = classify.classify_coarse(c, e)
    if snr >= 0:
        assert out["modulation_family"] == "constant-envelope"
    assert out["envelope_variation"] >= 0
    assert out["modulation_confidence"] == pytest.approx(min(1, abs(out["envelope_variation"]-.3)/.3))
    assert out["modulation_confidence_kind"] == "heuristic, not a calibrated probability"
    assert out["center_frequency_hz"] == e["center_frequency_hz"]


def test_coarse_varying_envelope_and_absolute_correction():
    c, d, _ = fixture("fm", 20, offset=100e6)
    t = np.arange(len(c.iq))/c.sample_rate
    c.iq *= (1+.95*np.sin(2*np.pi*20*t)).astype(np.float32)
    out = classify.classify_coarse(c, estimate_candidate(c, d))
    assert out["modulation_family"] == "varying-envelope"


def test_coarse_unknown_and_short_window():
    c, d, _ = fixture("bpsk", 10)
    d.update(center_frequency_hz=None)
    out = classify.classify_coarse(c, d)
    assert out["modulation_family"] is None
    assert out["modulation_confidence"] is None
    assert "not reliably" in out["modulation_status"]


def test_representative_uses_longest_pulse_not_gap():
    c, d, _ = fixture("pulsed", 10)
    d["pulse_windows"] = [d["pulse_windows"][0], d["pulse_windows"][1]]
    d["pulse_windows"][0]["end_sample"] -= 400
    e = estimate_candidate(c, d)
    segment = classify.corrected_segment(c, e, e["center_frequency_hz"])
    w = d["pulse_windows"][1]
    assert len(segment) == w["end_sample"]-w["start_sample"]-256


@pytest.mark.parametrize("kind", ["bpsk", "qpsk"])
def test_refinement_preserves_direct_estimate_and_absolute_reference(kind):
    c, d, _ = fixture(kind, 10, offset=100e6)
    coarse = classify.classify_coarse(c, estimate_candidate(c, d))
    refined = classify.refine_frequency(c, coarse)
    assert refined["center_frequency_hz"] == coarse["center_frequency_hz"]
    assert refined["center_frequency_refined_hz"] == pytest.approx(100e6+8000, abs=30)
    assert refined["refinement_order"] in (2, 4)


def test_refinement_150khz_bpsk_10db_mean_error():
    from backend.pipeline.ingest import Capture
    from backend.pipeline.detect import analyze_capture
    from backend.pipeline.synth_gen import make_signal
    errors = []
    # Preserve the generator waveform and noise; reinterpret its sample rate
    # at 1 MHz with the carrier set to 7200/48000 cycles/sample = 150 kHz.
    for seed in range(47, 57):
        x, _ = make_signal("bpsk", 10, seed=seed, frequency=7200)
        c = Capture(x, 1e6, {"source_kind": "iq", "filename": "150khz-bpsk",
                            "wav_disambiguation": {"result": "declared_iq"}})
        ds = analyze_capture(c).response["detections"]
        d = next(d for d in ds if d["freq_lower_hz"] < 150000 < d["freq_upper_hz"])
        out = classify.refine_frequency(c, classify.classify_coarse(c, estimate_candidate(c, d)))
        assert out["center_frequency_refined_hz"] is not None
        errors.append(abs(out["center_frequency_refined_hz"]-150000))
    assert np.mean(errors) < 50, errors


def test_refinement_varying_envelope_is_unknown():
    c, d, _ = fixture("bpsk", 10)
    d.update(modulation_family="varying-envelope")
    out = classify.refine_frequency(c, d)
    assert out["center_frequency_refined_hz"] is None
    assert out["refinement_order"] is None


@pytest.mark.parametrize("kind,order", [
    ("bpsk", 2),
    pytest.param("qpsk", 4, marks=pytest.mark.xfail(
        strict=True, reason="Fallback rung 2: QPSK phase rule passes only 2/5 seeds; target retained")),
])
@pytest.mark.parametrize("snr", [20, 10])
def test_exploratory_fine_rule_majority_acceptance(kind, order, snr):
    matches = 0
    rows = []
    for seed in range(47, 52):
        c, d, _ = fixture(kind, snr, seed=seed)
        e = classify.refine_frequency(c, classify.classify_coarse(c, estimate_candidate(c, d)))
        out = classify.classify_fine(c, e)
        rows.append((seed, out["refinement_order"], out["phase_cluster_spread_rad"]))
        matches += (out["refinement_order"] == order
                    and out["phase_cluster_spread_rad"] is not None
                    and out["phase_cluster_spread_rad"] < .8)
    assert matches > len(rows)/2, rows


@pytest.mark.parametrize("snr", [20, 10, 0, -5])
def test_fm_fine_falls_back_to_family(snr):
    c, d, _ = fixture("fm", snr)
    e = classify.refine_frequency(c, classify.classify_coarse(c, estimate_candidate(c, d)))
    out = classify.classify_fine(c, e)
    assert out["fine_modulation_label"] is None
    assert out["fine_modulation_confidence"] is None
    assert out["phase_cluster_spread_rad"] >= .8
    assert out["modulation_family"] == "constant-envelope"


def test_fine_unavailable_refinement_returns_nulls():
    c, d, _ = fixture("bpsk", 10)
    out = classify.classify_fine(c, d)
    assert out["fine_modulation_label"] is None
    assert out["fine_modulation_confidence"] is None
    assert out["phase_cluster_spread_rad"] is None


@pytest.mark.parametrize("kind", ["bpsk", "qpsk", "fm"])
@pytest.mark.parametrize("snr", [20, 10, 5, 0, -5])
def test_end_to_end_fallback_never_publishes_unvalidated_values(kind, snr):
    c, d, _ = fixture(kind, snr)
    # Previously supplied values must not leak through the enriched copy.
    d.update(fine_modulation_label="guessed", symbol_rate_hz=12345)
    out = classify.analyze_candidate(c, d)
    assert out["fine_modulation_label"] is None
    assert out["fine_modulation_confidence"] is None
    assert out["symbol_rate_hz"] is None
    assert "fallback rung 2" in out["symbol_rate_status"]
    assert d["fine_modulation_label"] == "guessed"


def test_end_to_end_audio_and_short_samples_are_unknown():
    c, d, _ = fixture("bpsk", 10)
    c.metadata["source_kind"] = "audio"
    out = classify.analyze_candidate(c, d)
    assert out["modulation_family"] is None
    assert out["center_frequency_refined_hz"] is None
    c.metadata["source_kind"] = "iq"
    d["end_sample"] = d["start_sample"]+1024
    out = classify.analyze_candidate(c, d)
    assert out["modulation_family"] is None
    assert out["center_frequency_refined_hz"] is None
