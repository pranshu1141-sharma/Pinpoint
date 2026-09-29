# Terminal CLI Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package PinPoint's existing batch CLI (`backend/cli.py`) as an installable, scriptable `pinpoint` terminal tool — new subcommands (`analyze --json`, `watch`, `summary`, `validate`, `--version`), `pip install -e .`, `--jobs N` parallelism, CI — without changing any analysis behaviour.

**Architecture:** A new thin wrapper module `backend/pinpoint_cli.py` imports and reuses `backend.cli`'s existing functions (`find_inputs`, `analyze_file`, `summary_rows`, `SUMMARY_FIELDS`, `ESTIMATORS`) — it adds no new analysis logic, only argument parsing, output-format plumbing (JSON Lines, process pool, polling loop, table printing, SigMF validation) around those functions. `backend/cli.py` itself is untouched so `python -m backend.cli` keeps working byte-for-byte. Packaging is a `pyproject.toml` at the repo root with a `pinpoint` console-script entry point.

**Tech Stack:** Python 3.11/3.12, argparse, `concurrent.futures.ProcessPoolExecutor`, stdlib `csv`/`json`/`tomllib`, `sigmf` (already a dependency), pytest, GitHub Actions.

## Global Constraints

- Work on branch `feat/terminal-cli`, created from `origin/main` (NOT local `main`, which is 35 commits behind and is missing `backend/cli.py` entirely).
- Never edit anything under `backend/pipeline/`, `backend/experimental/`, or `experiments/` — other active branches are changing those.
- `python -m backend.cli analyze <target> --out <dir>` must keep working exactly as today, unmodified.
- No analysis-behaviour changes anywhere. `backend/cli.py` is not modified by this plan.
- Outputs are deterministic: no wall-clock timestamps in result files (`TIMING_KEYS = ("elapsed_ms", "verify_elapsed_ms")` in `backend/cli.py` already strips these — reuse it via `analyze_file`, never re-derive it).
- `--jobs 1` output must be byte-identical to `--jobs 4` output (sort before writing).
- The process pool (`ProcessPoolExecutor`) is created only inside CLI entry-point functions in `backend/pinpoint_cli.py`, never at import time / module level.
- Do not add a `LICENSE` file. The user has chosen **MIT** for the `pyproject.toml` license metadata; do not add a `LICENSE` file yourself regardless.
- Minimum dependency versions already pinned in `backend/requirements.txt`: `numpy>=2.2,<3`, `scipy>=1.15,<2`, `sigmf>=1.2,<2`, `fastapi>=0.115,<1`, `uvicorn>=0.34,<1`, `python-multipart>=0.0.20,<1`, `pytest>=8,<10`, `httpx>=0.28,<1`. Reuse these exact ranges — do not invent new ones.
- Repo root for all commands below is `<repo-root>` = the git worktree root for `feat/terminal-cli` (contains `backend/`, `frontend/`, `README.md`). Tests use `ROOT = Path(__file__).resolve().parents[2]` exactly as `backend/tests/test_cli.py` already does.

---

## File Structure

- Create: `<repo-root>/pyproject.toml` — packaging metadata, `pinpoint` console-script.
- Create: `<repo-root>/backend/_version.py` — single-sourced version string.
- Create: `<repo-root>/backend/pinpoint_cli.py` — all new subcommands (analyze wrapper, watch, summary, validate, version).
- Create: `<repo-root>/backend/tests/test_pinpoint_cli.py` — tests for every subcommand.
- Create: `<repo-root>/backend/tests/test_packaging.py` — structural test of `pyproject.toml`.
- Create: `<repo-root>/.github/workflows/tests.yml` — CI.
- Modify: `<repo-root>/README.md` — add CI badge + "Terminal usage" section.

---

### Task 1: Branch setup + packaging scaffold (`pyproject.toml`, `backend/_version.py`)

**Files:**
- Create: `pyproject.toml`
- Create: `backend/_version.py`
- Test: `backend/tests/test_packaging.py`

