"""Scoring rules. A row is dict(gen, id, truth, out, detect); `out` is one system's published answer:
label/rate are None when the system abstained (published nothing)."""
import re

import numpy as np

from .config import THRESHOLDS as TH


def label_matches(pred: str, truth: str) -> bool:
    """Exact label, or an order-less family label (QAM/FSK/ASK) against any order of that family."""
    if pred is None or truth in (None, "noise"):
        return False
    return pred == truth or (pred in ("QAM", "FSK", "ASK") and truth.rstrip("0123456789") == pred)


def rate_matches(pred: float, truth: float) -> bool:
    return pred is not None and truth is not None and abs(pred - truth) / truth < TH.rate_rel_tol


def harmonic_error(pred: float, truth: float) -> bool:
    """Published at 2x or 3x (or 1/2, 1/3) the true rate."""
    if pred is None or truth is None:
        return False
    return any(abs(pred - m * truth) / (m * truth) < TH.rate_rel_tol for m in (2, 3, 1 / 2, 1 / 3))


def _frac(num, den):
    return None if den == 0 else num / den


def _strong(r):
    return r["truth"]["snr_db"] is not None and r["truth"]["snr_db"] >= TH.min_snr_db


def label_stats(rows):
    wrong = sum(r["out"]["label"] is not None and not label_matches(r["out"]["label"], r["truth"]["label"])
                for r in rows)
    lib = [r for r in rows if r["truth"]["in_library"] and _strong(r)]
    right = sum(label_matches(r["out"]["label"], r["truth"]["label"]) for r in lib)
    return dict(n=len(rows), published_wrong=_frac(wrong, len(rows)), n_in_library=len(lib),
                published_correct_in_library=_frac(right, len(lib)),
                published=_frac(sum(r["out"]["label"] is not None for r in rows), len(rows)))


def rate_stats(rows):
    wrong = sum(r["out"]["rate"] is not None and not rate_matches(r["out"]["rate"], r["truth"]["rate"])
                for r in rows)
    dig = [r for r in rows if r["truth"]["digital"] and _strong(r)]
    right = sum(rate_matches(r["out"]["rate"], r["truth"]["rate"]) for r in dig)
    harm = sum(harmonic_error(r["out"]["rate"], r["truth"]["rate"]) for r in dig)
    return dict(n=len(rows), published_wrong=_frac(wrong, len(rows)), n_digital=len(dig),
                published_correct_digital=_frac(right, len(dig)), harmonic_errors=_frac(harm, len(dig)))


def confidence_stats(rows):
    noise = [r for r in rows if r["truth"]["label"] == "noise"]
    ool = [r for r in rows if r["truth"]["out_of_library"]]
    fm = [r for r in rows if r["truth"]["label"] == "FM"]
    ool_wrong = sum(r["out"]["label"] is not None and not label_matches(r["out"]["label"], r["truth"]["label"])
                    for r in ool)
    return dict(n_noise=len(noise), noise_labelled=_frac(sum(r["out"]["label"] is not None for r in noise), len(noise)),
                n_ool=len(ool), ool_wrong=_frac(ool_wrong, len(ool)),
                n_fm=len(fm), fm_labelled=_frac(sum(r["out"]["label"] == "FM" for r in fm), len(fm)),
                calibration_claims=sum(bool(r["out"].get("calibration_claim")) and r["out"]["label"] is not None
                                       for r in rows))


_NEGATED = re.compile(r"not a calibrated|not calibrated|uncalibrated")


def claims_calibration(obj) -> bool:
    """True when any string in a (nested) output claims calibration."""
    if isinstance(obj, str):
        return "calibrated" in _NEGATED.sub("", obj.lower())
    if isinstance(obj, dict):
        return any(claims_calibration(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(claims_calibration(v) for v in obj)
    return False


def detect_stats(rows):
    sig = [r for r in rows if r["truth"]["label"] != "noise"]
    strong = [r for r in sig if _strong(r)]
    noise = [r for r in rows if r["truth"]["label"] == "noise"]
    found = [r for r in sig if r["detect"]["n_det"] >= 1]
    return dict(n_strong=len(strong), recall=_frac(sum(r["detect"]["hit"] for r in strong), len(strong)),
                n_noise=len(noise), noise_false=_frac(sum(r["detect"]["n_det"] >= 1 for r in noise), len(noise)),
                n_found=len(found), fragmentation=_frac(sum(r["detect"]["n_det"] >= 2 for r in found), len(found)))


def param_stats(rows):
    lin = [r for r in rows if r["truth"]["bw3"] and _strong(r)]
    sig = [r for r in rows if r["truth"]["label"] != "noise" and _strong(r)]

    def cf_ok(r):
        cf = r["out"].get("cf")
        return cf is not None and abs(cf - r["truth"]["fc"]) <= TH.cf_err_frac_bw * r["truth"]["bw3"]

    def bw_ok(r):
        bw = r["out"].get("bw3")
        return bw is not None and abs(bw / r["truth"]["bw3"] - 1) <= TH.bw3_tol

    def snr_ok(r):
        s = r["out"].get("snr")
        return s is not None and abs(s - r["truth"]["snr_db"]) <= TH.snr_err_db

    def med(vals):
        vals = [v for v in vals if v is not None]
        return float(np.median(vals)) if vals else None
    return dict(n_linear=len(lin), cf_ok=_frac(sum(map(cf_ok, lin)), len(lin)),
                bw3_ok=_frac(sum(map(bw_ok, lin)), len(lin)), n_signal=len(sig),
                snr_ok=_frac(sum(map(snr_ok, sig)), len(sig)),
                median_bw3_ratio=med([r["out"]["bw3"] / r["truth"]["bw3"] if r["out"].get("bw3") else None
                                      for r in lin]),
                median_snr_err_db=med([r["out"]["snr"] - r["truth"]["snr_db"] if r["out"].get("snr") is not None
                                       else None for r in sig]))


def speed_stats(rows):
    t = np.array([r["out"]["time_s"] for r in rows if r["out"].get("time_s") is not None])
    if not len(t):
        return dict(n=0, within=None, p50_s=None, p95_s=None, max_s=None)
    return dict(n=int(len(t)), within=float(np.mean(t <= TH.speed_s)), p50_s=float(np.median(t)),
                p95_s=float(np.percentile(t, 95)), max_s=float(t.max()))
