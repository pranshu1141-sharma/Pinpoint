# WP1 report: quick wins (branch `wp1-quick-wins`)

## Worse first
Nothing got worse. S1 (speed, G2) moved 89.2% → 90.4% between runs with no change to the code it times:
wall-clock noise, not an improvement.

## What changed
- `backend/pipeline/large_capture.py`: a track longer than one bounded re-read (2,000,000 samples) is no longer left
  null. `sampled_spans` picks 8 deterministic spans (one per evenly-picked pulse window for a pulsed track, else evenly
  spaced; together within one bounded read). Each span is analysed on its own (nothing concatenated); `_combine_spans`
  takes the median of centre frequency, bandwidths and SNR, and publishes a label only when at least half the spans
  publish it and none publishes a different one (rate: median of the agreeing spans, only if all within 5%).
  Every track now carries `analysis_spans` (start/end/label/tier/rate per span) and `analysis_span_method`.
  A track claiming samples beyond the file stays an explicit unknown (never read past the file).
- Docs: `docs/README.md` no longer says the product "does not identify modulation"; `JUDGE_DEFENSE_GUIDE.md` no longer
  lists "It identifies BPSK/QPSK/FM" as a claim to avoid, and gains a "Does it identify modulation?" answer. API_REFERENCE,
  ESTIMATE_CLASSIFY, LARGE_FILE_PROCESSING, LIMITATIONS, PROJECT_STATUS describe the sampled spans. CLAIMS' real-data
  paragraph corrected (see discrepancy below).
- X1 (`experiments/readiness/docs_check.py`) now checks `docs/README.md` and `docs/JUDGE_DEFENSE_GUIDE.md`, with new
  contradiction phrases for denying modulation identification and for "long tracks stay null" (the latter keyed to
  `def sampled_spans` existing in the code).

## Tests
382 passed, 3 skipped (baseline 380 passed, 3 skipped). `test_track_exceeding_bounded_reread_limit_is_explicit_unknown`
pinned the old null behaviour; it keeps its name and now asserts the sampled-span estimate (BPSK at 500 Bd over a
2.1 M-sample track, spans recorded and deterministic, Detect fields preserved, no read past the file). New:
`test_sampled_spans_follow_pulse_windows_and_disagreement_abstains`, `test_docs_check_covers_the_docs_index_and_judge_guide`.

## Scoreboard (before f73a69f → after)
| Criterion | G1 | G2 | G3 |
|---|---|---|---|
| D1–D3, P1–P3, L1–L2, R1–R2, C1–C3 | unchanged | unchanged | – |
| S1 speed | 100% → 100% | 89.2% → 90.4% ✗ (noise) | – |
| RD1 real recordings | – | – | 5/6 → **6/6 sane ✓** (`dect6` 99% bandwidth now 1.31 MHz) |
| X1 docs | – | – | 2 problems → 0 ✓ |
| Overall | | | 12/17 → 14/17 |

Real labels are unchanged: 2 of 6 recordings (bpsk_rect BPSK 50 kBd; iridium one candidate QPSK 25.0 kBd).
`dect6` and the long AIS track get estimates now, but no span passes the label margins.

## Discrepancies found
- `docs/HANDOFF.md` does not exist on any branch or in history; the brief's rules were followed directly.
- Local `main` (4f45717) is behind `origin/main` (f73a69f); the readiness work only exists on `origin/main`/`main-merge`.
  This work branches from f73a69f in the `Pinpoint-readiness` worktree.
- The brief says HEAD labels 1 of 6 real recordings; it labels 2 (Iridium detection 14: QPSK 25,017 Bd, correct).
  CLAIMS.md had said Iridium got no label; corrected.
- X1 failed at the baseline only because CLAIMS/LIMITATIONS quote a wall-clock number (S1 G2); `--sync-docs` fixes it.
