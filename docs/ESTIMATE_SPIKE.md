# Estimate spike: propose → verify (MDL)

> **Status update (readiness work):** the estimator is now wired into the product as the default modulation-label/symbol-rate path through `backend/pipeline/verify_estimator.py` (candidate window, decimation, cross-generator-calibrated margins), with added experts (least-squares pulse, 8PSK, unipolar 2-ASK, 4-FSK, an 8-tone probe) and fixes described in the branch history. The results below are the original spike evaluation; current measured numbers are in [READINESS.md](READINESS.md) and [CLAIMS.md](CLAIMS.md).

> **Original status (superseded):** this document describes the spike as first evaluated, when it was experimental and not imported by the product. All evidence here is synthetic AWGN only; full original numbers: [Estimate spike results](estimate_spike_results.md).

## At a glance

| | |
|---|---|
| What it does | Takes one detected segment (complex baseband + sample rate) and returns the best hypothesis: family/label, symbol rate (or none), and margins that act as confidence. |
| Families it can claim | BPSK, QPSK, 16-QAM (flat NRZ or RRC pulse), 2-FSK, AM, FM, and "nothing here" (null). |
| How it decides | Every hypothesis is checked by **rebuilding the capture** from it and scoring the leftover plus the information the hypothesis needs (MDL). Lowest score wins; confidence = score margin to competitors. |
| Where the code is | `backend/experimental/estimate_spike/` |
| Tests | `backend/tests/test_estimate_spike.py`: 41 pass, plus 1 documented expected failure (AM) |
| Evaluation harness | `experiments/estimate_spike/` (seeded generator, `run_eval`, `evaluate`) |
| Speed | 327 ms mean and 362 ms max per 4,096-sample segment on one core (limit 0.5 s) |
| Deterministic | Yes. No randomness in analysis. Same input → bit-identical scores, in any processing order. |
| Behind a flag | `PINPOINT_ESTIMATE_SPIKE=1` gates any future integration. There is none today. |

## Why it exists

The shipped estimator measures symbol rate with one spectral trick and attaches a heuristic confidence. It can be confidently wrong in predictable ways: 2× harmonics, or noise that looks like a rate line, and it cannot estimate FSK symbol rate at all. This spike tests another approach: **cheap estimators propose, an expensive checker verifies.**

```
score(h) = ln(mean |x − rebuild_h(x)|²) + cost_nats(h) / N_eff        (lower = better)
```

`cost_nats` charges `ln(alphabet size)` per symbol plus small per-block and per-parameter terms, so a hypothesis cannot win just by having more free parameters. A **null** hypothesis (`ln(mean|x|²)`, no cost) always competes. A family is claimed only if the library has a model that can rebuild it.

## Pipeline

1. **Carrier:** 4th-power spectral line (Hann window, zero-padded FFT, parabolic peak) → derotated signal `xc`.
2. **Router features:** six cheap numbers (envelope spread; carrier, 2nd- and 4th-power line prominence; instantaneous-frequency kurtosis and spread).
3. **PSK/QAM rate proposals:** multi-scale **gap-difference** lines. `xc` is smoothed at widths 1, 2, 4, 8 and differenced across a gap equal to the smoothing width, then the top 3 spectral peaks are taken, plus ½× and 2× of the first.
4. **PSK ranking + needle:** a quick QPSK/NRZ score keeps 3 finalists; each is nudged by ±0.3% and ±0.6% and the best is kept.
5. **FSK rate proposals:** the same gap-difference idea on the smoothed instantaneous-frequency track (widths 2, 4, 8, 16).
6. **FSK ranking:** Fisher ratio of per-symbol frequencies (how cleanly they split into two tones) keeps 3 finalists.
7. **FSK needle** (added after the prototype, see below): each FSK finalist is refined by a joint rate × timing search on the FSK model.
8. **Experts:** NRZ and RRC PSK/QAM on the PSK finalists, FSK on the FSK finalists, analog (AM/FM) once, null once.
9. **Decision:** lowest score wins, margins are computed, and thresholds are applied (next section).

### Experts

| Expert | Rebuild model | Notes |
|---|---|---|
| `nrz` | Per-symbol means snapped to BPSK/QPSK/16-QAM, one amplitude and phase per 16-symbol block | Timing from the symbol-rate line phase, then a fine search (±1, ±½, ±¼, ±⅛ sample). |
| `rrc` | Matched-filtered symbols snapped to the alphabet and rebuilt with an RRC pulse (α = 0.35, ±6 symbols) | Essential: without it, flat-block models prefer 2× the rate on shaped signals, and confident mistakes rise from 8 to 18. |
| `fsk` | Continuous-phase 2-FSK: Kay per-symbol frequency, 2-means tones, two bit-decision rules, amplitude refit per 8-symbol block | Timing: short-block search, then long-block refine, then dense ±½-sample scan. Accepts a timing hint from the needle. |
| `analog` | AM (low-passed real part on an aligned carrier) or FM (low-passed phase increments, constant amplitude), bandwidth chosen by MDL | Carrier only to FFT-bin accuracy; this is the AM weak spot. |
| `null` | Nothing | Always present. |

All experts share the `Hypothesis(expert, label, rate, score, residual)` result type, so adding a family means adding one expert.

### FSK needle refinement (new)

The FSK rate fit is needle-sharp. Before the needle, FSK finalists were up to 0.18% off in rate, which is up to about 0.6 symbols of timing drift across a 4,096-sample segment. The true-rate hypothesis then scored as much as 0.85 nats worse than at the exact rate, and 2× the rate sometimes won.

