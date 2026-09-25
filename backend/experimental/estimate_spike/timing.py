"""Symbol timing: spectral-line phase for the coarse estimate, then a memoized fine search."""
from typing import Callable, Sequence

import numpy as np


def spectral_line_timing(track: np.ndarray, rate: float, fs: float) -> float:
    """Timing phase (fraction of a symbol) from the symbol-rate line of a transition track.

    `track[m]` describes the change between samples m and m+1, hence the (m+1).
    """
    c = np.sum(track * np.exp(-2j * np.pi * rate * (np.arange(len(track)) + 1.0) / fs))
    return float((np.angle(c) / (2 * np.pi)) % 1.0)


def fine_search(fit: Callable[[float], tuple], tau0: float, sps: float,
                extra_phases: int = 0, steps: Sequence[float] = (0.25, 0.125)) -> tuple[float, tuple]:
    """Coarse-to-fine timing search over a fit returning (score, ...) tuples.

    Evaluates tau0 +/- {1, 0.5, 0} samples (plus `extra_phases` evenly spaced
    phases across the symbol), then refines by +/- each of `steps` samples.
    Returns (best timing phase in [0, 1), fit result at that phase).
    """
    seen: dict[float, tuple] = {}

    def ev(tau: float) -> tuple:
        key = round(tau % 1.0, 5)
        if key not in seen:
            seen[key] = fit(key)
        return seen[key]

    taus = [tau0 + o / sps for o in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    taus += [j / extra_phases for j in range(extra_phases)]
    best = min(taus, key=lambda u: ev(u)[0])
    for step in steps:
        best = min((best - step / sps, best, best + step / sps), key=lambda u: ev(u)[0])
    return best % 1.0, ev(best)
