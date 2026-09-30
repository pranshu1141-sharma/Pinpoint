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

# D1: 2-FSK/GMSK (discriminator) and OOK/ASK2, gated at the SNR each family's
# own measured BER-vs-SNR sweep clears 2% mean BER over 10 seeds (see
# backend/tests/test_decode_fsk_ask.py and DECODING.md's D1 sweep). Timing
# for both uses oerder_meyer_symbol_epoch, not Gardner: Gardner is a decision-
# directed loop tuned for the long, continuous PSK streams this module
# already validates (2,000+ symbol tails); AIS/rtl_433 bursts are far
# shorter, and the bake-off in experiments/decode_bakeoff/timing_bakeoff.py
# measured a non-data-aided feedforward estimator (Oerder & Meyer, 1988)
# beating a Mueller-Mueller decision-directed loop at every SNR from 10 dB
# up (100-seed mean BER, realistic random start delay: 2.05% vs 3.45% at
# 10 dB, 0.32% vs 1.38% at 15 dB) -- a decision-directed loop's early hard
# decisions are wrong more often at these SNRs, and that feeds back into its
# own timing estimate, which a block estimate with no feedback cannot do.
FSK_ASK_MIN_SNR_DB = {"fsk2": 10.0, "ask2": 8.0}
DECODE_MIN_SNR_DB.update(FSK_ASK_MIN_SNR_DB)

# fsk2/ask2 need only a handful of symbols to lock (Oerder-Meyer is a
# feedforward block estimate, not a loop needing thousands of symbols to
# converge like DECODE_MIN_TAIL_SYMBOLS below) -- but the confidence
# statistic both demappers gate on (FSK_MIN_CONFIDENCE/ASK_MIN_CONFIDENCE)
# needs enough symbols to be a stable estimate of its own spread; measured
# stable from 200 symbols up in backend/tests/test_decode_fsk_ask.py's
# fixtures (2,000-symbol bursts, comfortably above this floor).
FSK_ASK_MIN_SYMBOLS = 200

# The false-decode gate is NOT oerder_meyer_symbol_epoch's raw lock_fraction:
# measured (see DECODING.md's D1 section), that fraction stays small (~0.01
# -0.04 for FSK even at a workable 10-15 dB) because most of a discriminator
# or envelope signal's squared-nonlinearity power sits at DC, not because the
# timing estimate is unreliable there -- it does not separate real signal
# from pure noise at these SNRs (noise's own fraction, ~0.001-0.013, already
# overlaps a real 8 dB FSK signal's ~0.004-0.028). The gate that DOES
# separate cleanly, measured the same way, is the post-integrate-and-dump
# decision confidence (demap_fsk_bits'/demap_ask_bits' own returned
# `confidence`): pure complex AWGN's confidence tops out at 0.434 (FSK) /
# 0.453 (ASK) over 1,000/500 seeds, while a signal at each family's SNR gate
# sits at 0.50-0.90 (FSK) / 0.79-0.90 (ASK), and a wrong-hypothesis BPSK
# segment fed to either demapper scores 0.04 (FSK) / 0.40 (ASK) -- below
# both floors below. These thresholds carry the actual 0-false-decode
# requirement; see test_demap_fsk_bits_on_pure_noise_declines,
# test_demap_ask_bits_on_pure_noise_declines and
# test_demap_fsk_bits_on_wrong_hypothesis_declines.
FSK_MIN_CONFIDENCE = 0.46
ASK_MIN_CONFIDENCE = 0.55

# A CPFSK/GMSK symbol needs 2 samples either side of its centre for the
# integrate-and-dump window (see _integrate_and_dump); this is the same
# floor timing_recovery.gardner_timing_recovery states for its own linear
# interpolation, applied here to the integration window instead.
FSK_ASK_MIN_SPS = 4


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


def fsk_discriminator(x):
    """Instantaneous frequency, cycles/sample, via the angle of each
    consecutive-sample product (a non-coherent FM discriminator; phase-
    insensitive by construction, unlike the PSK path above)."""
    x = np.asarray(x, dtype=np.complex128)
    d = np.angle(x[1:] * np.conj(x[:-1])) / (2 * np.pi)
    return np.append(d, d[-1] if len(d) else 0.0)


