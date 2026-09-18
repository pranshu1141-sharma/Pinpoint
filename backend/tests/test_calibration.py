"""Phase 3 acceptance tests: calibration of Detect's two confidence scores.

Acceptance criterion: each score has a documented reliability diagram, an
ECE number, and either a calibration transform or an explicit
"uncalibrated, ECE=X" label in the API output.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from backend.pipeline import detect
from backend.pipeline.calibration import (IsotonicCalibrator, expected_calibration_error,
                                          pool_adjacent_violators, reliability_diagram)
from backend.pipeline.calibration_corpus import build_corpus
from backend.pipeline.detect import analyze_capture, calibrate_confidence
from backend.pipeline.ingest import Capture
from backend.pipeline.synth_gen import FS, make_signal

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"


def test_pool_adjacent_violators_is_monotone_non_decreasing():
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 1, 200)
    y = (x > 0.5).astype(float) + rng.normal(0, 0.1, 200)
    xs, y_fit = pool_adjacent_violators(x, y)
    assert np.all(np.diff(xs) >= 0)
    assert np.all(np.diff(y_fit) >= -1e-12)


def test_isotonic_calibrator_roundtrip_and_json():
    rng = np.random.default_rng(1)
    scores = rng.uniform(0, 1, 300)
    labels = (rng.uniform(0, 1, 300) < scores ** 2).astype(float)  # miscalibrated: true rate is score^2
    cal = IsotonicCalibrator().fit(scores, labels)
    calibrated = cal.predict(scores)
    # Calibrated predictions should track score^2 far better than the raw
    # score does, on the SAME data it was fit on (a sanity check on the fit
    # itself, not a generalization claim).
    assert np.mean(np.abs(calibrated - scores ** 2)) < np.mean(np.abs(scores - scores ** 2))
    restored = IsotonicCalibrator.from_json(cal.to_json())
    assert np.allclose(restored.predict(scores), calibrated)


def test_reliability_diagram_and_ece_on_perfectly_calibrated_data():
    rng = np.random.default_rng(2)
    scores = rng.uniform(0, 1, 20000)
    labels = (rng.uniform(0, 1, 20000) < scores).astype(float)
    rows = reliability_diagram(scores, labels, n_bins=10)
    assert len(rows) == 10
    assert sum(r["count"] for r in rows) == 20000
    ece = expected_calibration_error(scores, labels, n_bins=10)
    assert ece < 0.02  # perfectly calibrated by construction; only sampling noise remains


def test_reliability_diagram_and_ece_on_badly_miscalibrated_data():
    rng = np.random.default_rng(3)
    scores = rng.uniform(0.4, 0.6, 20000)  # always "unsure" ...
    labels = np.ones(20000)  # ... but always right
    ece = expected_calibration_error(scores, labels, n_bins=10)
    assert ece > 0.35


def test_shipped_calibrator_files_and_report_exist():
    """calibrate.py must have been run at least once and its output checked
    in -- these are the "documented reliability diagram" and "ECE number"
    the acceptance criterion asks for."""
    report_path = DOCS_DIR / "confidence-calibration.json"
    assert report_path.exists(), "run `cd backend && python3 -m pipeline.calibrate` and commit docs/confidence-calibration.json"
    report = json.loads(report_path.read_text())
    assert "synthetic" in report["corpus"]["origin"]
    for score_name in ("confidence", "confidence_evidence_based"):
        assert score_name in report
        assert isinstance(report[score_name]["raw_ece_held_out"], float)
        assert isinstance(report[score_name]["calibrated_ece_held_out"], float)
        assert len(report[score_name]["raw_reliability_diagram"]) > 0
        for suffix in ("raw", "calibrated"):
            svg_path = DOCS_DIR / f"calibration-{score_name.replace('_', '-')}-{suffix}.svg"
            assert svg_path.exists()
            assert "<svg" in svg_path.read_text()


def test_analyze_capture_publishes_calibrated_fields_or_explicit_uncalibrated_label():
    x, _ = make_signal("bpsk", 10)
    c = Capture(x, FS, {"source_kind": "iq", "filename": "x",
                       "wav_disambiguation": {"result": "declared_iq"}})
    detections = analyze_capture(c).response["detections"]
    assert detections
    for d in detections:
        assert "confidence_calibrated" in d and "confidence_calibration_status" in d
        assert "confidence_evidence_based_calibrated" in d and "confidence_evidence_based_calibration_status" in d
        status = d["confidence_calibration_status"]
        assert "isotonic-calibrated" in status or "uncalibrated" in status
        if "isotonic-calibrated" in status:
            assert d["confidence_calibrated"] is not None
            assert 0 <= d["confidence_calibrated"] <= 1


def test_calibrate_confidence_handles_missing_calibrator_file(monkeypatch, tmp_path):
    detect._load_calibrator.cache_clear()
    monkeypatch.setattr(detect, "_DOCS_DIR", tmp_path)
    value, status = calibrate_confidence("confidence", 0.9)
    assert value is None
    assert "uncalibrated" in status
    detect._load_calibrator.cache_clear()  # restore real docs dir for later tests


@pytest.mark.parametrize("score_name,max_ece", [("confidence", 0.05), ("confidence_evidence_based", 0.15)])
def test_shipped_calibrator_generalizes_to_a_fresh_held_out_corpus(score_name, max_ece):
    """Regression guard: rebuild a synthetic corpus with seeds independent of
    both calibrate.py's train and test splits (seed_offset=0, 100), and
    check the *shipped* calibrator file still meets a documented ECE bound.
    Protects against silent drift if detect.py's heuristics change later
    without rerunning calibrate.py."""
    fresh = build_corpus(seed_offset=500, seeds_per_combo=2)
    scores = np.array([r[score_name] for r in fresh])
    labels = np.array([r["label"] for r in fresh])
    calibrated = np.array([calibrate_confidence(score_name, s)[0] for s in scores])
    ece = expected_calibration_error(calibrated, labels)
    assert ece < max_ece, f"{score_name}: fresh-corpus ECE {ece:.4f} exceeds documented bound {max_ece}"
