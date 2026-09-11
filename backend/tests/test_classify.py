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
