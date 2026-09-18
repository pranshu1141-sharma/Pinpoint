"""Phase 1 symbol decoding for confirmed M-PSK fine-classified candidates.

Builds on backend/pipeline/timing_recovery.py's locked Gardner symbol
instants: once a "bpsk"/"qpsk"/"8psk"-labeled candidate's symbol timing is
recovered, this module estimates the residual constant carrier-phase offset
(a blind Mth-power estimate, the same family of technique refine_frequency
and qam_order already use for frequency/order) and maps each recovered
symbol to the nearest ideal M-PSK constellation point, producing an integer
symbol-index stream.

Scope boundary, stated once here because it governs every acceptance test in
backend/tests/test_decode.py: there is no absolute carrier-phase or
frame-start reference anywhere in this pipeline. Gardner recovers symbol
*timing*, not phase. The Mth-power phase estimate below removes a constant
residual phase but is inherently ambiguous by a factor of 2*pi*k/order for
any k in range(order) -- rotating every ideal constellation point by that
amount produces an identical, equally valid fit, and nothing in a single
capture with no known preamble/training sequence (matched filtering and
frame sync are deliberately out of scope elsewhere in this project; see
docs/LIMITATIONS_AND_ROADMAP.md) can resolve which rotation is "correct" in
an absolute sense. The published symbol_indices are therefore only ever
meaningful *relative to each other*, correct up to that unknown constant
rotation (mod `order`) and an unknown start offset (which recovered symbol
corresponds to the transmitter's first symbol). This module does not claim,
and must never be made to claim, an absolute decoded message. See
DECODING.md for the measured acceptance evidence and what remains open.
"""
import numpy as np

from .classify import corrected_segment
from .timing_recovery import gardner_timing_recovery

# Mirrors classify.FINE_LABELS' order values (2/4/8), keyed the other way.
DECODE_ORDERS = {"bpsk": 2, "qpsk": 4, "8psk": 8}

# Measured in validation (backend/tests/test_decode.py): mean symbol error
# rate against a best-fit-aligned truth stream, 10 seeds each, clears the 2%
# acceptance target well below 10 dB for bpsk/qpsk and below 13 dB for
# 8psk purely on SER grounds. But timing_recovery.gardner_timing_recovery
# is itself only validated to lock reliably at >=10 dB (its own module
# docstring); measured bpsk lock reliability specifically drops to 9/10
# seeds below 10 dB even though the symbols that DO lock decode cleanly.
# This gate is therefore set to 10 dB for bpsk/qpsk -- the timing-recovery
# floor, not a looser SER-only floor -- and to 15 dB for 8psk, where its
# much tighter decision boundaries (pi/8 apart vs pi/2 for bpsk or pi/4
# for qpsk) push the SER cliff itself above 10 dB.
DECODE_MIN_SNR_DB = {"bpsk": 10.0, "qpsk": 10.0, "8psk": 15.0}

# A tail of recovered symbols long enough for the Gardner loop to have
# converged (see timing_recovery.gardner_timing_recovery's own lock_window),
# short enough to keep the acceptance-test synthetic fixtures a manageable
# size. Symbols recovered before convergence are dropped, matching
# qam_order.py's own tail-window convention.
DECODE_MIN_TAIL_SYMBOLS = 2000


def estimate_phase_offset(symbols, order):
    """Blind Mth-power residual carrier-phase estimate, ambiguous mod
    2*pi/order -- see module docstring. None if the symbols carry no
    resolvable phase evidence (e.g. all zero)."""
    symbols = np.asarray(symbols, dtype=np.complex128)
    if len(symbols) == 0:
        return None
    mean_pow = np.mean(symbols ** order)
    if abs(mean_pow) == 0 or not np.isfinite(mean_pow):
        return None
    return float(np.angle(mean_pow) / order)


