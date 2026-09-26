"""propose -> verify Estimate spike (v5): one detected segment in, all scored hypotheses out."""
import time
from dataclasses import dataclass, field

import numpy as np

from .config import DEFAULT, SpikeConfig
from .dsp import carrier_estimate, derotate, noise_variance, rate_band
from .expert_analog import AnalogExpert, null_hypothesis
from .expert_fsk import FskExpert
from .experts_psk import LsPulsePskExpert, NrzPskExpert, RrcPskExpert
from .features import router_features
from .hypothesis import ALL_EXPERTS, Hypothesis
from .proposals import (fsk_needle_refine, fsk_proposals, needle_refine, psk_proposals, rank_fsk,
                        rank_psk)


def _fsk_side(x, fs, band, cfg, experts):
    """FSK proposals, needle and fits: independent of the PSK side until pooling."""
    local: dict[str, float] = {}

    def tm(key, fn):
        t0 = time.perf_counter()
        out = fn()
        local[key] = local.get(key, 0.0) + time.perf_counter() - t0
        return out
    if "fsk" not in experts:
        return [], [], [], [], local

    def screen_fsk():
        props = fsk_proposals(x, fs, band, cfg)
        return props, rank_fsk(x, fs, props, cfg)
    fprops, franked = tm("screen_fsk", screen_fsk)
    targets = [(r, None) for r in franked]
    if cfg.fsk_needle and franked:
        top = franked[:cfg.fsk_needle_top]
        targets = tm("needle_fsk", lambda: fsk_needle_refine(x, fs, top, band, cfg))
        targets += [(r, None) for r in franked[cfg.fsk_needle_top:]]
    fsk = FskExpert(cfg)
    fits = tm("fsk", lambda: [fsk.fit(x, x, fs, r, timing_hint=hint) for r, hint in targets])
    return fprops, franked, targets, [h for h in fits if h is not None], local


_POOL = None


def _pool():
    """One persistent worker thread for the FSK side. A worker process would parallelise better
    (the NumPy work is many small GIL-holding calls) but spawning processes from library code
    breaks callers without a __main__ guard, so it is not done. Same code, same result."""
    global _POOL
    if _POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verify-fsk")
    return _POOL


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
    fsk_finalists: list[float]            # after needle refinement when cfg.fsk_needle
    fsk_ranked: list[float]
    timings_s: dict[str, float] = field(default_factory=dict)  # diagnostic only

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "hypotheses"}
        d["hypotheses"] = [h.to_dict() for h in self.hypotheses]
        return d


def analyze_segment(x: np.ndarray, fs: float, cfg: SpikeConfig = DEFAULT,
                    experts: tuple[str, ...] = ALL_EXPERTS,
                    carrier_hint: float | None = None) -> SpikeResult:
    """Score every proposed hypothesis for one complex-baseband segment.

    Deterministic: no randomness. `experts` restricts which experts run
    (the null model always runs). Wall-clock timings are recorded but never
    influence the result. `carrier_hint` is a coarse carrier (e.g. the Detect
    band centre); without it the occupied-PSD centroid is used.
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

    # The PSK/QAM/ASK side and the FSK side share nothing until the hypotheses are
    # pooled, so the FSK side runs on a worker thread (cfg.threads > 1). Each side is the
    # same computation either way; hypotheses are pooled in a fixed order, so the result
    # does not depend on it.
    def psk_side():
        local: dict[str, float] = {}

        def tm(key, fn):
            t0 = time.perf_counter()
            out = fn()
            local[key] = local.get(key, 0.0) + time.perf_counter() - t0
            return out

        def screen_psk():
            f = carrier_estimate(x, fs, cfg.nfft, cfg.carrier_power, carrier_hint)
            xc = derotate(x, f, fs)
            props = psk_proposals(xc, fs, band, cfg)
            fin = needle_refine(xc, fs, rank_psk(xc, fs, props, cfg), band, cfg)
            return f, xc, props, fin
        carrier, xc, pprops, pfin = tm("screen_psk", screen_psk)
        hyps: list[Hypothesis] = []
        for name, expert in (("nrz", NrzPskExpert(cfg)), ("rrc", RrcPskExpert(cfg)), ("lsp", LsPulsePskExpert(cfg))):
            if name in experts:
                fits = tm(name, lambda: [expert.fit(x, xc, fs, r) for r in pfin])
                hyps += [h for h in fits if h is not None]
        analog = [tm("analog", lambda: AnalogExpert(cfg).fit(x, fs))] if "analog" in experts else []
        return carrier, xc, pprops, pfin, hyps, analog, local

    if cfg.threads > 1:
        side_b = _pool().submit(_fsk_side, x, fs, band, cfg, tuple(experts))
        side_a = psk_side()
        side_b = side_b.result()
    else:
        side_a, side_b = psk_side(), _fsk_side(x, fs, band, cfg, tuple(experts))
    carrier, xc, pprops, pfin, psk_hyps, analog, t_a = side_a
    fprops, franked, fsk_targets, fsk_hyps, t_b = side_b
    timings.update(t_a)
    timings.update(t_b)
    ffin = [r for r, _ in fsk_targets]
    hyps: list[Hypothesis] = psk_hyps + fsk_hyps + analog + [null_hypothesis(x)]
    # FM gate: FM may only win if the IF is not on discrete levels. Probe with more tones
    # than the library holds, and only when FM is currently the best explanation.
    if "fsk" in experts and cfg.fsk_probe_tones and min(hyps, key=lambda h: h.score).label == "FM":
        fsk = FskExpert(cfg)
        probes = timed("fsk_probe", lambda: [fsk.fit(x, xc, fs, r, timing_hint=hint, tones_set=cfg.fsk_probe_tones)
                                             for r, hint in fsk_targets])
        hyps += [h for h in probes if h is not None and h.label != "FSK2"]

    return SpikeResult(hypotheses=hyps, features=feats, noise_var=noise_variance(xc, fs),
                       total_power=float(np.mean(np.abs(x) ** 2)), carrier_hz=float(carrier),
                       psk_proposals=pprops, psk_finalists=pfin, fsk_proposals=fprops,
                       fsk_finalists=ffin, fsk_ranked=franked, timings_s=timings)
