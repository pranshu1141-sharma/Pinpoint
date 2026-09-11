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
