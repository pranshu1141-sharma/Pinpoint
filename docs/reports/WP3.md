# WP3 report: why does the product abstain? (branch `wp3-diagnosis`)

**Stopping here for your go-ahead, as instructed.** No product code changed in this WP; every number below comes from
measuring the product as it stands at `8673551` (WP2). Full tables: [`WP3_tables.md`](WP3_tables.md) (generated).

## Worse first
- Nothing in the product changed, so no accuracy criterion moved. The two wall-clock criteria moved by noise: S1 on G2
  90.4% → 88.8% (it was already failing), T1 0.821× → 0.874× (still passing).
- **X1 (docs) fails on a re-run.** It fails only because `CLAIMS.md` and `LIMITATIONS_AND_ROADMAP.md` quote the S1 G2
  wall-clock figure (90.4%), which cannot reproduce exactly. Same effect the WP1 report found. I did not re-sync the docs.
  Overall 17/25 → 16/25 is that and nothing else. A decision is needed (question 3).
- **My own first hypothesis was wrong.** I expected a missing wide-index FSK family to explain the `unexplained ≈ 0.87`
  abstentions on FSK2 files. The FSK expert fits its own tone positions, so it is not that. Detect's bounds are the cause (F below).

## What changed
- `experiments/readiness/diagnose.py` (written in WP2) was run; its docstring no longer claims to write a report.
- New, diagnostic only, never scored: `diagnose_report.py` (tables), `fsk_split_probe.py` (Detect band vs FSK tone split),
  `oracle_bounds.py` (upper bound: strongest packet, sane band, not refused). Artifacts: `artifacts/readiness/diagnosis.json`,
  `fsk_split_probe.json`, `oracle_bounds.json`.

## Tests
384 passed, 3 skipped, before and after (no product change).

## Scoreboard (WP2 committed → re-run at WP3 HEAD; new criteria unchanged)
| Criterion | G1 | G2 | G3 | G4 | G5 |
|---|---|---|---|---|---|
| D, P, L, R, C1–C3, A1, RD1 | unchanged | unchanged | unchanged | – | – |
| S1 speed | 100% ✓ | 90.4% → 88.8% ✗ (noise) | – | – | – |
| W1 wrong ≤ 3% / W2 correct ≥ 60% / W3 / W4 | – | – | – | 4.5% ✗ / 7.1% ✗ / 4.7% ✓ / 3.6% ✗ (identical) | – |
| RC1 correct ≥ 50% / RC2 wrong ≤ 5% / RC3 | – | – | – | – | 0.0% ✗ / 14.9% ✗ / 0.0% ✓ (identical) |
| T1 | – | – | – | – | 0.821× → 0.874× ✓ |
| X1 docs | – | – | 0 → 2 problems ✗ (timing quote) | – | – |
| Overall | | | | | 17/25 → 16/25 |

## What the diagnosis found
Scope: 93 real files (6 G3 + 87 G5 test, 790 Detect candidates), and every 3rd G4 test capture (107, noise excluded).
Cause = the first gate a candidate fails, in the product's own order. A file's *primary* candidate is its highest-SNR one.

**A. The current product's real-file outcome.** 2 correct labels (both G3), 18 wrong-label detections across 13 G5 files,
everything else abstains. Of the 18 wrong detections, **14 are at ≥ 15 dB SNR**: real signals mislabelled, not noise fragments.
RC3's 0% wrong rate is vacuous: the product publishes no correct label on which a rate could be wrong.

**B. Cause of abstention, by primary candidate (93 files).**
| Cause | Files |
|---|---|
| Pulsed refusal ("pulsed bursts not validated") | 56 (60%) |
| m_fam below threshold (non-pulsed) | 24 |
| noise-only model wins (`null_wins`) | 5, all OFDM/cellular negatives: correct abstentions |
| unexplained power, span-minority, short segment, usage | 2 + 2 + 1 + 1 |
| published: correct 1, wrong 1 | 2 |

Per candidate on G5, pulsed refusal is 454 of 753 (60%); `short_segment` is 10 (1%).

