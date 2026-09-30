"""D1 bake-off: GMSK/FSK symbol-timing recovery for SHORT bursts (AIS/rtl_433 scale:
tens to a few hundred symbols), not decode.py's existing long-continuous-stream PSK
case (Gardner, validated on 2,000+ symbol tails -- see backend/pipeline/timing_recovery.py).

Candidates (see docs/DECODE_DESIGN.md Sec 5):
  - Oerder-Meyer: non-data-aided, feedforward, block estimate from the squared
    frequency-discriminator output's DFT bin at the symbol rate. One-shot, no
    convergence transient -- the property that matters for a short burst.
  - Mueller-Mueller: decision-directed feedback loop (same PI-loop *pattern* already
    used by backend/pipeline/timing_recovery.py's Gardner recovery, cited from Rice,
    "Digital Communications: A Discrete-Time Approach", with M&M's own error term
    substituted in -- an independent implementation, not copied from that module).

This script is exploratory measurement only (same status as experiments/readiness/
diagnose.py in this project): it is not imported by production code and is not
unit-tested. Its output decides which method backend/pipeline/decode.py implements
for real; the loser's numbers are recorded in DECODING.md, not deleted.
"""
import numpy as np


def make_cpfsk_burst(seed, snr_db, n_bits, sps=8, h=0.5, levels=2, random_delay=True):
    """Binary (or M-level) CPFSK burst with known bits, unit-power AWGN at snr_db,
    and (by default) a random fractional start delay in [0, sps) -- a real capture's
    symbol boundary is never conveniently aligned to sample 0, and testing both
    methods only at exact alignment would flatter whichever one's initial guess
    happens to match the fixture's own coincidental phase.
    Rectangular frequency pulse (no Gaussian shaping -- GMSK's BT=0.4 shaping is a
    separate, smaller refinement measured once this base case is settled).
    """
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, levels, n_bits)
    dev = (bits - (levels - 1) / 2) * h / sps  # cycles/sample
    pad = int(np.ceil(sps))
    freq = np.repeat(dev, sps)
    delay = rng.uniform(0, sps) if random_delay else 0.0
    shift = int(np.floor(delay))
    frac = delay - shift
    freq = np.concatenate([np.full(pad, freq[0]), freq])
    phase = 2 * np.pi * np.cumsum(freq)
    x = np.exp(1j * phase)
    if frac > 0:
        x = x[:-1] * (1 - frac) + x[1:] * frac
    x = x[pad - shift:]
    noise_power = 1.0 / (10 ** (snr_db / 10))
    noise = (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x))) * np.sqrt(noise_power / 2)
    return (x + noise).astype(np.complex128), bits


def discriminator(x):
    """Instantaneous frequency, cycles/sample (angle of consecutive-sample product / 2pi)."""
    d = np.angle(x[1:] * np.conj(x[:-1])) / (2 * np.pi)
    return np.append(d, d[-1])


def oerder_meyer_tau(y, sps):
    """Fractional-sample symbol epoch (0..sps) from the DFT-at-symbol-rate phase of y^2."""
    y2 = (y - np.mean(y)) ** 2
    n = np.arange(len(y2))
    bin_ = np.sum(y2 * np.exp(-2j * np.pi * n / sps))
    if abs(bin_) == 0:
        return 0.0
    return float((-np.angle(bin_) / (2 * np.pi)) % 1.0 * sps)


def _integrate(y, center, sps):
    """Mean of y over the sps-sample window centred on `center` (integrate-and-dump:
    the correct discriminator receiver structure -- a single point sample is noise-
    dominated at moderate SNR; averaging over the symbol interval is the matched
    filter for a constant-frequency tone, see e.g. Proakis, Digital Communications,
    Ch.5 noncoherent FSK detection)."""
    lo = int(round(center - sps / 2))
    hi = lo + sps
    if lo < 0 or hi > len(y):
        return 0.0
    return float(np.mean(y[lo:hi]))


def mueller_muller_tau_trace(y, sps, loop_bw=0.02, damping=1.0):
    """Decision-directed M&M loop (binary hard decisions on the integrate-and-dump
    discriminator output), same PI-loop structure as timing_recovery's Gardner
    recovery. Returns the per-symbol tau trace (samples) and the recovered decisions.
    """
    theta = loop_bw / (damping + 1.0 / (4.0 * damping))
    denom = 1.0 + 2.0 * damping * theta + theta ** 2
    kp, ki = (4.0 * damping * theta) / denom, (4.0 * theta ** 2) / denom
    tau, freq_est, integ = sps / 2.0, 0.0, 0.0
    decisions, taus = [], []
    prev_a, prev_y = 0.0, 0.0
    n = 0.0
    while True:
        center = n + tau
        if center - sps / 2 < 0 or center + sps / 2 >= len(y):
            break
        yk = _integrate(y, center, sps)
        a = 1.0 if yk > 0 else -1.0
        err = prev_a * yk - a * prev_y
        integ += ki * err
        freq_est = integ
        tau_step = sps + kp * err + freq_est
        decisions.append(a)
        taus.append(center)
        prev_a, prev_y = a, yk
        n += tau_step if len(decisions) > 1 else sps
    return np.array(taus), np.array(decisions)


def _align_ber(decisions, truth_bits, max_shift=3):
    """Best-fit-aligned bit error rate (validation-only alignment, mirrors
    test_decode.py's best_alignment_ser for PSK): resolves start-offset and
    polarity, which -- like decode.py's PSK rotation ambiguity -- a single
    burst with no known preamble cannot resolve on its own."""
    dec = (np.asarray(decisions) > 0).astype(int)
    best = 1.0
    for polarity in (0, 1):
        d = dec if polarity == 0 else 1 - dec
        for shift in range(-max_shift, max_shift + 1):
            if shift >= 0:
                t = truth_bits[shift:shift + len(d)]
                dd = d[:len(t)]
            else:
                t = truth_bits[:len(d) + shift]
                dd = d[-shift:-shift + len(t)]
            if len(t) == 0:
                continue
            best = min(best, np.mean(t != dd))
    return best


def run(n_bits=300, sps=8, h=0.5, seeds=range(20)):
    rows = []
    for snr_db in (-2, 0, 3, 6, 10, 15):
        om_bers, mm_bers = [], []
        for seed in seeds:
            x, bits = make_cpfsk_burst(seed, snr_db, n_bits, sps, h)
            y = discriminator(x)

            tau = oerder_meyer_tau(y, sps)
            centers = tau + np.arange(n_bits) * sps
            in_range = (centers - sps / 2 >= 0) & (centers + sps / 2 < len(y))
            om_vals = np.array([_integrate(y, c, sps) for c in centers[in_range]])
            om_dec = (om_vals > 0.0).astype(int)
            om_bers.append(_align_ber(om_dec * 2 - 1, bits[in_range]))

            _, mm_dec = mueller_muller_tau_trace(y, sps)
            mm_bers.append(_align_ber(mm_dec, bits))
        rows.append((snr_db, float(np.mean(om_bers)), float(np.mean(mm_bers))))
    return rows


if __name__ == "__main__":
    print(f"{'SNR dB':>7} {'OM BER':>10} {'MM BER':>10}")
    for snr_db, om, mm in run():
        print(f"{snr_db:>7} {om:>10.4f} {mm:>10.4f}")
