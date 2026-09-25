# Estimate spike: propose → verify (MDL): results

**Status: experimental, methodology under test.** This is not the shipped Estimate stage. The shipped stage (`backend/pipeline/estimate.py`, `classify.py`) is unchanged, and nothing in `backend/pipeline` or `backend/api` imports this code (a test enforces that). All evidence below is **synthetic AWGN only**.

- Code: [`backend/experimental/estimate_spike/`](../backend/experimental/estimate_spike/)
- Tests: [`backend/tests/test_estimate_spike.py`](../backend/tests/test_estimate_spike.py)
- Harness: [`experiments/estimate_spike/`](../experiments/estimate_spike/). The prototype is kept for comparison in [`experiments/reference_spike/`](../experiments/reference_spike/).
- Machine-readable summary: [`estimate-spike-results.json`](estimate-spike-results.json)

## Method in one paragraph

Cheap estimators **propose** symbol rates. A multi-scale gap-difference spectral line on the carrier-corrected signal serves PSK/QAM, and the same on the instantaneous-frequency track serves FSK. Cheap scores rank the proposals, and every PSK finalist is needle-refined (±0.3%, ±0.6%). Expensive experts then **verify** each hypothesis by rebuilding the capture: NRZ PSK/QAM, RRC PSK/QAM, 2-FSK, AM/FM and a null model. Each score is `ln(residual) + cost_nats / N_eff` (MDL). The lowest score wins. Confidence is the margin to the best competing family (`m_fam`) and the best competing rate at least 5% away (`m_rate`), plus an `unexplained` signal-power fraction. Thresholds are fit on a calibration half and applied to a held-out test half.

## How to reproduce

```bash
.venv/bin/python -m pip install -r experiments/estimate_spike/requirements.txt   # scikit-learn (router only)
.venv/bin/python -m experiments.estimate_spike.run_eval --n 500 --seed 4 --out artifacts/estimate_spike/rows_seed4.json
.venv/bin/python -m experiments.estimate_spike.evaluate artifacts/estimate_spike/rows_seed4.json --json docs/estimate-spike-results.json
# exact prototype v5 behaviour:
.venv/bin/python -m experiments.estimate_spike.run_eval --n 500 --seed 4 --prototype --out artifacts/estimate_spike/rows_seed4_prototype.json
.venv/bin/python -m pytest backend/tests/test_estimate_spike.py -q
```

The seeded generator ([`signals.py`](../experiments/estimate_spike/signals.py)) draws random numbers in the same order as the prototype, so seed 4 produces the **same 500 captures bit for bit** (checked: 0/500 mismatches). The calibration/test split is the prototype's (`default_rng(0).random(500) < 0.5`, 277 test captures). I did not tune any threshold on the test half and did not try other seeds.

## Headline

1. **The port reproduces the prototype exactly.** With `--prototype`, every hypothesis score matches the reference code to within 2.5e-14 on the captures checked. Every cell of the brief's §6.3 accuracy/decision tables and the §6.4 ablation table is identical: 8/277 confidently wrong. The only exception is the router's top-1 row (see *Differences*).
2. **One deliberate deviation is on by default: FSK timing re-refinement.** After the prototype's 2-symbol-block timing search, the FSK expert re-refines timing locally with the 8-symbol scoring blocks. Without it, the required §6.5 regression test (h=1, 13 dB, Rs=80k: the true rate must beat 2×) fails on **12/30 seeds**; with it, 1/30 fail (h=0.5: 7/30 → 0/30). On the 500-capture evaluation it is a trade-off, not a free win. FSK raw label accuracy goes up (56.4% → 61.5%) and confident mistakes go down (8 → 7), but FSK raw rate accuracy drops from 50.0% to 47.4%, and the 9–14 dB FSK rate cell drops from 80% to 70% (the ±10 pt boundary). The root cause is below.
3. **Budget:** mean 125 ms and max 161 ms per 4,096-sample capture on one core; 0/500 captures over 0.5 s.
4. **Determinism:** no randomness in analysis code (enforced by a test). On 30 captures each: repeated runs and reversed processing order give bit-identical scores (30/30). Amplitude ×1000 and phase ×e^(j1.1) give the same winner, label, tier and rate, with margins within 1e-6 (30/30 each).

## Results: default configuration (FSK re-refine on)

Reference numbers (prototype v5, from the brief) are next to ours. ⚠ marks cells more than 10 pts from the reference.

### Raw best-hypothesis accuracy (all captures, no abstention)

