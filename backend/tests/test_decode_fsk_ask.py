"""D1 acceptance tests: 2-FSK/GMSK (discriminator) and OOK/ASK2 bit decoding,
backend/pipeline/decode.py.

Timing method: Oerder-Meyer (non-data-aided, feedforward), chosen by the
bake-off in experiments/decode_bakeoff/timing_bakeoff.py -- measured lower BER
than a Mueller-Mueller decision-directed loop at the SNRs these gates target
(100-seed mean, realistic random start delay): 10 dB 2.05% vs 3.45% BER,
15 dB 0.32% vs 1.38% BER. Full sweep in DECODING.md.

Fixture style mirrors test_decode.py's make_psk_fixture: independent of
synth_gen.py/experiments/readiness/impaired.py (neither tracks per-bit
ground truth), own truth-tracking generator, no RX matched filter/integrator
beyond what decode.py's own demapper does.
"""
import numpy as np
import pytest

from backend.pipeline import decode

SPS = 8


def make_cpfsk_fixture(snr_db, seed, n_bits=2000, sps=SPS, h=0.5, delay_frac=None):
    """Binary CPFSK (GMSK's unshaped limit; MSK's h=0.5) baseband segment with
    known truth bits and a random fractional start delay in [0, sps)."""
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, 2, n_bits)
    dev = (bits - 0.5) * h / sps  # cycles/sample
    delay = rng.uniform(0, sps) if delay_frac is None else delay_frac * sps
    pad = int(np.ceil(sps))
    shift = int(np.floor(delay))
    frac = delay - shift
    freq = np.concatenate([np.full(pad, dev[0]), np.repeat(dev, sps)])
    phase = 2 * np.pi * np.cumsum(freq)
    x = np.exp(1j * phase)
    if frac > 0:
        x = x[:-1] * (1 - frac) + x[1:] * frac
    x = x[pad - shift:]
    noise_power = 1.0 / (10 ** (snr_db / 10))
    noise = (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x))) * np.sqrt(noise_power / 2)
    return (x + noise).astype(np.complex128), bits


def make_ook_fixture(snr_db, seed, n_bits=2000, sps=SPS, off_level=0.0, delay_frac=None):
    """Unipolar 2-level ASK (OOK when off_level=0) baseband segment with
    known truth bits and a random fractional start delay in [0, sps)."""
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, 2, n_bits)
    levels = np.where(bits == 1, 1.0, off_level)
    delay = rng.uniform(0, sps) if delay_frac is None else delay_frac * sps
    pad = int(np.ceil(sps))
    shift = int(np.floor(delay))
    frac = delay - shift
    up = np.repeat(np.concatenate([[levels[0]], levels]), sps).astype(complex)
    if frac > 0:
        up = up[:-1] * (1 - frac) + up[1:] * frac
    x = up[sps - shift:]
    x = x * np.exp(1j * rng.uniform(0, 2 * np.pi))  # unknown constant carrier phase
    signal_power = np.mean(np.abs(x) ** 2)
    noise_power = signal_power / (10 ** (snr_db / 10))
    noise = (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x))) * np.sqrt(noise_power / 2)
    return (x + noise).astype(np.complex128), bits


def best_alignment_ber(bits, truth, max_shift=4):
    """Best-fit-aligned bit error rate over polarity and a small start-offset
    window -- validation-only, mirrors test_decode.py's best_alignment_ser;
    decode.py itself never sees truth bits."""
    bits = np.asarray(bits)
    truth = np.asarray(truth)
    best = 1.0
    for polarity in (0, 1):
        b = bits if polarity == 0 else 1 - bits
        for shift in range(-max_shift, max_shift + 1):
            if shift >= 0:
                t = truth[shift:shift + len(b)]
                bb = b[:len(t)]
            else:
                t = truth[:len(b) + shift]
                bb = b[-shift:-shift + len(t)]
            if len(t) == 0:
                continue
            best = min(best, float(np.mean(t != bb)))
    return best


# --- oerder_meyer_symbol_epoch: the shared timing primitive ---

def _grid_search_best_tau(y, sps, n_symbols, truth_bits):
    """Brute-force reference: the tau (0..sps, half-sample steps) whose
    integrate-and-dump decisions best match truth, used only to check
    oerder_meyer_symbol_epoch's estimate against an independent ground
    truth -- not a formula for what tau "should" be from the fixture's own
    delay parameter, which is fragile to restate correctly by hand."""
    best_tau, best_ber = None, 1.0
    for tau in np.arange(0, sps, 0.5):
        vals, in_range = decode._integrate_and_dump(y, tau, sps, n_symbols)
        if len(vals) < n_symbols // 2:
            continue
        bits = (vals > 0).astype(int)
        truth = truth_bits[:len(in_range)][in_range][:len(bits)]
        ber = best_alignment_ber(bits[:len(truth)], truth)
        if ber < best_ber:
            best_ber, best_tau = ber, tau
    return best_tau, best_ber


