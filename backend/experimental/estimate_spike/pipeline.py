"""propose -> verify Estimate spike (v5): one detected segment in, all scored hypotheses out."""
import time
from dataclasses import dataclass, field

import numpy as np

from .config import DEFAULT, SpikeConfig
from .dsp import derotate, mth_power_carrier, noise_variance, rate_band
from .expert_analog import AnalogExpert, null_hypothesis
from .expert_fsk import FskExpert
from .experts_psk import NrzPskExpert, RrcPskExpert
from .features import router_features
from .hypothesis import ALL_EXPERTS, Hypothesis
from .proposals import fsk_proposals, needle_refine, psk_proposals, rank_fsk, rank_psk


@dataclass
class SpikeResult:
    hypotheses: list[Hypothesis]
    features: dict[str, float]
    noise_var: float
    total_power: float
    carrier_hz: float
    psk_proposals: list[float]
    psk_finalists: list[float]
    fsk_proposals: list[float]
    fsk_finalists: list[float]
    timings_s: dict[str, float] = field(default_factory=dict)  # diagnostic only

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "hypotheses"}
        d["hypotheses"] = [h.to_dict() for h in self.hypotheses]
        return d


def analyze_segment(x: np.ndarray, fs: float, cfg: SpikeConfig = DEFAULT,
                    experts: tuple[str, ...] = ALL_EXPERTS) -> SpikeResult:
    """Score every proposed hypothesis for one complex-baseband segment.

    Deterministic: no randomness. `experts` restricts which experts run
    (the null model always runs). Wall-clock timings are recorded but never
    influence the result.
    """
    x = np.asarray(x)
    if not np.iscomplexobj(x) or x.ndim != 1:
        raise ValueError("Segment must be a 1-D complex baseband array.")
    if not (np.isfinite(fs) and fs > 0):
        raise ValueError("Sample rate must be positive and finite.")
    if len(x) < cfg.min_samples:
        raise ValueError(f"Segment needs at least {cfg.min_samples} samples.")
    if not np.all(np.isfinite(x)):
        raise ValueError("Segment contains NaN or Inf.")
    x = x.astype(np.complex128)
    band = rate_band(fs, cfg.rate_band)
    timings: dict[str, float] = {}

    def timed(key, fn):
        t0 = time.perf_counter()
        out = fn()
        timings[key] = timings.get(key, 0.0) + time.perf_counter() - t0
        return out

    feats = timed("features", lambda: router_features(x))

    def screen_psk():
        f = mth_power_carrier(x, fs, cfg.nfft, cfg.carrier_power)
        xc = derotate(x, f, fs)
        props = psk_proposals(xc, fs, band, cfg)
        fin = needle_refine(xc, fs, rank_psk(xc, fs, props, cfg), band, cfg)
        return f, xc, props, fin
    carrier, xc, pprops, pfin = timed("screen_psk", screen_psk)

    def screen_fsk():
        props = fsk_proposals(x, fs, band, cfg)
        return props, rank_fsk(x, fs, props, cfg)
    fprops, ffin = timed("screen_fsk", screen_fsk) if "fsk" in experts else ([], [])

    hyps: list[Hypothesis] = []
    rate_experts = {"nrz": (NrzPskExpert(cfg), pfin), "rrc": (RrcPskExpert(cfg), pfin),
                    "fsk": (FskExpert(cfg), ffin)}
    for name in ("nrz", "rrc", "fsk"):
        if name not in experts:
            continue
        expert, rates = rate_experts[name]
        fits = timed(name, lambda: [expert.fit(x, xc, fs, r) for r in rates])
        hyps += [h for h in fits if h is not None]
    if "analog" in experts:
        hyps.append(timed("analog", lambda: AnalogExpert(cfg).fit(x, fs)))
    hyps.append(null_hypothesis(x))

    return SpikeResult(hypotheses=hyps, features=feats, noise_var=noise_variance(xc, fs),
                       total_power=float(np.mean(np.abs(x) ** 2)), carrier_hz=float(carrier),
                       psk_proposals=pprops, psk_finalists=pfin, fsk_proposals=fprops,
                       fsk_finalists=ffin, timings_s=timings)
