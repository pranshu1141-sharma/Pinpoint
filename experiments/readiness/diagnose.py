"""WP3: why does the product abstain? One cause per candidate, with the evidence values.

    python -m experiments.readiness.diagnose            # G3 + G5 test files, and a G4 sample
    -> artifacts/readiness/diagnosis.json; tables: python -m experiments.readiness.diagnose_report
    (follow-ups: fsk_split_probe.py, oracle_bounds.py)

Each file goes through the batch-CLI path (backend.cli.analyze_file) with verify_candidate wrapped,
so the raw margins behind every published or withheld label are recorded (the product output is
unchanged). The cause is the FIRST gate a candidate fails, in the product's own order:

  not_iq            capture is not complex IQ
  pulsed            the verify estimator refuses pulsed candidates outright ("pulsed bursts not validated")
  short_segment     longest occupied window < MIN_SAMPLES after decimation
  null_wins         the noise-only model explains the segment best
  unknown_ce        an out-of-library constant-envelope probe (8 discrete IF levels) wins
  m_fam             family margin below threshold
  fm_digital        FM wins but not by m_fm_digital over the best digital hypothesis
  unexplained       winner leaves more than unexplained_max of the signal power unexplained
  usage             an alphabet point is unused (subset constellation)
  m_label           margin over the best other label below threshold
  span_disagree / span_minority   (long tracks) sampled spans disagree / too few spans publish
  analysis_failed   the bounded re-read could not be analysed
A published label with no rate is reported separately (rate_withheld: m_rate below threshold).

For pulsed candidates a counterfactual is recorded: the verify estimator run on the candidate's
longest burst as if it were not refused (decimated as the product would), with its margins and
gate outcome. It predicts the effect of lifting the refusal; it changes nothing in the product.

Detect-bounds evidence (G4 only, where the true band is known): the matched detection's width
over the true occupied width, and how many detections overlap the true band.
"""
import argparse
import collections
import json
from pathlib import Path

import numpy as np

from backend.pipeline import verify_estimator as ve
from . import g5, generators, systems
from .metrics import label_matches

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / "artifacts" / "readiness" / "diagnosis.json"


class Recorder:
    """Wraps verify_candidate to keep the raw evidence of every call."""

    def __init__(self):
        self.calls = []
        self.orig = ve.verify_candidate

    def __enter__(self):
        ve.verify_candidate = self
        return self

    def __exit__(self, *exc):
        ve.verify_candidate = self.orig

    def __call__(self, capture, candidate, *, return_raw=False):
        out = self.orig(capture, candidate, return_raw=True)
        rec = dict(freq=(candidate["freq_lower_hz"], candidate["freq_upper_hz"]), pulsed=bool(candidate.get("is_pulsed")),
                   status=out["verify_status"], label=out["modulation_label"], rate=out["symbol_rate_hz"],
                   tier=out["estimate_tier"], segment=out.get("verify_segment"))
        if "_raw" in out:
            r, d = out["_raw"]
            rec["evidence"] = evidence(r, d, out)
        elif candidate.get("is_pulsed") and capture.metadata.get("source_kind") == "iq":
            rec["counterfactual"] = counterfactual(capture, candidate)
        self.calls.append(rec)
        if not return_raw:
            out.pop("_raw", None)
        return out


def evidence(r, d, out):
    th, _, unit = ve.thresholds()
    best = min(r.hypotheses, key=lambda h: h.score)
    seg = out["verify_segment"]
    g = ve.gate(d, best.usage, th, unit, seg["samples"], seg["sample_rate_hz"],
                ve.fm_digital_margin(r.hypotheses, best.score), ve.label_margin(r.hypotheses, best))
    return dict(best=[d.expert, d.label, d.rate], family=d.family, m_fam=g["m_fam"], m_rate=g["m_rate"],
                m_label=float(ve.label_margin(r.hypotheses, best)),
                m_fm_digital=float(ve.fm_digital_margin(r.hypotheses, best.score)),
                unexplained=float(d.unexplained), usage=float(best.usage), samples=seg["samples"],
                fs=seg["sample_rate_hz"], th=dict(m_fam=th.m_fam, m_rate=th.m_rate, m_label=th.m_label,
                                                   unexplained_max=th.unexplained_max, min_usage=th.min_usage,
                                                   m_fm_digital=th.m_fm_digital))


