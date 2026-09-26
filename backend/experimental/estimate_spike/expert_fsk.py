"""Continuous-phase M-FSK expert (M = 2, 4: log2 M bits/symbol)."""
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


def _tone_clusters(mf: np.ndarray, sd: np.ndarray, fs: float, tones: int):
    """Tone frequencies from per-symbol frequencies (k-means with Kay tone estimates), or None."""
    inner, sdi = mf[1:-1], sd[1:-1]
    if tones == 2:
        if not (inner > 0).any() or not (inner <= 0).any():
            return None
        dec = mf > 0
        for _ in range(4):  # 2-means with Kay tone estimates
            di = dec[1:-1]
            fa = _kay_hz(sdi[di].sum(), fs) if di.any() else 0.0
            fb = _kay_hz(sdi[~di].sum(), fs) if (~di).any() else 0.0
            dec = np.abs(mf - fa) < np.abs(mf - fb)
        return np.array([fa, fb])
    c = np.quantile(inner, (np.arange(tones) + 0.5) / tones)
    for _ in range(6):
        lab = np.argmin(np.abs(inner[:, None] - c[None, :]), axis=1)
        if len(set(lab.tolist())) < tones:
            return None
        c = np.array([_kay_hz(sdi[lab == i].sum(), fs) for i in range(tones)])
    return c


def _score_at(p: _FskInputs, sps: float, tau: float, blk_syms: int, tones: int = 2) -> tuple:
    """(score, residual) of the M-FSK rebuild at samples/symbol `sps` and timing `tau`."""
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
    c = _tone_clusters(mf, sd, fs, tones)
    if c is None:
        return (np.inf, np.nan)
    decisions = [np.argmin(np.abs(mf[:, None] - c[None, :]), axis=1)]
    if tones == 2:   # non-coherent energy decisions too (one complex exponential per tone: 2-FSK only)
        energy = np.stack([np.abs(np.bincount(k, z.real, nk) + 1j * np.bincount(k, z.imag, nk))
                           for z in (p.xs * np.exp(-2j * np.pi * f * p.t) for f in c)], 1)
        decisions.append(np.argmax(energy, axis=1))
    blk = k // blk_syms
    nb = blk.max() + 1
    cnt = np.maximum(np.bincount(blk, minlength=nb), 1)
    res = np.inf
    # keep the better rebuild of the decision rules
    for sel in decisions:
        tone = c[sel][k]
        ph = np.exp(1j * 2 * np.pi * np.cumsum(tone) / fs)
        z = p.xs * np.conj(ph)
        cz = (np.bincount(blk, z.real, nb) + 1j * np.bincount(blk, z.imag, nb)) / cnt
        res = min(res, np.mean(np.abs(p.xs[msk] - (cz[blk] * ph)[msk]) ** 2) + TINY)
    n_eff, n_sym = int(msk.sum()), k.max() - 1
    score = np.log(res) + (n_sym * np.log(tones) + 1 + (nb + tones) * np.log(n_eff)) / n_eff
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
            timing_hint: Optional[float] = None, tones_set: Optional[tuple] = None) -> Optional[Hypothesis]:
        """Best of 2-FSK (full timing search) and each higher tone count in `tones_set`
        (default cfg.fsk_library_tones; timing refined from the 2-FSK optimum)."""
        cfg = self.cfg
        p = _prepare(x, fs)
        tau, (score, res) = self._timing(p, rate, timing_hint)
        best = (score, res, 2)
        sps = fs / rate
        for tones in (cfg.fsk_library_tones if tones_set is None else tones_set):
            if tones == 2:
                continue
            _, (s_m, r_m) = fine_search(lambda t: _score_at(p, sps, t, cfg.fsk_score_block, tones), tau, sps,
                                        extra_phases=cfg.fsk_quick_phases, steps=(0.25, 0.125, 0.0625))
            if s_m < best[0]:
                best = (s_m, r_m, tones)
        if not np.isfinite(best[0]):
            return None
        return Hypothesis(self.name, f"FSK{best[2]}", float(rate), best[0], best[1])

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
        best = self._needle(p, rate, 2)
        if best[0] is None:
            return float(rate), None
        for m in cfg.fsk_needle_tones:
            if m == 2:
                continue
            # only if m tones still fit better at the refined 2-FSK rate (at an offset rate,
            # drift makes 2-FSK look m-toned, so the tone count is judged after refinement)
            sps = fs / best[1]
            s2 = _score_at(p, sps, best[2], cfg.fsk_score_block, 2)[0]
            _, (sm, _) = fine_search(lambda t: _score_at(p, sps, t, cfg.fsk_score_block, m), best[2], sps,
                                     extra_phases=cfg.fsk_quick_phases)
            if sm < s2:
                cand = self._needle(p, rate, m)
                if cand[0] is not None and cand[0] < sm:
                    best = cand
        return float(best[1]), float(best[2])

    def _needle(self, p: _FskInputs, rate: float, tones: int) -> tuple:
        """(final needle score or None, rate, timing phase) of the joint rate x timing search."""
        cfg = self.cfg
        fs = p.fs
        centre = (len(p.nn) - 1) / 2
        sps0 = fs / rate
        if tones == 2:
            tau, (s0, _) = self._timing(p, rate, final_scan=False)  # the pattern search moves timing itself
        else:
            tau2, _ = self._timing(p, rate, final_scan=False)
            tau, (s0, _) = fine_search(lambda t: _score_at(p, sps0, t, cfg.fsk_score_block, tones), tau2, sps0,
                                       extra_phases=cfg.fsk_quick_phases)
        if not np.isfinite(s0):
            return (None, float(rate), None)
        c0 = centre * rate / fs + tau          # symbol coordinate at the centre
        seen: dict[tuple, float] = {}

        def ev(r: float, c: float) -> float:
            key = (round(r, 6), round(c, 6))
            if key not in seen:
                sps = fs / r
                seen[key] = _score_at(p, sps, (c - centre / sps) % 1.0, cfg.fsk_needle_block, tones)[0]
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
        return (ev(r_best, c_best), float(r_best), float((c_best - centre * r_best / fs) % 1.0))


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
