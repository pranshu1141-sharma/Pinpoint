"""QAM constellation order resolution (16/64/256) and APSK recognition.

Builds on backend/pipeline/timing_recovery.py: once a "qam"-labeled
candidate's symbol timing is recovered, this module classifies the
constellation using the normalized fourth-order moment

    kappa = E[|s|^4] / E[|s|^2]^2

a standard blind modulation-order statistic (e.g. Swami & Sadler, "Hierarchical
digital modulation classification using cumulants", 2000) that depends only on
the constellation's amplitude distribution, not on residual carrier phase --
unlike counting clusters directly, it does not require perfect phase/timing
lock to be meaningful.

This module estimates an order or an amplitude-ring family (APSK); it does
not decode symbols to bits.
"""
import numpy as np
from scipy import signal as scipy_signal

from .classify import _cluster_levels, corrected_segment
from .timing_recovery import gardner_timing_recovery

QAM_ORDERS = (16, 64, 256)

# Ideal (noiseless) kappa for square M-QAM with equally likely symbols,
# computed once from an exact constellation -- see
# backend/tests/test_qam_order.py::test_kappa_reference_values, which
# recomputes these from the same qam_constellation() function this module's
# own tests use, so a definition change here can't silently drift from what
# is actually being measured.
REFERENCE_KAPPA = {16: 1.3197, 64: 1.3815, 256: 1.3952}

# Measured in validation (backend/tests/test_qam_order.py): the estimator's
# standard deviation at 15-20 dB SNR with an 8000-symbol tail is ~0.013-0.018.
# The 64-vs-256 reference gap (0.0137) is smaller than that, so it is
# essentially unresolvable with this estimator regardless of SNR; the 16-vs-64
# gap (0.0618) is not. A candidate order is only published when the runner-up
# reference is at least this much farther away than the winner -- which in
# practice means 16 resolves confidently and {64, 256} is reported as an
# explicit, honest ambiguity rather than a guess.
QAM_ORDER_MARGIN = 0.02
QAM_ORDER_MIN_SNR_DB = 15.0
# Measured in validation: an averaging tail of 4000 symbols leaves kappa's
# own standard deviation (~0.02-0.025) large enough to occasionally push a
# genuine 16-QAM estimate to within QAM_ORDER_MARGIN of the 64-QAM
# reference, forcing an unnecessary "unresolved". 8000 symbols brings that
# down to ~0.013-0.018, clearing >=90% resolved across 20 synthetic seeds
# at 15-20 dB (backend/tests/test_qam_order.py).
QAM_ORDER_MIN_TAIL_SYMBOLS = 8000

APSK_OUTER_RING_CONCENTRATION_THRESHOLD = 0.05


def kappa_statistic(symbols):
    power = float(np.mean(np.abs(symbols) ** 2))
    if power <= 0:
        return None
    return float(np.mean(np.abs(symbols) ** 4) / power ** 2)


def denoised_kappa(symbols, snr_db):
    """kappa with the known AWGN contribution to the 2nd/4th moments removed,
    using the candidate's own measured SNR (already produced by Detect's
    noise-floor estimate upstream). For y = s + n with independent circular
    Gaussian noise n: E[|y|^2] = Ps + Pn and E[|y|^4] = E[|s|^4] + 4 Ps Pn +
    2 Pn^2 (a standard result from expanding |s+n|^4 in circular Gaussian
    moments). Both raw and denoised kappa were measured in validation; the
    denoised version tracks the ideal reference table much more closely
    across SNR (measured to remove most of a bias otherwise large enough by
    itself to push 16-QAM to be misread as 64-QAM near the 15 dB gate)."""
    y2 = float(np.mean(np.abs(symbols) ** 2))
    y4 = float(np.mean(np.abs(symbols) ** 4))
    snr_lin = 10 ** (snr_db / 10)
    noise_power = y2 / (1 + snr_lin)
    signal_power = y2 - noise_power
    if signal_power <= 0:
        return None
    s4 = y4 - 4 * signal_power * noise_power - 2 * noise_power ** 2
    if s4 <= 0:
        return None
    return float(s4 / signal_power ** 2)


def is_apsk(symbols, k_candidates=(2, 3, 4, 5)):
    """True if the outermost amplitude ring's phase is close to uniformly
    distributed -- the defining structural difference between APSK's
    deliberately uniform per-ring phase and square QAM's discrete, unevenly
    spaced per-magnitude-level phase. (The innermost, typically 4-point,
    corner ring is exactly 4-fold symmetric in both families and is not
    diagnostic, so only the outermost ring found is checked.) Returns None
    if amplitude clustering itself does not find a clean multi-ring fit."""
    mags = np.abs(symbols)
    found = _cluster_levels(mags, ks=k_candidates)
    if found is None or found[1] < 2:
        return None
    _, k, _, labels = found
    outer = labels == k - 1
    if np.sum(outer) < 16:
        return None
    phase = np.angle(symbols[outer])
    concentration = float(abs(np.mean(np.exp(1j * 4 * phase))))
    return concentration < APSK_OUTER_RING_CONCENTRATION_THRESHOLD


def resolve_order_from_kappa(kappa):
    """(order, status) from a kappa estimate, applying QAM_ORDER_MARGIN.
    order is None when the two closest reference orders are not separated by
    at least the margin -- an honest ambiguity, not a guess."""
    ranked = sorted(QAM_ORDERS, key=lambda m: abs(REFERENCE_KAPPA[m] - kappa))
    best, second = ranked[0], ranked[1]
    d_best, d_second = abs(REFERENCE_KAPPA[best] - kappa), abs(REFERENCE_KAPPA[second] - kappa)
    if d_second - d_best < QAM_ORDER_MARGIN:
        return None, f"order-unresolved (ambiguous between {best}-QAM and {second}-QAM)"
    confidence = float(np.clip((d_second - d_best) / QAM_ORDER_MARGIN, 0., 1.))
    return best, f"resolved ({confidence:.2f} margin confidence)"


