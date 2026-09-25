"""Experimental propose -> verify (MDL) Estimate spike. Methodology under test.

Not imported by Detect, the pipeline or the API. Any future integration must
check ENABLED (env PINPOINT_ESTIMATE_SPIKE=1). Results: docs/estimate_spike_results.md.
"""
import os

from .config import DEFAULT, SpikeConfig, Thresholds
from .decide import Decision, decide
from .hypothesis import Hypothesis
from .pipeline import SpikeResult, analyze_segment

ENABLED = os.environ.get("PINPOINT_ESTIMATE_SPIKE") == "1"

__all__ = ["DEFAULT", "ENABLED", "Decision", "Hypothesis", "SpikeConfig", "SpikeResult",
           "Thresholds", "analyze_segment", "decide"]
