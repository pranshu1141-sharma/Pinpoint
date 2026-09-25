"""Phase 1 acceptance tests for symbol decoding (backend/pipeline/decode.py).

Validates the stated acceptance criterion: at each modulation's gated SNR
(decode.DECODE_MIN_SNR_DB -- bpsk 5 dB, qpsk 8 dB, 8psk 15 dB, each set a
few dB above the measured point SER first clears the target), mean symbol
error rate (SER) after the best-fit global rotation/start-offset alignment
against known truth symbols is <=2% over 10 seeds. The alignment search is
a validation-only tool -- backend/pipeline/decode.py itself never sees the
truth symbols or resolves that ambiguity; see its module docstring and
DECODING.md for the full measured SER-vs-SNR sweep that set these gates.

Fixture style mirrors test_timing_recovery.py (TX-only root-raised-cosine
shaping, no RX matched filter): backend/pipeline/classify.corrected_segment,
the real production path, applies no RX matched filtering either (the real
pulse shape is not known a priori for an arbitrary captured signal), so this
is the representative case, not the more optimistic matched-filter fixture
qam_order's tests use for a different, already-documented reason.
"""
import numpy as np
import pytest
from scipy import signal as scipy_signal

from backend.pipeline import decode
from backend.pipeline.timing_recovery import gardner_timing_recovery

SPS = 8


def _rrc_taps(beta, span_symbols, sps_over):
    n = span_symbols * sps_over
    t = np.arange(-n, n + 1) / sps_over
    h = np.zeros_like(t)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-8:
            h[i] = 1.0 - beta + 4 * beta / np.pi
        elif beta > 0 and abs(abs(ti) - 1 / (4 * beta)) < 1e-8:
            h[i] = (beta / np.sqrt(2)) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta)) + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            h[i] = (np.sin(np.pi * ti * (1 - beta)) + 4 * beta * ti * np.cos(np.pi * ti * (1 + beta))) / (
                np.pi * ti * (1 - (4 * beta * ti) ** 2))
    return h / np.sqrt(np.sum(h ** 2))


def make_psk_fixture(order, snr_db, seed, delay_frac=0.0, n_symbols=40000, sps=SPS, beta=0.35, oversample=16):
    """A pulse-shaped baseband M-PSK segment with known truth symbol
    indices, independent of backend/pipeline/synth_gen.py (which records no
    per-symbol ground truth -- only aggregate metadata) -- generalizes
    test_timing_recovery.make_timing_fixture to arbitrary PSK order and
    returns the truth indices needed to measure SER.
    """
    rng = np.random.default_rng(seed)
    truth = rng.integers(0, order, n_symbols)
    symbols = np.exp(2j * np.pi * truth / order)
    sps_over = sps * oversample
    taps = _rrc_taps(beta, 6, sps_over)
    upsampled = np.zeros(n_symbols * sps_over, dtype=complex)
    upsampled[::sps_over] = symbols
    shaped = scipy_signal.fftconvolve(upsampled, taps, mode="full")
    group_delay = (len(taps) - 1) // 2
    start = group_delay + int(round(delay_frac * sps_over))
    x = shaped[start:start + (n_symbols - 8) * sps_over:oversample]
    noise_power = np.mean(np.abs(x) ** 2) / (10 ** (snr_db / 10))
    noise = (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x))) * np.sqrt(noise_power / 2)
    return (x + noise).astype(np.complex128), truth


def best_alignment_ser(decoded, truth_tail, order, max_shift=16):
    """Minimum symbol error rate over every cyclic rotation (mod order) and
    a small start-offset shift window -- resolves the rotation/small
    residual-alignment ambiguity decode.py itself deliberately leaves open,
    for measurement purposes only. `truth_tail` must already be the truth
    symbols aligned to the same trailing window as `decoded` (Gardner's
    recovered-symbol count tracks the input truth length to within a few
    symbols of startup/end trimming, not from an arbitrary offset -- see
    the caller). Mirrors how a real evaluation would need a short known
    reference to align to, which this project does not have in production
    (see decode.py's module docstring)."""
    decoded = np.asarray(decoded)
    truth_tail = np.asarray(truth_tail)
    best = 1.0
    for shift in range(-max_shift, max_shift + 1):
        if shift >= 0:
            t = truth_tail[shift:shift + len(decoded)]
            d = decoded[:len(t)]
        else:
            t = truth_tail[:len(decoded) + shift]
            d = decoded[-shift:-shift + len(t)]
        if len(t) == 0:
            continue
        for rot in range(order):
            errors = np.sum(((t + rot) % order) != d)
            ser = errors / len(t)
            best = min(best, ser)
    return best


@pytest.mark.parametrize("order,label", [(2, "bpsk"), (4, "qpsk"), (8, "8psk")])
def test_symbol_error_rate_within_2_percent_at_gated_snr_across_10_seeds(order, label):
    snr_db = decode.DECODE_MIN_SNR_DB[label]
    sers = []
    for seed in range(10):
        rng = np.random.default_rng(1000 + seed)
        delay = rng.uniform(-0.15, 0.15)
        x, truth = make_psk_fixture(order, snr_db, seed, delay)
        recovery = gardner_timing_recovery(x, SPS)
        assert recovery["lock_indicator"]
        symbols_full = recovery["symbols"]
        symbols = symbols_full[-decode.DECODE_MIN_TAIL_SYMBOLS:]
        truth_tail = truth[-len(symbols_full):][-decode.DECODE_MIN_TAIL_SYMBOLS:]
        idx, phase_hat, confidence = decode.demap_psk_symbols(symbols, order)
        assert idx is not None
        ser = best_alignment_ser(idx, truth_tail, order)
        sers.append(ser)
    mean_ser = float(np.mean(sers))
    assert mean_ser <= 0.02, f"{label}@{snr_db}dB mean SER={mean_ser:.4f} sers={sers}"


