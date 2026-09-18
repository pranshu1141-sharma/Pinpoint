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

Downstream IQ Estimate, coarse envelope classification, Mth-power carrier refinement, fine PSK classification, and gated symbol-rate estimation now run in synchronous uploads (≤1 MiB) and demos, with detail-table display and JSON export. **Async large uploads are no longer Detect-only:** each finished track gets a bounded direct re-read of its own span (≤2,000,000 samples) from disk and the same downstream pipeline, with a noise floor computed from that track's own re-read samples rather than a global block-median. A track whose span exceeds that bound gets an explicit unresolved status on every downstream field instead of a partial result. One residual, undocumented-as-solved risk: a track's frequency bounds are a union across blocks, so a drifting or hopping signal could get a wider analysis band than any single instant occupied, which can bias SNR/bandwidth quality (not correctness — existing bounds validation still guards against invalid bands). **Fine classification now publishes `bpsk`/`qpsk` labels and confidence when the phase-cluster spread clears its threshold, and symbol-rate estimation is implemented and gated to a confirmed PSK label plus ≥4.5 dB SNR** — both validated only on synthetic fixtures, and both still limited to BPSK/QPSK (no 8PSK, QAM, or other constellations). There is no demodulator, symbol recovery, decoder, content extractor, or report-generation workflow.

### Downstream validation boundary

The approved noise-subtracted centroid replaces the direct PSD peak only in Stage 1. Stage 3 retains its own raised-tone peak plus three-bin log-parabolic interpolation, now estimated from a full-segment-length periodogram (capped at 2^20 samples) instead of a fixed 1,024-point Welch average, so resolution scales with segment length. All 12 continuous fixtures pass the unchanged 2% frequency and 3 dB SNR targets; all nine >=0 dB fixtures pass coarse family classification after the existing band-isolation helper. Ten 150 kHz BPSK fixtures at 10 dB have refined mean absolute frequency error 0.0627 Hz, improved from the previously reported 0.4041 Hz by the resolution fix (direct-centroid MAE is unchanged at 5.6533 Hz). These are synthetic checks, not field-performance guarantees. Per-fixture numbers and usage are in [Estimate and Classify](ESTIMATE_CLASSIFY.md).

The fine phase-spread rule (circular spread <0.8 rad) now succeeds 5/5 on both BPSK and QPSK seeds at each of 20 and 10 dB, where QPSK previously succeeded only 2/5 — the root cause was the refinement resolution mismatch above, which for QPSK's M=4 raising accumulated residual frequency error into excess phase spread. Pulsed/gated-carrier candidates are explicitly excluded from fine classification (an unmodulated gated carrier would otherwise look like trivially perfect BPSK). FM candidates still correctly never resolve a label; their measured spread stays around 1.4 rad regardless of SNR. Symbol rate is now implemented: gated to a confirmed BPSK/QPSK fine label and measured SNR ≥4.5 dB, it is validated 30/30 within 5% of the generator's 500 Hz truth across bpsk/qpsk × {20,10,5} dB × five seeds; below the gate it stays null with an explicit reason. `fine_modulation_confidence` remains an explicit heuristic, not a calibrated probability, and only BPSK/QPSK are supported — no 8PSK, QAM, or other constellation order.

These functions support in-memory complex IQ only. Real audio returns explicit unknown fields; no Q channel is invented. Every pulse must contain at least 1,024 samples for Estimate. Classification needs 1,024 samples after trimming 128 FIR edge samples at each end. One short pulse makes the aggregate Estimate unknown rather than silently excluding that pulse. Overlapping pulse windows form a union; separate pulse PSDs are equally weighted, while SNR weights occupied samples by duration.

Bandwidths describe the measured PSD inside the Detect band. Half-power width is the connected lobe around the strongest peak; for FM it can describe one spectral line, not total modulation width. The 99% width integrates whole Welch bins and has one-bin resolution; threshold-truncated candidate bounds can understate full-signal occupied bandwidth. The generator provides nominal detection bands, not theoretical half-power widths; the 15% theoretical-width check is exercised on an analytical spectrum, with no claim of that accuracy on absent fixture truth. The required `unshaped-pulse-sidelobes` caveat is a ratio-triggered heuristic (>5 times the half-power width), not proof of rectangular pulse shaping; it also triggers on these FM spectra.

SNR uses raw occupied-sample power and the existing capture-level median noise density times sample rate. Other simultaneous emitters contaminate that power, and colored noise or wide occupancy can bias the floor. Centroid accuracy depends on candidate bounds and spectral symmetry. Envelope families and refinement sharpness are heuristics, not calibrated probabilities or proof of digital modulation. Mth-power refinement can lock to an FM spectral line; only the BPSK carrier-refinement accuracy is validated. No automatic source separation, phase tracking or synchronization loop is implied.

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

**Started, not complete.** One real, non-synthetic capture (a GNU Radio Conference signal-identification challenge recording) has been run through the full pipeline via three independent routes (direct function calls, the live API, and the dashboard), with results documented in [Real-data triage](REAL_DATA_TRIAGE.md). It found real signals at plausible frequencies, correctly flagged a weaker candidate for review, and correctly declined to publish a fine PSK label it wasn't confident about — but it is one file at one SNR with no severe hardware artifacts present, and surfaced at least one open question (refined-frequency instability across different amounts of the same real signal) that hasn't been investigated. This is not the dataset described below.

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

### 7. Extend Estimate and Classify beyond BPSK/QPSK

Fine PSK classification (bpsk/qpsk) and gated symbol-rate estimation are now implemented and validated against synthetic fixtures — the residual-frequency-accumulation root cause was fixed by matching the Mth-power refinement's periodogram resolution to segment length, and the symbol-rate estimator is validated 30/30 within 5% of truth across bpsk/qpsk × {20,10,5} dB. Both stages are also now reachable on the async large-capture path via per-track bounded re-reads (`backend/pipeline/large_capture.py`'s `enrich_track`), not just synchronous uploads. What remains genuinely open: extend beyond BPSK/QPSK to 8PSK, QAM, or other constellation orders; replace the heuristic `fine_modulation_confidence` with a calibrated probability; validate the symbol-rate estimator's behavior below 4.5 dB SNR instead of reporting it unknown; add held-out and real-capture evidence for both stages before expanding claims beyond synthetic fixtures; and assess whether a track's block-union frequency bounds (as opposed to a single instant's true occupied band) meaningfully bias downstream quality for drifting/hopping signals on the async path.

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