| Kind | n | Label right | ref | Rate right | ref |
|---|---|---|---|---|---|
| PSK | 163 | 70.6% | 70.6% | 65.0% | 65.0% |
| QAM16 | 61 | 65.6% | 65.6% | 65.6% | 65.6% |
| FSK2 | 78 | 61.5% | 56.4% | 47.4% | 50.0% |
| AM | 54 | 38.9% | 38.9% | n/a | n/a |
| FM | 49 | 51.0% | 51.0% | n/a | n/a |
| 8PSK | 47 | 0.0% | 0.0% | 59.6% | 59.6% |
| noise | 48 | 97.9% | 97.9% | n/a | n/a |

### Raw rate accuracy by SNR (ours / ref)

| | -6..-1 dB | -1..4 dB | 4..9 dB | 9..14 dB |
|---|---|---|---|---|
| PSK | 20.8% / 20.8% (n=53) | 81.6% / 81.6% (n=38) | 85.3% / 85.3% (n=34) | 92.1% / 92.1% (n=38) |
| QAM16 | 11.8% / 11.8% (n=17) | 72.7% / 72.7% (n=11) | 92.3% / 92.3% (n=13) | 90.0% / 90.0% (n=20) |
| FSK2 | 0.0% / 0.0% (n=21) | 15.4% / 15.4% (n=13) | 87.5% / 87.5% (n=24) | 70.0% / 80.0% (n=20) |

### Held-out decisions (test half, n=277); thresholds from calibration half: m_fam ≥ 0.411, m_rate ≥ 0.149, unexplained ≤ 0.097 (ref 0.411 / 0.149 / 0.097)

| Kind | n | Label shipped | Label right | Unknown-family | Rate shipped | Rate right | Confidently wrong |
|---|---|---|---|---|---|---|---|
| PSK | 94 (94) | 50% (50%) | 100% (100%) | 7% (7%) | 36% (36%) | 100% (100%) | 0 (0) |
| QAM16 | 34 (34) | 47% (47%) | 100% (100%) | 6% (6%) | 53% (53%) | 100% (100%) | 0 (0) |
| FSK2 | 42 (42) | 26% (26%) | 100% (100%) | 2% (2%) | 50% (57%) | 95% (92%) | 1 (2) |
| AM | 31 (31) | 6% (6%) | 50% (50%) | 3% (3%) | 3% (3%) | 0% (0%) | 2 (2) |
| FM | 26 (26) | 38% (38%) | 100% (100%) | 0% (0%) | 0% (0%) | n/a (n/a) | 0 (0) |
| 8PSK | 21 (21) | 19% (19%) | 0% (0%) | 5% (5%) | 29% (29%) | 100% (100%) | 4 (4) |
| noise | 29 (29) | 0% (0%) | n/a (n/a) | 0% (0%) | 0% (0%) | n/a (n/a) | 0 (0) |

Total confidently wrong: **7/277** (ref 8/277). Reference values in parentheses.

### Proposal recall (true rate within 2% of some proposal): ours / ref

| | ≥ 4 dB | −1..4 dB | < −1 dB |
|---|---|---|---|
| PSK/QAM gap-difference | 100% / 100% (n=105) | 100% / 96% (n=49) | 74% / 81% (n=70) |
| PSK/QAM old E1/E2 | 96% / 93% (n=105) | 61% / 62% (n=49) | 9% / 8% (n=70) |
| PSK/QAM finalists (after ranking + needle) | 92% / n/a (n=105) | 84% / n/a (n=49) | 19% / n/a (n=70) |
| FSK gap-difference | 100% / 98% (n=44) | 46% / 14–16% (n=13) | 19% / 4% (n=21) |
| FSK old E4 | 0% / 7% (n=44) | 0% / 0% (n=13) | 5% / 0% (n=21) |
| FSK finalists (after Fisher ranking) | 98% / n/a (n=44) | 23% / n/a (n=13) | 0% / n/a (n=21) |

### Ablations (test half)

| Variant | Confidently wrong | ref | Raw label acc (test half) | ref |
|---|---|---|---|---|
| full system | 7/277 | 8/277 | 59.6% | 59.6% |
| without rrc | 22/277 | 15/277 | 61.4% | 61.4% |
| without fsk | 2/277 | 2/277 | 49.5% | 49.5% |
| without analog | 4/277 | 3/277 | 52.3% | 52.3% |
| without null | 10/277 | 11/277 | 50.2% | n/a |

### Router (depth-4 tree on the 6 features, trained on calibration half)