def first_failure(ev):
    th = ev["th"]
    if ev["family"] == "none":
        return "null_wins"
    if ev["family"] == "unknown constant-envelope":
        return "unknown_ce"
    if not ev["m_fam"] >= th["m_fam"]:
        return "m_fam"
    if ev["best"][1] == "FM" and not ev["m_fm_digital"] >= th["m_fm_digital"]:
        return "fm_digital"
    if not ev["unexplained"] <= th["unexplained_max"]:
        return "unexplained"
    if not ev["usage"] >= th["min_usage"]:
        return "usage"
    if not ev["m_label"] >= th["m_label"]:
        return "m_label"
    return None


def counterfactual(capture, candidate):
    """Verify on the candidate's longest burst as if pulsed candidates were not refused."""
    lone = {**candidate, "is_pulsed": False}
    ws = candidate.get("pulse_windows") or []
    if ws:
        w = max(ws, key=lambda w: w["end_sample"] - w["start_sample"])
        lone.update(start_sample=w["start_sample"], end_sample=w["end_sample"], pulse_windows=[])
    seg, reason = ve.candidate_segment(capture, lone)
    burst = (lone["end_sample"] - lone["start_sample"])
    info = dict(bursts=len(ws), longest_burst_samples=burst,
                median_burst_samples=int(np.median([w["end_sample"] - w["start_sample"] for w in ws])) if ws else None)
    if seg is None:
        return dict(info, outcome="short_segment", reason=reason)
    out = ve.verify_candidate.orig(capture, lone, return_raw=True) if isinstance(ve.verify_candidate, Recorder) \
        else ve.verify_candidate(capture, lone, return_raw=True)
    r, d = out["_raw"]
    ev = evidence(r, d, out)
    return dict(info, outcome="labelled" if out["modulation_label"] else (first_failure(ev) or "rate_only"),
                label=out["modulation_label"], rate=out["symbol_rate_hz"], evidence=ev)


def cause_of(det, calls):
    """The recorded verify call(s) behind one output detection: first failing gate."""
    st = det.get("verify_status") or ""
    if "requires complex IQ" in st:
        return "not_iq"
    if "sampled spans disagree" in st:
        return "span_disagree"
    if "fewer than half" in st:
        return "span_minority"
    if "could not be analysed" in st:
        return "analysis_failed"
    if "pulsed" in st:
        return "pulsed"
    if "insufficient occupied samples" in st:
        return "short_segment"
    ev = next((c["evidence"] for c in calls if "evidence" in c), None)
    return first_failure(ev) if ev else "other: " + st


def _match(det, calls):
    lo, hi = det["freq_lower_hz"], det["freq_upper_hz"]
    return [c for c in calls if abs(c["freq"][0] - lo) < 1e-6 * max(1, abs(lo)) + 1 and abs(c["freq"][1] - hi) < 1e-6 * max(1, abs(hi)) + 1]


def run_file(path, meta_available=True):
    import argparse as ap
    from backend.cli import analyze_file
    args = ap.Namespace(sample_rate=None, datatype=None, wav_mode="auto", margin_db=8.0, estimator="verify")
    with Recorder() as rec:
        blob = analyze_file(path, args)
    return blob["detections"], rec.calls


