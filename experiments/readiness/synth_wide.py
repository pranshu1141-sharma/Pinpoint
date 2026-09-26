"""Widened copy of backend.pipeline.synth_gen.make_signal (G2). The original is untouched.

Differences from the original, all parameters rather than new shapes:
  * `sps` (samples/symbol) replaces the fixed 96; the smoothing FIR scales with it
    (2*sps+1 taps, cutoff 1.8*Rs), so the pulse shape in symbol units is identical
    to the shipped fixtures at every rate.
  * 4-FSK deviations scale with the rate (+-0.4, +-1.2 Rs), as the original's
    +-200/+-600 Hz were at 500 Bd.
  * held-out families for the abstention criterion: rectangular 8-QAM ("qam8",
    I in {-3,-1,1,3}, Q in {-1,1}) and 8-FSK ("fsk8", deviations (m - 3.5) * 0.4 Rs).
  * returns the noiseless signal too, for ground truth (never given to a system).
"""
import numpy as np
from scipy import signal

FS = 48000
LINEAR = ("bpsk", "qpsk", "8psk", "qam", "qam8")


def smoothing_taps(sps: int) -> np.ndarray:
    return signal.firwin(2 * sps + 1, 1.8 * FS / sps, fs=FS)


def make_signal(kind: str, snr_db: float, carrier_hz: float, sps: int, seed: int, n: int):
    """(x, clean) complex64/complex128 at fs 48 kHz; SNR = full-band signal / complex-noise power."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / FS
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)
    if kind == "noise":
        return noise.astype(np.complex64), np.zeros(n, complex)
    k = n // sps + 1
    rate = FS / sps
    if kind in LINEAR or kind == "ask":
        if kind in ("bpsk", "qpsk", "8psk"):
            order = {"bpsk": 2, "qpsk": 4, "8psk": 8}[kind]
            symbols = np.exp(2j * np.pi * rng.integers(0, order, k) / order)
        elif kind == "qam":
            levels = np.array([-1., -.45, .45, 1.])
            symbols = levels[rng.integers(0, 4, k)] + 1j * levels[rng.integers(0, 4, k)]
        elif kind == "qam8":
            symbols = np.array([-3., -1., 1., 3.])[rng.integers(0, 4, k)] + 1j * np.array([-1., 1.])[rng.integers(0, 2, k)]
        else:
            symbols = np.array([.4, 1.])[rng.integers(0, 2, k)]
        base = signal.fftconvolve(np.repeat(symbols, sps)[:n], smoothing_taps(sps), mode="same")
    elif kind in ("fsk", "fsk8"):
        levels = 4 if kind == "fsk" else 8
        deviations = rate * (np.arange(levels) - (levels - 1) / 2) * 0.8 if levels == 4 else \
            rate * (np.arange(levels) - 3.5) * 0.4
        freq_seq = np.repeat(deviations[rng.integers(0, levels, k)], sps)[:n]
        base = np.exp(1j * 2 * np.pi * np.cumsum(freq_seq) / FS)
    elif kind == "fm":
        base = np.exp(1j * 700 / 230 * np.sin(2 * np.pi * 230 * t))
    else:
        raise ValueError(f"Unknown kind: {kind}")
    base = base / np.sqrt(np.mean(np.abs(base) ** 2)) * 10 ** (snr_db / 20)
    clean = base * np.exp(2j * np.pi * carrier_hz * t)
    return (clean + noise).astype(np.complex64), clean
