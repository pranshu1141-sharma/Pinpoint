"""2-tone continuous-phase FSK expert (1 bit/symbol)."""
from typing import Optional

import numpy as np

from .config import SpikeConfig
from .dsp import TINY
from .hypothesis import Hypothesis
from .timing import fine_search, spectral_line_timing


def _kay_hz(s: complex, fs: float) -> float:
    return float(np.angle(s) * fs / (2 * np.pi))


class FskExpert:
    """Rebuild the capture as 2-FSK at a proposed rate.

    Per-symbol frequency uses Kay's estimator (sum x[n+1]conj(x[n]) over symbol
    interiors, one angle) - averaging angles is biased. Timing is searched with
    short phase blocks (wide basin) and scored with long ones.
    """
    name = "fsk"

    def __init__(self, cfg: SpikeConfig):
        self.cfg = cfg

    def fit(self, x: np.ndarray, xc: np.ndarray, fs: float, rate: float) -> Optional[Hypothesis]:
        cfg = self.cfg
        sps = fs / rate
        nn = np.arange(len(x))
        t = nn / fs
        fi = np.angle(x[1:] * np.conj(x[:-1])) * fs / (2 * np.pi)
        f0 = np.median(fi)
        xs = x * np.exp(-2j * np.pi * f0 * t)
        fi = np.append(fi - f0, 0.0)
        dd = np.append(xs[1:] * np.conj(xs[:-1]), 0.0)
        tau0 = spectral_line_timing(np.abs(np.diff(fi)), rate, fs)

        def at(tau: float, blk_syms: int) -> tuple:
            u = nn / sps + tau
            k = np.floor(u).astype(int)
            k -= k.min()
            frac = u - np.floor(u)
            interior = ((frac * sps > 1.0) & ((1 - frac) * sps > 1.0)).astype(float)
            msk = (k > 0) & (k < k.max())
            nk = k.max() + 1
            sd = np.bincount(k, dd.real * interior, nk) + 1j * np.bincount(k, dd.imag * interior, nk)
            mf = np.angle(sd) * fs / (2 * np.pi)
            inner = mf[1:-1]
            if not (inner > 0).any() or not (inner <= 0).any():
                return (np.inf, np.nan)
            dec = mf > 0
            for _ in range(4):  # 2-means with Kay tone estimates
                di = dec[1:-1]
                fa = _kay_hz(sd[1:-1][di].sum(), fs) if di.any() else 0.0
                fb = _kay_hz(sd[1:-1][~di].sum(), fs) if (~di).any() else 0.0
                dec = np.abs(mf - fa) < np.abs(mf - fb)
            za = xs * np.exp(-2j * np.pi * fa * t)
            zb = xs * np.exp(-2j * np.pi * fb * t)
            ea = np.abs(np.bincount(k, za.real, nk) + 1j * np.bincount(k, za.imag, nk))
            eb = np.abs(np.bincount(k, zb.real, nk) + 1j * np.bincount(k, zb.imag, nk))
            blk = k // blk_syms
            nb = blk.max() + 1
            cnt = np.maximum(np.bincount(blk, minlength=nb), 1)
            res = np.inf
            # nearest-tone vs non-coherent energy decisions; keep the better rebuild
            for bits in (np.abs(mf - fa) < np.abs(mf - fb), ea >= eb):
                tone = np.where(bits, fa, fb)[k]
                ph = np.exp(1j * 2 * np.pi * np.cumsum(tone) / fs)
                z = xs * np.conj(ph)
                cz = (np.bincount(blk, z.real, nb) + 1j * np.bincount(blk, z.imag, nb)) / cnt
                res = min(res, np.mean(np.abs(xs[msk] - (cz[blk] * ph)[msk]) ** 2) + TINY)
            n_eff, n_sym = int(msk.sum()), k.max() - 1
            score = np.log(res) + (n_sym * np.log(2) + 1 + (nb + 2) * np.log(n_eff)) / n_eff
            return (float(score), float(res))

        best_tau, _ = fine_search(lambda tau: at(tau, cfg.fsk_search_block), tau0, sps,
                                  extra_phases=cfg.fsk_search_phases, steps=(0.25, 0.125, 0.0625))
        if cfg.fsk_rescore_refine:
            _, (score, res) = fine_search(lambda tau: at(tau, cfg.fsk_score_block), best_tau, sps,
                                          steps=(0.25, 0.125, 0.0625))
        else:
            score, res = at(best_tau, cfg.fsk_score_block)
        if not np.isfinite(score):
            return None
        return Hypothesis(self.name, "FSK2", float(rate), score, res)


def fsk_quick_score(x: np.ndarray, fs: float, rate: float, cfg: SpikeConfig) -> float:
    """Cheap ranking: Fisher ratio of per-symbol frequencies split at the median, best timing."""
    dd = np.append(x[1:] * np.conj(x[:-1]), 0)
    sps = fs / rate
    nn = np.arange(len(x))
    best = -1.0
    for tau in np.arange(cfg.fsk_quick_phases) / cfg.fsk_quick_phases:
        u = nn / sps + tau
        k = np.floor(u).astype(int)
        k -= k.min()
        nk = k.max() + 1
        frac = u - np.floor(u)
        w = ((frac * sps > 1) & ((1 - frac) * sps > 1)).astype(float)
        mf = np.angle(np.bincount(k, dd.real * w, nk) + 1j * np.bincount(k, dd.imag * w, nk))[1:-1]
        thr = np.median(mf)
        a, b = mf[mf > thr], mf[mf <= thr]
        if len(a) > 2 and len(b) > 2:
            best = max(best, (a.mean() - b.mean()) ** 2 / (a.var() + b.var() + 1e-9))
    return float(best)