def estimate_qam_symbol_rate(capture, candidate):
    """Delay-and-multiply symbol rate for "qam"-labeled candidates, mirroring
    classify.estimate_symbol_rate's structure but on the squared-magnitude
    envelope (differenced) rather than the squared real part: QAM's joint
    amplitude/phase symbol transitions modulate |x|^2 at the symbol rate the
    same way BPSK/QPSK/8PSK/ASK's phase/amplitude transitions modulate
    Re(x)^2, but classify.py's nonlinearity is PSK/ASK-specific (real-part
    based) and was never validated for QAM -- see
    backend/tests/test_qam_order.py for the validation this generalizes on.
    """
    out = {"symbol_rate_hz": None, "symbol_rate_status": "not reliably estimated (requires qam label)"}
    if candidate.get("fine_modulation_label") != "qam":
        return out
    snr = candidate.get("snr_db")
    if snr is None or not np.isfinite(snr) or snr < QAM_ORDER_MIN_SNR_DB:
        out["symbol_rate_status"] = f"not reliably estimated (SNR below validated {QAM_ORDER_MIN_SNR_DB} dB gate)"
        return out
    frequency_hz = candidate.get("center_frequency_refined_hz") or candidate.get("center_frequency_hz")
    x = corrected_segment(capture, candidate, frequency_hz)
    if x is None:
        return out
    nonlin = np.diff(np.abs(x).astype(np.float64) ** 2)
    nperseg = min(len(nonlin), 1 << 18)
    if nperseg < 8:
        out["symbol_rate_status"] = "not reliably estimated (insufficient occupied samples)"
        return out
    f, p = scipy_signal.welch(nonlin, fs=capture.sample_rate, window="hann", nperseg=nperseg,
                              noverlap=nperseg // 2, detrend=False, scaling="density")
    skip = 4
    if len(p) < skip + 2 or np.max(p[skip:]) <= 0:
        out["symbol_rate_status"] = "not reliably estimated (no resolved spectral peak)"
        return out
    peak_power = float(np.max(p[skip:]))
    threshold = peak_power / 10 ** .3
    candidates_idx = np.flatnonzero(p[skip:] >= threshold) + skip
    rate = float(f[int(candidates_idx.min())])
    if rate <= 0:
        out["symbol_rate_status"] = "not reliably estimated (nonpositive candidate rate)"
        return out
    out.update(symbol_rate_hz=rate,
               symbol_rate_status="estimated (envelope nonlinearity + lowest-near-peak spectral heuristic)")
    return out


def resolve_qam_order(capture, candidate):
    """Resolve constellation order/family for a "qam"-labeled candidate.

    Returns candidate merged with: qam_symbol_rate_hz, qam_order (16/64/256
    or None), qam_order_confidence, constellation_family ("square-qam",
    "apsk", or None), qam_order_status (always explains the result, whether
    resolved or not).
    """
    out = {**candidate, "qam_symbol_rate_hz": None, "qam_order": None,
           "qam_order_confidence": None, "constellation_family": None,
           "qam_order_status": "not reliably resolved (requires a qam label)"}
    if candidate.get("fine_modulation_label") != "qam":
        return out
    rate_info = estimate_qam_symbol_rate(capture, candidate)
    out["qam_symbol_rate_hz"] = rate_info["symbol_rate_hz"]
    if rate_info["symbol_rate_hz"] is None:
        out["qam_order_status"] = f"not reliably resolved ({rate_info['symbol_rate_status']})"
        return out
    sps = capture.sample_rate / rate_info["symbol_rate_hz"]
    if sps < 4:
        out["qam_order_status"] = "not reliably resolved (insufficient samples/symbol for timing recovery)"
        return out
    frequency_hz = candidate.get("center_frequency_refined_hz") or candidate.get("center_frequency_hz")
    segment = corrected_segment(capture, candidate, frequency_hz)
    if segment is None or len(segment) < 2 * QAM_ORDER_MIN_TAIL_SYMBOLS * sps:
        out["qam_order_status"] = "not reliably resolved (segment too short for validated timing-recovery config)"
        return out
    recovery = gardner_timing_recovery(segment, sps)
    if not recovery["lock_indicator"]:
        out["qam_order_status"] = "not reliably resolved (symbol-timing recovery did not lock)"
        return out
    symbols = recovery["symbols"][-QAM_ORDER_MIN_TAIL_SYMBOLS:]
    apsk = is_apsk(symbols)
    if apsk:
        out.update(constellation_family="apsk",
                   qam_order_status="classified apsk (uniform outer-ring phase heuristic, order unresolved)")
        return out
    out["constellation_family"] = "square-qam"
    kappa = denoised_kappa(symbols, candidate.get("snr_db"))
    if kappa is None:
        out["qam_order_status"] = "not reliably resolved (degenerate power estimate)"
        return out
    order, status = resolve_order_from_kappa(kappa)
    if order is None:
        out["qam_order_status"] = status
        return out
    ranked = sorted(QAM_ORDERS, key=lambda m: abs(REFERENCE_KAPPA[m] - kappa))
    confidence = float(np.clip(
        (abs(REFERENCE_KAPPA[ranked[1]] - kappa) - abs(REFERENCE_KAPPA[ranked[0]] - kappa)) / QAM_ORDER_MARGIN,
        0., 1.))
    out.update(qam_order=order, qam_order_confidence=confidence, qam_order_status=status)
    return out
