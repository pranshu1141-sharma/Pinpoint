"""Fit and report calibration for Detect's two confidence scores.

Run as a script to regenerate the shipped calibrator files and reliability
diagrams:

    cd backend && python3 -m pipeline.calibrate

Splits the synthetic corpus (backend/pipeline/calibration_corpus.py) into an
independent train/test split by seed range -- ECE is always reported on the
held-out test split, and the calibrator shipped for production use in
detect.py is refit on the union of both splits (standard practice: report
generalization on a split kept out of that specific fit, then use all
available labeled data for the version that ships).
"""
import json
from pathlib import Path

import numpy as np

from .calibration import IsotonicCalibrator, expected_calibration_error, reliability_diagram, reliability_diagram_svg
from .calibration_corpus import build_corpus

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
SCORES = ("confidence", "confidence_evidence_based")
CALIBRATION_SEEDS_PER_COMBO = 8


def run(train_seed_offset=0, test_seed_offset=100):
    # 8 seeds per combination: 3 left the isotonic fit too noisy to generalise (fresh-corpus ECE)
    train = build_corpus(seed_offset=train_seed_offset, seeds_per_combo=CALIBRATION_SEEDS_PER_COMBO)
    test = build_corpus(seed_offset=test_seed_offset, seeds_per_combo=CALIBRATION_SEEDS_PER_COMBO)
    report = {"corpus": {"train_n": len(train), "test_n": len(test),
                         "train_positive_rate": float(np.mean([r["label"] for r in train])),
                         "test_positive_rate": float(np.mean([r["label"] for r in test])),
                         "origin": "synthetic (backend/pipeline/calibration_corpus.py); "
                                   "no real-file calibration performed in this pass"}}
    for score_name in SCORES:
        tr_scores = np.array([r[score_name] for r in train])
        tr_labels = np.array([r["label"] for r in train])
        te_scores = np.array([r[score_name] for r in test])
        te_labels = np.array([r["label"] for r in test])

        raw_ece_test = expected_calibration_error(te_scores, te_labels)
        raw_diagram_test = reliability_diagram(te_scores, te_labels)

        cal = IsotonicCalibrator().fit(tr_scores, tr_labels)
        cal_te_scores = cal.predict(te_scores)
        cal_ece_test = expected_calibration_error(cal_te_scores, te_labels)
        cal_diagram_test = reliability_diagram(cal_te_scores, te_labels)

        # Ship a calibrator fit on ALL labeled data (train+test) -- the ECE
        # numbers above, from the train-only fit evaluated on held-out test,
        # are the honest generalization estimate; this final refit only
        # changes which knots are used, not the reported accuracy claim.
        all_scores = np.concatenate([tr_scores, te_scores])
        all_labels = np.concatenate([tr_labels, te_labels])
        shipped = IsotonicCalibrator().fit(all_scores, all_labels)

        calibrator_path = DOCS_DIR / f"calibration-{score_name.replace('_', '-')}.json"
        calibrator_path.write_text(json.dumps(shipped.to_json(), indent=2))

        raw_svg = reliability_diagram_svg(raw_diagram_test, f"{score_name}: raw (held-out test, ECE={raw_ece_test:.3f})")
        cal_svg = reliability_diagram_svg(cal_diagram_test, f"{score_name}: isotonic-calibrated (held-out test, ECE={cal_ece_test:.3f})")
        (DOCS_DIR / f"calibration-{score_name.replace('_', '-')}-raw.svg").write_text(raw_svg)
        (DOCS_DIR / f"calibration-{score_name.replace('_', '-')}-calibrated.svg").write_text(cal_svg)

        report[score_name] = {
            "raw_ece_held_out": raw_ece_test,
            "calibrated_ece_held_out": cal_ece_test,
            "raw_reliability_diagram": raw_diagram_test,
            "calibrated_reliability_diagram": cal_diagram_test,
            "calibrator_file": calibrator_path.name,
        }
    (DOCS_DIR / "confidence-calibration.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    r = run()
    for score in SCORES:
        print(score, "raw ECE:", round(r[score]["raw_ece_held_out"], 4),
              "calibrated ECE:", round(r[score]["calibrated_ece_held_out"], 4))
