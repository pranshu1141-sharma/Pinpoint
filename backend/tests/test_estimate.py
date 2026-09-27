from copy import deepcopy

import numpy as np
import pytest

from backend.pipeline import estimate
from backend.pipeline.detect import analyze_capture, estimate_noise_floor
from backend.pipeline.ingest import Capture
from backend.pipeline.synth_gen import FS, make_signal


def fixture(kind, snr, seed=47, frequency=8000, offset=None):
    x, truth = make_signal(kind, snr, seed=seed, frequency=frequency)
    c = Capture(x, FS, {"source_kind": "iq", "filename": "synthetic",
                       "center_frequency_hz": offset,
                       "wav_disambiguation": {"result": "declared_iq"}})
    ds = analyze_capture(c).response["detections"]
    d = next(d for d in ds if d["freq_lower_hz"] < frequency < d["freq_upper_hz"])
    return c, d, truth[0]


@pytest.mark.parametrize("kind", ["bpsk", "qpsk", "fm"])
@pytest.mark.parametrize("snr", [20, 10, 0, -5])
def test_estimate_continuous_acceptance(kind, snr):
    c, d, truth = fixture(kind, snr)
    before = deepcopy(d)
    e = estimate.estimate_candidate(c, d)
    assert d == before
    assert e["center_frequency_hz"] == pytest.approx(8000, rel=.02)
    assert e["snr_db"] == pytest.approx(truth["snr_db"], abs=3)
    assert 0 < e["bandwidth_3db_hz"] <= e["bandwidth_99pct_hz"]
    assert e["estimate_status"] == "estimated"
    # Generator bounds describe nominal detection extent, not theoretical FWHM.
    if truth.get("bandwidth_3db_hz") is not None:
        assert e["bandwidth_3db_hz"] == pytest.approx(truth["bandwidth_3db_hz"], rel=.15)


def test_absolute_frequency_and_power_scale():
    c, d, _ = fixture("qpsk", 10, frequency=-8000, offset=100e6)
    a = estimate.estimate_candidate(c, d)
    c.iq *= .01
    b = estimate.estimate_candidate(c, d)
    assert a["center_frequency_hz"] == pytest.approx(100e6-8000, abs=160)
    for key in ("center_frequency_hz", "bandwidth_3db_hz", "bandwidth_99pct_hz", "snr_db"):
        assert a[key] == pytest.approx(b[key], abs=.01)


def test_pulses_average_all_windows_without_gap_power():
    c, d, _ = fixture("pulsed", 10)
    e = estimate.estimate_candidate(c, d)
    assert e["snr_db"] == pytest.approx(10, abs=3)
    windows = estimate.occupied_windows(c, d)
    f, p = estimate.occupied_psd(c, windows)
    expected = np.mean([estimate_noise_floor(c.iq[a:b], FS)[1] for a, b in windows], axis=0)
    np.testing.assert_allclose(p, expected, rtol=1e-6)
    assert len(f) == 1024


def test_overlapping_pulses_form_union_and_exclude_end():
    c, d, _ = fixture("pulsed", 10)
    d.update(start_sample=1000, end_sample=5000, pulse_windows=[
        {"start_sample": 1000, "end_sample": 3000},
        {"start_sample": 2000, "end_sample": 5000}])
    assert estimate.occupied_windows(c, d) == [(1000, 5000)]


def test_bandwidths_against_known_spectra():
    f = np.arange(-5000., 5001., 10.)
    p = np.exp(-.5*(f/300)**2)
    half, occupied = estimate.measure_bandwidths(f, p)
    assert half == pytest.approx(2*np.sqrt(2*np.log(2))*300, rel=.15)
    assert occupied == pytest.approx(2*2.575829*300, abs=20)
    # A detached weak lobe must not broaden the connected half-power lobe.
    p += .2*np.exp(-.5*((f-3000)/150)**2)
    half2, occupied2 = estimate.measure_bandwidths(f, p)
    assert half2 == pytest.approx(half)
    assert occupied2 > occupied


def test_short_and_audio_candidates_are_explicit_unknowns():
    c, d, _ = fixture("bpsk", 10)
    d["end_sample"] = d["start_sample"]+100
    e = estimate.estimate_candidate(c, d)
    assert e["center_frequency_hz"] is None
    assert "insufficient" in e["estimate_status"]
    c.metadata["source_kind"] = "audio"
    e = estimate.estimate_candidate(c, d)
    assert e["snr_db"] is None
    assert "IQ" in e["estimate_status"]


def test_zero_power_has_no_fabricated_numbers():
    c, d, _ = fixture("bpsk", 10)
    c.iq[:] = 0
    e = estimate.estimate_candidate(c, d)
    assert all(e[k] is None for k in ("center_frequency_hz", "snr_db", "bandwidth_3db_hz", "bandwidth_99pct_hz"))


def test_invalid_windows_are_rejected():
    c, d, _ = fixture("bpsk", 10)
    d["end_sample"] = len(c.iq)+1
    with pytest.raises(ValueError, match="sample"):
        estimate.estimate_candidate(c, d)


def test_generator_records_symbol_rate_in_truth_files(tmp_path):
    import json
    from backend.pipeline.synth_gen import save_capture
    for kind in ("bpsk", "qpsk", "fm"):
        x, truth = make_signal(kind, 5)
        save_capture(tmp_path/kind, x, truth)
        saved = json.loads((tmp_path/f"{kind}.truth.json").read_text())
        assert saved["signals"][0]["symbol_rate_hz"] == (500 if kind != "fm" else None)


# ---- WP5: bandwidth collapse and SNR bias on wideband / short captures

