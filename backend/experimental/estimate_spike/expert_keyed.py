"""Rate-free keyed two-level expert: OOK (two amplitude levels) and 2-FSK (two IF levels) with free transition times.

Real keyed bursts (pulse-width/position OOK, packet FSK) do not sit on one symbol grid, so the rate
experts cannot rebuild them and a free-form AM/FM envelope wins (readiness step 2 diagnosis). This
expert segments the burst into runs of two states and rebuilds it run by run. Each transition costs
ln N nats (one arbitrary position), each real parameter 0.5 ln N, as the other experts charge, so a
continuous analog message (a transition every few samples) loses to AM/FM and a fixed-rate symbol
stream loses to the rate experts (ln M nats per symbol). No symbol rate is claimed (rate is None).
"""
import numpy as np

from .config import SpikeConfig
from .dsp import TINY
from .expert_analog import _carrier_peak
from .hypothesis import Hypothesis

SMOOTH = (1, 3, 5)          # moving-average lengths tried for the state statistic
MIN_RUN = (1, 2, 3)         # runs shorter than this are merged into their neighbours
OOK_CONTRAST = 2.0          # on level >= 2x the off rms (6 dB), else not keyed
FSK_SEPARATION = 2.0        # tone split >= 2x the within-tone spread of the smoothed IF


def _smooth(v: np.ndarray, w: int) -> np.ndarray:
    return v if w == 1 else np.convolve(v, np.ones(w) / w, mode="same")


def _two_means(v: np.ndarray) -> tuple[float, float]:
    """1-D 2-means (Lloyd), started at the 10th/90th percentiles."""
    lo, hi = np.percentile(v, (10, 90))
    for _ in range(20):
        thr = 0.5 * (lo + hi)
        a, b = v[v <= thr], v[v > thr]
        if not len(a) or not len(b):
            break
        lo, hi = float(a.mean()), float(b.mean())
    return float(lo), float(hi)


def _runs(state: np.ndarray, min_run: int) -> list[tuple[int, int, bool]]:
    """[(start, end, state)] with runs shorter than min_run merged into the previous run."""
    edges = np.flatnonzero(np.diff(state.astype(np.int8))) + 1
    bounds = np.concatenate([[0], edges, [len(state)]])
    runs: list[list] = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        s = bool(state[a])
        if runs and (b - a < min_run or runs[-1][2] == s):
            runs[-1][1] = b
        else:
            runs.append([int(a), int(b), s])
    # a short first run cannot merge backwards: fold it forwards
    if len(runs) > 1 and runs[0][1] - runs[0][0] < min_run:
        runs[1][0] = 0
        runs.pop(0)
    merged: list[list] = []
    for r in runs:
        if merged and merged[-1][2] == r[2]:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [tuple(r) for r in merged]


class KeyedExpert:
    name = "keyed"

    def __init__(self, cfg: SpikeConfig):
        self.cfg = cfg

    def fit(self, x: np.ndarray, fs: float) -> list[Hypothesis]:
        return [h for h in (self._ook(x, fs), self._fsk(x, fs)) if h is not None]

    def _ook(self, x: np.ndarray, fs: float):
        n = len(x)
        xd = x * np.exp(-2j * np.pi * _carrier_peak(x, fs) * np.arange(n) / fs)
        per_param, per_edge = 0.5 * np.log(n) / n, np.log(n) / n
        env = np.abs(xd)
        best = None
        for w in SMOOTH:
            e = _smooth(env, w)
            lo, hi = _two_means(e)
            on = e > 0.5 * (lo + hi)
            for m in MIN_RUN:
                runs = _runs(on, m)
                on_runs = [(a, b) for a, b, s in runs if s]
                off = np.concatenate([xd[a:b] for a, b, s in runs if not s]) if len(on_runs) < len(runs) else xd[:0]
                if len(on_runs) < 2 or not len(off):
                    continue
                rebuild = np.zeros(n, complex)
                for a, b in on_runs:
                    rebuild[a:b] = xd[a:b].mean()
                on_level = np.mean([abs(rebuild[a]) for a, _ in on_runs])
                if on_level < OOK_CONTRAST * np.sqrt(np.mean(np.abs(off) ** 2)):
                    continue
                res = float(np.mean(np.abs(xd - rebuild) ** 2) + TINY)
                score = np.log(res) + 2 * len(on_runs) * per_param + (len(runs) - 1) * per_edge
                if best is None or score < best[0]:
                    best = (float(score), res)
        return None if best is None else Hypothesis(self.name, "ASK2", None, best[0], best[1])

    def _fsk(self, x: np.ndarray, fs: float):
        n = len(x)
        per_param, per_edge = 0.5 * np.log(n) / n, np.log(n) / n
        inst = np.angle(x[1:] * np.conj(x[:-1])) * fs / (2 * np.pi)
        inst = np.concatenate([inst[:1], inst])
        best = None
        for w in SMOOTH:
            f = _smooth(inst, w)
            f0, f1 = _two_means(f)
            hi = f > 0.5 * (f0 + f1)
            spread = np.sqrt(np.mean(np.where(hi, f - f1, f - f0) ** 2))
            if f1 - f0 < FSK_SEPARATION * spread:
                continue
            for m in MIN_RUN:
                runs = _runs(hi, m)
                if sum(s for *_, s in runs) < 2 or sum(not s for *_, s in runs) < 2:
                    continue
                state = np.zeros(n, bool)
                for a, b, s in runs:
                    state[a:b] = s
                # tone levels from the run members, then a phase-continuous two-tone rebuild
                g0, g1 = float(np.median(f[~state])), float(np.median(f[state]))
                phase = np.cumsum(2 * np.pi * np.where(state, g1, g0) / fs)
                unit = np.exp(1j * phase)
                proj = x * np.conj(unit)
                amp = float(np.mean(np.abs(proj)))
                rebuild = np.empty(n, complex)
                for a, b, _ in runs:
                    rebuild[a:b] = amp * unit[a:b] * np.exp(1j * np.angle(proj[a:b].sum()))
                res = float(np.mean(np.abs(x - rebuild) ** 2) + TINY)
                score = np.log(res) + (3 + len(runs)) * per_param + (len(runs) - 1) * per_edge
                if best is None or score < best[0]:
                    best = (float(score), res)
        return None if best is None else Hypothesis(self.name, "FSK2", None, best[0], best[1])