def oerder_meyer_symbol_epoch(y, sps):
    """Non-data-aided feedforward symbol-timing epoch (Oerder & Meyer, 1988):
    the DFT bin of y**2 at the symbol rate (1/sps cycles/sample) carries a
    tone at the true symbol epoch for any signal whose relevant nonlinearity
    (discriminator output for FSK/GMSK, envelope for ASK/OOK) transitions at
    symbol boundaries. Returns (tau, lock_fraction): tau in samples, 0..sps;
    lock_fraction is |bin| / sum(|y**2 - mean|), in [0, 1] by the triangle
    inequality, near 0 for signals with no periodic component at 1/sps (pure
    noise) and typically >0.5 for a genuine symbol stream at a workable SNR
    (see OERDER_MEYER_MIN_LOCK_FRACTION and its measured basis above). None
    if y is degenerate (empty or exactly flat).
    """
    y = np.asarray(y, dtype=np.float64)
    if len(y) < sps:
        return None
    y2 = (y - np.mean(y)) ** 2
    ac = y2 - np.mean(y2)   # the DC term of y2 carries no timing information
    total = np.sum(np.abs(ac))
    if total == 0 or not np.isfinite(total):
        return None
    n = np.arange(len(ac))
    bin_ = np.sum(ac * np.exp(-2j * np.pi * n / sps))
    if not np.isfinite(bin_):
        return None
    tau = float((-np.angle(bin_) / (2 * np.pi)) % 1.0 * sps)
    lock_fraction = float(min(1.0, abs(bin_) / total))
    return tau, lock_fraction


def _integrate_and_dump(y, tau, sps, n_symbols):
    """Mean of y over each sps-sample window centred on tau + k*sps, for
    k=0..n_symbols-1 -- the matched filter for a signal constant within a
    symbol interval (both the discriminator output of an unshaped CPFSK
    symbol and the envelope of an unshaped ASK symbol are exactly that).
    Symbols whose window would run past either end of y are dropped."""
    win = int(round(sps))
    centers = tau + np.arange(n_symbols) * sps
    half = sps / 2.0
    in_range = (centers - half >= 0) & (centers + half <= len(y))
    centers = centers[in_range]
    los = np.round(centers - half).astype(int)
    vals = np.array([float(np.mean(y[lo:lo + win])) for lo in los])
    return vals, in_range


