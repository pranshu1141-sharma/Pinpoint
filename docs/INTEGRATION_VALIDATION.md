# Synchronous API and dashboard integration verification

Verified locally on 2026-09-11. Integration rung 1 is delivered: synchronous API, dashboard detail and JSON export are connected, and the optional async path was tested and deliberately remains Detect-only. At that date the underlying DSP was at fallback rung 2 (fine labels/confidences and symbol rate always null); this has since changed, see below. No plot code, breakdown code or motion code changed.

**Update (later pass):** fine PSK classification and symbol-rate estimation are no longer stubbed; see [Estimate and Classify](ESTIMATE_CLASSIFY.md) for the current field behavior and measured evidence. Field names, endpoints and the checks below are otherwise unaffected — that fix only changed `backend/pipeline/classify.py`'s internal estimator, not the API/dashboard wiring verified here.

## Checks

- Before integration: 104 backend tests passed, two documented strict expected failures.
- After integration: `python -m pytest backend/tests -q` — 120 passed, two identical expected failures; two upstream dependency deprecation warnings.
- `node --test frontend/tests/bolt-adapter.test.ts frontend/tests/detection-detail.test.mjs` — six passed. Tests render the actual detail component and cover zero/negative values, sub-Hz RF display, inline caveats, missing stage fields, explicit null text and real-audio reasons.
- `npm --prefix frontend run build` — TypeScript and Vite succeeded. Existing non-failing chunk-size advisory; main JavaScript bundle 782.24 kB.
- Real HTTP calls to local Uvicorn for all 12 continuous fixtures and their JSON exports. All 21 returned stage fields also match the independent pre-integration artifact in the API regression tests; original 2% center tolerance and correct family at ≥0 dB are unchanged.
- IQ and audio demo API tests preserve all null fields; pulsed SigMF test verifies occupied windows and RF tuning offsets. Existing layer, spectrogram and export tests pass.
- A real 5,376,000-byte IQ upload traverses the normal HTTP 202 route, scans all 672,000 samples across two blocks, merges candidates and exports them. Downstream stage fields remain absent; no first-block values are represented as full-track measurements.
- Actual dashboard IQ demo displays measured/refined centers, both bandwidths, full-band SNR, heuristic family confidence, inline FM caveat, fine **Not reliably estimated** and symbol **Not attempted**. Existing Detect-band rows have explicit Detect labels.

## Actual continuous-fixture API measurements

Each fixture uses seed 47, 48 kHz sampling, two seconds and 8,000 Hz baseband truth. `C` = constant-envelope, `V` = varying-envelope. Full raw JSON values, including refinement and diagnostic fields, are saved in [integration-validation.json](integration-validation.json). All fine labels/confidences and symbol-rate values are null.

| Fixture | SNR truth dB | Center Hz | SNR measured dB | −3 dB width Hz | 99% width Hz | Family |
|---|---:|---:|---:|---:|---:|---|
| BPSK | 20 | 8000.0738 | 19.9670 | 453.4709 | 1500.000 | C |
| BPSK | 10 | 8000.2585 | 9.9686 | 453.3546 | 1500.000 | C |
| BPSK | 0 | 8000.7829 | −0.0357 | 454.8802 | 1546.875 | C |
| BPSK | −5 | 8002.9963 | −5.0580 | 460.0697 | 843.750 | V |
| QPSK | 20 | 7998.7465 | 19.9665 | 446.2499 | 1500.000 | C |
| QPSK | 10 | 7998.7002 | 9.9645 | 446.8942 | 1546.875 | C |
| QPSK | 0 | 7998.3521 | −0.0501 | 450.3514 | 1546.875 | C |
| QPSK | −5 | 7998.8692 | −5.0838 | 459.2943 | 796.875 | C |
| FM | 20 | 8000.0241 | 19.9634 | 65.7666 | 1921.875 | C |
| FM | 10 | 8000.0918 | 9.9717 | 65.6996 | 1921.875 | C |
| FM | 0 | 8000.3433 | −0.0153 | 65.7402 | 1921.875 | C |
| FM | −5 | 8019.0019 | −5.0232 | 66.2438 | 1687.500 | C |

## Bundled IQ demo

The four-second mixed capture has a 100 MHz tuning frequency. These are measured values, not labels derived from its truth file:

| Candidate | Center Hz | Refined center Hz | −3 dB width Hz | 99% width Hz | Full-band SNR dB | Family confidence (heuristic) |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 99989000.12515 | 99988999.96318 | 439.74285 | 1546.875 | 7.47547 | 0.16988 |
| 1 | 100003998.58547 | 100004459.76417 | 66.30350 | 1921.875 | 7.47547 | 0.41428 |
| 2, pulsed | 100014000.09093 | 100013999.67341 | 82.70273 | 140.625 | 10.86099 | 0.86395 |

All three return constant-envelope. Candidate 1 carries `unshaped-pulse-sidelobes` inline. That width ratio does not prove unshaped pulses: FM's narrow spectral lines also trigger it. The raised-tone refinement is a heuristic and is visibly worse on this FM candidate; the direct estimate is preserved alongside it. Coarse family does not distinguish FM from PSK.

The two continuous candidates share full-band occupied-sample SNR because they occupy the same time interval in this mixed capture. Other simultaneous sources contribute to this measure. It is not isolated per-emitter SNR; the validated convention has been preserved rather than silently changed for integration.

## Measured latency

Five real `/api/demo?kind=iq` responses before integration reported **155.705, 185.287, 175.931, 164.134, 166.969 ms**, mean **169.605 ms**. Five final integrated responses reported **662.072, 660.806, 658.470, 651.791, 710.556 ms**, mean **668.739 ms**. An earlier integrated sample averaged **520.487 ms** (527.149, 524.642, 500.184, 548.305, 502.153).

The final measured increase is approximately **499 ms**, or **3.94×** total analysis time. This is a material relative increase, although the bundled demo remains under one second of server analysis on this machine. These are development-machine measurements with varying concurrent work, not a controlled benchmark or a latency guarantee. No claim of negligible overhead is made. Optimizing repeated stage processing is separate future work; this integration preserves the existing validated functions.

The synchronous timer includes Detect and downstream processing but excludes ingest/serialization and browser drawing. The unchanged pipeline log continues to report Detect's own duration. Large-file timings and behavior are unaffected by this integration.