def test_oerder_meyer_symbol_epoch_matches_grid_search_ber_noiseless():
    """An unshaped rectangular CPFSK pulse has a wide-open eye (only the
    exact transition-boundary sample is ambiguous), so many tau values tie
    at 0% BER -- comparing oerder_meyer_symbol_epoch's raw tau against one
    particular grid-search tau is not a meaningful test here. What has to
    hold is that OM's own tau achieves BER as good as the grid search's
    best, at every tested start delay."""
    sps = SPS
    n_bits = 500
    for true_delay_frac in (0.0, 0.25, 0.5, 0.75):
        x, bits = make_cpfsk_fixture(40.0, seed=1, n_bits=n_bits, sps=sps, delay_frac=true_delay_frac)
        y = decode.fsk_discriminator(x)
        result = decode.oerder_meyer_symbol_epoch(y, sps)
        assert result is not None
        tau, lock = result
        n_symbols = int((len(y) - tau) // sps)
        _, best_ber = _grid_search_best_tau(y, sps, n_symbols, bits)
        assert best_ber < 0.01, f"delay={true_delay_frac}: grid search itself found no good tau"
        vals, in_range = decode._integrate_and_dump(y, tau, sps, n_symbols)
        om_bits = (vals > 0).astype(int)
        truth = bits[:len(in_range)][in_range][:len(om_bits)]
        om_ber = best_alignment_ber(om_bits[:len(truth)], truth)
        assert om_ber < 0.01, f"delay={true_delay_frac} OM tau={tau} BER={om_ber} vs grid-search {best_ber}"


def test_oerder_meyer_symbol_epoch_on_pure_noise_has_low_lock():
    rng = np.random.default_rng(0)
    y = rng.standard_normal(4000)
    result = decode.oerder_meyer_symbol_epoch(y, SPS)
    assert result is not None
    _, lock = result
    assert lock < 0.3, f"pure noise lock={lock} (expected low)"


# --- demap_fsk_bits: BER vs SNR ---

FSK_GATE_SNR_DB = 10.0


def test_fsk_bit_error_rate_within_2_percent_at_gated_snr_across_10_seeds():
    bers = []
    for seed in range(10):
        x, bits = make_cpfsk_fixture(FSK_GATE_SNR_DB, seed, n_bits=2000)
        result = decode.demap_fsk_bits(x, SPS)
        assert result[0] is not None, f"seed={seed} failed to lock at gate SNR"
        recovered_bits, tau, confidence = result
        bers.append(best_alignment_ber(recovered_bits, bits))
    mean_ber = float(np.mean(bers))
    assert mean_ber <= 0.02, f"mean BER={mean_ber:.4f} bers={bers}"


def test_fsk_bit_error_rate_below_gate_exceeds_2_percent():
    below_snr = 4.0
    bers = []
    for seed in range(10):
        x, bits = make_cpfsk_fixture(below_snr, seed, n_bits=2000)
        result = decode.demap_fsk_bits(x, SPS)
        if result[0] is None:
            bers.append(0.5)
            continue
        recovered_bits, tau, confidence = result
        bers.append(best_alignment_ber(recovered_bits, bits))
    mean_ber = float(np.mean(bers))
    assert mean_ber > 0.02, f"below-gate mean BER={mean_ber:.4f} (expected above 2% gate)"


def test_demap_fsk_bits_on_pure_noise_declines():
    """False-decode rate on noise must be 0%: pure noise must never produce
    a confident bit stream."""
    for seed in range(20):
        rng = np.random.default_rng(9000 + seed)
        noise = (rng.standard_normal(2000 * SPS) + 1j * rng.standard_normal(2000 * SPS)) / np.sqrt(2)
        result = decode.demap_fsk_bits(noise, SPS)
        assert result[0] is None, f"seed={seed}: decoded bits from pure noise"


def test_demap_fsk_bits_on_wrong_hypothesis_declines():
    """False-decode rate on a wrong-hypothesis input (a clean PSK segment
    fed to the FSK demapper) must be 0%: constant-envelope PSK has no
    frequency-domain symbol-rate line for the FSK discriminator to lock to
    in the way real FSK does, so it must decline, not fabricate bits."""
    rng = np.random.default_rng(42)
    n_symbols = 2000
    truth = rng.integers(0, 2, n_symbols)
    symbols = np.exp(1j * np.pi * truth)  # BPSK
    x = np.repeat(symbols, SPS).astype(complex)
    noise_power = 1.0 / (10 ** (20.0 / 10))
    noise = (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x))) * np.sqrt(noise_power / 2)
    result = decode.demap_fsk_bits((x + noise).astype(np.complex128), SPS)
    assert result[0] is None, "FSK demapper falsely locked onto a BPSK segment"


