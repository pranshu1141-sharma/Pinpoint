# Limitations and roadmap

This document records what the current project can support, what remains incomplete, and the order in which later work should be approached. It prevents planned capabilities from being mistaken for shipped behavior.

## Implemented Phase 1 capability

The application currently provides:

- explicit raw IQ, SigMF, mono WAV, and disambiguated stereo WAV ingestion;
- adaptive noise-referenced energy detection;
- candidate time and baseband-frequency bounds;
- pulse windows, median pulse width, and median PRI where measurable;
- heuristic confidence and a review flag;
- inspectable waterfall, PSD, pipeline log, candidate list, layers, and real-audio review clips;
- JSON and SigMF annotation export;
- disk-backed scanning through 2 GiB;
- automated synthetic, API, layer, block-boundary, failure, and cleanup tests;
- a measured real 1 GiB end-to-end integration artifact.

## Incomplete within the requested Detect tiers

| Item | Status | What is missing |
|---|---|---|
| Statistical “not noise” evidence | Not built | No kurtosis, spectral-kurtosis, normality, or higher-order statistic is computed. |
| Coarse-to-fine scanning | Not built | Every processing block runs the full 1,024-point scan; no cheap coarse pre-pass selects regions for refinement. |
| Calibrated confidence | Not built | Current confidence is an explicit heuristic and has no probability calibration dataset. |
| Local cell CFAR | Not built | Threshold adapts to a capture/block median, not guard/reference cells around each time-frequency cell. |

## Deliberately out of Phase 1

The UI labels these capabilities as planned, and the backend contains no hidden implementation for them:

- cyclostationary analysis;
- deep-learning spectrogram detection;
- co-channel source separation;
- frequency-hopping tracking;
- matched filtering;
- real-time streaming.

The wider Estimate, Classify, and Report stages are also absent. There is no modulation classifier, demodulator, symbol recovery, decoder, content extractor, or report-generation workflow.

## Algorithm limits

### Noise model

The frequency-median noise floor works best when noise is roughly stationary and a minority of bins contain signals. Colored noise, impulsive interference, changing gain, and wide occupancy can bias it. Large files improve locality by estimating per block, but still do not use cell-level reference windows.

### Resolution

The 1,024-sample window fixes the nominal bin width, and the 256-sample hop fixes frame spacing. Window leakage broadens measured bounds. Two-bin/two-frame morphology rejects isolated noise but can also remove legitimate sub-resolution energy.

### Pulse timing

The 1 ms power smoothing and minimum 2 ms retained interval limit short-pulse sensitivity and edge accuracy. The 257-tap isolation filter broadens transitions. Pulse width and PRI summarize the windows associated with one band and can mix independent emitters.

### Association

Candidates are grouped by occupied frequency bands. The detector does not create source tracks or solve overlaps. Large-file merge logic follows continuity across adjacent blocks based on frequency overlap; it does not infer hopping identity.

### Confidence

The score combines threshold excess and occupancy. It is useful for triage but cannot be read as a posterior probability, precision estimate, or regulatory-grade alarm confidence.

## System limits

- One local compute job at a time.
- Maximum capture size 2 GiB.
- Maximum metadata size 1 MiB.
- Large packed 24-bit WAV unsupported.
- Finished job lifetime 30 minutes; newest three retained.
- Job/layer state is in memory and disappears on restart.
- No authentication, TLS, user isolation, durable database, or server-side audit trail.
- Signal Breakdown previews are bounded to eight seconds or one million samples.
- Hard failure above 4,096 candidates or 200,000 pulse windows.
- Frontend production build does not package or supervise the Python service.

## Recommended roadmap

### 1. Establish field validation

Collect representative, legally usable captures covering receivers, rates, gains, bandwidths, noise colors, interference, weak signals, and negative examples. Define detection and false-alarm metrics before tuning heuristics. Preserve acquisition metadata and build train/validation/test separation if learned methods are considered later.

### 2. Add statistical noise evidence

Implement spectral kurtosis or another justified higher-order statistic as a separate evidence channel. Validate it against Gaussian, impulsive, and occupied-band fixtures. Do not collapse it into the current confidence score until calibration data supports the combination.

### 3. Implement local adaptive thresholding

Add guard and reference cells in time/frequency, edge handling, robust estimators, and an explicit probability-of-false-alarm model where its assumptions hold. Compare against the current median-margin baseline on fixed datasets.

### 4. Calibrate review scores

Use labeled field data to map measurable features to reliability. Publish calibration plots and define operational thresholds. Retain the underlying evidence values so users can inspect why a score changed.

### 5. Add coarse-to-fine optimization if profiling warrants it

Profile large real captures first. A coarse stage should preserve short events and guarantee refinement coverage. Measure missed-event risk, runtime, and peak memory against the current complete block scan.

### 6. Build source tracking and separation as separate features

Frequency hopping and co-channel separation need their own data models, evaluation criteria, and operator displays. Do not overload the present candidate-band association with source-identity claims.

### 7. Add Estimate and Classify

Create explicit downstream contracts that consume Detect candidates. Potential Estimate outputs include center frequency, occupied bandwidth, SNR under a declared measurement method, symbol rate, and timing stability. Classification should support unknown/review states and be evaluated on held-out data.

### 8. Add demodulation/decoding only for declared waveforms

Each demodulator needs a known hypothesis, synchronization chain, error checks, and provenance. Export recovered media only when the chain supports it. Never label filtered real audio as decoded IQ.

### 9. Harden service operations

Add a persistent job store, worker queue, configurable storage, authentication, audit logs, observability, cancellation, quotas, safe file inspection, and restart recovery before remote or multi-user deployment.

### 10. Refactor the frontend as features grow

Split `App.tsx` into dedicated feature components/hooks, consolidate alerts, add schema-generated API types, and add targeted browser tests for upload/polling/recovery. Keep plots tied to backend units and provenance.

## Completion criteria for future work

A roadmap item should move to **complete** only when:

1. implementation exists in the active execution path;
2. outputs are visible or accessible through a documented API;
3. relevant negative and boundary cases are tested;
4. units, assumptions, and failure states are documented;
5. measured evidence supports its claim;
6. the dashboard labels uncertainty honestly.
