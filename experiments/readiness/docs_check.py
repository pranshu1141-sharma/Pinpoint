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
DOCS = ("README.md", "docs/PROJECT_STATUS.md", "docs/CLAIMS.md", "docs/LIMITATIONS_AND_ROADMAP.md")
MARKER = re.compile(r"<!--rj:([\w.\-]+)-->[ ]?([^\s|<]+)")

# phrase (lower-case) -> file whose existence makes the phrase false
CONTRADICTIONS = {
    "does not classify modulation": "backend/pipeline/classify.py",
    "no demodulation or decoding exists": "backend/pipeline/decode.py",
    "it is **not** wired into the api": "backend/pipeline/verify_estimator.py",
    # stale status prose about the estimate spike, false once it is the product path
    "methodology under test": "backend/pipeline/verify_estimator.py",
    "is under test in `backend/experimental": "backend/pipeline/verify_estimator.py",
    "is not imported by detect": "backend/pipeline/verify_estimator.py",
}
MARKED = ("docs/CLAIMS.md", "docs/LIMITATIONS_AND_ROADMAP.md")   # files whose rj markers are synced
WINDOW_CLAIM = re.compile(r"caps the window at ([\d,]+) samples")
# claims that must carry their fixture conditions on the same line
CONDITIONAL = ("30/30",)
CONDITION_WORDS = ("fixture", "synth_gen", "synthetic")


def _max_samples(root):
    p = root / "backend" / "pipeline" / "verify_estimator.py"
    m = re.search(r"^MAX_SAMPLES = (\d+)", p.read_text(), re.M) if p.exists() else None
    return int(m.group(1)) if m else None


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
    if not (root / "docs" / "CLAIMS.md").exists():
        problems.append("docs/CLAIMS.md is missing")
    for rel in MARKED:
        doc = root / rel
        if not doc.exists():
            continue
        name = Path(rel).name
        for path, shown in MARKER.findall(doc.read_text()):
            want = lookup(readiness, path)
            if want is None:
                problems.append(f"{name} marker {path}: no such readiness.json value")
            elif fmt(want) != shown:
                problems.append(f"{name} marker {path}: says {shown}, readiness.json has {fmt(want)}")
    status = root / "docs" / "PROJECT_STATUS.md"
    embedded = _block(status.read_text()) if status.exists() else None
    if embedded is None or _comparable(embedded) != _comparable(readiness.get("bars", "")):
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
        cap = _max_samples(root)
        for claimed in WINDOW_CLAIM.findall(text):
            if cap is not None and int(claimed.replace(",", "")) != cap:
                problems.append(f"{rel}: says the window is capped at {claimed} samples, code has {cap:,}")
        for line in text.splitlines():
            if any(c in line for c in CONDITIONAL) and not any(w in line.lower() for w in CONDITION_WORDS):
                problems.append(f"{rel}: unconditional claim: {line.strip()[:90]}")
    return not problems, problems


START, END = "<!-- readiness:start -->", "<!-- readiness:end -->"


def _block(text):
    if START not in text or END not in text:
        return None
    return text[text.index(START) + len(START):text.index(END)].strip()


def _comparable(bars):
    """Bars without the Docs and Overall lines: the docs criterion itself changes those."""
    return [ln for ln in bars.strip().splitlines() if not ln.startswith(("Docs", "Overall"))]


def sync(readiness: dict, root: Path = ROOT):
    """Rewrite the bars block in PROJECT_STATUS and every rj-marked number in CLAIMS from readiness.json."""
    status = root / "docs" / "PROJECT_STATUS.md"
    if status.exists() and START in status.read_text():
        text = status.read_text()
        head, tail = text[:text.index(START) + len(START)], text[text.index(END):]
        status.write_text(f"{head}\n{readiness['bars'].strip()}\n{tail}")
    def repl(m):
        want = lookup(readiness, m.group(1))
        return m.group(0) if want is None else f"<!--rj:{m.group(1)}--> {fmt(want)}"
    for rel in MARKED:
        doc = root / rel
        if doc.exists():
            doc.write_text(MARKER.sub(repl, doc.read_text()))
