"""Analog experts (AM / FM with MDL-chosen message bandwidth) and the null model."""
import numpy as np

from .config import SpikeConfig
from .dsp import TINY, fft_lowpass, parabolic_offset
from .hypothesis import Hypothesis


class AnalogExpert:
    name = "analog"

    def __init__(self, cfg: SpikeConfig):
        self.cfg = cfg

    def fit(self, x: np.ndarray, fs: float) -> Hypothesis:
        n = len(x)
        fc = _carrier_peak(x, fs)
        xd = x * np.exp(-2j * np.pi * fc * np.arange(n) / fs)
        per_param = 0.5 * np.log(n) / n
        dphi = np.angle(xd[1:] * np.conj(xd[:-1]))
        ph_am = np.angle(np.mean(xd))
        amp = np.mean(np.abs(xd))
        best = (np.inf, "AM", np.nan)
        for frac in self.cfg.analog_bandwidths:
            bw = frac * fs
            n_par = 2 * bw * n / fs
            # AM: real message on an aligned carrier
            r = fft_lowpass(np.real(xd * np.exp(-1j * ph_am)), bw, fs).real
            res = np.mean(np.abs(xd - r * np.exp(1j * ph_am)) ** 2) + TINY
            score = np.log(res) + (n_par + 1) * per_param
            if score < best[0]:
                best = (float(score), "AM", float(res))
            # FM: smooth phase, constant amplitude
            ps = np.concatenate([[0], np.cumsum(fft_lowpass(dphi, bw, fs).real)])
            c = np.angle(np.mean(xd * np.exp(-1j * ps)))
            res = np.mean(np.abs(xd - amp * np.exp(1j * (ps + c))) ** 2) + TINY
            score = np.log(res) + (n_par + 2) * per_param
            if score < best[0]:
                best = (float(score), "FM", float(res))
        return Hypothesis(self.name, best[1], None, best[0], best[2])


def _carrier_peak(x: np.ndarray, fs: float) -> float:
    """Strongest spectral line below one bin: 4x zero-padded FFT, parabolic on log power.
    A half-bin error rotates the carrier by pi over the segment and breaks the AM rebuild."""
    nf = 4 << int(np.ceil(np.log2(len(x))))
    mag = np.abs(np.fft.fft(x, nf)) ** 2 + TINY
    k = int(np.argmax(mag))
    d = parabolic_offset(np.log(mag[k - 1]), np.log(mag[k]), np.log(mag[(k + 1) % nf]))
    f = (k + d) * fs / nf
    return f - fs if f > fs / 2 else f


def null_hypothesis(x: np.ndarray) -> Hypothesis:
    """'Nothing here': the rebuild is zero, so the residual is the total power (no cost)."""
    p = float(np.mean(np.abs(x) ** 2))
    return Hypothesis("null", "none", None, float(np.log(p)), p)
