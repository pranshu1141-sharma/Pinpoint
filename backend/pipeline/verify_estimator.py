"""Modulation label and symbol rate for one Detect candidate: the propose -> verify (MDL) estimator.

The candidate's time and frequency bounds select the samples; the band is mixed to its
centre, low-passed and decimated to ~OVERSAMPLE x the occupied bandwidth, and capped at
MAX_SAMPLES around the middle of the longest occupied window. The estimator rebuilds the
segment under competing hypotheses (PSK/QAM with several pulse models, M-FSK, AM/FM,
noise) and publishes a label or rate only when its margin over every rival passes a
threshold fit on a cross-generator calibration split (docs/verify-thresholds.json).
Margins are nats, not probabilities. Deterministic: no randomness.
"""
import json
from functools import lru_cache
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy import signal

from backend.experimental.estimate_spike import Thresholds, analyze_segment, decide
from backend.experimental.estimate_spike.hypothesis import DIGITAL_EXPERTS, UNKNOWN_CE
from .estimate import occupied_windows
from .ingest import Capture

OVERSAMPLE = 4          # decimated rate ~ OVERSAMPLE x the candidate bandwidth (plan: 4-8x)
MAX_SAMPLES = 8192      # window cap after decimation
MIN_SAMPLES = 2000      # the estimator's minimum segment
THRESHOLDS_FILE = Path(__file__).resolve().parents[2] / "docs" / "verify-thresholds.json"


@lru_cache(maxsize=1)
def thresholds() -> tuple[Thresholds, str, str]:
    """(fitted margins, provenance, margin unit); the spike's defaults when no calibration file exists."""
    if not THRESHOLDS_FILE.exists():
        return Thresholds(), "spike defaults (single-generator calibration, seed 4)", "sample"
    blob = json.loads(THRESHOLDS_FILE.read_text())
    return Thresholds(**blob["thresholds"]), blob["provenance"], blob.get("margin_unit", "sample")


def gate(d, usage: float, th: Thresholds, unit: str, n: int, fs: float) -> dict:
    """Publication decision from raw margins (per-sample nats) rescaled to the calibrated unit."""
    sps = fs / d.rate if d.rate else float("nan")
    scale = {"sample": 1.0, "symbol": sps, "total": float(n)}[unit]
    m_fam, m_rate = d.m_fam * scale, d.m_rate * scale
    fam_pass = d.family != "none" and m_fam >= th.m_fam
    label = bool(fam_pass and d.unexplained <= th.unexplained_max and d.family != UNKNOWN_CE
                 and usage >= th.min_usage)
    # a rate means "this is digital at R": only when the family margin passes too
    rate = bool(fam_pass and d.expert in DIGITAL_EXPERTS and np.isfinite(m_rate) and m_rate >= th.m_rate)
    tier = "labelled" if label else ("unknown_family" if fam_pass else "abstain")
    return dict(label=label, rate=rate, tier=tier, m_fam=m_fam, m_rate=m_rate)


def candidate_segment(capture: Capture, candidate: dict):
    """(baseband segment, decimated rate) for the candidate, or (None, reason)."""
    fs = float(capture.sample_rate)
    windows = occupied_windows(capture, candidate)
    if not windows:
        return None, "no occupied samples"
    a, b = max(windows, key=lambda w: w[1] - w[0])
    lo, hi = float(candidate["freq_lower_hz"]), float(candidate["freq_upper_hz"])
    width = max(hi - lo, fs / 1024)
    centre = (lo + hi) / 2
    n = b - a
    decim = max(1, int(fs // (OVERSAMPLE * width)))
    decim = max(1, min(decim, n // MIN_SAMPLES))
    if n // decim < MIN_SAMPLES:
        return None, f"insufficient occupied samples ({n} < {MIN_SAMPLES})"
    # take only what the cap needs (plus filter margin), centred in the window
    need = min(n, (MAX_SAMPLES + 64) * decim)
    a0 = a + (n - need) // 2
    x = np.asarray(capture.iq[a0:a0 + need], dtype=np.complex128)
    x = x * np.exp(-2j * np.pi * centre * (np.arange(len(x)) + a0) / fs)
    if decim > 1:
        x = signal.resample_poly(x, 1, decim)
    if len(x) > MAX_SAMPLES:
        s = (len(x) - MAX_SAMPLES) // 2
        x = x[s:s + MAX_SAMPLES]
    return (x, fs / decim), None


def verify_candidate(capture: Capture, candidate: dict, *, return_raw: bool = False) -> dict:
    """Verify-estimator fields for one candidate (see module docstring)."""
    th, provenance, unit = thresholds()
    out = {"estimator": "verify", "modulation_label": None, "verify_family": None, "symbol_rate_hz": None,
           "m_fam": None, "m_rate": None, "unexplained": None, "estimate_tier": "abstain",
           "label_needs_review": True, "verify_best_hypothesis": None, "verify_segment": None,
           "verify_elapsed_ms": None,
           "verify_thresholds": {**th.__dict__, "margin_unit": unit, "provenance": provenance},
           "verify_status": "not reliably estimated"}
    if capture.metadata.get("source_kind") != "iq":
        out["verify_status"] = "not reliably estimated (requires complex IQ)"
        return out
    if candidate.get("is_pulsed"):
        out["verify_status"] = "not reliably estimated (pulsed bursts not validated)"
        return out
    seg, reason = candidate_segment(capture, candidate)
    if seg is None:
        out["verify_status"] = f"not reliably estimated ({reason})"
        return out
    x, fs = seg
    t0 = perf_counter()
    r = analyze_segment(x, fs, carrier_hint=0.0)
    raw = Thresholds(m_fam=-np.inf, m_rate=-np.inf, unexplained_max=np.inf, min_usage=0.0)
    d = decide(r.hypotheses, r.noise_var, r.total_power, raw)
    usage = min(r.hypotheses, key=lambda h: h.score).usage
    g = gate(d, usage, th, unit, len(x), fs)
    out.update(
        modulation_label=d.label if g["label"] else None,
        verify_family=(d.family if g["tier"] == "labelled" else
                       ("unknown constant-envelope family" if d.family == UNKNOWN_CE else "unknown family")
                       if g["tier"] == "unknown_family" else None),
        symbol_rate_hz=float(d.rate) if g["rate"] else None,
        m_fam=_num(g["m_fam"]), m_rate=_num(g["m_rate"]), unexplained=_num(d.unexplained),
        estimate_tier=g["tier"], label_needs_review=not g["label"],
        verify_best_hypothesis={"expert": d.expert, "label": d.label, "rate_hz": d.rate},
        verify_segment={"sample_rate_hz": fs, "samples": int(len(x))},
        verify_elapsed_ms=round(1e3 * (perf_counter() - t0), 1),
        verify_status={"labelled": "estimated (label margin passed)",
                       "unknown_family": "unknown family (structure outside the library)",
                       "abstain": "not reliably estimated (margins below thresholds)"}[g["tier"]])
    if return_raw:
        out["_raw"] = (r, d)
    return out


def _num(v):
    return None if v is None or not np.isfinite(v) else float(v)
