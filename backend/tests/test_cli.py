"""WP9: offline batch CLI (python -m backend.cli analyze <file-or-folder> --out <dir>)."""
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from backend.cli import main

ROOT = Path(__file__).resolve().parents[2]
BUNDLED = [ROOT / "backend/data/demo/demo.sigmf-data", ROOT / "backend/data/demo/demo.sigmf-meta",
           ROOT / "backend/data/demo/audio_demo.wav", ROOT / "test-audio/01-steady-tone.wav"]


def _run(*args):
    return subprocess.run([sys.executable, "-m", "backend.cli", *map(str, args)], cwd=ROOT,
                          capture_output=True, text=True)


@pytest.fixture
def inputs(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    for f in BUNDLED:
        shutil.copy(f, d / f.name)
    return d


def test_folder_writes_json_sigmf_and_a_review_first_summary(inputs, tmp_path):
    out = tmp_path / "out"
    r = _run("analyze", inputs, "--out", out)
    assert r.returncode == 0, r.stderr
    for stem in ("demo", "audio_demo", "01-steady-tone"):
        blob = json.loads((out / f"{stem}.json").read_text())
        assert blob["estimator"] == "verify" and blob["detections"]
        meta = json.loads((out / f"{stem}.sigmf-meta").read_text())
        assert len(meta["annotations"]) == len(blob["detections"])
    rows = list(csv.DictReader((out / "summary.csv").open()))
    assert {r["file"] for r in rows} == {"demo.sigmf-data", "audio_demo.wav", "01-steady-tone.wav"}
    review = [r["needs_review"] == "true" for r in rows]
    assert review == sorted(review, reverse=True)          # needs_review rows first
    demo = [r for r in rows if r["file"] == "demo.sigmf-data"]
    assert any(r["label"] == "BPSK" for r in demo)         # the demo's 10 dB BPSK source


def test_outputs_are_deterministic(inputs, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert _run("analyze", inputs, "--out", a).returncode == 0
    assert _run("analyze", inputs, "--out", b).returncode == 0
    for f in sorted(p.name for p in a.iterdir()):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_malformed_input_gives_a_nonzero_exit_and_is_reported(inputs, tmp_path):
    (inputs / "broken.wav").write_bytes(b"not a wav file")
    out = tmp_path / "out"
    r = _run("analyze", inputs, "--out", out)
    assert r.returncode != 0
    rows = list(csv.DictReader((out / "summary.csv").open()))
    broken = [r for r in rows if r["file"] == "broken.wav"]
    assert broken and broken[0]["error"] and broken[0]["needs_review"] == "true"
    assert (out / "demo.json").exists()                     # the other files were still analysed


def test_raw_iq_needs_explicit_rate_and_datatype(tmp_path):
    raw = tmp_path / "in" / "x.iq"
    raw.parent.mkdir()
    raw.write_bytes((ROOT / "backend/data/demo/demo.sigmf-data").read_bytes())
    assert _run("analyze", raw, "--out", tmp_path / "o1").returncode != 0
    r = _run("analyze", raw, "--out", tmp_path / "o2", "--sample-rate", "48000", "--datatype", "cf32_le")
    assert r.returncode == 0, r.stderr


def test_rtl433_named_cu8_needs_no_rate_or_datatype(tmp_path):
    """WP2: raw 8-bit IQ as rtl_433 writes it; datatype from the suffix, rate and centre from the name."""
    from backend.pipeline.ingest import raw_hints
    assert raw_hints("g001_433.92M_250k.cu8") == {"datatype": "cu8", "sample_rate": 250000.0,
                                                  "center_frequency_hz": 433920000.0}
    assert raw_hints("capture.cu8") == {"datatype": "cu8", "sample_rate": None, "center_frequency_hz": None}
    rng = np.random.default_rng(0)
    n, fs = 131072, 250000
    t = np.arange(n)
    bits = np.repeat(rng.integers(0, 2, n // 50 + 1), 50)[:n]
    x = bits * 0.6 * np.exp(2j * np.pi * 0.1 * t) + 0.02 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    raw = np.empty(2 * n, np.uint8)
    raw[0::2] = np.clip(np.round(x.real * 127.5 + 127.5), 0, 255)
    raw[1::2] = np.clip(np.round(x.imag * 127.5 + 127.5), 0, 255)
    src = tmp_path / "in"
    src.mkdir()
    raw.tofile(src / "g001_433.92M_250k.cu8")
    raw.tofile(src / "noname.cu8")
    out = tmp_path / "out"
    assert main(["analyze", str(src), "--out", str(out)]) == 2          # noname.cu8 has no rate: reported
    blob = json.loads((out / "g001_433.92M_250k.json").read_text())
    assert blob["metadata"]["sample_rate"] == fs and blob["metadata"]["datatype"] == "cu8"
    assert blob["metadata"]["center_frequency_hz"] == 433.92e6
    assert any(abs((d["freq_lower_hz"] + d["freq_upper_hz"]) / 2 - 25000) < 5000 for d in blob["detections"])
    rows = list(csv.DictReader((out / "summary.csv").open()))
    assert any(r["file"] == "noname.cu8" and r["error"] for r in rows)
