# Judge defense guide

This guide gives concise, technically accurate answers for a demonstration or review. The strongest presentation is to show evidence in the running product and distinguish current Detect behavior from later phases.

## Thirty-second project explanation

SIH26147 Detect is an offline RF/audio capture triage system. It validates the recording format, estimates a noise floor, scans time and frequency for energy above that floor, groups evidence into candidate regions, measures pulse timing, and exposes every major intermediate representation for operator review. It accepts captures up to 2 GiB with bounded-memory block processing. It does not claim modulation classification or decoded content in Phase 1.

## What to demonstrate

1. Start with the bundled IQ demo and point out that it runs through the same API as an upload.
2. Show the waterfall, three candidates, frequency/time bounds, pulse windows, PSD, and pipeline log.
3. Select the pulsed candidate and show envelope-derived width and PRI.
4. Open Signal Breakdown and explain isolation/downconversion without calling it demodulation.
5. Switch to the audio demo and play raw, isolated, noise-referenced, and detected-region clips.
6. Show JSON and SigMF annotation exports.
7. Show the completion and limitation matrices in [PROJECT_STATUS.md](PROJECT_STATUS.md).
8. If large-file capacity is questioned, show `backend/large-file-validation.json` and explain the boundary/middle/tail fixture.

## Common questions

### Is this CFAR?

It is CFAR-style adaptive energy detection because the threshold follows a measured noise estimate. It is not a calibrated cell-averaging CFAR with guard/reference cells or a guaranteed false-alarm probability. The current baseline uses a frequency-median Welch floor per small capture or per large-file block plus a tunable dB margin.

### What does confidence mean?

Confidence is an explainable heuristic based on threshold excess and occupancy. It is bounded between zero and 0.99, and values below 0.70 require review. It is not a probability. Calibration needs labeled field data.

### Are the power values dBm?

No. They are dB relative to one sample-unit squared per hertz. The capture does not provide the gain, impedance, ADC scale, and antenna calibration needed for dBm.

### Are candidate frequencies absolute RF frequencies?

They are baseband offsets. If SigMF supplies a center frequency, the app retains it separately. An operator can derive an RF estimate from acquisition context, but the detector does not silently change the coordinate system.

### Does the system decode audio from IQ?

No. IQ is complex baseband and needs a waveform-specific demodulation chain before it can become meaningful audio or data. Signal Breakdown gives visual isolation layers only. Real-audio WAV inputs can produce filtered listening clips because the supplied channel is already audio.

### Why ask how to interpret a stereo WAV?

Two channels can be stereo audio or I/Q. The automatic check requires strong Hilbert quadrature evidence, low direct correlation, and balanced power. If evidence is inconclusive, guessing would corrupt the spectrum, so the operator confirms known provenance.

### Can it handle a 1 GB file?

Yes, up to a 2 GiB hard limit. Files above 1 MiB are copied to disk and analyzed in 524,288-sample cores with boundary context. The checked 1 GiB run on 2026-09-10 scanned 134,217,728 complex samples, found bursts at a block boundary, middle, and tail, and peaked at 263.90 MiB backend working set on the tested machine.

### Does the overview mean data was downsampled before detection?

No. Each block uses its full-resolution spectrogram for detection. Only the retained dashboard overview is maximum-pooled to at most 768 time rows.

### What happens at block boundaries?

Each block has guard samples on both sides, aligned to the STFT hop. Only core samples are published. Adjacent-block candidates merge when their frequency overlap is at least half the narrower band, and overlapping pulse windows join.

### How were results validated?

The routine suite checks continuous BPSK, QPSK, and FM across four SNRs, pulse timing, multiple noise seeds, scaling, short bursts, SigMF cases, WAV interpretation, API contracts, media layers, block boundaries, tail corruption, cleanup, and failure states. A separate opt-in test uploads an actual 1 GiB file. These are synthetic/regression results, not field certification.

### Why use synthetic data?

Synthetic fixtures provide exact known bounds and repeatability, which is useful for regression tests. They do not cover hardware impairments or field interference. The roadmap starts with collecting representative field data before calibration or stronger performance claims.

### What is missing from Tier 1?

Confidence and review workflow are implemented. Statistical non-Gaussianity evidence such as kurtosis and coarse-to-fine scanning are not implemented.

### What Tier 2 features work?

None are represented as working. Cyclostationary analysis, deep-learning detection, co-channel separation, hopping tracking, matched filtering, and live streaming are labeled planned.

### Why no real-time streaming?

The design target for this phase is offline evidence-first analysis. Streaming needs a different ingestion lifecycle, stable real-time budgets, incremental state, cancellation/backpressure, and long-running resource controls.

### What happens with no candidates?

The analysis completes successfully with an empty list. It means no region passed the current evidence rules at that margin; it is not proof the capture contains no signal.

### What prevents false precision?

The UI displays baseband units, review flags, the exact detector method, threshold/noise summaries, measured resolution, and explicit limitations. It avoids dBm, probability, classification, and decoded-content claims without the required evidence.

## Evidence files to keep ready

| Evidence | Purpose |
|---|---|
| `backend/validation-report.json` | Per-fixture measured candidates and timing. |
| `backend/large-file-validation.json` | Actual 1 GiB scan, memory, runtime, and endpoint checks. |
| `test-audio/measured-results.json` | Manual WAV pack expected behavior. |
| `backend/tests/` | Executable contracts and boundary cases. |
| `docs/PROJECT_STATUS.md` | Requirement-by-requirement completion. |
| `docs/BACKEND_PIPELINE.md` | Exact algorithm and formula provenance. |

## Claims to avoid

- “It identifies BPSK/QPSK/FM.” The detector sees energy; fixture names belong to ground truth.
- “Confidence is 90% probability.” The score is not calibrated.
- “The power is dBm.” It is uncalibrated sample-unit PSD.
- “It decodes IQ to sound.” It does not demodulate.
- “It guarantees CFAR.” It uses an adaptive median-margin threshold.
- “It analyzes unlimited files.” The explicit limit is 2 GiB with resource and complexity caps.
- “Synthetic recall proves field performance.” Field validation remains future work.

## If a live demo behaves unexpectedly

Keep the explanation tied to observable state. Check the backend connection, input interpretation, sample rate/datatype, margin, job progress, and pipeline log. If a candidate is absent, lower the margin only as an operator experiment and state that this trades sensitivity against false alarms. Do not relabel a failure as a hidden feature.