| Mode | Mean time / capture | ref | Same answer as dense | ref | Raw label acc | ref | Confidently wrong | ref |
|---|---|---|---|---|---|---|---|---|
| dense | 124 ms | 177 ms | n/a | n/a | 59.6% | 59.6% | 7/277 | 8/277 |
| top-1 | 40 ms | 52 ms | 59.9% | 57.4% | 53.4% | 51.3% | 4/277 | 1/277 |
| top-2 | 52 ms | 80 ms | 85.9% | 83.8% | 56.0% | 59.6% | 4/277 | 1/277 |

### Per-stage timing (all captures, one core)

| Stage | mean ms | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| features | 0.5 | 0.5 | 0.5 | 0.6 |
| screen_psk | 6.6 | 6.6 | 7.2 | 8.5 |
| screen_fsk | 6.1 | 6.1 | 7.3 | 8.5 |
| nrz | 5.7 | 5.3 | 7.7 | 9.0 |
| rrc | 49.4 | 52.2 | 55.7 | 68.0 |
| fsk | 54.5 | 54.1 | 57.3 | 86.7 |
| analog | 1.6 | 1.6 | 1.8 | 2.2 |
| total | 125.0 | 127.9 | 134.7 | 161.0 |

Captures over the 0.5 s budget: 0/500.

## Results: prototype-faithful configuration (`--prototype`)

### Raw best-hypothesis accuracy (all captures, no abstention)

| Kind | n | Label right | ref | Rate right | ref |
|---|---|---|---|---|---|
| PSK | 163 | 70.6% | 70.6% | 65.0% | 65.0% |
| QAM16 | 61 | 65.6% | 65.6% | 65.6% | 65.6% |
| FSK2 | 78 | 56.4% | 56.4% | 50.0% | 50.0% |
| AM | 54 | 38.9% | 38.9% | n/a | n/a |
| FM | 49 | 51.0% | 51.0% | n/a | n/a |
| 8PSK | 47 | 0.0% | 0.0% | 59.6% | 59.6% |
| noise | 48 | 97.9% | 97.9% | n/a | n/a |

### Raw rate accuracy by SNR (ours / ref)

| | -6..-1 dB | -1..4 dB | 4..9 dB | 9..14 dB |
|---|---|---|---|---|
| PSK | 20.8% / 20.8% (n=53) | 81.6% / 81.6% (n=38) | 85.3% / 85.3% (n=34) | 92.1% / 92.1% (n=38) |
| QAM16 | 11.8% / 11.8% (n=17) | 72.7% / 72.7% (n=11) | 92.3% / 92.3% (n=13) | 90.0% / 90.0% (n=20) |
| FSK2 | 0.0% / 0.0% (n=21) | 15.4% / 15.4% (n=13) | 87.5% / 87.5% (n=24) | 80.0% / 80.0% (n=20) |

### Held-out decisions (test half, n=277); thresholds from calibration half: m_fam ≥ 0.411, m_rate ≥ 0.149, unexplained ≤ 0.097 (ref 0.411 / 0.149 / 0.097)

| Kind | n | Label shipped | Label right | Unknown-family | Rate shipped | Rate right | Confidently wrong |
|---|---|---|---|---|---|---|---|
| PSK | 94 (94) | 50% (50%) | 100% (100%) | 7% (7%) | 36% (36%) | 100% (100%) | 0 (0) |
| QAM16 | 34 (34) | 47% (47%) | 100% (100%) | 6% (6%) | 53% (53%) | 100% (100%) | 0 (0) |
| FSK2 | 42 (42) | 26% (26%) | 100% (100%) | 2% (2%) | 57% (57%) | 92% (92%) | 2 (2) |
| AM | 31 (31) | 6% (6%) | 50% (50%) | 3% (3%) | 3% (3%) | 0% (0%) | 2 (2) |
| FM | 26 (26) | 38% (38%) | 100% (100%) | 0% (0%) | 0% (0%) | n/a (n/a) | 0 (0) |
| 8PSK | 21 (21) | 19% (19%) | 0% (0%) | 5% (5%) | 29% (29%) | 100% (100%) | 4 (4) |
| noise | 29 (29) | 0% (0%) | n/a (n/a) | 0% (0%) | 0% (0%) | n/a (n/a) | 0 (0) |

Total confidently wrong: **8/277** (ref 8/277). Reference values in parentheses.

### Proposal recall (true rate within 2% of some proposal): ours / ref

