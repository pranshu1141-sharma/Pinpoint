"""PSK/QAM experts: rebuild the capture as snapped symbols with a flat (NRZ) or RRC pulse."""
from typing import Optional

import numpy as np

from .alphabets import LABEL, snap_to_alphabet
from .config import SpikeConfig
from .dsp import TINY, rrc_pulse
from .hypothesis import Hypothesis
from .timing import fine_search, spectral_line_timing


def transition_timing(xc: np.ndarray, rate: float, fs: float) -> float:
    return spectral_line_timing(np.abs(np.diff(xc)) ** 2, rate, fs)


def _nrz_at(xc: np.ndarray, sps: float, tau: float, alphabets, block: int) -> tuple:
    """(score, order, residual) for flat symbols at timing tau; partial end symbols dropped."""
    k = np.floor(np.arange(len(xc)) / sps + tau).astype(int)
    k -= k.min()
    msk = (k > 0) & (k < k.max())
    kk = k[msk] - 1
    cnt = np.bincount(kk).astype(float)
    cnt[cnt == 0] = 1
    xm = xc[msk]
    m = (np.bincount(kk, xm.real) + 1j * np.bincount(kk, xm.imag)) / cnt
    n_eff, n_sym = int(msk.sum()), len(m)
    best = (np.inf, None, np.nan)
    for order in alphabets:
        rec = snap_to_alphabet(m, order, block)
        res = np.mean(np.abs(xm - rec[kk]) ** 2) + TINY
        score = np.log(res) + (n_sym * np.log(order) + np.ceil(n_sym / block) * np.log(n_eff)) / n_eff
        if score < best[0]:
            best = (float(score), order, float(res))
    return best


def nrz_quick_score(xc: np.ndarray, fs: float, rate: float, cfg: SpikeConfig) -> float:
    """Cheap ranking score: QPSK alphabet only, spectral-line timing only."""
    sps = fs / rate
    return _nrz_at(xc, sps, transition_timing(xc, rate, fs), (4,), cfg.snap_block)[0]


class NrzPskExpert:
    name = "nrz"

    def __init__(self, cfg: SpikeConfig):
        self.cfg = cfg

    def fit(self, x: np.ndarray, xc: np.ndarray, fs: float, rate: float) -> Optional[Hypothesis]:
        sps = fs / rate
        _, (score, order, res) = fine_search(
            lambda tau: _nrz_at(xc, sps, tau, self.cfg.alphabets, self.cfg.snap_block),
            transition_timing(xc, rate, fs), sps)
        if order is None:
            return None
        return Hypothesis(self.name, LABEL[order], float(rate), score, res)


class RrcPskExpert:
    """Matched-filter symbol estimates, snap inner symbols, rebuild with the RRC pulse.

    Removing this expert roughly doubles confident mistakes: flat-block models
    fit RRC signals better at 2x the rate.
    """
    name = "rrc"

    def __init__(self, cfg: SpikeConfig):
        self.cfg = cfg

    def fit(self, x: np.ndarray, xc: np.ndarray, fs: float, rate: float) -> Optional[Hypothesis]:
        cfg, span = self.cfg, self.cfg.rrc_span
        sps = fs / rate
        nn = np.arange(len(xc))
        edge = int(np.ceil((span + 1) * sps))
        msk = np.zeros(len(xc), bool)
        msk[edge:len(xc) - edge] = True
        n_eff = int(msk.sum())
        if n_eff < 256:
            return None
        best = (np.inf, None, np.nan)
        for phi in np.arange(cfg.rrc_phases) / cfg.rrc_phases:
            u = nn / sps - phi
            k0 = np.floor(u).astype(int)
            ks = [k0 + d for d in range(-span, span + 1)]
            ps = [rrc_pulse(u - k, cfg.rrc_alpha) for k in ks]
            kmin = min(k.min() for k in ks)
            ks = [k - kmin for k in ks]
            nk = max(k.max() for k in ks) + 1
            num = sum(np.bincount(k, xc.real * p, nk) + 1j * np.bincount(k, xc.imag * p, nk)
                      for k, p in zip(ks, ps))
            den = sum(np.bincount(k, p * p, nk) for k, p in zip(ks, ps)) + 1e-12
            a = num / den
            inner = slice(span + 1, nk - span - 1)
            n_sym = inner.stop - inner.start
            for order in cfg.alphabets:
                aq = a.copy()
                aq[inner] = snap_to_alphabet(a[inner], order, cfg.snap_block)
                rec = sum(aq[k] * p for k, p in zip(ks, ps))
                res = np.mean(np.abs(xc[msk] - rec[msk]) ** 2) + TINY
                cost = n_sym * np.log(order) + np.ceil(n_sym / cfg.snap_block) * np.log(n_eff) + np.log(n_eff)
                score = np.log(res) + cost / n_eff
                if score < best[0]:
                    best = (float(score), order, float(res))
        if best[1] is None:
            return None
        return Hypothesis(self.name, LABEL[best[1]], float(rate), best[0], best[2])
