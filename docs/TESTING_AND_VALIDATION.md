# Testing and validation

The project separates automated regression tests, generated ground truth, measured validation artifacts, and optional large integration checks. This keeps passing tests from being presented as field-performance certification.

## Routine verification commands

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m backend.validate
npm --prefix frontend run build
```

The first command checks Python behavior and API contracts. The second regenerates measured synthetic results in `backend/validation-report.json`. The frontend build performs TypeScript checking and creates a production bundle.

## Latest verification snapshot

The documentation audit ran the commands above on 2026-09-10:

- backend: **42 passed** in 26.90 seconds;
- validation: report written successfully with **12/12** continuous-fixture recall;
- frontend: TypeScript and Vite production build succeeded, transforming 2,796 modules in 44.04 seconds.

The backend run emitted two non-failing deprecation warnings from the installed Starlette/AnyIO test stack. Vite emitted a non-failing chunk-size advisory because the main minified JavaScript bundle is 905.77 kB (282.55 kB gzip). These are maintenance signals, not failed checks.

## Experimental Estimate spike

The experimental estimator ([Estimate spike](ESTIMATE_SPIKE.md)) has its own tests and evaluation harness. Neither touches Detect.

```bash
.venv/bin/python -m pytest backend/tests/test_estimate_spike.py -q
.venv/bin/python -m experiments.estimate_spike.run_eval --n 500 --seed 4 --out artifacts/estimate_spike/rows_seed4.json
.venv/bin/python -m experiments.estimate_spike.evaluate artifacts/estimate_spike/rows_seed4.json --json docs/estimate-spike-results.json
```

Snapshot on 2026-09-26 (branch `feat/estimate-spike`): the full backend suite gave **271 passed, 3 skipped, 1 xfailed**. The spike file gave 41 passed plus the documented AM xfail. Evaluation on seed 4 (500 captures): 8/277 confidently wrong on the held-out half, and 0/500 captures over the 0.5 s budget. `--prototype` reproduces the reference prototype's tables exactly. Tables and discussion: [Estimate spike results](estimate_spike_results.md).

## Synthetic fixture generator

Run:

```powershell
.\.venv\Scripts\python.exe -m backend.pipeline.synth_gen
```

The generator is deterministic and uses a 48 kHz sample rate. It creates:

- BPSK at 20, 10, 0, and -5 dB SNR;
- QPSK at the same four SNRs;
- FM at the same four SNRs;
- an eight-pulse signal;
- pure noise;
- a mixed IQ demo with BPSK, FM, and a pulsed signal;
- a two-second real-audio WAV demo.

BPSK/QPSK symbols are 96 samples and use a 193-tap, 900 Hz shaping filter. The FM fixture uses 700 Hz deviation and a 230 Hz modulating tone. The pulsed fixture begins at sample 4,800, uses 2,400-sample width and 12,000-sample PRI. Ground truth is written into separate `.truth.json` files; the detector does not read those files.

SNR is defined as total generated signal power divided by full-band complex noise power. Pulsed SNR is measured while the pulse is on. This definition differs from receiver SNR measured in a narrow post-detection bandwidth.

## Python test coverage

### Detector tests

`backend/tests/test_detect.py` checks:

- all 12 modulation/SNR fixture combinations are detected;
- detected frequency and time bounds stay within declared tolerances;
- eight-pulse width, PRI, and window count;
- ten independent noise seeds produce zero candidates under the tested settings;
- scaling an input amplitude by 100 changes power by approximately 40 dB;
- fixed-debug behavior agrees with an equivalent explicit threshold;
- WAV ambiguity and explicit interpretation;
- 15 SigMF datatype/metadata cases;
- all three mixed-demo emitters;
- isolated 20, 40, 80, and 300 ms bursts;
- a single pulse receives no invented PRI;
- continuous signals are not labeled pulsed.

Current bound tolerances are 1,400 Hz in frequency and 0.08 seconds in time for continuous fixtures. Pulse timing tests constrain width/PRI error to under 150/100 samples for the dedicated fixture.

### API and layer tests

`backend/tests/test_api.py` checks:

- upload/result response structure;
- spectrogram dimensions, edges, and aggregation contract;
- four IQ layers with no audio URLs;
- IQ decimation;
- envelope/PRI responses;
- validated SigMF export;
- five real-audio layers;
- distinct valid RIFF/WAV bytes for raw and filtered clips at 48 kHz;
- WAV ambiguity and user override;
- malformed/unsupported request behavior.

### Large-capture tests

`backend/tests/test_large_capture.py` checks:

- candidates that cross a block boundary;
- a signal near the final partial block;
- overview height capped at 768 rows;
- layer previews capped at one million samples;
- invalid samples near the file end are detected;
- asynchronous IQ and audio jobs reach complete sample coverage;
- job cleanup and retention behavior;
- failures publish an explicit failed state with no partial result.

## Measured synthetic validation

The checked-in `backend/validation-report.json` records an actual detector run. Its summary currently reports:

| Measurement | Result |
|---|---:|
| Continuous fixtures | 12 |
| Continuous fixture recall | 1.0 |
| Pulsed truth width | 2,400 samples |
| Measured pulsed width | 2,374 samples |
| Pulsed truth PRI | 12,000 samples |
| Measured PRI | 12,000 samples |
| Measured pulse windows | 8 |
| Pure-noise candidates | 0 |

The file preserves candidate bounds, confidence, threshold excess, noise floor, and timing for every fixture. These results are evidence for deterministic synthetic cases. They do not establish performance on field captures, probability of detection, probability of false alarm, or robustness to every interference environment.

## Audio test pack

`test-audio/` contains five 24 kHz, five-second PCM16 WAV files:

| File | Intended content | Current measured behavior |
|---|---|---|
| `01-steady-tone.wav` | One steady tone plus noise | 1 candidate |
| `02-two-tones.wav` | Two separated tones plus noise | 2 candidates |
| `03-pulsed-tone.wav` | Ten repeated tone pulses | 1 pulsed candidate; width 2,400, PRI 12,000, 10 windows |
| `04-short-burst.wav` | One isolated tone burst | 1 candidate; one measured burst and no PRI |
| `05-noise-only.wav` | Noise only | 0 candidates |

`test-audio/measured-results.json` is the machine-readable result, and `test-audio/detect-wav-test-pack.zip` packages the fixtures for manual upload. The short-burst measured width is affected by filter/envelope boundaries and is not treated as a modulation fact.

## Optional real 1 GiB check

`backend/tests/run_gib_check.py` performs the expensive end-to-end test documented in [LARGE_FILE_PROCESSING.md](LARGE_FILE_PROCESSING.md). The checked-in result from 2026-09-10 confirms all 134,217,728 complex samples were scanned, three strategically placed bursts were found, the tail layers worked, and peak backend working set was 263.90 MiB in that run.

This check is not part of the routine suite because it consumes substantial disk, time, and the only compute slot.

## How to interpret failures

- A detector fixture failure can indicate a numerical/library regression, threshold behavior change, or intentional algorithm change whose validation bounds need review.
- An API failure can indicate a schema, status-code, lifecycle, or media-contract regression.
- A frontend build failure usually indicates TypeScript/schema drift or dependency/tooling trouble.
- A 1 GiB check failure should be separated into upload, job progress, full-sample coverage, detection location, spectrogram, layer, memory, or cleanup failure before changing the algorithm.

Do not weaken a bound only to make a changed implementation pass. Update a test when the intended contract has changed and the new behavior has evidence.

## Reproducibility notes

Python direct dependencies are constrained in `backend/requirements.txt`; exact tested versions are frozen in `backend/requirements-lock.txt`. Frontend dependency ranges are in `frontend/package.json`, and exact npm resolution is in `frontend/package-lock.json`. Synthetic generation uses a deterministic seed. Timing and memory measurements will vary across machines.
