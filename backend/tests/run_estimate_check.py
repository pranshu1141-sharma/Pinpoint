"""Reproduce downstream measurements: python -m backend.tests.run_estimate_check.

Truth is used only here for scoring, never by the pipeline functions.
"""
import json
from pathlib import Path

import numpy as np

from backend.pipeline.classify import analyze_candidate, corrected_segment
from backend.pipeline.detect import analyze_capture
from backend.pipeline.ingest import Capture
from backend.pipeline.synth_gen import make_signal
from backend.tests.test_estimate import fixture


def main():
    continuous = []
    for kind in ("bpsk", "qpsk", "fm"):
        for snr in (20, 10, 0, -5):
            c, d, truth = fixture(kind, snr)
            out = analyze_candidate(c, d)
            continuous.append({"kind": kind, "seed": 47, "truth_snr_db": snr,
                               "truth_frequency_hz": 8000,
                               "truth_symbol_rate_hz": truth["symbol_rate_hz"],
                               "frequency_error_pct": abs(out["center_frequency_hz"]-8000)/80,
                               "result": out})
    refinement = []
    for seed in range(47, 57):
        x, _ = make_signal("bpsk", 10, seed=seed, frequency=7200)
        c = Capture(x, 1e6, {"source_kind": "iq", "filename": "150khz-bpsk",
                            "wav_disambiguation": {"result": "declared_iq"}})
        ds = analyze_capture(c).response["detections"]
        d = next(d for d in ds if d["freq_lower_hz"] < 150000 < d["freq_upper_hz"])
        out = analyze_candidate(c, d)
        refinement.append({"seed": seed, "truth_frequency_hz": 150000,
                           "direct_error_hz": out["center_frequency_hz"]-150000,
                           "refined_error_hz": out["center_frequency_refined_hz"]-150000,
                           "order": out["refinement_order"]})
    fine = []
    for kind, order in (("bpsk", 2), ("qpsk", 4)):
        for snr in (20, 10):
            for seed in range(47, 52):
                c, d, _ = fixture(kind, snr, seed=seed)
                out = analyze_candidate(c, d)
                spread = out["phase_cluster_spread_rad"]
                # Counterfactual diagnostic isolates frequency drift's effect.
                # The true frequency is NEVER provided to analyze_candidate.
                oracle = corrected_segment(c, out, 8000.)
                r = abs(np.mean(np.exp(1j*order*np.angle(oracle).astype(float))))
                fine.append({"kind": kind, "snr_db": snr, "seed": seed,
                             "selected_order": out["refinement_order"],
                             "phase_cluster_spread_rad": spread,
                             "refined_error_hz": out["center_frequency_refined_hz"]-8000,
                             "oracle_frequency_spread_rad": float(np.sqrt(max(0, -2*np.log(r)))),
                             "would_pass_requested_rule": bool(out["refinement_order"] == order
                                                                and spread is not None and spread < .8),
                             "published_fine_label": out["fine_modulation_label"]})
    rate_fallback = []
    for kind in ("bpsk", "qpsk"):
        for snr in (10, 5, 0, -5):
            c, d, truth = fixture(kind, snr)
            out = analyze_candidate(c, d)
            rate_fallback.append({"kind": kind, "truth_snr_db": snr,
                                  "measured_snr_db": out["snr_db"],
                                  "truth_symbol_rate_hz": truth["symbol_rate_hz"],
                                  "symbol_rate_hz": out["symbol_rate_hz"],
                                  "symbol_rate_status": out["symbol_rate_status"]})
    report = {
        "scope": "Fallback rung 2: Estimate + coarse family + refinement; fine diagnostics only; symbol rate not attempted",
        "methods": {"direct_center": "noise-subtracted in-band centroid",
                    "refinement": "separate 1024-point Hann Welch Mth-power peak with log-parabolic interpolation",
                    "coarse": "existing 257-tap band isolation; 128-sample edge trim; envelope coefficient of variation",
                    "bandwidth": "raw averaged in-band PSD; connected interpolated half-power lobe; shortest whole-bin 99% power band"},
        "continuous": continuous, "refinement_150khz_bpsk_10db": refinement,
        "refinement_direct_mae_hz": float(np.mean([abs(r["direct_error_hz"]) for r in refinement])),
        "refinement_refined_mae_hz": float(np.mean([abs(r["refined_error_hz"]) for r in refinement])),
        "exploratory_fine_rule": fine, "symbol_rate_fallback": rate_fallback,
        "qualification": "Deterministic synthetic evidence only. No theoretical half-power truth exists in generator; nominal detection bands are not that truth. No symbol-rate accuracy claim.",
    }
    path = Path(__file__).resolve().parents[2]/"docs"/"estimate-classify-validation.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(f"Wrote {path}")
    print("kind SNR_truth center_Hz error_pct SNR_measured BW3_Hz BW99_Hz envelope_variation family")
    for row in continuous:
        out = row["result"]
        print(row["kind"], row["truth_snr_db"],
              f'{out["center_frequency_hz"]:.4f}', f'{row["frequency_error_pct"]:.4f}',
              *(f'{out[k]:.4f}' for k in ("snr_db", "bandwidth_3db_hz", "bandwidth_99pct_hz", "envelope_variation")),
              out["modulation_family"])
    print("Refinement MAE:", report["refinement_direct_mae_hz"], "->", report["refinement_refined_mae_hz"], "Hz")


if __name__ == "__main__":
    main()
