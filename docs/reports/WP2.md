# WP2 report: measurement that reflects the real world (branch `wp2-benchmarks`)

## Worse first
No product behaviour changed, so no number got worse. The new benchmarks show the product is worse on realistic
data than G1/G2 suggested: on real G5 test files it publishes a **wrong label on 13 of 87 files (14.9%)** and a
correct label on none; on impaired G4 it publishes wrong labels on 4.5% of captures.

## What changed
- Criteria registered in `experiments/readiness/config.py` and committed (5331f26) before first measurement:
  W1-W4 (G4), RC1-RC3 (G5), T1 (throughput).
- G4 (`experiments/readiness/impaired.py`, `generators.g4_*`): G1/G2 families plus drift, Wiener phase noise, 2-3 tap
  multipath, IQ imbalance, DC spike, adjacent interferer, coloured noise, mild clipping; 524,288 samples at 200 kS/s;
  336 test captures (seeds 400000+), calibration seeds 500000+ (refused by the scoreboard).
- G5 (`g5_build.py`, `g5_manifest.json`, `g5.py`): 170 real captures, truth written and split frozen by protocol
  (sha256 pinned in config, enforced by a test) before any data was downloaded or run. rtl_433_tests captures: one per
  rtl_433 decoder, truth from its `r_device` at rtl_433 02cd4b6; IQEngine: cited positives and OFDM negatives.
  Test split: 87 files (45 rate-scored).
- Ingest: `cu8`/`ci8` SigMF datatypes (in-memory and disk paths share one normalisation); the CLI accepts raw
  `.cu8/.cs8/.cs16` and reads rate/centre from rtl_433 names (`g001_433.92M_250k.cu8`); explicit flags override.
- Scoreboard: G4 rows for both systems; one timed batch-CLI run over G3 + G5 test gives RC1-RC3 and T1.

## Tests
Full suite: 384 passed, 3 skipped (the one failure in the first run, a test assuming three generators, was
extended to five). New: frozen-threshold values, frozen G5 split, rtl_433-named `cu8` CLI ingest.

## Scoreboard (WP1 → WP2; new criteria are baselines at HEAD)
| Criterion | G1 | G2 | G3 | G4 | G5 |
|---|---|---|---|---|---|
| D1-D3, P1-P3, L1-L2, R1-R2, C1-C3, RD1, A1, X1 | unchanged | unchanged | unchanged | – | – |
| W1 wrong labels <= 3% | – | – | – | 4.5% ✗ | – |
| W2 correct >= 60% | – | – | – | 7.1% ✗ | – |
| W3 out-of-library wrong <= 10% | – | – | – | 4.7% ✓ | – |
| W4 wrong rates <= 3% | – | – | – | 3.6% ✗ | – |
| RC1 correct label >= 50% of files | – | – | – | – | 0.0% ✗ |
| RC2 wrong label <= 5% of files | – | – | – | – | 14.9% ✗ |
| RC3 wrong rate <= 5% | – | – | – | – | 0.0% ✓ |
| T1 time / duration <= 1 | – | – | – | – | 0.821x ✓ |
Overall 17/25.

## Next
WP3: `experiments/readiness/diagnose.py` (written, not yet run) assigns every abstention and wrong label one cause.