def demap_psk_symbols(symbols, order):
    """Nearest-constellation-point integer symbol index (0..order-1) for
    each recovered symbol, after removing the blind Mth-power phase
    estimate.

    Returns (symbol_indices, phase_offset_hat, confidence). All three are
    None if no phase offset could be estimated. confidence is 1 minus the
    mean angular error to the nearest ideal point, normalized by half the
    inter-point spacing (so 1.0 means every symbol landed exactly on an
    ideal point, 0.0 means the average symbol is exactly on a decision
    boundary) -- an explainable diagnostic, not a calibrated probability,
    consistent with this project's other confidence fields.
    """
    phase_hat = estimate_phase_offset(symbols, order)
    if phase_hat is None:
        return None, None, None
    aligned = np.asarray(symbols, dtype=np.complex128) * np.exp(-1j * phase_hat)
    angles = np.angle(aligned)
    step = 2 * np.pi / order
    idx = np.round(angles / step).astype(int) % order
    ideal_angle = idx * step
    # Wrapped angular error to the assigned ideal point.
    err = np.angle(np.exp(1j * (angles - ideal_angle)))
    mean_abs_err = float(np.mean(np.abs(err)))
    confidence = float(max(0., 1. - mean_abs_err / (step / 2)))
    return idx, phase_hat, confidence


def decode_candidate(capture, candidate):
    """Decode symbols for a confirmed bpsk/qpsk/8psk candidate.

    Returns candidate merged with: decoded_symbol_indices (list[int] or
    None), decoded_symbol_count, decode_phase_offset_rad,
    decode_confidence, decode_rotation_ambiguity_modulus (order, or None),
    decode_status (always explains the result, whether decoded or declined).
    """
    out = {**candidate, "decoded_symbol_indices": None, "decoded_symbol_count": None,
           "decode_phase_offset_rad": None, "decode_confidence": None,
           "decode_rotation_ambiguity_modulus": None,
           "decode_status": "not attempted (requires a confirmed bpsk/qpsk/8psk fine label)"}
    label = candidate.get("fine_modulation_label")
    order = DECODE_ORDERS.get(label)
    if order is None:
        return out
    snr = candidate.get("snr_db")
    if snr is None or not np.isfinite(snr):
        out["decode_status"] = "not attempted (unknown SNR)"
        return out
    min_snr = DECODE_MIN_SNR_DB[label]
    if snr < min_snr:
        out["decode_status"] = f"not attempted (SNR below validated {min_snr} dB gate)"
        return out
    symbol_rate = candidate.get("symbol_rate_hz")
    if symbol_rate is None or not np.isfinite(symbol_rate) or symbol_rate <= 0:
        out["decode_status"] = "not attempted (no reliable symbol-rate estimate)"
        return out
    sps = capture.sample_rate / symbol_rate
    if sps < 4:
        out["decode_status"] = "not attempted (insufficient samples/symbol for timing recovery)"
        return out
    frequency_hz = candidate.get("center_frequency_refined_hz") or candidate.get("center_frequency_hz")
    segment = corrected_segment(capture, candidate, frequency_hz)
    if segment is None or len(segment) < 2 * DECODE_MIN_TAIL_SYMBOLS * sps:
        out["decode_status"] = "not attempted (segment too short for validated timing-recovery config)"
        return out
    recovery = gardner_timing_recovery(segment, sps)
    if not recovery["lock_indicator"]:
        out["decode_status"] = "not attempted (symbol-timing recovery did not lock)"
        return out
    symbols = recovery["symbols"][-DECODE_MIN_TAIL_SYMBOLS:]
    idx, phase_hat, confidence = demap_psk_symbols(symbols, order)
    if idx is None:
        out["decode_status"] = "not attempted (degenerate phase estimate)"
        return out
    out.update(
        decoded_symbol_indices=idx.tolist(),
        decoded_symbol_count=int(len(idx)),
        decode_phase_offset_rad=phase_hat,
        decode_confidence=confidence,
        decode_rotation_ambiguity_modulus=order,
        decode_status=(
            "decoded (Mth-power blind phase alignment + nearest-constellation-point demapping); "
            f"symbol indices are correct only up to an unknown constant rotation mod {order} "
            "and an unknown start offset -- see DECODING.md"),
    )
    return out