def _g1_capture(label, rate, snr, seed, shaping="NRZ"):
    from experiments.estimate_spike.signals import generate
    x, t = generate(np.random.default_rng(seed), "PSK", 1e6, 4096, snr_db=snr, rate=rate, label=label,
                    shaping=shaping)
    c = Capture(np.asarray(x, np.complex64), 1e6, {"source_kind": "iq", "filename": "g1",
                                                   "wav_disambiguation": {"result": "declared_iq"}})
    r = analyze_capture(c)
    d = max(r.response["detections"], key=lambda d: d["freq_upper_hz"] - d["freq_lower_hz"])
    return c, d, r.noise_floor


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_wideband_qpsk_on_a_short_capture_keeps_bandwidth_and_snr(seed):
    # the plan's example: 12 dB, 137 kSym/s QPSK reported a 3.2 kHz bandwidth and 6.7 dB SNR
    from backend.pipeline.classify import analyze_candidate
    c, d, floor = _g1_capture("QPSK", 137e3, 12.0, seed)
    e = estimate.estimate_candidate(c, d, noise_floor=floor)
    assert e["bandwidth_3db_hz"] == pytest.approx(0.8859 * 137e3, rel=0.25)
    # sinc^2 sidelobes fill the band, so no spectral region holds noise alone; the product
    # measures SNR from the published model's residual instead
    out = analyze_candidate(c, d, noise_floor=floor)
    assert out["estimate_tier"] == "labelled" and out["snr_method"].startswith("model residual")
    assert out["snr_db"] == pytest.approx(12.0, abs=2.0)


@pytest.mark.parametrize("sps,carrier,seed", [(96, 8000, 1), (24, 3000, 2), (48, 15000, 3)])
def test_shipped_family_bandwidth_within_25_percent(sps, carrier, seed):
    from experiments.readiness.generators import pulse_bw3
    from experiments.readiness.synth_wide import make_signal as wide
    x, _ = wide("qpsk", 20, carrier, sps, seed, 24000)
    c = Capture(np.asarray(x, np.complex64), FS, {"source_kind": "iq", "filename": "g2",
                                                  "wav_disambiguation": {"result": "declared_iq"}})
    r = analyze_capture(c)
    d = next(d for d in r.response["detections"] if d["freq_lower_hz"] < carrier < d["freq_upper_hz"])
    e = estimate.estimate_candidate(c, d, noise_floor=r.noise_floor)
    assert e["bandwidth_3db_hz"] == pytest.approx(pulse_bw3(sps), rel=0.25)


@pytest.mark.parametrize("label,rate,seed", [("8PSK", 114e3, 4), ("QPSK", 94e3, 5), ("8PSK", 55e3, 6)])
def test_published_linear_label_refines_the_centre_frequency(label, rate, seed):
    from backend.pipeline.classify import analyze_candidate
    from experiments.estimate_spike.signals import generate
    rng = np.random.default_rng(seed)
    state = rng.bit_generator.state
    x, _ = generate(rng, "PSK", 1e6, 4096, snr_db=10.0, rate=rate, label=label, shaping="NRZ")
    rng2 = np.random.default_rng()
    rng2.bit_generator.state = state
    rng2.standard_normal(4096), rng2.standard_normal(4096)
    foff = rng2.uniform(-1e5, 1e5)                      # the generator's carrier draw
    c = Capture(np.asarray(x, np.complex64), 1e6, {"source_kind": "iq", "filename": "g1",
                                                   "wav_disambiguation": {"result": "declared_iq"}})
    r = analyze_capture(c)
    d = max(r.response["detections"], key=lambda d: d["freq_upper_hz"] - d["freq_lower_hz"])
    out = analyze_candidate(c, d, noise_floor=r.noise_floor)
    assert out["estimate_tier"] == "labelled"
    assert abs(out["center_frequency_refined_hz"] - foff) <= 0.1 * 0.8859 * rate


@pytest.mark.parametrize("cid", ["G1-7-0021", "G1-7-0031", "G1-7-0061"])
def test_verify_mode_does_not_publish_the_legacy_refinement_when_it_is_wrong(cid):
    # the legacy M-th power heuristic refined these to 12-26 kHz off; verify's own carrier is used
    from backend.pipeline.classify import analyze_candidate
    from experiments.readiness import generators, systems
    cap = next(c for c in generators.g1_captures(int(cid.split("-")[-1]) + 1) if c.id == cid)
    pc, res, _, prim, _ = systems.detect(cap)
    out = analyze_candidate(pc, prim, noise_floor=res.noise_floor)
    assert out["estimate_tier"] == "labelled"
    assert abs(out["center_frequency_refined_hz"] - cap.truth["fc"]) <= 0.1 * cap.truth["bw3"]
    assert "verify" in out["refinement_status"]


def test_snr_is_not_inflated_by_a_receiver_stopband():
    # 25% of the band in an anti-alias stopband pulled the percentile floor far below the in-band noise
    from scipy import signal
    from experiments.readiness.synth_wide import make_signal as wide
    rng = np.random.default_rng(0)
    n = 48000
    _, clean = wide("qpsk", 200, 3000, 48, 1, n)
    w = signal.lfilter(signal.firwin(255, 0.75), 1, (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2))
    w = w / np.sqrt(np.mean(np.abs(w) ** 2))
    x = clean / np.sqrt(np.mean(np.abs(clean) ** 2)) * np.sqrt(10) + w
    c = Capture(np.asarray(x, np.complex64), FS, {"source_kind": "iq", "filename": "t",
                                                 "wav_disambiguation": {"result": "declared_iq"}})
    r = analyze_capture(c)
    d = next(d for d in r.response["detections"] if d["freq_lower_hz"] < 3000 < d["freq_upper_hz"])
    e = estimate.estimate_candidate(c, d, noise_floor=r.noise_floor)
    assert e["snr_db"] == pytest.approx(10.0, abs=3.0)