# Each below-gate SNR is a measured point (see DECODING.md's full sweep)
# where mean SER is clearly above the 2% target for that modulation --
# spaced by the modulation's own measured cliff, not a fixed offset from
# its gate (bpsk/qpsk/8psk clear 2% at very different margins above their
# respective cliffs).
BELOW_GATE_SNR_DB = {"bpsk": 1.0, "qpsk": 4.0, "8psk": 10.0}


@pytest.mark.parametrize("label,order", [("bpsk", 2), ("qpsk", 4), ("8psk", 8)])
def test_below_gated_snr_symbol_error_rate_exceeds_2_percent(label, order):
    """Documents why the gate sits where it does: at a measured point below
    DECODE_MIN_SNR_DB, mean SER is clearly above the 2% target -- the gate
    tracks a real measured cliff, not an arbitrary round number."""
    below_snr = BELOW_GATE_SNR_DB[label]
    sers = []
    for seed in range(10):
        rng = np.random.default_rng(1000 + seed)
        delay = rng.uniform(-0.15, 0.15)
        x, truth = make_psk_fixture(order, below_snr, seed, delay)
        recovery = gardner_timing_recovery(x, SPS)
        if not recovery["lock_indicator"]:
            continue
        symbols_full = recovery["symbols"]
        symbols = symbols_full[-decode.DECODE_MIN_TAIL_SYMBOLS:]
        truth_tail = truth[-len(symbols_full):][-decode.DECODE_MIN_TAIL_SYMBOLS:]
        idx, phase_hat, confidence = decode.demap_psk_symbols(symbols, order)
        sers.append(best_alignment_ser(idx, truth_tail, order))
    assert sers, f"{label}@{below_snr}dB never locked across 10 seeds"
    mean_ser = float(np.mean(sers))
    assert mean_ser > 0.02, f"{label}@{below_snr}dB mean SER={mean_ser:.4f} (expected above 2% gate)"


def test_decode_candidate_end_to_end_gates_and_status():
    """decode_candidate declines with an explicit status for every gate
    (unconfirmed label, low SNR, missing symbol rate) and produces a
    plausible symbol stream, with the documented ambiguity fields set,
    once every gate is cleared."""
    from backend.pipeline.ingest import Capture

    base_candidate = {
        "fine_modulation_label": None, "snr_db": 20.0, "symbol_rate_hz": 6000.0,
        "center_frequency_hz": 0.0, "freq_lower_hz": -3000.0, "freq_upper_hz": 3000.0,
        "start_sample": 0, "end_sample": 1000, "is_pulsed": False,
    }
    capture = Capture(np.zeros(1000, dtype=np.complex64), 48000.0, {"source_kind": "iq"})

    out = decode.decode_candidate(capture, base_candidate)
    assert out["decoded_symbol_indices"] is None
    assert "requires a confirmed" in out["decode_status"]

    low_snr = {**base_candidate, "fine_modulation_label": "bpsk", "snr_db": 5.0}
    out = decode.decode_candidate(capture, low_snr)
    assert out["decoded_symbol_indices"] is None
    assert "SNR below" in out["decode_status"]

    no_rate = {**base_candidate, "fine_modulation_label": "bpsk", "symbol_rate_hz": None}
    out = decode.decode_candidate(capture, no_rate)
    assert out["decoded_symbol_indices"] is None
    assert "symbol-rate" in out["decode_status"]

    order, snr_db = 2, 20
    fs = 48000
    symbol_rate = fs / SPS
    x, truth = make_psk_fixture(order, snr_db, seed=1, n_symbols=40000, sps=SPS)
    lo, hi = -symbol_rate * 1.5, symbol_rate * 1.5
    n = len(x)
    padded = np.zeros(n + 256, dtype=np.complex64)
    padded[128:128 + n] = x
    capture2 = Capture(padded, fs, {"source_kind": "iq"})
    candidate = {
        "fine_modulation_label": "bpsk", "snr_db": float(snr_db), "symbol_rate_hz": float(symbol_rate),
        "center_frequency_hz": 0.0, "center_frequency_refined_hz": 0.0,
        "freq_lower_hz": lo, "freq_upper_hz": hi,
        "start_sample": 0, "end_sample": len(padded), "is_pulsed": False,
    }
    out = decode.decode_candidate(capture2, candidate)
    assert out["decoded_symbol_indices"] is not None
    assert out["decoded_symbol_count"] == decode.DECODE_MIN_TAIL_SYMBOLS
    assert out["decode_rotation_ambiguity_modulus"] == order
    assert 0.0 <= out["decode_confidence"] <= 1.0
    assert "correct only up to an unknown constant rotation" in out["decode_status"]
