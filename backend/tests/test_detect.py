import numpy as np
import pytest
from backend.pipeline.synth_gen import make_signal, FS, generate_suite
from backend.pipeline.ingest import Capture, load_capture, AmbiguousCapture
from backend.pipeline.detect import analyze_capture


def capture(x):
    return Capture(x, FS, {"source_kind": "iq", "filename": "synthetic", "wav_disambiguation": {"result": "declared_iq"}})


@pytest.mark.parametrize("kind", ["bpsk", "qpsk", "fm"])
@pytest.mark.parametrize("snr", [20, 10, 0, -5])
def test_recall_frequency_and_time(kind, snr):
    x, truth = make_signal(kind, snr)
    ds = analyze_capture(capture(x)).response["detections"]
    matches = [d for d in ds if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"]]
    assert matches, (kind, snr, ds)
    d = matches[0]
    assert abs(d["freq_lower_hz"]-truth[0]["freq_lower_hz"]) < 1400
    assert abs(d["freq_upper_hz"]-truth[0]["freq_upper_hz"]) < 1400
    assert d["start_sample"] < FS*.08
    assert d["end_sample"] > len(x)-FS*.08


def test_pulse_width_and_pri():
    x, _ = make_signal("pulsed", 10)
    ds = analyze_capture(capture(x)).response["detections"]
    d = next(d for d in ds if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"])
    assert d["is_pulsed"]
    assert abs(d["pulse_width_samples"]-2400) < 150
    assert abs(d["pri_samples"]-12000) < 100
    assert len(d["pulse_windows"]) == 8


@pytest.mark.parametrize("seed", range(10))
def test_noise_false_alarms(seed):
    x, _ = make_signal("noise", seed=seed)
    assert analyze_capture(capture(x)).response["detections"] == []


@pytest.mark.parametrize("kind", ["bpsk", "qpsk", "fm", "pulsed"])
def test_evidence_based_confidence_is_a_second_independent_score(kind):
    """confidence_evidence_based (a power coefficient-of-variation shape
    statistic) must never replace or match confidence (threshold-excess +
    occupancy) -- it is deliberately a separate, uncombined evidence channel
    (roadmap item 2)."""
    x, _ = make_signal(kind, 10)
    d = next(d for d in analyze_capture(capture(x)).response["detections"] if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"])
    assert 0 <= d["confidence_evidence_based"] <= .99
    assert d["confidence_evidence_based_kind"] == "heuristic, not a calibrated probability"
    assert d["power_cv_deviation"] >= 0
    assert d["confidence_evidence_based"] != d["confidence"]


def test_evidence_based_confidence_separates_signal_from_pure_noise_regions():
    """Measured directly: every pure-noise region tested (matching typical
    candidate sample sizes) has power_cv_deviation <=0.03; every real
    synthetic signal region tested has >=0.08. This pins that separation."""
    from backend.pipeline.detect import compute_spectrogram, power_cv_deviation
    x, _ = make_signal("noise", 10)
    _, _, power = compute_spectrogram(x, FS, 1024, False)
    rng = np.random.default_rng(1)
    for _ in range(20):
        fa = rng.integers(0, power.shape[0]-30)
        fb = fa+rng.integers(15, 30)
        ta = rng.integers(0, power.shape[1]-300)
        tb = ta+rng.integers(200, 370)
        assert power_cv_deviation(power[fa:fb, ta:tb]) <= .05
    for kind in ("bpsk", "qpsk", "fm", "pulsed"):
        x, _ = make_signal(kind, 10)
        d = next(d for d in analyze_capture(capture(x)).response["detections"] if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"])
        assert d["power_cv_deviation"] >= .05, (kind, d["power_cv_deviation"])


def test_adaptive_tracks_noise_scale_and_debug_agrees():
    x, _ = make_signal("qpsk", 10)
    a = analyze_capture(capture(x)).response
    b = analyze_capture(capture(x*.01)).response
    assert len(a["detections"]) == len(b["detections"])
    assert b["noise_floor_db"] == pytest.approx(a["noise_floor_db"]-40, abs=.01)
    fixed = analyze_capture(capture(x), mode="fixed_debug", fixed_threshold_db=a["threshold_db"]).response
    assert [(d["start_sample"], d["freq_lower_hz"]) for d in fixed["detections"]] == [(d["start_sample"], d["freq_lower_hz"]) for d in a["detections"]]


def test_input_requires_explicit_metadata():
    with pytest.raises(AmbiguousCapture):
        load_capture("x.iq", b"\0"*8192)
    with pytest.raises(ValueError, match="incomplete"):
        load_capture("x.iq", b"\0"*8193, FS, "cf32_le")
    with pytest.raises(ValueError, match="NaN"):
        load_capture("x.iq", np.full(1024, np.nan, dtype="<c8").tobytes(), FS, "cf32_le")


def test_suite_files_roundtrip(tmp_path):
    generate_suite(tmp_path)
    # 7 continuous kinds (bpsk/qpsk/8psk/ask/qam/fsk/fm) x 4 SNRs, plus
    # pulsed/noise, plus demo.
    assert len(list(tmp_path.glob("*.sigmf-data"))) == 7*4+2+1
    c = load_capture("demo.sigmf-data", (tmp_path/"demo.sigmf-data").read_bytes(), sigmf_meta=(tmp_path/"demo.sigmf-meta").read_bytes())
    result = analyze_capture(c).response
    assert len(result["detections"]) == 3


@pytest.mark.parametrize("duration", [.02, .04, .08, .3])
def test_single_short_burst_is_localized_with_no_invented_pri(duration):
    x, _ = make_signal("noise")
    start = FS//2
    width = int(FS*duration)
    x[start:start+width] += 4*np.exp(2j*np.pi*8000*np.arange(width)/FS)
    ds = analyze_capture(capture(x)).response["detections"]
    d = next(d for d in ds if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"])
    assert d["is_pulsed"]
    assert d["pri_samples"] is None
    assert len(d["pulse_windows"]) == 1
    assert abs(d["start_sample"]-start) < 150
    assert abs(d["pulse_width_samples"]-width) < 150


@pytest.mark.parametrize("kind", ["bpsk", "qpsk", "fm"])
def test_continuous_signal_is_not_claimed_as_pulse_train(kind):
    x, _ = make_signal(kind, 10)
    ds = analyze_capture(capture(x)).response["detections"]
    assert all(not d["is_pulsed"] for d in ds)