| | ≥ 4 dB | −1..4 dB | < −1 dB |
|---|---|---|---|
| PSK/QAM gap-difference | 100% / 100% (n=105) | 100% / 96% (n=49) | 74% / 81% (n=70) |
| PSK/QAM old E1/E2 | 96% / 93% (n=105) | 61% / 62% (n=49) | 9% / 8% (n=70) |
| PSK/QAM finalists (after ranking + needle) | 92% / n/a (n=105) | 84% / n/a (n=49) | 19% / n/a (n=70) |
| FSK gap-difference | 100% / 98% (n=44) | 46% / 14–16% (n=13) | 19% / 4% (n=21) |
| FSK old E4 | 0% / 7% (n=44) | 0% / 0% (n=13) | 5% / 0% (n=21) |
| FSK finalists (after Fisher ranking) | 98% / n/a (n=44) | 23% / n/a (n=13) | 0% / n/a (n=21) |

### Ablations (test half)

| Variant | Confidently wrong | ref | Raw label acc (test half) | ref |
|---|---|---|---|---|
| full system | 8/277 | 8/277 | 59.6% | 59.6% |
| without rrc | 15/277 | 15/277 | 61.4% | 61.4% |
| without fsk | 2/277 | 2/277 | 49.5% | 49.5% |
| without analog | 3/277 | 3/277 | 52.3% | 52.3% |
| without null | 11/277 | 11/277 | 50.2% | n/a |

### Router (depth-4 tree on the 6 features, trained on calibration half)

| Mode | Mean time / capture | ref | Same answer as dense | ref | Raw label acc | ref | Confidently wrong | ref |
|---|---|---|---|---|---|---|---|---|
| dense | 108 ms | 177 ms | n/a | n/a | 59.6% | 59.6% | 8/277 | 8/277 |
| top-1 | 28 ms | 52 ms | 61.0% | 57.4% | 51.3% | 51.3% | 3/277 | 1/277 |
| top-2 | 49 ms | 80 ms | 83.8% | 83.8% | 59.6% | 59.6% | 1/277 | 1/277 |

### Per-stage timing (all captures, one core)

| Stage | mean ms | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| features | 0.5 | 0.4 | 0.5 | 0.6 |
| screen_psk | 6.5 | 6.5 | 7.2 | 8.0 |
| screen_fsk | 6.1 | 6.1 | 7.3 | 8.6 |
| nrz | 5.6 | 5.3 | 7.6 | 9.0 |
| rrc | 48.9 | 51.6 | 55.4 | 58.3 |
| fsk | 38.6 | 38.5 | 40.4 | 43.1 |
| analog | 1.6 | 1.6 | 1.7 | 2.0 |
| total | 108.4 | 111.0 | 118.1 | 123.0 |

Captures over the 0.5 s budget: 0/500.

## Required tests (§6.5)

`backend/tests/test_estimate_spike.py`: **33 passed, 1 expected failure**. The full backend suite passes 263, skips 3 and has 1 xfail; the skips are pre-existing tests, and Detect tests are unchanged.

| Test | Result |
|---|---|
| Each expert fits its own family at 13 dB (residual within 0.3 nats of ln σ², beats rival experts): BPSK-NRZ, QPSK-NRZ, QAM16-NRZ, QPSK-RRC, FSK h=1, FM | pass |
| Same test, AM | **expected failure (strict xfail).** The analog expert takes the carrier from the FFT-bin argmax, which is up to ~120 Hz off at 4,096 samples (up to ~3 rad of rotation across the capture), and the fixed-phase AM model cannot absorb it. At 13 dB on 8 seeds, the AM model won only 3 times. This is known weak spot §7.2; I did not fix it. |
| FSK timing regression (h=1, 13 dB, Rs=80k, 10 seeds): true rate beats 2× | pass (needs the re-refine deviation) |
| Needle regression: BPSK NRZ at 9–14 dB, 6 seeds, never reported at 2× | pass |
| Noise only, 20 seeds: all abstain | pass |
| Repeatability, order independence, ×1000 amplitude, e^(j1.1) phase (30 captures each) | pass (30/30 each) |
| Timing budget: 4,096 samples in < 0.5 s | pass |
| Other sample rate and length (2 MS/s, 8,192 samples, BPSK at 13 dB) | pass |
| Invalid input (too short, fs ≤ 0 or NaN, real-valued) raises `ValueError` | pass |
| Isolation from `backend/pipeline` and `backend/api`; no RNG in the module | pass |

## Differences from the reference (gaps over ±10 pts, and other notable ones)

