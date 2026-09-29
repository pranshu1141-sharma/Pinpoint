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
