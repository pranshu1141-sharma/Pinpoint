"""2-tone continuous-phase FSK expert (1 bit/symbol)."""
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .config import SpikeConfig
from .dsp import TINY
from .hypothesis import Hypothesis
from .timing import fine_search, spectral_line_timing


def _kay_hz(s: complex, fs: float) -> float:
    return float(np.angle(s) * fs / (2 * np.pi))


@dataclass(frozen=True)
class _FskInputs:
    """Rate-independent preparation, shared by every rate tried on one segment."""
    fs: float
    nn: np.ndarray
    t: np.ndarray
    xs: np.ndarray        # centred on the median instantaneous frequency
    dd: np.ndarray        # xs[n+1] conj(xs[n]), zero-padded to len(xs)
    fi_track: np.ndarray  # |diff(instantaneous frequency)|, for spectral-line timing


def _prepare(x: np.ndarray, fs: float) -> _FskInputs:
    nn = np.arange(len(x))
    t = nn / fs
    fi = np.angle(x[1:] * np.conj(x[:-1])) * fs / (2 * np.pi)
    f0 = np.median(fi)
    xs = x * np.exp(-2j * np.pi * f0 * t)
    fi = np.append(fi - f0, 0.0)
    dd = np.append(xs[1:] * np.conj(xs[:-1]), 0.0)
    return _FskInputs(fs, nn, t, xs, dd, np.abs(np.diff(fi)))


def _score_at(p: _FskInputs, sps: float, tau: float, blk_syms: int) -> tuple:
    """(score, residual) of the 2-FSK rebuild at samples/symbol `sps` and timing `tau`."""
    fs = p.fs
    u = p.nn / sps + tau
    k = np.floor(u).astype(int)
    k -= k.min()
    frac = u - np.floor(u)
    interior = ((frac * sps > 1.0) & ((1 - frac) * sps > 1.0)).astype(float)
    msk = (k > 0) & (k < k.max())
    nk = k.max() + 1
    # Kay-style: sum complex phase-difference products, take the angle once
    sd = np.bincount(k, p.dd.real * interior, nk) + 1j * np.bincount(k, p.dd.imag * interior, nk)
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
    za = p.xs * np.exp(-2j * np.pi * fa * p.t)
    zb = p.xs * np.exp(-2j * np.pi * fb * p.t)
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
        z = p.xs * np.conj(ph)
        cz = (np.bincount(blk, z.real, nb) + 1j * np.bincount(blk, z.imag, nb)) / cnt
        res = min(res, np.mean(np.abs(p.xs[msk] - (cz[blk] * ph)[msk]) ** 2) + TINY)
    n_eff, n_sym = int(msk.sum()), k.max() - 1
    score = np.log(res) + (n_sym * np.log(2) + 1 + (nb + 2) * np.log(n_eff)) / n_eff
    return (float(score), float(res))


class FskExpert:
    """Rebuild the capture as 2-FSK at a proposed rate.

    Per-symbol frequency uses Kay's estimator (sum x[n+1]conj(x[n]) over symbol
    interiors, one angle) - averaging angles is biased. Timing is searched with
    short phase blocks (wide basin) and scored with long ones.
    """
    name = "fsk"

    def __init__(self, cfg: SpikeConfig):
        self.cfg = cfg

    def _timing(self, p: _FskInputs, rate: float, hint: Optional[float] = None,
                final_scan: bool = True) -> tuple[float, tuple]:
        """Best timing phase at `rate` and the scoring-block result there.

        `hint` is an extra starting timing (e.g. from the needle search); the
        better of the refined starts is kept. `final_scan` adds a dense scan of
        +-cfg.fsk_final_scan samples, because the score is jagged below one sample.
        """
        cfg = self.cfg
        sps = p.fs / rate
        long_fit = lambda tau: _score_at(p, sps, tau, cfg.fsk_score_block)
        steps = (0.25, 0.125, 0.0625)
        tau0 = spectral_line_timing(p.fi_track, rate, p.fs)
        short_tau, _ = fine_search(lambda tau: _score_at(p, sps, tau, cfg.fsk_search_block), tau0, sps,
                                   extra_phases=cfg.fsk_search_phases, steps=steps)
        if not cfg.fsk_rescore_refine:
            return short_tau, long_fit(short_tau)
        starts = [short_tau] if hint is None else [short_tau, hint]
        best = min((fine_search(long_fit, tau, sps, steps=steps) for tau in starts), key=lambda b: b[1][0])
        if final_scan and cfg.fsk_final_scan > 0:
            n = int(round(cfg.fsk_final_scan / cfg.fsk_final_scan_step))
            for j in range(-n, n + 1):
                if j == 0:
                    continue
                tau = (best[0] + j * cfg.fsk_final_scan_step / sps) % 1.0
                result = long_fit(tau)
                if result[0] < best[1][0]:
                    best = (tau, result)
        return best

    def fit(self, x: np.ndarray, xc: np.ndarray, fs: float, rate: float,
            timing_hint: Optional[float] = None) -> Optional[Hypothesis]:
        _, (score, res) = self._timing(_prepare(x, fs), rate, timing_hint)
        if not np.isfinite(score):
            return None
        return Hypothesis(self.name, "FSK2", float(rate), score, res)

    def refine_rate(self, x: np.ndarray, fs: float, rate: float) -> tuple[float, Optional[float]]:
        """Needle refinement of one FSK finalist (the rate fit is needle-sharp).

        Joint rate x timing pattern search on the scoring-block model. The state
        is (rate, symbol coordinate at the middle of the segment), so a rate
        step leaves mid-segment alignment unchanged. Start from the timing found
        at the proposed rate, scan a rate grid spanning +-fsk_needle_span, then
        move within the 3x3 rate/timing neighbourhood until no neighbour
        improves, halving both steps each time. Returns (rate, timing phase at
        that rate), the timing to pass to fit() as a hint.
        """
        cfg = self.cfg
        p = _prepare(x, fs)
        centre = (len(x) - 1) / 2
        tau, (s0, _) = self._timing(p, rate, final_scan=False)  # the pattern search moves timing itself
        if not np.isfinite(s0):
            return float(rate), None
        c0 = centre * rate / fs + tau          # symbol coordinate at the centre
        seen: dict[tuple, float] = {}

        def ev(r: float, c: float) -> float:
            key = (round(r, 6), round(c, 6))
            if key not in seen:
                sps = fs / r
                seen[key] = _score_at(p, sps, (c - centre / sps) % 1.0, cfg.fsk_needle_block)[0]
            return seen[key]

        step = cfg.fsk_needle_grid_step
        n = int(round(cfg.fsk_needle_span / step))
        r_best = min((rate * (1 + j * step) for j in range(-n, n + 1)), key=lambda r: ev(r, c0))
        c_best = c0
        t_step = cfg.fsk_needle_timing_step * rate / fs   # samples -> symbols
        while step > cfg.fsk_needle_min_step:
            step /= 2
            t_step = max(t_step / 2, cfg.fsk_needle_min_timing_step * rate / fs)
            for _ in range(cfg.fsk_needle_max_moves):
                cands = [(r_best * (1 + a * step), c_best + b * t_step)
                         for a in (-1, 0, 1) for b in (-1, 0, 1)]
                r_new, c_new = min(cands, key=lambda rc: ev(*rc))
                if (r_new, c_new) == (r_best, c_best):
                    break
                r_best, c_best = r_new, c_new
        return float(r_best), float((c_best - centre * r_best / fs) % 1.0)

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
