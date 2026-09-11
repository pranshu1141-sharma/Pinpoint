"""Opt-in, explicitly heuristic IQ modulation measurements."""
import numpy as np

from .detect import EPS, estimate_noise_floor, isolate_band
from .estimate import NFFT, estimate_candidate, interpolated_peak, occupied_windows, tuning_frequency
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


def refine_frequency(capture: Capture, candidate: dict) -> dict:
    """Choose the sharper M=2/4 raised tone; retain Stage 1's direct estimate.

    This is a PSK synchronization hypothesis, not proof of modulation. FM can
    also have sharp spectral lines. Fine classification must independently test
    phase concentration. A peak at the Nyquist boundary is left unresolved.
    """
    out = {**candidate, "center_frequency_refined_hz": None, "refinement_order": None,
           "refinement_sharpness": None,
           "refinement_status": "not reliably refined (requires constant-envelope evidence)"}
    if candidate.get("modulation_family") != "constant-envelope":
        return out
    center = candidate.get("center_frequency_hz")
    x = corrected_segment(capture, candidate, center)
    if x is None:
        return out
    scale = float(np.max(np.abs(x)))
    if scale <= 0 or not np.isfinite(scale):
        return out
    # Normalization preserves frequency/sharpness and avoids Mth-power overflow.
    x = (x/scale).astype(np.complex64)
    hypotheses = []
    for order in (2, 4):
        f, p, _ = estimate_noise_floor(x**order, capture.sample_rate)
        peak = interpolated_peak(f, p)
        if peak is None:
            continue
        sharpness = float(np.max(p)/max(float(np.median(p)), EPS))
        hypotheses.append((sharpness, order, peak/order))
    if not hypotheses:
        out["refinement_status"] = "not reliably refined (unresolved raised tone)"
        return out
    sharpness, order, residual = max(hypotheses)
    out.update(center_frequency_refined_hz=float(center+residual), refinement_order=order,
               refinement_sharpness=sharpness, refinement_status="refined (Mth-power peak heuristic)")
    return out


def classify_fine(capture: Capture, candidate: dict) -> dict:
    """Fallback rung 2: expose phase diagnostics but never publish a fine label.

    The requested spread <0.8 rule failed the QPSK majority acceptance check
    at both 20 and 10 dB (2/5 seeds each). BPSK success alone is insufficient
    to claim Stage 4. Retain this diagnostic to make the limitation measurable.
    """
    out = {**candidate, "fine_modulation_label": None, "fine_modulation_confidence": None,
           "phase_cluster_spread_rad": None,
           "fine_modulation_status": "not reliably classified (no phase refinement)"}
    order = candidate.get("refinement_order")
    if candidate.get("modulation_family") != "constant-envelope" or order not in (2, 4):
        return out
    x = corrected_segment(capture, candidate, candidate.get("center_frequency_refined_hz"))
    if x is None or not np.any(np.abs(x) > 0):
        return out
    phase = np.angle(x).astype(np.float64)
    concentration = float(abs(np.mean(np.exp(1j*order*phase))))
    if concentration <= 0:
        out["fine_modulation_status"] = "not reliably classified (no phase concentration)"
        return out
    spread = float(np.sqrt(max(0., -2*np.log(min(1., concentration)))))
    out["phase_cluster_spread_rad"] = spread
    out["fine_modulation_status"] = "not reliably classified (fallback rung 2: fine acceptance not met)"
    return out


def analyze_candidate(capture: Capture, candidate: dict, *, noise_floor=None) -> dict:
    """Run the validated downstream stages on a copy of one Detect candidate.

    Fine classification is diagnostic-only and symbol-rate estimation was not
    attempted after the Stage 4 acceptance failure. Neither field can accidentally
    retain an earlier guessed value from the input candidate.
    """
    out = estimate_candidate(capture, candidate, noise_floor=noise_floor)
    out = classify_coarse(capture, out)
    out = refine_frequency(capture, out)
    out = classify_fine(capture, out)
    out.update(symbol_rate_hz=None,
               symbol_rate_status="not reliably estimated (not attempted: fallback rung 2)")
    return out
