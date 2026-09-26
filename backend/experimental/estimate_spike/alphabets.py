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
# Negative orders are unipolar amplitude keying with |order| levels fitted per capture.
LABEL = {2: "BPSK", 4: "QPSK", 8: "8PSK", 16: "QAM16", -2: "ASK2"}


def alphabet_size(order: int) -> int:
    return abs(order)


def extra_params(order: int) -> int:
    """Alphabet parameters fitted per capture (ASK levels), charged 0.5 ln N each."""
    return abs(order) if order < 0 else 0


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
    if order < 0:
        return _snap_ask(m, -order, block, return_index)
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


def _snap_ask(m: np.ndarray, levels: int, block: int, return_index: bool):
    """Unipolar ASK: one carrier phase per block (angle(sum m^2)/2, sign so the mean is
    positive), then `levels` real amplitude levels fitted over the whole capture (the
    amplitude carries the data, so it is not re-normalised per block)."""
    k = len(m)
    nb = -(-k // block)
    mp = np.zeros(nb * block, complex)
    mp[:k] = m
    mb = mp.reshape(nb, block)
    theta = np.angle((mb ** 2).sum(1)) / 2
    u = mb * np.exp(-1j * theta)[:, None]
    flip = u.real.sum(1) < 0
    theta = theta + np.pi * flip
    r = (mb * np.exp(-1j * theta)[:, None]).real.reshape(-1)[:k]
    c = np.quantile(r, (np.arange(levels) + 0.5) / levels)
    for _ in range(8):
        lab = np.argmin(np.abs(r[:, None] - c[None, :]), axis=1)
        c = np.array([r[lab == i].mean() if np.any(lab == i) else c[i] for i in range(levels)])
        c = np.maximum(c, 0.0)          # unipolar: levels share one sign (OOK allows 0); bipolar is PSK
    idx = np.argmin(np.abs(r[:, None] - c[None, :]), axis=1)
    rec = c[idx] * np.exp(1j * np.repeat(theta, block)[:k])
    return (rec, idx) if return_index else rec