- **Router top-1** (both configurations): 61.0% same-as-dense against the brief's 57.4%, and 3/277 confidently wrong against 1/277. Re-running the *unmodified reference* `evaluate4.py` on this machine gives the same 61.0% and 3/277, so the gap comes from the environment (scikit-learn 1.9.1 on Python 3.14; the tree's tie-breaking between equally good splits differs), not from the port. Top-2 matches exactly in prototype mode. Router timings are lower than the brief's (108 ms dense against 177 ms) only because this machine is faster. The shares match (top-2 ≈ 45% of dense).
- **Proposal recall table.** The reference code has no script for this table, so I computed it myself: the true rate within 2% of *any* proposal, binned by capture SNR. PSK/QAM rows match within 7 pts (< −1 dB: 74% against 81%). The **FSK gap-difference row is much higher than the brief** (−1..4 dB: 46% against 14–16%, n=13; < −1 dB: 19% against 4%, n=21). The brief's FSK figures are close to what I get for FSK *finalists after the Fisher ranking* (98 / 23 / 0%), so the brief most likely measured recall after ranking. I report both rows and can't confirm which one the brief meant. The "old E4" FSK row at ≥ 4 dB is 0% against 7%. The sample sizes are small (n=13–44).
- **Default configuration, FSK 9–14 dB rate: 70% against 80%**, and **without-RRC ablation: 22/277 against 15/277**. Both come from the FSK deviation. For the 2 FSK captures that got better and the 4 that got worse, I compared each capture across the two runs. The regressions are all h=1 at 8–10 dB, where 2× now beats the true rate. Root cause: **FSK finalists are not needle-refined.** The brief refines only PSK finalists. On capture 45, the proposed rate is 0.02% off the truth, and the true-rate score is −1.775 at the proposed rate against −2.106 at the exact rate. The better timing makes the 2× hypothesis competitive with that degraded fit (−1.815). At the *exact* rates, true beats 2× in all four regressed captures. The ablation shifts because thresholds are re-fit per variant on the calibration half, and the FSK scores changed.

## Deliberate deviations from the prototype

1. FSK timing re-refinement with scoring-length blocks (`SpikeConfig.fsk_rescore_refine`, default on; `--prototype` turns it off). The effects are above.
2. Generalisation: every rate, bandwidth and band is a fraction of fs. The rate band is `[0.01, 0.3]·fs`, and the analog bandwidths are `(3, 6, 12, 25, 50)e-3·fs`. At 1 MS/s this is identical to the prototype. One difference: the dedupe/line-peak band upper edge is 300 kHz, while the prototype's old E1/E2 proposers used 250 kHz. Those are kept as-is in `legacy_proposers.py`, only for the recall table.
3. The FFT size grows to the next power of two ≥ len(x) (minimum 16,384), so long segments are not truncated. There is no effect at 4,096 samples.
4. An expert that can't form a hypothesis (e.g. RRC with fewer than 256 usable samples, or FSK with only one tone cluster) returns nothing instead of an infinite-score entry. That is equivalent for decisions.
5. Decision tiers (`decide.py`): `labelled` when family margin, unexplained limit and a non-null winner all pass; `unknown_family` when the family margin passes but unexplained is over the limit; otherwise `abstain`. The **rate is published independently** whenever `m_rate` passes, as in the prototype's evaluation. That is slightly more permissive than the brief's §4.6 wording, which puts the rate inside tiers; I followed the reference so the tables are comparable. `needs_review = not labelled`. The margins are in nats, not probabilities.

## Still weak (brief §7, not fixed here)

1. **Unknown families:** 8-PSK (held out) gets a confident wrong label in 19% of test captures; the unexplained-power flag catches only 5%.
2. **AM:** 38.9% labelled right. The carrier is estimated only to the FFT bin (see the AM xfail above), which is a concrete first fix.
3. **FSK below 4 dB:** finalist recall is 23% at −1..4 dB and 0% below −1 dB.
4. **Below −1 dB** most captures abstain. That is the correct behaviour at this physics limit.
5. **MSK (FSK h=0.5) vs offset-QPSK** are equivalent, so near-ties are expected.
6. **FSK finalists lack needle refinement.** This is new from this work, and it is the most likely next fix; it has to fit the time budget, since each FSK fit takes about 18 ms.
7. **Validation is synthetic only:** AWGN, 4,096-sample segments, no multipath, no real over-the-air captures. The next step is public SigMF recordings.

## Per-stage timing notes

RRC (≈49 ms) and FSK (≈55 ms with the re-refine, ≈39 ms without) dominate. The screens and features cost about 13 ms. With the router's top-2 selection, the mean time falls to about 52 ms per capture.
