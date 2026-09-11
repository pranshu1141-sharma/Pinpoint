"""Opt-in, explicitly heuristic IQ modulation measurements."""
import numpy as np

from .detect import isolate_band
from .estimate import NFFT, occupied_windows, tuning_frequency
from .ingest import Capture


def corrected_segment(capture: Capture, candidate: dict, frequency_hz):
    """Longest occupied window, isolated then corrected to the requested center.

    isolate_band already mixes by the midpoint of the Detect bounds. Only the
    remaining offset is removed here; subtract acquisition tuning metadata once.
    Trim 128 samples at each end (the existing FIR's half support), so zero-padding
    transients do not masquerade as envelope variation. No pulses are joined.
    """
    if (capture.metadata.get("source_kind") != "iq" or frequency_hz is None
            or not np.isfinite(frequency_hz)):
        return None
    windows = occupied_windows(capture, candidate)
    if not windows:
        return None
    a, b = max(windows, key=lambda w: w[1]-w[0])
    if b-a < NFFT+256:
        return None
    lo, hi = candidate["freq_lower_hz"], candidate["freq_upper_hz"]
    fs = capture.sample_rate
    if not (np.isfinite(fs) and fs > 0 and np.isfinite(lo) and np.isfinite(hi)
            and -fs/2 <= lo < hi <= fs/2 and np.isfinite(capture.iq[a:b]).all()):
        raise ValueError("Finite IQ, positive sample rate and valid frequency bounds required.")
    isolated = isolate_band(capture.iq[a:b], fs, lo, hi)
    residual = frequency_hz-tuning_frequency(capture)-(lo+hi)/2
    corrected = isolated*np.exp(-2j*np.pi*residual*np.arange(b-a)/fs)
    return corrected[128:-128].astype(np.complex64)


def classify_coarse(capture: Capture, candidate: dict) -> dict:
    """Constant/varying envelope family, never an analog/digital assertion."""
    out = {**candidate, "modulation_family": None, "modulation_confidence": None,
           "envelope_variation": None,
           "modulation_confidence_kind": "heuristic, not a calibrated probability",
           "modulation_status": "not reliably classified (insufficient IQ evidence)"}
    x = corrected_segment(capture, candidate, candidate.get("center_frequency_hz"))
    if x is None:
        return out
    envelope = np.abs(x).astype(np.float64)
    mean = float(np.mean(envelope))
    if not np.isfinite(envelope).all() or mean <= 0:
        return out
    variation = float(np.std(envelope)/mean)
    out.update(envelope_variation=variation,
               modulation_family="constant-envelope" if variation < .3 else "varying-envelope",
               modulation_confidence=min(1., abs(variation-.3)/.3),
               modulation_status="classified (isolated-envelope heuristic)")
    return out
