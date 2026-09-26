"""WP4: the verify estimator wired into analyze_candidate, the API and the large-capture path."""
import numpy as np
import pytest

from backend.pipeline import classify
from backend.pipeline.detect import analyze_capture
from backend.pipeline.ingest import Capture
from backend.pipeline.synth_gen import make_signal
from experiments.readiness.metrics import claims_calibration


def _cap(x, fs, name="t"):
    return Capture(np.asarray(x, np.complex64), float(fs),
                   {"source_kind": "iq", "filename": name, "wav_disambiguation": {"result": "declared_iq"}})


def _primary(c, lo, hi):
    ds = analyze_capture(c)
    return max((d for d in ds.response["detections"] if d["freq_upper_hz"] > lo and d["freq_lower_hz"] < hi),
               key=lambda d: min(d["freq_upper_hz"], hi) - max(d["freq_lower_hz"], lo)), ds


def test_verify_is_the_default_estimator_and_labels_a_shipped_fixture():
    x, _ = make_signal("qpsk", 15, duration=0.5, seed=3, frequency=8000)
    c = _cap(x, 48000)
    d, ds = _primary(c, 7000, 9000)
    out = classify.analyze_candidate(c, d, noise_floor=ds.noise_floor)
    assert out["estimator"] == "verify"
    assert out["modulation_label"] == "QPSK" and out["estimate_tier"] == "labelled"
    assert abs(out["symbol_rate_hz"] - 500) / 500 < 0.05
    assert out["fine_modulation_label"] is None          # legacy labels only under the flag
    for key in ("m_fam", "m_rate", "unexplained", "label_needs_review", "verify_family"):
        assert key in out


def test_legacy_estimator_is_available_under_the_flag_and_marked():
    x, _ = make_signal("bpsk", 15, duration=0.5, seed=3, frequency=8000)
    c = _cap(x, 48000)
    d, ds = _primary(c, 7000, 9000)
    out = classify.analyze_candidate(c, d, noise_floor=ds.noise_floor, estimator="legacy")
    assert out["estimator"] == "legacy"
    assert out["label_provenance"] == "legacy (fixture-validated only)"
    assert out["fine_modulation_label"] == "bpsk"
    with pytest.raises(ValueError):
        classify.analyze_candidate(c, d, estimator="nope")


def test_candidate_window_is_band_isolated_decimated_and_capped():
    from backend.pipeline.verify_estimator import MAX_SAMPLES, candidate_segment
    rng = np.random.default_rng(1)
    n, fs = 200_000, 1e6
    t = np.arange(n)
    sy = rng.choice([-1.0, 1.0], n // 20 + 1)
    x = np.repeat(sy, 20)[:n] * np.exp(2j * np.pi * 0.2 * t) * 3 + \
        (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)
    c = _cap(x, fs)
    d, _ = _primary(c, 150e3, 250e3)
    (seg, fs2), reason = candidate_segment(c, d)
    assert reason is None and len(seg) <= MAX_SAMPLES
    width = d["freq_upper_hz"] - d["freq_lower_hz"]
    assert 3 * width <= fs2 <= 12 * width
    # the other half of the band is gone: the segment is centred on the candidate
    spec = np.abs(np.fft.fft(seg)) ** 2
    f = np.fft.fftfreq(len(seg), 1 / fs2)
    assert abs(np.sum(f * spec) / np.sum(spec)) < 0.05 * fs2


def test_pulsed_and_audio_candidates_abstain_explicitly():
    x, _ = make_signal("pulsed", 14, duration=0.5, seed=4, frequency=5000)
    c = _cap(x, 48000)
    ds = analyze_capture(c).response["detections"]
    out = classify.analyze_candidate(c, ds[0])
    assert out["estimate_tier"] == "abstain" and out["modulation_label"] is None
    assert "pulsed" in out["verify_status"]


def test_no_calibration_claim_appears_beside_a_published_label():
    x, _ = make_signal("qpsk", 15, duration=0.5, seed=3, frequency=8000)
    c = _cap(x, 48000)
    d, ds = _primary(c, 7000, 9000)
    out = classify.analyze_candidate(c, d, noise_floor=ds.noise_floor)
    assert out["modulation_label"] is not None and not claims_calibration(out)