`FskExpert.refine_rate` fixes this:

1. Find timing at the proposed rate (short-block search plus long-block refine).
2. Keep the symbol alignment fixed **at the middle of the segment**, because a small rate error leaves the timing right there, and scan a rate grid over ±0.25% in 0.05% steps.
3. **Pattern search** over the 3×3 rate × timing neighbourhood, halving both steps each round, down to 1e-5 in rate and 1/16 sample in timing.
4. Return `(rate, timing)`. The timing is passed to `FskExpert.fit` as an extra starting point, and the fit keeps whichever start scores better.

Because the score jumps at sub-sample scales (samples switch symbols at the boundaries), the final FSK fit also ends with a dense ±½-sample timing scan. After the needle, refined FSK hypotheses score as well as fits at the exact true rate (median −0.006 nats, worst +0.021).

| Seed 4, 500 captures | Before (prototype) | After needle |
|---|---|---|
| FSK rate right, all SNRs | 50.0% | **57.7%** |
| FSK rate right, 4–9 dB / 9–14 dB | 87.5% / 80% | **95.8% / 95%** |
| FSK labels shipped (test half), all correct | 26% | **40%** |
| Confident FSK mistakes | 2 | **0** |
| Mean / max time per capture | 108 / 123 ms | 327 / 362 ms |

## Decision and confidence

- `m_fam`: best score of any *other family* minus the winner's score.
- `m_rate`: for digital winners, best score among digital hypotheses whose rate differs by ≥ 5%, minus the winner's score.
- `m_null`: null score minus the winner's score.
- `unexplained`: the share of signal power (above the Welch noise estimate) that the winner's rebuild left over.

Thresholds are **fit on a calibration half and applied to a held-out test half**: the smallest margin that reaches ≥ 95% precision. Current values: `m_fam ≥ 0.383`, `m_rate ≥ 0.179`, `unexplained ≤ 0.102`. The prototype's defaults (0.411 / 0.149 / 0.097) are kept in `Thresholds()`.

| Tier | When | `needs_review` |
|---|---|---|
| `labelled` | Family margin passes, winner is not null, unexplained is under the limit | false |
| `unknown_family` | Family margin passes but too much signal is left unexplained (a family the library can't rebuild, e.g. 8-PSK) | true |
| `abstain` | Otherwise | true |

The symbol rate is published whenever `m_rate` passes, independently of the tier, as in the prototype's evaluation. Margins are in **nats, not probabilities**.

## Using it

```python
from backend.experimental.estimate_spike import analyze_segment, decide, Thresholds

result = analyze_segment(iq_segment, sample_rate)          # complex 1-D array, ≥ 2,000 samples
d = decide(result.hypotheses, result.noise_var, result.total_power, Thresholds())
d.to_json()
```

`to_json()` returns SigMF-annotation-shaped keys: `estimate_spike:family`, `estimate_spike:label`, `symbol_rate_hz`, `confidence` (the margins), `needs_review`, `estimate_spike:tier`, `estimate_spike:best_hypothesis`. `result.timings_s` gives per-stage timing, and `result.psk_proposals` / `fsk_finalists` show what was proposed.

Every constant lives in `SpikeConfig` (`config.py`). Frequencies are fractions of the sample rate (rate band `[0.01, 0.3]·fs`), so any sample rate and length works.

| Switch | Effect |
|---|---|
| `fsk_rescore_refine=False, fsk_needle=False` | Exact prototype v5 behaviour (`run_eval --prototype`). |
| `fsk_needle=False` | Keep FSK timing re-refinement, skip the needle (`run_eval --no-fsk-needle`). |
| `analyze_segment(..., experts=("nrz", "rrc"))` | Run only some experts (the null model always runs). |

## Reproducing the evaluation

```bash
.venv/bin/python -m pip install -r experiments/estimate_spike/requirements.txt
.venv/bin/python -m experiments.estimate_spike.run_eval --n 500 --seed 4 --out artifacts/estimate_spike/rows_seed4.json
.venv/bin/python -m experiments.estimate_spike.evaluate artifacts/estimate_spike/rows_seed4.json --json docs/estimate-spike-results.json
.venv/bin/python -m pytest backend/tests/test_estimate_spike.py -q
```

scikit-learn is needed only for the router table in `evaluate`; product code never imports it. The generator reproduces the prototype's 500 captures bit for bit, and with `--prototype` every table in the task brief is reproduced exactly (except the router's top-1 row, which depends on the scikit-learn version).

## Known limits

1. **Unknown families:** held-out 8-PSK gets a confident wrong label in about 24% of test captures; the unexplained-power flag rarely catches it.
2. **AM:** about 37% labelled right; the carrier is estimated only to FFT-bin accuracy.
3. **FSK below 4 dB:** finalist recall is 23% at −1..4 dB and 0% below −1 dB.
4. **Below −1 dB** it mostly abstains, which is correct at that SNR.
5. **Time headroom:** the needle (≈163 ms) plus FSK fits (≈95 ms) are most of the cost, leaving about 140 ms of headroom at worst. The router's top-2 mode averages 100 ms.
6. **Thresholds are sensitive** to a few calibration captures. After the FSK improvement they loosened slightly, which let two unchanged non-FSK captures through.
7. **Synthetic only:** AWGN, 4,096-sample segments, no multipath, no real over-the-air captures. The next step is public SigMF recordings.