# --- demap_ask_bits: BER vs SNR ---

ASK_GATE_SNR_DB = 8.0


def test_ask_bit_error_rate_within_2_percent_at_gated_snr_across_10_seeds():
    bers = []
    for seed in range(10):
        x, bits = make_ook_fixture(ASK_GATE_SNR_DB, seed, n_bits=2000)
        result = decode.demap_ask_bits(x, SPS)
        assert result[0] is not None, f"seed={seed} failed to lock at gate SNR"
        recovered_bits, tau, confidence = result
        bers.append(best_alignment_ber(recovered_bits, bits))
    mean_ber = float(np.mean(bers))
    assert mean_ber <= 0.02, f"mean BER={mean_ber:.4f} bers={bers}"


def test_ask_bit_error_rate_below_gate_exceeds_2_percent():
    below_snr = 2.0
    bers = []
    for seed in range(10):
        x, bits = make_ook_fixture(below_snr, seed, n_bits=2000)
        result = decode.demap_ask_bits(x, SPS)
        if result[0] is None:
            bers.append(0.5)
            continue
        recovered_bits, tau, confidence = result
        bers.append(best_alignment_ber(recovered_bits, bits))
    mean_ber = float(np.mean(bers))
    assert mean_ber > 0.02, f"below-gate mean BER={mean_ber:.4f} (expected above 2% gate)"


def test_demap_ask_bits_on_pure_noise_declines():
    for seed in range(20):
        rng = np.random.default_rng(9500 + seed)
        noise = (rng.standard_normal(2000 * SPS) + 1j * rng.standard_normal(2000 * SPS)) / np.sqrt(2)
        result = decode.demap_ask_bits(noise, SPS)
        assert result[0] is None, f"seed={seed}: decoded bits from pure noise"


# --- decode_candidate dispatch for fsk2/ask2 ---

def _padded_capture(x, fs, symbol_rate):
    from backend.pipeline.ingest import Capture
    n = len(x)
    padded = np.zeros(n + 256, dtype=np.complex64)
    padded[128:128 + n] = x
    lo, hi = -symbol_rate * 1.5, symbol_rate * 1.5
    capture = Capture(padded, fs, {"source_kind": "iq"})
    candidate = {
        "snr_db": None, "symbol_rate_hz": float(symbol_rate),
        "center_frequency_hz": 0.0, "center_frequency_refined_hz": 0.0,
        "freq_lower_hz": lo, "freq_upper_hz": hi,
        "start_sample": 0, "end_sample": len(padded), "is_pulsed": False,
    }
    return capture, candidate


def test_decode_candidate_fsk2_end_to_end():
    fs = 48000.0
    symbol_rate = fs / SPS
    x, bits = make_cpfsk_fixture(20.0, seed=1, n_bits=3000, sps=SPS)
    capture, candidate = _padded_capture(x, fs, symbol_rate)
    candidate.update(fine_modulation_label="fsk2", snr_db=20.0)
    out = decode.decode_candidate(capture, candidate)
    assert out["decoded_symbol_indices"] is not None
    assert out["decode_status"].startswith("decoded")
    assert 0.0 <= out["decode_confidence"] <= 1.0


def test_decode_candidate_ask2_end_to_end():
    fs = 48000.0
    symbol_rate = fs / SPS
    x, bits = make_ook_fixture(20.0, seed=1, n_bits=3000, sps=SPS)
    capture, candidate = _padded_capture(x, fs, symbol_rate)
    candidate.update(fine_modulation_label="ask2", snr_db=20.0)
    out = decode.decode_candidate(capture, candidate)
    assert out["decoded_symbol_indices"] is not None
    assert out["decode_status"].startswith("decoded")


def test_decode_candidate_fsk2_below_gate_declines():
    fs = 48000.0
    symbol_rate = fs / SPS
    x, bits = make_cpfsk_fixture(20.0, seed=1, n_bits=3000, sps=SPS)
    capture, candidate = _padded_capture(x, fs, symbol_rate)
    candidate.update(fine_modulation_label="fsk2", snr_db=2.0)
    out = decode.decode_candidate(capture, candidate)
    assert out["decoded_symbol_indices"] is None
    assert "SNR below" in out["decode_status"]
