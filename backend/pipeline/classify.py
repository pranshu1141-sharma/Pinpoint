"""Opt-in, explicitly heuristic IQ modulation measurements."""
import numpy as np
from scipy import signal as scipy_signal

from .detect import EPS, estimate_noise_floor, isolate_band
from .estimate import NFFT, estimate_candidate, interpolated_peak, occupied_windows, tuning_frequency
from .ingest import Capture

# Master-context Stage 5 Monte Carlo validation: ~100/95% correct at 10/5 dB,
# collapsing below 0 dB where differentiation noise amplification dominates.
# 4.5, not 5.0, so measurement noise around a true 5 dB signal (+/-0.1 dB here)
# does not arbitrarily exclude half of exactly-5-dB fixtures from the gate.
SYMBOL_RATE_MIN_SNR_DB = 4.5


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
    # A fixed 1024-point Welch average caps raw resolution at fs/1024 (~46.9 Hz
    # here) regardless of how long the occupied segment is. Over a ~2 s segment
    # that residual, multiplied by the M=4 (QPSK) raised-tone order, accumulates
    # into multiple radians of phase drift and defeats fine classification below.
    # A single full-segment periodogram trades averaging (unneeded for a strong,
    # near-stationary raised tone) for resolution matched to the segment length.
    nperseg = min(len(x), 1 << 20)
    hypotheses = []
    for order in (2, 4):
        f, p, _ = estimate_noise_floor(x**order, capture.sample_rate, nperseg=nperseg)
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


FINE_LABELS = {2: "bpsk", 4: "qpsk"}
FINE_SPREAD_THRESHOLD = .8


def classify_fine(capture: Capture, candidate: dict) -> dict:
    """Publish a fine PSK label only when the measured phase spread clears the
    threshold; otherwise expose the diagnostic without a label.

    Matching the Mth-power peak search's resolution to the segment length (see
    refine_frequency) removed the residual-frequency phase drift that previously
    failed QPSK's majority acceptance check; both BPSK (order 2) and QPSK
    (order 4) now pass 5/5 at 20 and 10 dB. FM stays above threshold because its
    continuous phase modulation, not carrier-frequency imprecision, drives its
    spread.

    Pulsed candidates are excluded: an unmodulated gated carrier has trivially
    perfect phase concentration (spread near zero), which this rule cannot
    distinguish from genuine phase-locked PSK. Only continuous candidates were
    validated, so pulsed bursts stay an explicit unknown rather than a false
    "bpsk" label.
    """
    out = {**candidate, "fine_modulation_label": None, "fine_modulation_confidence": None,
           "phase_cluster_spread_rad": None,
           "fine_modulation_status": "not reliably classified (no phase refinement)"}
    order = candidate.get("refinement_order")
    if candidate.get("is_pulsed"):
        out["fine_modulation_status"] = "not reliably classified (pulsed bursts not validated)"
        return out
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
    if spread < FINE_SPREAD_THRESHOLD:
        out.update(fine_modulation_label=FINE_LABELS[order],
                   fine_modulation_confidence=float(1.-spread/FINE_SPREAD_THRESHOLD),
                   fine_modulation_status="classified (phase-cluster concentration heuristic)")
    else:
        out["fine_modulation_status"] = "not reliably classified (phase spread above threshold)"
    return out


def estimate_symbol_rate(capture: Capture, candidate: dict) -> dict:
    """Delay-and-multiply symbol rate: differentiate, square, and Welch-PSD the
    refined, corrected segment's real part; rectangular-NRZ transitions make
    every harmonic of the true rate nearly equal-strength, so the lowest bin
    within ~3 dB of the global max is picked instead of the raw argmax.

    The nonlinearity is non-negative, so its huge DC term leaks into the first
    few bins under the Hann window's main lobe; left unmasked, that leakage can
    sit within 3 dB of the true rate and get selected as the "lowest" harmonic.
    The first four bins (the observed main-lobe width) are excluded from the
    search entirely, not just the DC bin itself.

    Gated to the validated ~5-20 dB SNR range; differentiation's noise
    amplification below that range was not solved and is reported explicitly
    rather than returning a wrong number.
    """
    out = {**candidate, "symbol_rate_hz": None,
           "symbol_rate_status": "not reliably estimated (requires a confirmed PSK fine label)"}
    if candidate.get("fine_modulation_label") not in FINE_LABELS.values():
        return out
    snr = candidate.get("snr_db")
    if snr is None or not np.isfinite(snr):
        out["symbol_rate_status"] = "not reliably estimated (unknown SNR)"
        return out
    if snr < SYMBOL_RATE_MIN_SNR_DB:
        out["symbol_rate_status"] = "not reliably estimated (SNR below validated 5-20 dB range)"
        return out
    frequency_hz = candidate.get("center_frequency_refined_hz") or candidate.get("center_frequency_hz")
    x = corrected_segment(capture, candidate, frequency_hz)
    if x is None:
        return out
    nonlin = np.diff(np.real(x).astype(np.float64))**2
    nperseg = min(len(nonlin), 1 << 20)
    if nperseg < 8:
        out["symbol_rate_status"] = "not reliably estimated (insufficient occupied samples)"
        return out
    f, p = scipy_signal.welch(nonlin, fs=capture.sample_rate, window="hann", nperseg=nperseg,
                              noverlap=nperseg//2, detrend=False, scaling="density")
    # Exclude the DC bin and its Hann-window leakage neighbors (observed main-lobe
    # width: 4 bins), not just bin 0 -- they carry the nonlinearity's mean, not a
    # symbol harmonic, but can be strong enough to masquerade as one.
    skip = 4
    if len(p) < skip+2 or np.max(p[skip:]) <= 0:
        out["symbol_rate_status"] = "not reliably estimated (no resolved spectral peak)"
        return out
    peak_power = float(np.max(p[skip:]))
    threshold = peak_power/10**.3
    candidates_idx = np.flatnonzero(p[skip:] >= threshold)+skip
    rate = float(f[int(candidates_idx.min())])
    if rate <= 0:
        out["symbol_rate_status"] = "not reliably estimated (nonpositive candidate rate)"
        return out
    out.update(symbol_rate_hz=rate,
               symbol_rate_status="estimated (nonlinearity + lowest-near-peak spectral heuristic)")
    return out


def analyze_candidate(capture: Capture, candidate: dict, *, noise_floor=None) -> dict:
    """Run the validated downstream stages on a copy of one Detect candidate.

    Neither downstream field can accidentally retain an earlier guessed value
    from the input candidate.
    """
    out = estimate_candidate(capture, candidate, noise_floor=noise_floor)
    out = classify_coarse(capture, out)
    out = refine_frequency(capture, out)
    out = classify_fine(capture, out)
    out = estimate_symbol_rate(capture, out)
    return out