**C. If the pulsed refusal were simply lifted** (verify run on each candidate's longest burst): 474 pulsed candidates →
247 too short, 66 m_fam, 47 unexplained, 12 fm_digital, 11 usage, **89 published: 25 correct, 64 wrong**. The wrong ones are
`AM` on OOK ×33, `FM` on FSK ×18, `FSK4`/`QPSK` on FSK ×9, `QPSK` on OOK ×3, `QAM16` on QPSK ×1. Lifting alone would wreck RC2.

**D. Detect bounds on FSK2 files** (28 files, tone split of the strongest burst vs the top candidate's bandwidth):
candidate narrower than half the split on **15**, wider than twice the split on **10**, plausible on 3. Files typically
carry 3–12 candidates within 3 dB of each other SNR-wise: one FSK signal shattered into per-tone lines or lobes, or
swallowed by a band 5–12× too wide. The tone split is a rough measure (15th/85th IF percentile inside one burst).

**E. Oracle experiment** (strongest packet, band derived from the file's own signal and its expected rate, not refused; an
upper bound, uses truth-derived rate for the band):
- **ASK2/OOK (14 files with rates): 8 correct, 0 wrong**, 6 abstain (3 unexplained, 3 usage).
  Rates on those 8: 3 within 5%, **3 wrong** (Manchester-coded at 2.03×, 2.06× and 1.16×), 2 withheld.
- **FSK2 (27 files): 3 correct, 7 wrong (`FM` ×5, `FSK4` ×2), 17 abstain** (7 fm_digital, 5 unexplained, 3 short, 2 other).
  Good bounds and packet analysis alone do not fix FSK.
- The two AIS recordings (GMSK; G3 by sampled span, G5 as a burst) get `FM` with margin 2.2 and 4.2 nats/sample and 0.00 unexplained:
  **the existing FSK h = 0.5 expert does not explain GMSK** (n = 2, so treat as strong indication, not proof).

**F. G4 (impaired synthetic).** 88% abstain (94/107); 7 correct, 6 wrong. Abstentions: m_fam 37, unexplained 35 (median
0.33 against a 0.119 limit), fm_digital 15, other 7. **SNR does not help**: abstain 85% / 85% / 85% / 96% and correct
11% / 11% / 4% / 0% across <5 / 5–10 / 10–15 / ≥15 dB. The limit is model bias from the impairments, not noise.
**4 of the 6 wrong labels are `QAM16`** (truth BPSK, 8PSK, ASK2, QAM8), the highest-order model absorbing distortion; when
pulsed G5 candidates are analysed as bursts, `QAM16` is the best-fitting model on 14 of them (11 files). Detect bounds on G4: median 1.11× the true width,
p90 5.9×; >2× too wide on 29/107; 8/107 captures fragmented into several detections; 0 misses.

**G. The "unknown family" tier overclaims.** The tier ("structure outside the library") is assigned when the family
margin passes but unexplained power is too high or an alphabet point is unused. It covers 39 real candidates (34 G5) and 38
of 107 G4 captures, and **every real one has an in-library truth** (ASK2 24, FSK2 9, QPSK 3, FM 2, BPSK 1; G4: 31 of 38).
It is an impairment and mismodelling symptom, not evidence of missing families, so the analyst is told something untrue.
No label is published in it, so C2 (which scores labels) does not see it.

**H. Margins do not protect on real or impaired data.** Wrong labels have m_fam 0.29–2.9 nats/sample against a 0.168
threshold (correct G4 labels: 0.58–1.95). Pooled AUC of m_fam for correct-above-wrong is 0.62 (9 correct vs 24 wrong; tiny
n, a warning rather than a measurement). Thresholds were fit at 4,096 samples on clean G1/G2.

## Ranked fixes with predicted impact
| # | Fix | Evidence | Predicted impact | Confidence |
|---|---|---|---|---|
| 1 | Analyse each pulsed candidate as packets instead of refusing it, shipped with fixes 2, 4 and 5 | 60% of files' primary; oracle OOK 8/14, 0 wrong | RC1 0% → ≤ 11/41 probed files (≤ 27%; ≤ 13% of all 84 labelled test files if the 37 rate-less OOK files gain nothing). **Cannot reach 50% alone.** RC2 worsens unless 4 and 5 ship together. | Medium (oracle uses truth-derived band) |
| 2 | Fix Detect bounds: group same-timing narrow candidates into one signal, and reject over-wide bands, before estimation | 25/28 FSK2 files unusable bounds; 5 of the FSK→FM wrong labels come from files whose top candidate is < 0.3× the split | Unlocks nothing by itself (oracle: 3 correct + 7 wrong); prerequisite for 3; removes the lobe-level wrong `FM`/`AM` labels | Medium-high |
| 3 | GFSK/GMSK expert (WP5a) so FSK beats FM on shaped FSK | 12/27 oracle FSK2 end as wrong `FM` (5) or `fm_digital` abstain (7); AIS ×2 | ≤ 12/27 FSK2 files (44%) move from abstain/wrong to a chance at correct; every FM-on-burst wrong label goes away | Medium |
| 4 | Honesty gate for real/impaired data (also: stop calling in-library signals "unknown family"): guard catch-all labels (`QAM16`, `8PSK`, `FSK4`) with a margin over the next lower model; add an `AM`-is-digital check like `fm_digital`; refit on G4 **calibration** seeds only | 4/6 G4 wrong = QAM16; 33 `AM`-on-OOK wrongs if refusal lifted; AUC 0.62 | G4 W1 4.5% → ≈ 1.5% if the QAM16 wrongs go (sample of 6, wide interval); RC2 protection for fix 1 | Medium |
| 5 | OOK rate: report pulse-width classes, withhold single-rate claims (WP5b) | 3 of 6 published OOK rates wrong (Manchester 2×) | Without it, lifting refusal for OOK fails RC3 (50% wrong rates against ≤ 5%) | High |
| 6 | Impairment-robust front end (carrier drift and phase noise, IQ imbalance, DC, multipath, interferer) | G4 unexplained-dominated, SNR-independent | W2 7.1% → up to 60% is the target; the share each impairment costs is **unknown**. Run a one-at-a-time ablation on G4 calibration seeds first. | Low until ablated |
| 7 | Short-packet handling (< 2,000 raw samples), joint bursts | 5 of 54 G5 pulsed primaries (9%) | ≤ ~5 files | High that it is small |

**Not supported by the data.** (a) DE-QPSK / π/4-DQPSK: no evidence; only 2 QPSK test files, and Iridium already gets a
correct QPSK label. (b) Missing families as the explanation for "unknown family" outcomes (see G: they are all in-library truths), and the OFDM
negatives are abstained correctly (`null_wins`). (c) Your expectation that short bursts dominate: pulsed **refusal** dominates, burst
length only matters for ~9% of pulsed primaries.

## Consequence for WP4 (please read before approving it)
G4 abstention is bias-dominated and independent of SNR, and real-file abstention is dominated by a refusal and by wrong
bounds, not by too little data. Accumulating windows reduces variance, so I expect it to move W2, RC1 and RC2 little, and
MDL margins that grow with N could make wrong labels more confident. This is a prediction from the diagnosis, untested;
WP4's own G4 interactive-vs-thorough comparison is where it would be settled. I would do fixes 2, 1, 4, 5 first
(they are what WP4's per-pulse-window design needs anyway), then aggregation, and treat fix 6 as its own measured WP.

## Limits of this diagnosis
Primary = highest SNR (Iridium's primary has −2 dB SNR, so it is arbitrary for some G3 tracks). Tone split is rough. Oracle
band uses the manifest's expected rate, so it is an upper bound and was never used to fit anything. G4 is a 1-in-3 sample.
Two long files (`KIDDE`, G5 AIS) do not fit in memory and are absent from the oracle and probe.

## Next step / blocking questions
1. Go-ahead, and are you happy with the reorder above (bounds, packet analysis, honesty gate, OOK rate before aggregation)?
2. Scoring policy check: an `AM` label on an on-off-keyed burst counts as wrong today (truth `ASK2`). I think that is
   right (OOK is digital); confirm.
3. X1: the docs quote a wall-clock number. May I make the docs quote S1 rounded (or drop the marker) so X1 stops failing
   on noise? That changes the check, not a threshold, so I have not done it.
4. This work lives in the `Pinpoint-readiness` worktree. Your checkout's `main` is behind `origin/main`, and its
   uncommitted frontend edits are untouched.