def diagnose_real():
    rows = []
    for stem, data, meta, entry in g5.folder_files():
        dets, calls = run_file(data)
        truth = entry["allowed_labels"] if entry else None
        if entry is None:
            g3 = {r["file"]: r for r in json.loads((Path(g5.__file__).with_name("real_manifest.json")).read_text())["recordings"]}[stem]
            truth = g3["allowed_labels"]
        for d in dets:
            mine = _match(d, calls)
            row = dict(set="G3" if entry is None else "G5", file=stem, det=d["id"], truth=truth,
                       coding=(entry or {}).get("truth", {}).get("coding"), expected_rate=(entry or {}).get("expected_rate_hz"),
                       band=[d["freq_lower_hz"], d["freq_upper_hz"]], pulsed=d.get("is_pulsed"),
                       label=d.get("modulation_label"), rate=d.get("symbol_rate_hz"), snr_db=d.get("snr_db"),
                       bw99=d.get("bandwidth_99pct_hz"), status=d.get("verify_status"),
                       spans=len(d.get("analysis_spans") or []))
            if d.get("modulation_label") is None:
                row["cause"] = cause_of(d, mine)
            elif d.get("symbol_rate_hz") is None and d["modulation_label"] not in ("FM", "AM"):
                row["cause"] = "rate_withheld"
            ev = [c.get("evidence") for c in mine if c.get("evidence")]
            cf = [c.get("counterfactual") for c in mine if c.get("counterfactual")]
            if ev:
                row["evidence"] = ev[0]
            if cf:
                row["counterfactual"] = cf[0]
                row["counterfactual_correct"] = bool(cf[0].get("label")) and any(label_matches(cf[0]["label"], t) for t in truth)
                row["counterfactual_wrong"] = bool(cf[0].get("label")) and not row["counterfactual_correct"]
            row["correct"] = bool(row["label"]) and any(label_matches(row["label"], t) for t in truth)
            row["wrong"] = bool(row["label"]) and not row["correct"]
            rows.append(row)
        print(stem, len(dets), flush=True)
    return rows


def diagnose_g4(stride=3):
    rows = []
    for s in generators.g4_specs()[::stride]:
        cap = generators.g4_capture(**s)
        if cap.truth["label"] == "noise":
            continue
        with Recorder() as rec:
            pc, res, dets, primary, info = systems.detect(cap)
            if primary is None:
                rows.append(dict(set="G4", file=cap.id, truth=[cap.truth["label"]], cause="detect_miss", snr_db=cap.truth["snr_db"]))
                continue
            out = systems.classify.analyze_candidate(pc, primary, noise_floor=res.noise_floor)
        lo, hi = cap.truth["band"]
        width_ratio = (primary["freq_upper_hz"] - primary["freq_lower_hz"]) / (hi - lo)
        row = dict(set="G4", file=cap.id, truth=[cap.truth["label"]], snr_db=cap.truth["snr_db"], sps=s["sps"],
                   label=out["modulation_label"], rate=out["symbol_rate_hz"], status=out["verify_status"],
                   n_overlap=info["n_overlap"], width_ratio=width_ratio, in_library=cap.truth["in_library"])
        if out["modulation_label"] is None:
            row["cause"] = cause_of(out, rec.calls)
        elif out["symbol_rate_hz"] is None and out["modulation_label"] not in ("FM", "AM"):
            row["cause"] = "rate_withheld"
        ev = [c.get("evidence") for c in rec.calls if c.get("evidence")]
        if ev:
            row["evidence"] = ev[0]
        row["correct"] = bool(row["label"]) and label_matches(row["label"], cap.truth["label"])
        row["wrong"] = bool(row["label"]) and not row["correct"]
        rows.append(row)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--g4-stride", type=int, default=3)
    ap.add_argument("--skip-real", action="store_true")
    args = ap.parse_args(argv)
    old = json.loads(OUT_JSON.read_text()) if OUT_JSON.exists() else {}
    real = old.get("real", []) if args.skip_real else diagnose_real()
    g4 = diagnose_g4(args.g4_stride)
    OUT_JSON.write_text(json.dumps(dict(real=real, g4=g4), indent=1, default=float) + "\n")
    for name, rows in (("real", real), ("g4", g4)):
        c = collections.Counter(r.get("cause") for r in rows if r.get("cause"))
        print(name, c.most_common())


if __name__ == "__main__":
    main()
