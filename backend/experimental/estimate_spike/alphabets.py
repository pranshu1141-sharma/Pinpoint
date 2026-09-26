"""Finite symbol alphabets and block-wise snapping (amplitude + phase tracked per block)."""
import numpy as np
from scipy.stats import poisson

_LEVELS = np.array([-3, -1, 1, 3.0])
ALPHABETS = {
    2: np.array([1.0 + 0j, -1.0 + 0j]),
    4: np.array([1 + 1j, 1 - 1j, -1 + 1j, -1 - 1j]) / np.sqrt(2),
    8: np.exp(2j * np.pi * np.arange(8) / 8),
    16: (_LEVELS[:, None] + 1j * _LEVELS[None, :]).ravel() / np.sqrt(10),
}
LABEL = {2: "BPSK", 4: "QPSK", 8: "8PSK", 16: "QAM16"}


def usage_ratio(idx: np.ndarray, order: int) -> float:
    """p-value that every alphabet point is in use: probability, under uniform use of all
    `order` points, of a least-used count this small, 1 - (1 - PoissonCDF(min; n/order))^order.
    Small values mean a different (e.g. subset) constellation explains the symbols."""
    if len(idx) == 0:
        return 0.0
    c = int(np.bincount(idx, minlength=order).min())
    tail = float(poisson.cdf(c, len(idx) / order))
    return float(1.0 - (1.0 - tail) ** order)


def snap_to_alphabet(m: np.ndarray, order: int, block: int, return_index: bool = False):
    """Snap per-symbol values to the alphabet, fitting one amplitude and phase per block.

    BPSK phase: angle(sum m^2)/2; QPSK/16-QAM: angle(-sum m^4)/4; 8PSK: angle(sum m^8)/8.
    Amplitude: mean |m| / mean |alphabet point|. With return_index, also the point indices.
    """
    k = len(m)
    nb = -(-k // block)
    mp = np.zeros(nb * block, complex)
    mp[:k] = m
    mb = mp.reshape(nb, block)
    valid = np.zeros(nb * block, bool)
    valid[:k] = True
    valid = valid.reshape(nb, block)
    pts = ALPHABETS[order]
    amp = (np.abs(mb) * valid).sum(1) / valid.sum(1) / np.mean(np.abs(pts)) + 1e-12
    if order == 2:
        theta = np.angle((mb ** 2).sum(1)) / 2
    elif order == 8:
        theta = np.angle((mb ** 8).sum(1)) / 8
    else:
        theta = np.angle(-(mb ** 4).sum(1)) / 4
    u = mb * np.exp(-1j * theta)[:, None] / amp[:, None]
    idx = np.argmin(np.abs(u[..., None] - pts), axis=-1)
    rec = ((amp * np.exp(1j * theta))[:, None] * pts[idx]).reshape(-1)[:k]
    return (rec, idx.reshape(-1)[:k]) if return_index else rec
