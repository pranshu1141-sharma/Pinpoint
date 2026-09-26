"""The common currency of every expert: a scored, rebuildable hypothesis.

score = ln(mean |x - rebuild(x)|^2) + cost_nats / N_eff   (lower is better)
"""
from dataclasses import dataclass, asdict
from typing import Optional, Protocol

import numpy as np

# Hypotheses that only probe for structure outside the library: never published as a label.
UNKNOWN_CE = "unknown constant-envelope"
FAMILY = {"BPSK": "PSK", "QPSK": "PSK", "8PSK": "PSK", "QAM16": "QAM16", "FSK2": "FSK", "FSK4": "FSK", "FSK8": UNKNOWN_CE,
          "AM": "AM", "FM": "FM", "none": "none"}
DIGITAL_EXPERTS = ("nrz", "rrc", "lsp", "fsk")
ALL_EXPERTS = ("nrz", "rrc", "lsp", "fsk", "analog")


@dataclass(frozen=True)
class Hypothesis:
    expert: str
    label: str
    rate: Optional[float]
    score: float
    residual: float
    usage: float = 1.0      # p-value that all alphabet points are used (1.0 when not applicable)

    @property
    def family(self) -> str:
        return FAMILY[self.label]

    def to_dict(self) -> dict:
        return asdict(self)


class RateExpert(Protocol):
    """A digital family plugin: rebuild the capture at a proposed symbol rate."""
    name: str

    def fit(self, x: np.ndarray, xc: np.ndarray, fs: float, rate: float) -> Hypothesis: ...


UNFIT = float("inf")
