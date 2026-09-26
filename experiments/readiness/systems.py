"""The systems under test, reduced to one scored row per capture.

shipped: Detect + backend.pipeline.classify.analyze_candidate (its default estimator).
verify:  the propose -> verify spike. Uses analyze_candidate(estimator="verify") once
         that exists (WP4); before that, the spike runs on the whole capture.
"""
import inspect
import time

import numpy as np

from backend.pipeline import classify
from backend.pipeline.detect import analyze_capture
from backend.pipeline.ingest import Capture as PCapture
from .metrics import claims_calibration

SHIPPED_LABELS = {"bpsk": "BPSK", "qpsk": "QPSK", "8psk": "8PSK", "qam": "QAM", "fsk": "FSK", "ask": "ASK"}


def has_estimator_flag() -> bool:
    return "estimator" in inspect.signature(classify.analyze_candidate).parameters


def product_estimator() -> str:
    if not has_estimator_flag():
        return "shipped"
    return {"legacy": "shipped"}.get(inspect.signature(classify.analyze_candidate).parameters["estimator"].default,
                                     "verify")


def _pcapture(cap):
    return PCapture(np.asarray(cap.x, np.complex64), float(cap.fs),
                    {"source_kind": "iq", "filename": cap.id, "wav_disambiguation": {"result": "declared_iq"}})


def _overlap(d, band):
    return max(0.0, min(d["freq_upper_hz"], band[1]) - max(d["freq_lower_hz"], band[0]))


def detect(cap):
    pc = _pcapture(cap)
    res = analyze_capture(pc)
    dets = res.response["detections"]
    band = cap.truth["band"]
    primary = None
    if band is not None:
        scored = [(d, _overlap(d, band)) for d in dets]
        scored = [s for s in scored if s[1] > 0]
        if scored:
            primary = max(scored, key=lambda s: s[1])[0]
    info = dict(n_det=len(dets), hit=primary is not None,
                n_overlap=sum(_overlap(d, band) > 0 for d in dets) if band else 0,
                bands=[[d["freq_lower_hz"], d["freq_upper_hz"]] for d in dets])
    return pc, res, dets, primary, info


def shipped_label(out: dict):
    lab = SHIPPED_LABELS.get(out.get("fine_modulation_label"))
    if lab == "QAM" and out.get("qam_order"):
        lab = f"QAM{out['qam_order']}"
    return lab


def _analyze(pc, d, res, **kw):
    t0 = time.perf_counter()
    out = classify.analyze_candidate(pc, d, noise_floor=res.noise_floor, **kw)
    return out, time.perf_counter() - t0


def _row_from_candidate(out, elapsed, verify: bool):
    if verify:
        label, rate = out.get("modulation_label"), out.get("symbol_rate_hz")
    else:
        label = shipped_label(out)
        rate = out.get("symbol_rate_hz") if out.get("symbol_rate_hz") is not None else out.get("qam_symbol_rate_hz")
    return dict(label=label, rate=rate, cf=out.get("center_frequency_refined_hz") or out.get("center_frequency_hz"),
                bw3=out.get("bandwidth_3db_hz"), snr=out.get("snr_db"), time_s=elapsed,
                calibration_claim=claims_calibration(out) if label is not None else False,
                tier=out.get("estimate_tier"), status=out.get("fine_modulation_status"))


def empty_out():
    return dict(label=None, rate=None, cf=None, bw3=None, snr=None, time_s=None, calibration_claim=False)


def run_candidates(cap, verify: bool):
    """Detect, then the estimator on the matched candidate (on noise: on every candidate)."""
    pc, res, dets, primary, info = detect(cap)
    kw = {"estimator": "verify" if verify else "legacy"} if has_estimator_flag() else {}
    if cap.truth["label"] == "noise":
        out = empty_out()
        for d in dets:
            o, el = _analyze(pc, d, res, **kw)
            row = _row_from_candidate(o, el, verify)
            if row["label"] is not None or out["time_s"] is None:
                out = row
            if row["label"] is not None:
                break
        return out, info
    if primary is None:
        return empty_out(), info
    o, el = _analyze(pc, primary, res, **kw)
    return _row_from_candidate(o, el, verify), info


def run_verify_whole(cap):
    from backend.experimental.estimate_spike import analyze_segment, decide
    t0 = time.perf_counter()
    r = analyze_segment(np.asarray(cap.x, complex), cap.fs)
    d = decide(r.hypotheses, r.noise_var, r.total_power)
    el = time.perf_counter() - t0
    return dict(label=d.label if d.label_shipped else None, rate=d.rate if d.rate_shipped else None,
                cf=None, bw3=None, snr=None, time_s=el, calibration_claim=False, tier=d.tier,
                best=[d.expert, d.label, d.rate], m_fam=d.m_fam, m_rate=d.m_rate)


def run(system: str, cap) -> dict:
    truth = {k: (list(v) if isinstance(v, tuple) else v) for k, v in cap.truth.items()}
    if system == "shipped":
        out, info = run_candidates(cap, verify=False)
    elif system == "verify":
        if has_estimator_flag():
            out, info = run_candidates(cap, verify=True)
        else:
            out, info = run_verify_whole(cap), None
    else:
        raise ValueError(system)
    return dict(gen=cap.gen, id=cap.id, truth=truth, out=out, detect=info)