**Interfaces:**
- Produces: `backend._version.__version__` (a `str`, e.g. `"0.1.0"`) — consumed by `backend/pinpoint_cli.py` in Task 2 for `--version`.
- Produces: console-script `pinpoint` in `pyproject.toml` pointing at `backend.pinpoint_cli:run` (that function is written in Task 2 — `pyproject.toml` can reference it before it exists; `pip install -e .` doesn't import it, only records the entry point).

- [ ] **Step 1: Create the branch from `origin/main`**

```bash
git fetch origin
git worktree add ../Pinpoint-terminal-cli -b feat/terminal-cli origin/main
cd ../Pinpoint-terminal-cli
```

(All later steps in this plan run with this worktree as the working directory / `ROOT`.)

- [ ] **Step 2: Write the failing structural test for `pyproject.toml`**

```python
# backend/tests/test_packaging.py
"""WP: pyproject.toml exists, is valid, and declares the pinpoint console-script."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_declares_pinpoint_entry_point_and_pinned_deps():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["scripts"]["pinpoint"] == "backend.pinpoint_cli:run"
    deps = data["project"]["dependencies"]
    assert "numpy>=2.2,<3" in deps
    assert "scipy>=1.15,<2" in deps
    assert "sigmf>=1.2,<2" in deps
    assert data["project"]["license"] == {"text": "MIT"}


def test_version_module_matches_pyproject_dynamic_source():
    from backend._version import __version__
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "backend._version.__version__"
    assert __version__  # non-empty string
```

- [ ] **Step 2b: Run it to verify it fails**

Run: `pytest backend/tests/test_packaging.py -v`
Expected: FAIL — `pyproject.toml` does not exist yet (`FileNotFoundError`), and `backend._version` doesn't exist (`ModuleNotFoundError`).

- [ ] **Step 3: Write `backend/_version.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "pinpoint"
dynamic = ["version"]
description = "PinPoint offline RF capture detector: batch analysis terminal CLI"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    "numpy>=2.2,<3",
    "scipy>=1.15,<2",
    "sigmf>=1.2,<2",
]

[project.optional-dependencies]
server = [
    "fastapi>=0.115,<1",
    "uvicorn>=0.34,<1",
    "python-multipart>=0.0.20,<1",
]
test = [
    "pytest>=8,<10",
    "httpx>=0.28,<1",
]

[project.scripts]
pinpoint = "backend.pinpoint_cli:run"

[tool.setuptools.dynamic]
version = { attr = "backend._version.__version__" }

[tool.setuptools.packages.find]
include = ["backend*"]
exclude = ["backend.tests*"]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest backend/tests/test_packaging.py -v`
Expected: PASS

- [ ] **Step 6: Manually verify real installability (not a pytest test — network/venv dependent)**

```bash
python3 -m venv /tmp/pinpoint-install-check
/tmp/pinpoint-install-check/bin/pip install -e ".[server,test]"
/tmp/pinpoint-install-check/bin/python -m backend.cli analyze backend/data/demo --out /tmp/pp-old-cli-check
```

Expected: install succeeds, and the old `python -m backend.cli` invocation still runs (via the venv's interpreter) even though only `pinpoint` is exposed as a console-script — confirms packaging didn't break the module invocation. Keep this venv around; Task 9 reuses it for the entry-point sanity check.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml backend/_version.py backend/tests/test_packaging.py
git commit -m "build: add pyproject.toml packaging scaffold for the pinpoint CLI"
```

---

### Task 2: `backend/pinpoint_cli.py` core — `analyze` wrapper (jobs=1, no `--json` yet) + `--version`

**Files:**
- Create: `backend/pinpoint_cli.py`
- Test: `backend/tests/test_pinpoint_cli.py`

**Interfaces:**
- Consumes: `backend.cli.{ESTIMATORS, SUFFIXES, SUMMARY_FIELDS, analyze_file, find_inputs, summary_rows}` (all already defined in `backend/cli.py`, unmodified).
- Consumes: `backend._version.__version__` (Task 1).
- Produces: `backend.pinpoint_cli.run(argv=None) -> int` — the console-script target.
- Produces: `backend.pinpoint_cli.build_parser() -> argparse.ArgumentParser` — used directly by later tasks' tests.
- Produces: `backend.pinpoint_cli._add_shared_analyze_args(parser)` — reused by `watch` in Task 7.
- Produces: `backend.pinpoint_cli._analyze_one(path, args) -> tuple[str, dict | None, str | None]` (name, blob-or-None, error-or-None) — reused by `--jobs` (Task 4) and `watch` (Task 7).
- Produces: `backend.pinpoint_cli._run_batch(inputs, args, jobs) -> list[tuple[str, dict | None, str | None]]` — reused by Task 4 and Task 7.
- Produces: `backend.pinpoint_cli.cmd_analyze(args) -> int`.

- [ ] **Step 1: Write the failing byte-identity test**

```python
# backend/tests/test_pinpoint_cli.py
"""Terminal CLI (pinpoint) subcommands: thin wrappers over backend.cli, no analysis-behaviour changes."""
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUNDLED = [ROOT / "backend/data/demo/demo.sigmf-data", ROOT / "backend/data/demo/demo.sigmf-meta",
           ROOT / "backend/data/demo/audio_demo.wav", ROOT / "test-audio/01-steady-tone.wav"]


def _run_old(*args):
    return subprocess.run([sys.executable, "-m", "backend.cli", *map(str, args)], cwd=ROOT,
                          capture_output=True, text=True)


def _run_new(*args):
    return subprocess.run([sys.executable, "-m", "backend.pinpoint_cli", *map(str, args)], cwd=ROOT,
                          capture_output=True, text=True)


@pytest.fixture
def inputs(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    for f in BUNDLED:
        shutil.copy(f, d / f.name)
    return d


def test_analyze_jobs1_matches_old_backend_cli_byte_for_byte(inputs, tmp_path):
    old_out, new_out = tmp_path / "old", tmp_path / "new"
    r_old = _run_old("analyze", inputs, "--out", old_out)
    r_new = _run_new("analyze", inputs, "--out", new_out, "--jobs", "1")
    assert r_old.returncode == r_new.returncode == 0, (r_old.stderr, r_new.stderr)
    old_files = sorted(p.name for p in old_out.iterdir())
    new_files = sorted(p.name for p in new_out.iterdir())
    assert old_files == new_files
    for name in old_files:
        assert (old_out / name).read_bytes() == (new_out / name).read_bytes(), name


def test_version_flag():
    r = _run_new("--version")
    assert r.returncode == 0
    assert r.stdout.strip() == "pinpoint 0.1.0"


def test_analyze_without_out_or_json_is_a_usage_error(inputs, tmp_path):
    r = _run_new("analyze", inputs)
    assert r.returncode == 1
    assert "--out" in r.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/test_pinpoint_cli.py -v`
Expected: FAIL — `backend.pinpoint_cli` module does not exist (`ModuleNotFoundError` surfaces as non-zero/garbled subprocess output, or import error if run directly).

- [ ] **Step 3: Write `backend/pinpoint_cli.py`**

```python
"""Terminal packaging around the offline batch CLI (backend.cli): adds --json, --jobs,
watch, summary and validate around the same find_inputs/analyze_file/summary_rows
functions backend.cli already uses. No analysis logic lives here."""
import argparse
import csv
import json
import sys
from pathlib import Path

from backend._version import __version__
from backend.cli import ESTIMATORS, SUMMARY_FIELDS, analyze_file, find_inputs, summary_rows


def _add_shared_analyze_args(parser):
    parser.add_argument("--estimator", choices=ESTIMATORS, default="verify")
    parser.add_argument("--sample-rate", type=float, default=None, help="required for raw .iq")
    parser.add_argument("--datatype", default=None, help="required for raw .iq (e.g. cf32_le, ci16_le)")
    parser.add_argument("--wav-mode", default="auto", choices=("auto", "iq", "audio_left", "audio_right"))
    parser.add_argument("--margin-db", type=float, default=8.0)


def _analyze_one(path, args):
    """Runs in a worker process when --jobs > 1: (file name, blob-or-None, error-or-None)."""
    try:
        return path.name, analyze_file(path, args), None
    except Exception as exc:                     # malformed/ambiguous input: reported, never raised
        return path.name, None, f"{type(exc).__name__}: {exc}"


def _run_batch(inputs, args, jobs):
    """Analyzes every input, returning one (name, blob, error) triple per input, in input order.
    jobs=1 is a plain sequential loop; jobs>1 uses a process pool. ProcessPoolExecutor.map
    preserves call order in its results regardless of completion order, so output is the
    same either way."""
    if jobs == 1:
        return [_analyze_one(path, args) for path in inputs]
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(_analyze_one, inputs, [args] * len(inputs)))


def _write_outputs(name, blob, out_dir):
    stem = name[:-len(".sigmf-data")] if name.lower().endswith(".sigmf-data") else Path(name).stem
    sigmf = blob["sigmf"]
    (out_dir / f"{stem}.json").write_text(
        json.dumps({k: v for k, v in blob.items() if k != "sigmf"}, indent=1, sort_keys=True) + "\n")
    (out_dir / f"{stem}.sigmf-meta").write_text(json.dumps(sigmf, indent=1, sort_keys=True) + "\n")


def cmd_analyze(args):
    try:
        inputs = find_inputs(args.target)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.out is None and not args.json:
        print("--out is required unless --json is given", file=sys.stderr)
        return 1
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)

    results = _run_batch(inputs, args, args.jobs)

    rows, failed, json_lines = [], 0, []
    for name, blob, err in results:
        if err is not None:
            failed += 1
            rows.append({k: "" for k in SUMMARY_FIELDS} | {"needs_review": "true", "file": name, "error": err})
            print(f"{name}: {err}", file=sys.stderr)
            continue
        if args.out is not None:
            _write_outputs(name, blob, args.out)
        rows += summary_rows(blob)
        if args.json:
            for d in sorted(blob["detections"], key=lambda d: str(d["id"])):
                json_lines.append({"file": name, **d})

    if args.json:
        for obj in json_lines:
            print(json.dumps(obj, sort_keys=True))

    if args.out is not None:
        rows.sort(key=lambda r: (r["needs_review"] != "true", r["file"], str(r["detection_id"])))
        with (args.out / "summary.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)
            w.writeheader()
            w.writerows(rows)

    dest = f" -> {args.out}" if args.out is not None else ""
    print(f"analysed {len(inputs) - failed}/{len(inputs)} captures{dest}",
          file=sys.stderr if args.json else sys.stdout)
    return 2 if failed else 0


def build_parser():
    ap = argparse.ArgumentParser(prog="pinpoint")
    ap.add_argument("--version", action="version", version=f"pinpoint {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    an = sub.add_parser("analyze", help="analyse a capture file or every capture in a folder")
    an.add_argument("target", type=Path)
    an.add_argument("--out", type=Path, default=None)
    an.add_argument("--json", action="store_true", help="write per-detection JSON Lines to stdout")
    an.add_argument("--jobs", type=int, default=1)
    _add_shared_analyze_args(an)
    an.set_defaults(func=cmd_analyze)
    return ap


def run(argv=None):
    args = build_parser().parse_args(argv)
    if args.jobs < 1:
        print("--jobs must be >= 1", file=sys.stderr)
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(run())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_pinpoint_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pinpoint_cli.py backend/tests/test_pinpoint_cli.py
git commit -m "feat: add pinpoint CLI with analyze wrapper and --version"
```

---

### Task 3: `analyze --json` — JSON Lines to stdout, progress to stderr

**Files:**
- Modify: `backend/tests/test_pinpoint_cli.py` (append)

The implementation already exists from Task 2 (`args.json` branch in `cmd_analyze`) — this task is pure test coverage to lock the behaviour down, since Task 2's implementation was written ahead of its own test for this flag (shared code path).

**Interfaces:**
- Consumes: `cmd_analyze` (Task 2), unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_json_flag_writes_jsonl_to_stdout_and_progress_to_stderr(inputs):
    r = _run_new("analyze", inputs, "--json")
    assert r.returncode == 0, r.stderr
    lines = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    assert lines, "expected at least one detection line"
    assert all("file" in obj for obj in lines)
    assert {obj["file"] for obj in lines} <= {"demo.sigmf-data", "audio_demo.wav", "01-steady-tone.wav"}
    assert "analysed" in r.stderr           # progress went to stderr, not stdout
    assert "analysed" not in r.stdout       # stdout is pure JSONL, pipeable to jq


def test_json_flag_with_out_also_writes_files(inputs, tmp_path):
    out = tmp_path / "out"
    r = _run_new("analyze", inputs, "--json", "--out", out)
    assert r.returncode == 0, r.stderr
    assert (out / "summary.csv").exists()
    lines = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    assert lines
```

- [ ] **Step 2: Run to verify it fails or passes**

Run: `pytest backend/tests/test_pinpoint_cli.py -k json -v`
Expected: PASS immediately (Task 2 already implements this path) — if it fails, the failure is a real bug in Task 2's `--json` branch; fix `cmd_analyze` in `backend/pinpoint_cli.py` until it passes rather than editing the test.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_pinpoint_cli.py
git commit -m "test: cover pinpoint analyze --json JSON Lines output"
```

---

### Task 4: `--jobs N` determinism

**Files:**
- Modify: `backend/tests/test_pinpoint_cli.py` (append)

The pooling implementation already exists from Task 2 (`_run_batch`) — this task adds the determinism test the spec requires, and fixes any ordering bug it finds.

**Interfaces:**
- Consumes: `_run_batch`, `cmd_analyze` (Task 2), unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_jobs_4_matches_jobs_1_byte_for_byte(inputs, tmp_path):
    out1, out4 = tmp_path / "j1", tmp_path / "j4"
    r1 = _run_new("analyze", inputs, "--out", out1, "--jobs", "1")
    r4 = _run_new("analyze", inputs, "--out", out4, "--jobs", "4")
    assert r1.returncode == r4.returncode == 0, (r1.stderr, r4.stderr)
    names1 = sorted(p.name for p in out1.iterdir())
    names4 = sorted(p.name for p in out4.iterdir())
    assert names1 == names4
    for name in names1:
        assert (out1 / name).read_bytes() == (out4 / name).read_bytes(), name


def test_jobs_4_json_output_matches_jobs_1(inputs):
    r1 = _run_new("analyze", inputs, "--json", "--jobs", "1")
    r4 = _run_new("analyze", inputs, "--json", "--jobs", "4")
    assert r1.returncode == r4.returncode == 0, (r1.stderr, r4.stderr)
    lines1 = sorted(r1.stdout.splitlines())
    lines4 = sorted(r4.stdout.splitlines())
    assert lines1 == lines4
```

- [ ] **Step 2: Run to verify it passes (or fix `_run_batch`/`cmd_analyze` if not)**

Run: `pytest backend/tests/test_pinpoint_cli.py -k jobs_4 -v`
Expected: PASS. If the file-output test fails because per-file JSON/SigMF content differs between jobs counts, the bug is almost certainly a worker process re-importing NumPy with different BLAS thread settings changing float rounding — pin `OMP_NUM_THREADS=1`/`OPENBLAS_NUM_THREADS=1` in the test environment (not in library code) before concluding it's a real determinism bug in the pool itself, since `analyze_file` performs the exact same computation regardless of which process runs it.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_pinpoint_cli.py
git commit -m "test: cover pinpoint analyze --jobs 4 determinism vs --jobs 1"
```

---

### Task 5: `pinpoint summary <out-dir>`

**Files:**
- Modify: `backend/pinpoint_cli.py`
- Modify: `backend/tests/test_pinpoint_cli.py` (append)

**Interfaces:**
- Consumes: `summary.csv` written by `cmd_analyze` (Task 2), with `SUMMARY_FIELDS` columns from `backend.cli`.
- Produces: `backend.pinpoint_cli.cmd_summary(args) -> int`, registered as the `summary` subcommand.

- [ ] **Step 1: Write the failing test**

```python
def test_summary_prints_needs_review_first_and_totals(inputs, tmp_path):
    out = tmp_path / "out"
    assert _run_new("analyze", inputs, "--out", out).returncode == 0
    r = _run_new("summary", out)
    assert r.returncode == 0, r.stderr
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    header_idx = next(i for i, l in enumerate(lines) if l.startswith("needs_review"))
    body = lines[header_idx + 2:]                 # skip header + separator row
    true_seen_false = False
    for line in body:
        if not line.startswith("true") and not line.startswith("false"):
            break                                  # totals line
        if line.startswith("false"):
            true_seen_false = True
        elif true_seen_false:
            pytest.fail(f"a 'true' row appeared after a 'false' row: {line}")
    totals = lines[-1]
    assert totals.startswith("files=") and "detections=" in totals and "labelled=" in totals
    assert "abstained=" in totals and "errors=" in totals


def test_summary_missing_out_dir_is_a_usage_error(tmp_path):
    r = _run_new("summary", tmp_path / "does-not-exist")
    assert r.returncode == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/test_pinpoint_cli.py -k summary -v`
Expected: FAIL — `summary` subcommand not registered.

- [ ] **Step 3: Add `cmd_summary` and register the subcommand**

Add to `backend/pinpoint_cli.py`:

```python
def cmd_summary(args):
    csv_path = args.out_dir / "summary.csv"
    if not csv_path.exists():
        print(f"{csv_path} does not exist", file=sys.stderr)
        return 1
    rows = list(csv.DictReader(csv_path.open()))
    rows.sort(key=lambda r: (r["needs_review"] != "true", r["file"], r["detection_id"]))
    cols = ["needs_review", "file", "detection_id", "label", "tier", "snr_db", "status", "error"]
    widths = {c: max([len(c)] + [len(r[c]) for r in rows]) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(r[c].ljust(widths[c]) for c in cols))
    files = {r["file"] for r in rows}
    labelled = sum(1 for r in rows if r["label"])
    errors = sum(1 for r in rows if r["error"])
    abstained = sum(1 for r in rows if not r["label"] and not r["error"])
    print(f"files={len(files)} detections={len(rows)} labelled={labelled} abstained={abstained} errors={errors}")
    return 0
```

In `build_parser()`, after the `analyze` subparser block, add:

```python
    su = sub.add_parser("summary", help="print a terminal table from an --out folder's summary.csv")
    su.add_argument("out_dir", type=Path)
    su.set_defaults(func=cmd_summary)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_pinpoint_cli.py -k summary -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pinpoint_cli.py backend/tests/test_pinpoint_cli.py
git commit -m "feat: add pinpoint summary subcommand"
```

---

### Task 6: `pinpoint validate <out-dir>`

**Files:**
- Modify: `backend/pinpoint_cli.py`
- Modify: `backend/tests/test_pinpoint_cli.py` (append)

**Interfaces:**
- Consumes: `.sigmf-meta` files written by `cmd_analyze` (Task 2); `sigmf.SigMFFile` from the `sigmf` package (already a pinned dependency, same import `backend/pipeline/sigmf_io.py` already uses: `from sigmf import SigMFFile`).
- Produces: `backend.pinpoint_cli.cmd_validate(args) -> int`, registered as the `validate` subcommand.

- [ ] **Step 1: Write the failing test**

```python
def test_validate_passes_on_analyze_output(inputs, tmp_path):
    out = tmp_path / "out"
    assert _run_new("analyze", inputs, "--out", out).returncode == 0
    r = _run_new("validate", out)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout


def test_validate_fails_on_corrupted_meta(inputs, tmp_path):
    out = tmp_path / "out"
    assert _run_new("analyze", inputs, "--out", out).returncode == 0
    meta_path = next(out.glob("*.sigmf-meta"))
    broken = json.loads(meta_path.read_text())
    broken.pop("global", None)                     # required SigMF top-level key
    meta_path.write_text(json.dumps(broken))
    r = _run_new("validate", out)
    assert r.returncode != 0


def test_validate_no_meta_files_is_a_usage_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run_new("validate", empty)
    assert r.returncode == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest backend/tests/test_pinpoint_cli.py -k validate -v`
Expected: FAIL — `validate` subcommand not registered.

- [ ] **Step 3: Add `cmd_validate` and register the subcommand**

Add to `backend/pinpoint_cli.py`:

```python
def cmd_validate(args):
    from sigmf import SigMFFile
    metas = sorted(args.out_dir.glob("*.sigmf-meta"))
    if not metas:
        print(f"no .sigmf-meta files found in {args.out_dir}", file=sys.stderr)
        return 1
    failed = 0
    for path in metas:
        metadata = json.loads(path.read_text())
        try:
            SigMFFile(metadata=metadata).validate()
            print(f"{path.name}: OK")
        except Exception as exc:
            failed += 1
            print(f"{path.name}: {exc}", file=sys.stderr)
    return 2 if failed else 0
```

In `build_parser()`, after the `summary` subparser block, add:

```python
    va = sub.add_parser("validate", help="validate every .sigmf-meta in an --out folder")
    va.add_argument("out_dir", type=Path)
    va.set_defaults(func=cmd_validate)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_pinpoint_cli.py -k validate -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pinpoint_cli.py backend/tests/test_pinpoint_cli.py
git commit -m "feat: add pinpoint validate subcommand"
```

---

### Task 7: `pinpoint watch <dir> --out <dir>`

**Files:**
- Modify: `backend/pinpoint_cli.py`
- Modify: `backend/tests/test_pinpoint_cli.py` (append)

**Interfaces:**
- Consumes: `find_inputs`, `_run_batch`, `_write_outputs` (Task 2).
- Produces: `backend.pinpoint_cli._load_processed(out_dir) -> set[str]`, `_save_processed(out_dir, processed)`, `_watch_once(args, sizes, processed) -> None` (mutates `sizes`/`processed` in place; one poll cycle, importable directly by tests to avoid sleeping in the unit tests), `cmd_watch(args) -> int` (the infinite polling loop with `Ctrl-C` handling), registered as the `watch` subcommand.

- [ ] **Step 1: Write the failing tests**

```python
def test_watch_once_processes_a_stable_file_and_skips_it_next_time(tmp_path):
    from backend.pinpoint_cli import _watch_once, build_parser

    src = tmp_path / "in"
    src.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    shutil.copy(ROOT / "backend/data/demo/demo.sigmf-data", src / "demo.sigmf-data")
    shutil.copy(ROOT / "backend/data/demo/demo.sigmf-meta", src / "demo.sigmf-meta")

    args = build_parser().parse_args(["watch", str(src), "--out", str(out)])
    sizes, processed = {}, set()

    _watch_once(args, sizes, processed)             # first poll: just records the size, not yet "stable"
    assert not (out / "demo.json").exists()
    assert not processed

    _watch_once(args, sizes, processed)              # second poll: size unchanged -> stable -> analysed
    assert (out / "demo.json").exists()
    assert len(processed) == 1

    _watch_once(args, sizes, processed)               # third poll: already processed -> skipped, not re-written
    written_at = (out / "demo.json").stat().st_mtime
    _watch_once(args, sizes, processed)
    assert (out / "demo.json").stat().st_mtime == written_at


def test_watch_state_file_persists_processed_files_across_restarts(tmp_path):
    from backend.pinpoint_cli import _load_processed, _save_processed

    out = tmp_path / "out"
    out.mkdir()
    assert _load_processed(out) == set()
    _save_processed(out, {"/a/b.wav", "/a/c.wav"})
    assert _load_processed(out) == {"/a/b.wav", "/a/c.wav"}
    assert (out / ".pinpoint-watch-state.json").exists()


def test_watch_stops_cleanly_on_sigint(tmp_path):
    import signal
    import time

    src = tmp_path / "in"
    src.mkdir()
    out = tmp_path / "out"
    proc = subprocess.Popen([sys.executable, "-m", "backend.pinpoint_cli", "watch", str(src), "--out", str(out),
                             "--poll-interval", "0.1"], cwd=ROOT, stderr=subprocess.PIPE, text=True)
    time.sleep(0.5)
    proc.send_signal(signal.SIGINT)
    returncode = proc.wait(timeout=5)
    assert returncode == 0
    assert "stopped" in proc.stderr.read()
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest backend/tests/test_pinpoint_cli.py -k watch -v`
Expected: FAIL — `watch` subcommand and helpers don't exist.

- [ ] **Step 3: Add watch helpers, `cmd_watch`, and register the subcommand**

Add near the top of `backend/pinpoint_cli.py`, after the existing imports:

```python
import time
```

Add after `_write_outputs`:

```python
def _state_path(out_dir):
    return out_dir / ".pinpoint-watch-state.json"


def _load_processed(out_dir):
    path = _state_path(out_dir)
    return set(json.loads(path.read_text())["processed"]) if path.exists() else set()


def _save_processed(out_dir, processed):
    _state_path(out_dir).write_text(json.dumps({"processed": sorted(processed)}, indent=1, sort_keys=True) + "\n")


def _watch_once(args, sizes, processed):
    """One poll cycle: analyses every capture whose size has been unchanged since the
    previous cycle and that hasn't been processed before. Mutates sizes/processed in place."""
    if not args.target.is_dir():
        raise FileNotFoundError(f"{args.target} does not exist")
    candidates = [p for p in find_inputs(args.target) if str(p.resolve()) not in processed]
    seen = {str(p.resolve()) for p in candidates}
    stable = []
    for p in candidates:
        key = str(p.resolve())
        size = p.stat().st_size
        if sizes.get(key) == size:
            stable.append(p)
        else:
            sizes[key] = size
    for key in [k for k in sizes if k not in seen]:
        del sizes[key]
    if not stable:
        return
    for name, blob, err in _run_batch(stable, args, args.jobs):
        path = next(p for p in stable if p.name == name)
        processed.add(str(path.resolve()))
        if err is not None:
            print(f"{name}: {err}", file=sys.stderr)
            continue
        _write_outputs(name, blob, args.out)
        print(f"analysed {name}", file=sys.stderr)
    _save_processed(args.out, processed)


def cmd_watch(args):
    args.out.mkdir(parents=True, exist_ok=True)
    processed = _load_processed(args.out)
    sizes = {}
    print(f"watching {args.target} (poll every {args.poll_interval}s, Ctrl-C to stop)", file=sys.stderr)
    try:
        while True:
            _watch_once(args, sizes, processed)
            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 0
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
```

In `build_parser()`, after the `validate` subparser block, add:

```python
    wa = sub.add_parser("watch", help="poll a folder and analyse new captures as they arrive")
    wa.add_argument("target", type=Path)
    wa.add_argument("--out", type=Path, required=True)
    wa.add_argument("--jobs", type=int, default=1)
    wa.add_argument("--poll-interval", type=float, default=2.0)
    _add_shared_analyze_args(wa)
    wa.set_defaults(func=cmd_watch)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_pinpoint_cli.py -k watch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pinpoint_cli.py backend/tests/test_pinpoint_cli.py
git commit -m "feat: add pinpoint watch subcommand with polling and a processed-files state file"
```

---

### Task 8: CI workflow + README docs

**Files:**
- Create: `.github/workflows/tests.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: `pyproject.toml` extras `server`/`test` (Task 1), all `pinpoint` subcommands (Tasks 2–7).

- [ ] **Step 1: Write `.github/workflows/tests.yml`**

```yaml
name: tests

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[server,test]"
      - run: pytest backend/tests -v
```

- [ ] **Step 2: Verify the YAML parses (no GitHub Actions runner available locally)**

```bash
python3 -c "import tomllib" # confirms python3.11+ toolchain in use for this check
python3 - <<'PY'
import re
text = open(".github/workflows/tests.yml").read()
assert "python-version" in text and "3.11" in text and "3.12" in text
assert "pip install -e \".[server,test]\"" in text
assert "pytest backend/tests" in text
print("workflow file looks structurally correct")
PY
```

Expected: prints "workflow file looks structurally correct". (Full validation happens on the actual push in Task 9.)

- [ ] **Step 3: Add the CI badge and "Terminal usage" section to `README.md`**

Read `README.md` first to find the exact top-of-file line and the existing "Batch analysis (offline CLI)" section (currently right after the "Modulation label and symbol rate" section) — insert the badge as the second line (right under the `# SIH26147 — PinPoint` title) and replace/extend the existing "Batch analysis (offline CLI)" section with:

```markdown
# SIH26147 — PinPoint

![tests](https://github.com/pranshu1141-sharma/Pinpoint/actions/workflows/tests.yml/badge.svg)
```

Add this new section right after the existing "Batch analysis (offline CLI)" section:

````markdown
## Terminal usage (`pinpoint`)

Install once (editable, so code changes take effect immediately):

```bash
pip install -e .          # core: numpy, scipy, sigmf
pip install -e ".[server]" # + FastAPI/uvicorn, if you also want the dashboard API
```

Exit codes, for every subcommand below: `0` everything analysed/validated cleanly, `1` a usage
error (bad path, missing required flag), `2` at least one input was malformed, ambiguous, or
failed validation (still listed in `summary.csv` / printed, never silently skipped).

**`analyze`** — same behaviour as `python -m backend.cli analyze`:

```bash
pinpoint analyze path/to/captures --out results/
```

**`analyze --json`** — per-detection JSON Lines on stdout (progress/logs go to stderr), for piping:

```bash
pinpoint analyze path/to/captures --json | jq -c 'select(.needs_review == false) | {file, label: .modulation_label, snr_db}'
```

**`analyze --jobs N`** — one worker process per file; `--jobs 1` (the default) and `--jobs 4`
produce byte-identical output, just faster:

```bash
pinpoint analyze path/to/captures --out results/ --jobs 4
```

**`watch`** — polls a folder, analyses each capture once its size stops changing between polls,
and never re-analyses a file it's already processed (tracked in `results/.pinpoint-watch-state.json`).
Stops cleanly on Ctrl-C:

```bash
pinpoint watch incoming/ --out results/
```

**`summary`** — a terminal table from an existing `--out` folder's `summary.csv`, rows needing
review first, plus totals:

```bash
pinpoint summary results/
```

**`validate`** — validates every `.sigmf-meta` written into an `--out` folder with the `sigmf`
library's own validator:

```bash
pinpoint validate results/
```

**`--version`**:

```bash
pinpoint --version
```

`--estimator`, `--sample-rate`, `--datatype`, `--wav-mode` and `--margin-db` work the same way on
every subcommand above as they do on `python -m backend.cli analyze`.
````

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/tests.yml README.md
git commit -m "ci: run tests on push/PR for Python 3.11 and 3.12; document terminal usage"
```

---

### Task 9: Final verification and report

**Files:** none (verification only).

- [ ] **Step 1: Confirm identical output between the old and new CLI on a real folder**

```bash
pinpoint analyze backend/data/real --out /tmp/pp-new-real
python -m backend.cli analyze backend/data/real --out /tmp/pp-old-real
diff -rq /tmp/pp-old-real /tmp/pp-new-real
```

Expected: `diff -rq` prints nothing (no differences). If it does, stop and debug with
`superpowers:systematic-debugging` before proceeding — do not report success.

- [ ] **Step 2: Time `--jobs 4` vs `--jobs 1` on the G5 real-capture folder (`backend/data/real`, 87 files per the WP2 commit history)**

```bash
time pinpoint analyze backend/data/real --out /tmp/pp-j1 --jobs 1
time pinpoint analyze backend/data/real --out /tmp/pp-j4 --jobs 4
diff -rq /tmp/pp-j1 /tmp/pp-j4
```

Expected: `diff -rq` prints nothing; note both wall-clock times for the final report.

- [ ] **Step 3: Run the full test suite**

```bash
pytest backend/tests -v
```

Expected: all tests pass, including the pre-existing suite (`test_cli.py`, `test_api.py`, etc. — unaffected by this branch) and every new test from Tasks 1–8. Record the total test count.

- [ ] **Step 4: Confirm `python -m backend.cli` still works standalone**

```bash
python -m backend.cli analyze backend/data/demo --out /tmp/pp-old-invocation-check
```

Expected: exit 0, same as before this branch existed.

- [ ] **Step 5: Report to the user**

Summarize: every file added/changed (from the `File Structure` section above), total test count
(old + new), the Task 9 Step 1 identical-output result, the Task 9 Step 2 wall-clock numbers for
`--jobs 1` vs `--jobs 4` on `backend/data/real`, and anything skipped or not done (e.g., the
`LICENSE` file was intentionally not added — license metadata is set to MIT in `pyproject.toml`
per the user's answer). Do not push or open a PR unless the user asks.
