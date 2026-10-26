# Detect bounds: occupied-bandwidth edge refinement (readiness step 1)

## Goal

Pass the pre-registered WP4a bounds criteria without regressing any currently passing criterion:

| ID | Criterion (registered 2026-09-29, `experiments/readiness/config.py`) | Baseline |
|---|---|---|
| B1 | ≥ 85% of G4 test emitter captures have a Detect band 0.5–2× the true occupied width | 66.9% (calibration, ablation `all`) |
| B2 | ≤ 5% of G4 test emitter captures split into several detections | 8.1% (calibration, ablation `all`) |
| B3 | ≥ 60% of rated G5 FSK2 test files have a band 0.5–2× (tone split + 2 × expected rate) | 12 of 27 (WP3b probe, test) |

## What the calibration data says (probes on G5 calibration FSK2, 25 rated files that fit in memory)

The problem is **over-wide bands, not shattered ones**:

- **Today:** 8/25 good bounds, 12/25 more than 2× too wide, and 4 where no band contains the burst centre.
- **Why they are wide:** the bands match the burst spectrum's width 20–30 dB below its peak. A threshold 8 dB above the noise floor catches the spectral skirts of 15–25 dB bursts, and `merge_fragments` chains skirts and sidelobes (3–8 raw bands per candidate).
- **Edge rules compared** on the burst spectrum minus the noise floor (ok = width/truth in 0.5–2):

| Rule | −10 dB | −15 dB | −20 dB | OBW90 | **OBW95** | OBW99 |
|---|---|---|---|---|---|---|
| ok / 25 | 19 | 21 | 18 | 21 | **22** | 14 |
| > 2× | 0 | 0 | 5 | 0 | **0** | 10 |

  Peak-relative rules collapse onto narrow carrier spikes; the 95% occupied bandwidth does not.
- **Envelope-correlation merge (approach A as proposed): measured, deferred.** Joining neighbours with envelope correlation ≥ 0.8 (fragments) or ≤ −0.5 (alternating FSK tones) moves 8/25 → 10/25 good bounds and does not fix width. It also needs one FIR isolation pass over the capture per pair. Revisit it only if B3 still fails after refinement.

## Design

**Where:** `backend/pipeline/detect.py`, in `analyze_capture`, after `merge_fragments` and before evidence and pulse measurement. New function `refine_edges(power, rows, frames, floor_bin, fraction)`. It is pure, testable, and uses no FIR or extra capture pass.

1. Candidate spectrum: mean of `power[rows][:, active frames]` over the candidate's rows (bins), minus the per-bin noise floor (`floor`), clipped at 0.
2. Edges at the `(1 − f)/2` and `1 − (1 − f)/2` points of that spectrum's cumulative power, with `OCCUPIED_FRACTION = f` (0.95 unless tuning on calibration data says otherwise). Edges only **shrink** within the detected extent. A candidate with fewer than `MIN_REFINE_BINS` bins, or with no power above the floor, keeps its extent.
3. Published fields: `freq_lower_hz`/`freq_upper_hz` become the refined edges. New fields `freq_extent_lower_hz`/`freq_extent_upper_hz` keep the threshold-crossing extent, plus `bounds_method` (`"occupied 95%"` or `"threshold extent"`). The dashboard and docs say which one is shown.
4. `isolate_band` and the envelope and pulse measurement use the refined band, because that is what gets published. **Risk:** downstream estimation also isolates by these bounds, and a tighter band could cost labels or bandwidth accuracy. Mitigation: check L1/L2, R1/R2, P1–P3 and D1–D3 on calibration seeds before any test scoring. If labels regress, estimation keeps the extent as its isolation window (`analysis band = extent`, published bounds = refined) and this is stated in the docs.
5. The large-capture block path (`large_capture.py`) builds detections through the same code path and inherits the change. Its tracks are verified with the existing large-capture tests.

## Measurement

- **Scoreboard:** add B1–B3 to `experiments/readiness/scoreboard.py` (test seeds / test split only). Reuse `ablation.width_ratio` (G4) and the corrected `fsk_split_probe` truth (G5).
- **Tuning harness, calibration only:**
  - G4 calibration seeds 500000+ via `ablation.py --conditions all`;
  - G5 calibration FSK2 files via a calibration flag on `fsk_split_probe.py`;
  - G1/G2 calibration seeds for the regression check.
- **Test seeds are scored once**, after the fraction is fixed.

## Acceptance

- B1, B2 and B3 pass on test data, or the report says by how much they miss. No threshold is changed after test scoring.
- No currently passing criterion fails. D3 (G1 fragmentation) is reported, not targeted; this change does not touch fragmentation.
- Full backend suite passes. New unit tests for `refine_edges`: a flat band, a band with skirts, a narrow spike on a wide pedestal, too few bins, and nothing above the floor.

## Out of scope

The envelope-correlation merge (deferred, above), interferer splitting (step 2), and D3 negative-SNR fragmentation (step 4).
