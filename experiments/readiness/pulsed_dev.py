"""Readiness step 2 (RC1/RC2): calibration-only harness for analysing pulsed candidates as bursts.

    python -m experiments.readiness.pulsed_dev collect     # G5 calibration files -> artifacts/readiness/pulsed_dev/*.json
    python -m experiments.readiness.pulsed_dev report      # file-level RC1/RC2 on calibration, product vs variants
    python -m experiments.readiness.pulsed_dev collect-bursts   # + per-burst and joined-burst tables (pulsed_dev_bursts/)
    python -m experiments.readiness.pulsed_dev report-bursts    # RC1/RC2 on calibration for each multi-burst rule

G5 *calibration* files only; the test split is never read here (scored once by the scoreboard).
`collect` runs each file once through the batch-CLI path (backend.cli.analyze_file) and keeps, for every
candidate, the full hypothesis table behind its verify call. A pulsed candidate, which the product refuses,
is also analysed on its longest burst as if it were not refused. `report` re-decides every candidate from
the stored tables, so gate variants are compared in seconds without re-running the estimator.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy import signal

from backend.experimental.estimate_spike import Thresholds, decide
from backend.experimental.estimate_spike.hypothesis import DIGITAL_EXPERTS, Hypothesis
from backend.pipeline import verify_estimator as ve
from . import g5
from .metrics import label_matches

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "readiness" / "pulsed_dev"


def calibration_entries():
    return [e for e in g5.manifest() if e["split"] == "calibration"]


def _table(r, x_len, fs):
    return dict(hyps=[dict(expert=h.expert, label=h.label, rate=h.rate, score=float(h.score), residual=float(h.residual),
                           usage=float(h.usage)) for h in r.hypotheses],
                noise_var=float(r.noise_var), total_power=float(r.total_power), samples=int(x_len), fs=float(fs))


def _burst(capture, candidate):
    """The candidate restricted to its longest pulse window, not refused."""
    lone = {**candidate, "is_pulsed": False}
    ws = candidate.get("pulse_windows") or []
    if ws:
        w = max(ws, key=lambda w: w["end_sample"] - w["start_sample"])
        lone.update(start_sample=w["start_sample"], end_sample=w["end_sample"], pulse_windows=[])
    return lone


class Recorder:
    """Wraps verify_candidate: product output unchanged, every candidate's hypothesis table kept."""

    def __init__(self):
        self.calls, self.orig = [], ve.verify_candidate

    def __enter__(self):
        ve.verify_candidate = self
        return self

    def __exit__(self, *exc):
        ve.verify_candidate = self.orig

    def __call__(self, capture, candidate, *, return_raw=False):
        out = self.orig(capture, candidate, return_raw=True)
        rec = dict(band=[candidate["freq_lower_hz"], candidate["freq_upper_hz"]], pulsed=bool(candidate.get("is_pulsed")),
                   bursts=len(candidate.get("pulse_windows") or []), product_label=out["modulation_label"],
                   product_status=out["verify_status"])
        target = candidate
        if candidate.get("is_pulsed") and capture.metadata.get("source_kind") == "iq":
            target = _burst(capture, candidate)
            rec["burst_samples"] = target["end_sample"] - target["start_sample"]
        seg, reason = ve.candidate_segment(capture, target)
        if seg is None:
            rec["skip"] = reason
        elif "_raw" in out and not candidate.get("is_pulsed"):
            rec["table"] = _table(out["_raw"][0], out["verify_segment"]["samples"], out["verify_segment"]["sample_rate_hz"])
        else:
            from backend.experimental.estimate_spike import analyze_segment
            x, fs, _ = seg
            rec["table"] = _table(analyze_segment(x, fs, carrier_hint=0.0), len(x), fs)
        self.calls.append(rec)
        if not return_raw:
            out.pop("_raw", None)
        return out


def collect(only=None):
    import argparse as ap
    from backend.cli import analyze_file
    OUT.mkdir(parents=True, exist_ok=True)
    args = ap.Namespace(sample_rate=None, datatype=None, wav_mode="auto", margin_db=8.0, estimator="verify")
    for e in calibration_entries():
        dst = OUT / f"{e['id']}.json"
        if dst.exists() or (only and e["id"] not in only):
            continue
        data = g5.DATA / f"{e['id']}.sigmf-data"
        try:
            with Recorder() as rec:
                blob = analyze_file(data, args)
            dets = blob["detections"]
        except (MemoryError, ValueError) as exc:
            dst.write_text(json.dumps(dict(id=e["id"], error=repr(exc))) + "\n")
            print(e["id"], "error", exc, flush=True)
            continue
        dst.write_text(json.dumps(dict(id=e["id"], stratum=e["stratum"], allowed=e["allowed_labels"],
                                       expected_rate_hz=e.get("expected_rate_hz"), coding=e.get("truth", {}).get("coding"),
                                       n_detections=len(dets), product_labels=[d.get("modulation_label") for d in dets],
                                       calls=rec.calls), default=float) + "\n")
        print(e["id"], len(dets), "candidates", flush=True)


MAX_BURSTS = 8