def demap_fsk_bits(x, sps, min_confidence=FSK_MIN_CONFIDENCE):
    """Non-coherent discriminator demapper for binary CPFSK/GMSK: Oerder-Meyer
    timing on the squared discriminator output, then integrate-and-dump per
    symbol, hard-thresholded at zero (the two frequency deviations are
    symmetric around the segment's own median instantaneous frequency by
    construction of the discriminator itself needing no absolute phase or
    frequency reference).

    Returns (bits, tau, confidence), all None if confidence does not clear
    min_confidence -- declines rather than guesses; see FSK_MIN_CONFIDENCE's
    docstring for why confidence, not the timing estimate's own raw lock
    fraction, is what actually separates a real signal from noise or a
    wrong-hypothesis input here. confidence is 1 minus the mean normalized
    distance of each integrated value's magnitude from the mean magnitude,
    an explainable diagnostic matching demap_psk_symbols' convention, not a
    calibrated probability.
    """
    x = np.asarray(x, dtype=np.complex128)
    if len(x) < 2 * sps:
        return None, None, None
    y = fsk_discriminator(x)
    result = oerder_meyer_symbol_epoch(y, sps)
    if result is None:
        return None, None, None
    tau, _lock = result
    n_symbols = int((len(y) - tau) // sps)
    vals, _ = _integrate_and_dump(y, tau, sps, n_symbols)
    if len(vals) == 0:
        return None, None, None
    spread = np.std(vals)
    if spread == 0:
        return None, None, None
    dist = np.abs(np.abs(vals) - np.mean(np.abs(vals)))
    confidence = float(max(0.0, 1.0 - np.mean(dist) / (np.mean(np.abs(vals)) + 1e-30)))
    if confidence < min_confidence:
        return None, None, None
    bits = (vals > 0).astype(int)
    return bits, tau, confidence


def demap_ask_bits(x, sps, min_confidence=ASK_MIN_CONFIDENCE):
    """Envelope demapper for unipolar 2-level ASK (OOK when the off level is
    zero): Oerder-Meyer timing directly on the squared envelope (already the
    right nonlinearity -- an ASK symbol's envelope, unlike its complex value,
    needs no carrier-phase reference), integrate-and-dump per symbol, then a
    2-means threshold between the two integrated levels (not a fixed
    zero-threshold like demap_fsk_bits: ASK's two levels are not symmetric
    around zero, and the "off" level is not always exactly zero -- see
    g5_manifest.json's OOK_* note that the off level is allowed to be
    nonzero).

    Returns (bits, tau, confidence); all None if confidence does not clear
    min_confidence (see ASK_MIN_CONFIDENCE's docstring) or the two levels
    cannot be separated (degenerate: every integrated value equal).
    """
    x = np.asarray(x, dtype=np.complex128)
    if len(x) < 2 * sps:
        return None, None, None
    y = np.abs(x) ** 2
    result = oerder_meyer_symbol_epoch(y, sps)
    if result is None:
        return None, None, None
    tau, _lock = result
    n_symbols = int((len(y) - tau) // sps)
    vals, _ = _integrate_and_dump(y, tau, sps, n_symbols)
    if len(vals) == 0 or np.ptp(vals) == 0:
        return None, None, None
    lo, hi = float(np.min(vals)), float(np.max(vals))
    for _ in range(10):
        thresh = (lo + hi) / 2
        low_mask = vals <= thresh
        if not low_mask.any() or low_mask.all():
            break
        new_lo, new_hi = float(np.mean(vals[low_mask])), float(np.mean(vals[~low_mask]))
        if new_lo == lo and new_hi == hi:
            break
        lo, hi = new_lo, new_hi
    thresh = (lo + hi) / 2
    bits = (vals > thresh).astype(int)
    span = (hi - lo) or 1e-30
    dist_to_level = np.where(bits == 1, np.abs(vals - hi), np.abs(vals - lo))
    confidence = float(max(0.0, 1.0 - np.mean(dist_to_level) / (span / 2)))
    if confidence < min_confidence:
        return None, None, None
    return bits, tau, confidence


DECODE_FAMILY_METHOD = {"bpsk": "psk", "qpsk": "psk", "8psk": "psk", "fsk2": "fsk", "ask2": "ask"}


def _decode_psk(capture, candidate, out, label):
    order = DECODE_ORDERS[label]
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


def _decode_fsk_or_ask(capture, candidate, out, label, method):
    symbol_rate = candidate.get("symbol_rate_hz")
    if symbol_rate is None or not np.isfinite(symbol_rate) or symbol_rate <= 0:
        out["decode_status"] = "not attempted (no reliable symbol-rate estimate)"
        return out
    sps = capture.sample_rate / symbol_rate
    if sps < FSK_ASK_MIN_SPS:
        out["decode_status"] = "not attempted (insufficient samples/symbol for timing recovery)"
        return out
    frequency_hz = candidate.get("center_frequency_refined_hz") or candidate.get("center_frequency_hz")
    segment = corrected_segment(capture, candidate, frequency_hz)
    if segment is None or len(segment) < 2 * FSK_ASK_MIN_SYMBOLS * sps:
        out["decode_status"] = "not attempted (segment too short for a stable confidence estimate)"
        return out
    demapper, method_name = (
        (demap_fsk_bits, "non-coherent discriminator demapping") if method == "fsk"
        else (demap_ask_bits, "envelope demapping"))
    bits, tau, confidence = demapper(segment, sps)
    if bits is None:
        out["decode_status"] = "not attempted (confidence below the validated false-decode gate)"
        return out
    out.update(
        decoded_symbol_indices=bits.tolist(),
        decoded_symbol_count=int(len(bits)),
        decode_phase_offset_rad=None,
        decode_confidence=confidence,
        decode_rotation_ambiguity_modulus=2,
        decode_status=(
            f"decoded (Oerder-Meyer symbol timing + {method_name}); "
            "bits are correct only up to an unknown polarity/level assignment mod 2 "
            "and an unknown start offset -- see DECODING.md"),
    )
    return out


def decode_candidate(capture, candidate):
    """Decode symbols/bits for a confirmed bpsk/qpsk/8psk/fsk2/ask2 candidate.

    Returns candidate merged with: decoded_symbol_indices (list[int] or
    None), decoded_symbol_count, decode_phase_offset_rad (PSK only),
    decode_confidence, decode_rotation_ambiguity_modulus (order, or None),
    decode_status (always explains the result, whether decoded or declined).
    """
    out = {**candidate, "decoded_symbol_indices": None, "decoded_symbol_count": None,
           "decode_phase_offset_rad": None, "decode_confidence": None,
           "decode_rotation_ambiguity_modulus": None,
           "decode_status": "not attempted (requires a confirmed bpsk/qpsk/8psk/fsk2/ask2 fine label)"}
    label = candidate.get("fine_modulation_label")
    method = DECODE_FAMILY_METHOD.get(label)
    if method is None:
        return out
    snr = candidate.get("snr_db")
    if snr is None or not np.isfinite(snr):
        out["decode_status"] = "not attempted (unknown SNR)"
        return out
    min_snr = DECODE_MIN_SNR_DB[label]
    if snr < min_snr:
        out["decode_status"] = f"not attempted (SNR below validated {min_snr} dB gate)"
        return out
    if method == "psk":
        return _decode_psk(capture, candidate, out, label)
    return _decode_fsk_or_ask(capture, candidate, out, label, method)
