"""Docs honesty check (criterion X1): the prose must agree with the code and with readiness.json.

Rules:
  1. docs/CLAIMS.md exists, and every `<!--rj:dotted.path-->` marker in it is followed by
     the value found at that path in readiness.json (formatted by `fmt`).
  2. docs/PROJECT_STATUS.md embeds the current bars block verbatim.
  3. README.md, PROJECT_STATUS.md and CLAIMS.md contain none of the contradiction phrases
     below while the contradicting code exists, and no unconditional fixture claims.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ("README.md", "docs/PROJECT_STATUS.md", "docs/CLAIMS.md")
MARKER = re.compile(r"<!--rj:([\w.\-]+)-->\s*([^\s|<]+)")

# phrase (lower-case) -> file whose existence makes the phrase false
CONTRADICTIONS = {
    "does not classify modulation": "backend/pipeline/classify.py",
    "no demodulation or decoding exists": "backend/pipeline/decode.py",
    "it is **not** wired into the api": "backend/pipeline/verify_estimator.py",
}
# claims that must carry their fixture conditions on the same line
CONDITIONAL = ("30/30",)
CONDITION_WORDS = ("fixture", "synth_gen", "synthetic")


def lookup(obj, path):
    for part in path.split("."):
        if isinstance(obj, list):
            obj = next((x for x in obj if x.get("name") == part or x.get("id") == part), None) \
                if not part.isdigit() else obj[int(part)]
        else:
            obj = obj.get(part) if isinstance(obj, dict) else None
        if obj is None:
            return None
    return obj


def fmt(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{100 * v:.1f}%" if 0 <= v <= 1 else f"{v:.3g}"
    return str(v)


def check(readiness: dict, root: Path = ROOT):
    problems = []
    claims = root / "docs" / "CLAIMS.md"
    if not claims.exists():
        problems.append("docs/CLAIMS.md is missing")
    else:
        for path, shown in MARKER.findall(claims.read_text()):
            want = lookup(readiness, path)
            if want is None:
                problems.append(f"CLAIMS.md marker {path}: no such readiness.json value")
            elif fmt(want) != shown:
                problems.append(f"CLAIMS.md marker {path}: says {shown}, readiness.json has {fmt(want)}")
    status = root / "docs" / "PROJECT_STATUS.md"
    bars = readiness.get("bars", "")
    if not status.exists() or bars.strip() not in status.read_text():
        problems.append("docs/PROJECT_STATUS.md does not embed the current readiness bars")
    for rel in DOCS:
        p = root / rel
        if not p.exists():
            continue
        text = p.read_text()
        low = text.lower()
        for phrase, code in CONTRADICTIONS.items():
            if phrase in low and (root / code).exists():
                problems.append(f"{rel}: says '{phrase}' but {code} exists")
        for line in text.splitlines():
            if any(c in line for c in CONDITIONAL) and not any(w in line.lower() for w in CONDITION_WORDS):
                problems.append(f"{rel}: unconditional claim: {line.strip()[:90]}")
    return not problems, problems
