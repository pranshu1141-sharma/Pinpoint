"""Decision rule: lowest MDL score wins; confidence is the margin to competing hypotheses."""
from dataclasses import dataclass, asdict
from typing import Iterable, Optional

import numpy as np

from .config import SpikeConfig, DEFAULT, Thresholds
from .hypothesis import ALL_EXPERTS, DIGITAL_EXPERTS, UNKNOWN_CE, Hypothesis


@dataclass(frozen=True)
class Decision:
    expert: str
    family: str
    label: str
    rate: Optional[float]
    m_fam: float
    m_null: float
    m_rate: float           # NaN for non-digital winners
    unexplained: float      # NaN when the winner is the null model
    tier: str               # "labelled" | "unknown_family" | "abstain"
    label_shipped: bool
    rate_shipped: bool

    @property
    def needs_review(self) -> bool:
        return not self.label_shipped

    def to_json(self) -> dict:
        """SigMF-annotation-shaped summary; margins are nats, not probabilities."""
        return {
            "estimate_spike:family": self.family if self.tier == "labelled" else
            ("unknown" if self.tier == "unknown_family" else None),
            "estimate_spike:label": self.label if self.label_shipped else None,
            "symbol_rate_hz": self.rate if self.rate_shipped else None,
            "confidence": {"family_margin_nats": _num(self.m_fam), "rate_margin_nats": _num(self.m_rate),
                           "null_margin_nats": _num(self.m_null), "unexplained_fraction": _num(self.unexplained)},
            "needs_review": self.needs_review,
            "estimate_spike:tier": self.tier,
            "estimate_spike:best_hypothesis": {"expert": self.expert, "label": self.label, "rate_hz": self.rate},
        }


def _num(v: float) -> Optional[float]:
    return None if v is None or not np.isfinite(v) else float(v)


def decide(hyps: list[Hypothesis], noise_var: float, total_power: float,
           thresholds: Thresholds = Thresholds(), active: Iterable[str] = ALL_EXPERTS,
           cfg: SpikeConfig = DEFAULT) -> Decision:
    """Pick the winner among active experts (+ null) and apply the margin thresholds
    (fit on a calibration split, never on test data)."""
    active = set(active)
    pool = [h for h in hyps if h.expert in active or h.expert == "null"]
    best = min(pool, key=lambda h: h.score)
    null = min((h.score for h in pool if h.expert == "null"), default=np.inf)
    other_fam = [h.score for h in pool if h.family != best.family]
    m_fam = (min(other_fam) - best.score) if other_fam else 0.0
    m_rate = np.nan
    if best.expert in DIGITAL_EXPERTS:
        alt = [h.score for h in pool if h.expert in DIGITAL_EXPERTS
               and abs(h.rate - best.rate) / best.rate >= cfg.rate_margin_tol]
        m_rate = (min(alt) - best.score) if alt else 0.0
    unexplained = np.nan
    if best.family != "none":
        unexplained = max(best.residual - noise_var, 0) / max(total_power - noise_var, 1e-12)
    fam_pass = best.family != "none" and m_fam >= thresholds.m_fam
    # A probe hypothesis (e.g. 8 discrete IF levels) winning means "structure outside the
    # library": FM cannot win it, and no label is published (unknown constant-envelope family).
    label_shipped = bool(fam_pass and unexplained <= thresholds.unexplained_max and best.family != UNKNOWN_CE
                         and best.usage >= thresholds.min_usage)
    rate_shipped = bool(best.expert in DIGITAL_EXPERTS and m_rate >= thresholds.m_rate)
    tier = "labelled" if label_shipped else ("unknown_family" if fam_pass else "abstain")
    return Decision(best.expert, best.family, best.label, best.rate, float(m_fam), float(null - best.score),
                    float(m_rate), float(unexplained), tier, label_shipped, rate_shipped)