def burst_segments(capture, candidate, max_bursts=MAX_BURSTS):
    """(per-burst segments, joined segment) of a pulsed candidate, each as (x, fs) or None.

    Per burst: the product's own segment builder on each of the longest `max_bursts` windows.
    Joined: every window in time order (until MAX_SAMPLES is reached), each mixed to the band centre with the capture's
    absolute sample index (carrier phase continuous across gaps), decimated by one common factor, and
    concatenated, capped at MAX_SAMPLES."""
    fs = float(capture.sample_rate)
    ws = sorted(candidate.get("pulse_windows") or [], key=lambda w: w["end_sample"] - w["start_sample"], reverse=True)
    per = []
    for w in ws[:max_bursts]:
        seg, _ = ve.candidate_segment(capture, {**candidate, "is_pulsed": False, "start_sample": w["start_sample"],
                                                "end_sample": w["end_sample"], "pulse_windows": []})
        per.append(None if seg is None else seg[:2])
    lo, hi = float(candidate["freq_lower_hz"]), float(candidate["freq_upper_hz"])
    width, centre = max(hi - lo, fs / 1024), (lo + hi) / 2
    decim = max(1, int(fs // (ve.OVERSAMPLE * width)))
    parts, total = [], 0
    for w in sorted(ws, key=lambda w: w["start_sample"]):
        a, b = w["start_sample"], w["end_sample"]
        x = np.asarray(capture.iq[a:b], dtype=np.complex128) * np.exp(-2j * np.pi * centre * np.arange(a, b) / fs)
        if decim > 1:
            if len(x) < 4 * decim:
                continue
            x = signal.resample_poly(x, 1, decim)
        parts.append(x)
        total += len(x)
        if total >= ve.MAX_SAMPLES:
            break
    joined = np.concatenate(parts)[:ve.MAX_SAMPLES] if parts else np.zeros(0, complex)
    return per, ((joined, fs / decim) if len(joined) >= ve.MIN_SAMPLES and len(parts) >= 2 else None)


class BurstRecorder(Recorder):
    """Recorder that also keeps per-burst and joined-burst tables for pulsed candidates."""

    def __call__(self, capture, candidate, *, return_raw=False):
        out = super().__call__(capture, candidate, return_raw=return_raw)
        rec = self.calls[-1]
        if candidate.get("is_pulsed") and capture.metadata.get("source_kind") == "iq":
            from backend.experimental.estimate_spike import analyze_segment
            per, joined = burst_segments(capture, candidate)
            rec["burst_tables"] = [None if s is None else _table(analyze_segment(s[0], s[1], carrier_hint=0.0), len(s[0]), s[1])
                                   for s in per]
            rec["joined_table"] = None if joined is None else _table(
                analyze_segment(joined[0], joined[1], carrier_hint=0.0), len(joined[0]), joined[1])
        return out


def collect_bursts(only=None):
    import argparse as ap
    from backend.cli import analyze_file
    dst_dir = OUT.with_name("pulsed_dev_bursts")
    dst_dir.mkdir(parents=True, exist_ok=True)
    args = ap.Namespace(sample_rate=None, datatype=None, wav_mode="auto", margin_db=8.0, estimator="verify")
    for e in calibration_entries():
        dst = dst_dir / f"{e['id']}.json"
        if dst.exists() or (only and e["id"] not in only):
            continue
        try:
            with BurstRecorder() as rec:
                dets = analyze_file(g5.DATA / f"{e['id']}.sigmf-data", args)["detections"]
        except (MemoryError, ValueError) as exc:
            dst.write_text(json.dumps(dict(id=e["id"], error=repr(exc))) + "\n")
            print(e["id"], "error", exc, flush=True)
            continue
        dst.write_text(json.dumps(dict(id=e["id"], stratum=e["stratum"], allowed=e["allowed_labels"],
                                       expected_rate_hz=e.get("expected_rate_hz"), n_detections=len(dets),
                                       calls=rec.calls), default=float) + "\n")
        print(e["id"], len(dets), "candidates", flush=True)


# ---------------------------------------------------------------- offline re-decision
def _hyps(table):
    return [Hypothesis(**h) for h in table["hyps"]]


def redecide(table, gate_fn=None):
    """(label or None, evidence) for one stored table under the product's gate, then an optional extra gate."""
    th, _, unit = ve.thresholds()
    hyps = _hyps(table)
    raw = Thresholds(m_fam=-np.inf, m_rate=-np.inf, unexplained_max=np.inf, min_usage=0.0)
    d = decide(hyps, table["noise_var"], table["total_power"], raw)
    best = min(hyps, key=lambda h: h.score)
    g = ve.gate(d, best.usage, th, unit, table["samples"], table["fs"], ve.fm_digital_margin(hyps, best.score),
                ve.label_margin(hyps, best))
    ev = dict(label=d.label, expert=d.expert, family=d.family, m_fam=g["m_fam"], unexplained=float(d.unexplained),
              m_digital=_digital_margin(hyps, best), tier=g["tier"])
    label = d.label if g["label"] else None
    if label and gate_fn is not None and not gate_fn(ev, hyps):
        label = None
    return label, ev


def _digital_margin(hyps, best):
    """Per-sample gap from an analog winner (AM/FM) to the best digital hypothesis (inf when none)."""
    dig = [h.score for h in hyps if h.expert in DIGITAL_EXPERTS]
    return (min(dig) - best.score) if dig else float("inf")


def load():
    return [json.loads(p.read_text()) for p in sorted(OUT.glob("*.json"))]


def score(files, *, pulsed=False, gate_fn=None):
    """File-level RC1/RC2 on calibration under one variant: product (pulsed refused) or pulsed bursts analysed."""
    have = correct = wrong = 0
    wrongs = []
    for f in files:
        if "error" in f:
            continue
        labels = []
        for c in f["calls"]:
            if "table" not in c or (c["pulsed"] and not pulsed):
                continue
            lab, ev = redecide(c["table"], gate_fn)
            if lab:
                labels.append(lab)
                if not any(label_matches(lab, a) for a in f["allowed"]):
                    wrongs.append((f["id"], lab, ev))
        ok = [l for l in labels if any(label_matches(l, a) for a in f["allowed"])]
        have += bool(f["allowed"])
        correct += bool(f["allowed"]) and bool(ok)
        wrong += len(ok) < len(labels)
    n = sum("error" not in f for f in files)
    return dict(files=n, with_label=have, rc1=correct / max(have, 1), rc2=wrong / max(n, 1), correct=correct,
                wrong=wrong, wrongs=wrongs)


def report():
    files = load()
    for name, kw in (("product (pulsed refused)", {}), ("pulsed bursts analysed", dict(pulsed=True))):
        s = score(files, **kw)
        print(f"{name:28s} files={s['files']} RC1={s['rc1']:.1%} ({s['correct']}/{s['with_label']}) "
              f"RC2={s['rc2']:.1%} ({s['wrong']}/{s['files']})")
    s = score(files, pulsed=True)
    import collections
    print("wrong labels (pulsed analysed):", collections.Counter((w[1], tuple(next(f['allowed'] for f in files if f['id'] == w[0]))) for w in s["wrongs"]).most_common())


ANALOG = ("AM", "FM")


def _burst_labels(c):
    """(labels of the per-burst tables, number of bursts analysed)."""
    tabs = [t for t in c.get("burst_tables") or [] if t]
    return [redecide(t)[0] for t in tabs], len(tabs)


def pulsed_label(c, variant, no_analog):
    """Label a pulsed candidate under one multi-burst variant (None = withheld)."""
    labs, n = _burst_labels(c)
    got = [l for l in labs if l]
    joined = redecide(c["joined_table"])[0] if c.get("joined_table") else None
    if variant == "joined":
        lab = joined
    elif variant == "agree":
        lab = got[0] if len(got) >= 2 and len(set(got)) == 1 and len(got) >= n / 2 else None
    elif variant == "joined_noconflict":
        lab = joined if joined and all(l == joined for l in got) else None
    elif variant == "joined_or_agree":
        a = pulsed_label(c, "agree", False)
        j = pulsed_label(c, "joined_noconflict", False)
        lab = j or a if not (j and a and j != a) else None
    else:
        raise ValueError(variant)
    return None if (lab in ANALOG and no_analog) else lab


def score_bursts(files, variant, no_analog=True):
    have = correct = wrong = n = 0
    wrongs, rights = [], []
    for f in files:
        if "error" in f:
            continue
        n += 1
        labels = []
        for c in f["calls"]:
            if c["pulsed"]:
                lab = pulsed_label(c, variant, no_analog) if "burst_tables" in c else None
            else:
                lab = redecide(c["table"])[0] if "table" in c else None
            if lab:
                labels.append(lab)
        ok = [l for l in labels if any(label_matches(l, a) for a in f["allowed"])]
        have += bool(f["allowed"])
        correct += bool(f["allowed"]) and bool(ok)
        wrong += len(ok) < len(labels)
        wrongs += [(f["id"], l) for l in set(labels) - set(ok)]
        rights += [(f["id"], l) for l in set(ok)]
    return dict(files=n, rc1=correct / max(have, 1), rc2=wrong / max(n, 1), correct=correct, with_label=have,
                wrong=wrong, wrongs=wrongs, rights=rights)


def report_bursts():
    import collections
    files = [json.loads(p.read_text()) for p in sorted(OUT.with_name("pulsed_dev_bursts").glob("*.json"))]
    for variant in ("joined", "agree", "joined_noconflict", "joined_or_agree"):
        for no_analog in (False, True):
            s = score_bursts(files, variant, no_analog)
            print(f"{variant:18s} no_analog={no_analog!s:5s} RC1={s['rc1']:.1%} ({s['correct']}/{s['with_label']}) "
                  f"RC2={s['rc2']:.1%} ({s['wrong']}/{s['files']})  wrong labels: "
                  f"{dict(collections.Counter(l for _, l in s['wrongs']))}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "collect-bursts", "report", "report-bursts"])
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    {"collect": collect, "collect-bursts": collect_bursts, "report-bursts": lambda _: report_bursts()}.get(a.cmd, lambda _: report())(a.only)


if __name__ == "__main__":
    sys.exit(main())
