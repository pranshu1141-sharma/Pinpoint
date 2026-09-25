"""Finite symbol alphabets and block-wise snapping (amplitude + phase tracked per block)."""
import numpy as np

_LEVELS = np.array([-3, -1, 1, 3.0])
ALPHABETS = {
    2: np.array([1.0 + 0j, -1.0 + 0j]),
    4: np.array([1 + 1j, 1 - 1j, -1 + 1j, -1 - 1j]) / np.sqrt(2),
    16: (_LEVELS[:, None] + 1j * _LEVELS[None, :]).ravel() / np.sqrt(10),
}
LABEL = {2: "BPSK", 4: "QPSK", 16: "QAM16"}


def snap_to_alphabet(m: np.ndarray, order: int, block: int) -> np.ndarray:
    """Snap per-symbol values to the alphabet, fitting one amplitude and phase per block.

    BPSK phase: angle(sum m^2)/2; QPSK/16-QAM: angle(-sum m^4)/4.
    Amplitude: mean |m| / mean |alphabet point|.
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
    else:
        theta = np.angle(-(mb ** 4).sum(1)) / 4
    u = mb * np.exp(-1j * theta)[:, None] / amp[:, None]
    q = pts[np.argmin(np.abs(u[..., None] - pts), axis=-1)]
    return ((amp * np.exp(1j * theta))[:, None] * q).reshape(-1)[:k]
