# Claims we can defend

Every number below comes from `docs/readiness.json`, written by `python -m experiments.readiness.scoreboard`. Numbers after an `rj` marker are rewritten from that file by `--sync-docs`, and the docs criterion fails if any of them drifts. All of them are **synthetic, held-out test data**: none is a field-performance claim. Real recordings (G3) have not been processed yet.

**Conditions shared by every row**

| Generator | What it is | Size | SNR |
|---|---|---|---|
| G1 | Spike corpus (`experiments/estimate_spike/signals.py`), test seed 7: BPSK/QPSK (NRZ or RRC 0.35), 16-QAM, 2-FSK (h 0.5/1), 8PSK, AM, FM, noise; rates 25–160 kSym/s; random carrier ±100 kHz | 300 captures × 4,096 samples at 1 MS/s | uniform −6…14 dB (full-band) |
| G2 | Widened shipped fixture family (`experiments/readiness/synth_wide.py`), test seeds 100000+: BPSK/QPSK/8PSK/16-QAM/2-ASK/4-FSK × carriers {0, 3, 8, 15} kHz × {12, 24, 48, 96} samples/symbol, FM, noise, plus held-out 8-FSK and rectangular 8-QAM | 1,032 captures × 24,000 samples at 48 kS/s | 5, 10, 20 dB |

"At ≥ 5 dB" means full-band SNR (total signal power ÷ complex noise power over the whole capture bandwidth). Thresholds were fit only on calibration seeds (G1 seed 4, G2 seeds 200000+), never on these test seeds.

## Modulation label (product estimator: verify)

| Claim | G1 | G2 |
|---|---|---|
| Captures with a **wrong** label published (all captures, including noise and held-out families) | <!--rj:stats.verify.G1.label.published_wrong--> 0.3% | <!--rj:stats.verify.G2.label.published_wrong--> 1.4% |
| In-library digital captures at ≥ 5 dB labelled **correctly** (BPSK, QPSK, 8PSK, 16-QAM, 2-FSK, 4-FSK, 2-ASK present in that generator) | <!--rj:stats.verify.G1.label.published_correct_in_library--> 97.6% | <!--rj:stats.verify.G2.label.published_correct_in_library--> 94.4% |
| Noise-only captures given a label | <!--rj:stats.verify.G1.confidence.noise_labelled--> 0.0% | <!--rj:stats.verify.G2.confidence.noise_labelled--> 0.0% |
| Held-out families (8-FSK, rectangular 8-QAM; G2 only) given a **wrong** label | – | <!--rj:stats.verify.G2.confidence.ool_wrong--> 13.5% |

## Symbol rate

| Claim | G1 | G2 |
|---|---|---|
| Captures with a **wrong** rate published (> 5% error) | <!--rj:stats.verify.G1.rate.published_wrong--> 1.7% | <!--rj:stats.verify.G2.rate.published_wrong--> 1.0% |
| Digital captures at ≥ 5 dB with a **correct** rate published (within 5%) | <!--rj:stats.verify.G1.rate.published_correct_digital--> 94.0% | <!--rj:stats.verify.G2.rate.published_correct_digital--> 91.2% |

## Parameters (linear modulations for frequency and bandwidth; all signals for SNR; ≥ 5 dB)

| Claim | G1 | G2 |
|---|---|---|
| Centre frequency within 10% of the true −3 dB bandwidth | <!--rj:stats.verify.G1.params.cf_ok--> 97.0% | <!--rj:stats.verify.G2.params.cf_ok--> 99.0% |
| −3 dB bandwidth within ±25% of the pulse-shape truth | <!--rj:stats.verify.G1.params.bw3_ok--> 92.4% | <!--rj:stats.verify.G2.params.bw3_ok--> 98.6% |
| SNR within 2 dB | <!--rj:stats.verify.G1.params.snr_ok--> 99.2% | <!--rj:stats.verify.G2.params.snr_ok--> 98.3% |

## Detect

| Claim | G1 | G2 |
|---|---|---|
| Signals at ≥ 5 dB overlapped by a detection | <!--rj:stats.shipped.G1.detect.recall--> 100.0% | <!--rj:stats.shipped.G2.detect.recall--> 100.0% |
| Noise captures with any detection | <!--rj:stats.shipped.G1.detect.noise_false--> 0.0% | <!--rj:stats.shipped.G2.detect.noise_false--> 0.0% |
| Single-signal captures split into ≥ 2 detections (**not yet acceptable**) | <!--rj:stats.shipped.G1.detect.fragmentation--> 3.5% | <!--rj:stats.shipped.G2.detect.fragmentation--> 0.2% |

## What we do not claim

- **Speed:** the verify estimator does not yet meet 0.5 s per candidate. The share of candidates within 0.5 s is <!--rj:stats.verify.G1.speed.within--> 100.0% on G1 and <!--rj:stats.verify.G2.speed.within--> 90.0% on G2.
- **FM coverage on G1:** the FM-over-digital margin gate needed to stop 8-FSK/4-FSK being published as FM also withholds most G1 FM labels.
- **Real recordings:** none processed yet (G3 empty).
- **Calibrated probabilities:** margins are nats, not probabilities. Detect's isotonic confidence was fit on one synthetic corpus and is labelled "uncalibrated across generators".
- **The legacy estimator** (`estimator=legacy`): its fixture numbers (e.g. 30/30 symbol rates at ≥ 4.5 dB) hold only on the `synth_gen` fixtures (48 kHz, 96 samples/symbol, one filter). On G1 it publishes wrong labels on <!--rj:stats.shipped.G1.label.published_wrong--> 16.7% of captures.
