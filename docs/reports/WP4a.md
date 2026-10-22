# WP4a report: Detect bounds (readiness step 1, branch `readiness/detect-bounds`)

Design: [`docs/superpowers/specs/2026-10-23-detect-bounds-design.md`](../superpowers/specs/2026-10-23-detect-bounds-design.md).
Tuned on calibration data only (G4 seeds 500000+, G5 calibration split); test seeds scored once, at `a762ad0`.

## Worse first
- **G4 wrong labels rose on test: W1 4.5% → 6.25% (15 → 21 of 336), W4 wrong rates 3.6% → 4.8%, W3 4.7% → 7.8%** (still passes).
  Calibration did not predict this: there, wrong labels stayed at 5 of 160 at the chosen guard. Tighter bounds let the
  estimator see impaired signals more clearly, which yields more correct labels (W2 7.1% → 10.7%) and also more
  confident wrong ones. This makes step 3's honesty gate (catch-all labels such as `QAM16` need a margin over the next
  lower model) more urgent.
- **RC2 (G5 wrong labels) 14.9% → 16.1%:** one more file of 87.
- **B1 and B2 fail:** G4 bounds ok 66.6% against 85%, fragmented 7.2% against 5%. Over-wide G4 bands come from the
  co-channel interferer and coloured noise, which this step does not address (step 2).
- S1 speed G2 90.4% → 88.4%, inside the measured run-to-run spread (88.8–94.0%); X1 tolerates it.

## What changed
- `detect.refine_edges`: published `freq_lower_hz`/`freq_upper_hz` keep 95% of the candidate's power above the
  noise floor (its active frames), widened 1.6× about the centre and never past the threshold-crossing extent.
  New fields: `freq_extent_lower_hz`/`freq_extent_upper_hz` (the old bounds) and `bounds_method`.
- The legacy estimator keeps analysing the extent it was fixture-validated on (its pinned evidence is unchanged).
  The verify estimator, the product default, uses the refined bounds.
- Large-capture tracks union the extent fields across blocks, like the bounds.
- The scoreboard gains a "Detect bounds" phase: B1/B2 from G4 rows (`metrics.bounds_stats`), B3 from
  `fsk_split_probe` on the G5 FSK2 test split. `bounds_dev.py` is the calibration-only tuning harness.
- The dashboard detail panel shows the threshold extent when it differs from the published edges.

## Tuning (calibration only)
| Guard | G5 cal FSK2 good bounds | G4 clean: too narrow / wrong | G4 impaired: too wide / correct / wrong |
|---|---|---|---|
| off (old) | 8/25 | 5 / 1 | 43 / 13 / 5 |
| 1.0 | 17/25 | 16 / 5 | 36 / 31 / 7 |
| **1.6 (chosen)** | **19/25** | **5 / 3** | 39 / 15 / 5 |
| 2.0 | 15/25 | 5 / 2 | 40 / 13 / 5 |

At 1.0, MSK-like FSK2 (h = 0.5) loses the outer power that separates it from FM and PSK. **Carried to step 2:**
1.0 gave the estimator 31 correct impaired labels instead of 13, because a tight isolation window excludes the
interferer. The estimator's isolation window and the published bounds should be separate.

## Regression check on dev seeds (G1 seed 21, G2 900000+; neither calibration nor test)
G1 identical in every statistic. G2: wrong labels 2.0% → 1.6%, correct 92.5% → 95.0%, rates correct 84.0% → 86.4%,
held-out wrong 19.8% → 15.6%; centre/bandwidth/SNR ok all ≥ 97.9%.

## Scoreboard (before → after, test)
| ID | Before | After |
|---|---|---|
| B3 | – | **92.6% ✓** (25/27; was 12/27 by the same probe) |
| B1 / B2 | – | 66.6% ✗ / 7.2% ✗ |
| L1 / L2 (G2) | 1.26% / 93.9% | 1.16% / 95.0% |
| R1 / R2 (G1) | 1.0% / 95.2% | 1.33% / 94.0% |
| W1 / W2 / W3 / W4 | 4.5% / 7.1% / 4.7% / 3.6% | 6.25% / 10.7% / 7.8% / 4.8% |
| RC2 | 14.9% | 16.1% |
| Overall | 17/25 | 18/28 |

Unchanged: D1–D3, P3, C1–C3, RC1, RC3, RD1, A1, X1.

## Tests
446 passed, 3 skipped (new: `test_detect_bounds.py`, and bounds/B3 tests in `test_readiness.py`).

## Next
Step 2 (interferer, coloured noise, DC): a separate, tighter estimator isolation window, and interferer-aware bounds for B1/B2.
