# Project Completion Status

This is the requirement-by-requirement ledger for the original SIH26147 Phase 1 prompt, audited against the current repository. “Complete” means complete for the stated Phase 1 requirement, not production readiness or field validation.

## Executive status

| Scope | Status | Evidence and qualification |
|---|---|---|
| Hard constraints | Complete | Real API data, qualified stage claims, explicit ambiguous-input handling, Tier 2 roadmap placeholders. |
| Tier 0 backend | Complete | All six required capabilities are implemented and tested. |
| Tier 1 backend | Partial | Confidence/review is built; statistical non-Gaussianity and coarse-to-fine scanning are not built. |
| Downstream IQ analysis | Integrated; DSP validated for BPSK/QPSK | Estimate, coarse envelope family, carrier refinement, fine PSK classification (bpsk/qpsk), and gated symbol-rate estimation run in synchronous uploads and demos, JSON export and dashboard detail. Fine labels publish on 5/5 seeds at 20/10 dB for both BPSK and QPSK; symbol rate is estimated 30/30 within 5% of truth when SNR ≥4.5 dB and a PSK label is confirmed, else explicitly null. Only BPSK/QPSK are supported; async large uploads remain Detect-only. |
| Tier 2 | Correctly excluded | All six prohibited features remain nonfunctional roadmap items. |
| Synthetic data | Complete | BPSK, QPSK, FM at four SNRs, pulses, noise, mixed demo, separate truth files. |
| FastAPI layer | Complete | All three required endpoints exist; supporting job, audio, export, demo, envelope, and health endpoints were added. |
| Dashboard | Complete for specified Detect UI and synchronous detail integration | Required panels, interactions, real-data states, animation, breakdown layers and Estimate/coarse/refinement detail rows exist. |
| Deliverable structure | Complete | `backend/`, `frontend/`, tests, bundled demo files, and run documentation exist. |
| Large-file extension | Complete to stated limit | Up to 2 GiB accepted; a real 1 GiB upload was scanned and measured. |
| Production deployment | Not delivered | The project runs locally. No production hosting, authentication, durable queue, or persistent database exists. |

## Hard constraints

| Original constraint | Status | Implementation |
|---|---|---|
| Build Tier 0 first; Tier 1 only after; do not implement Tier 2 | Complete | Tier 0 is implemented. One Tier 1 item is implemented. Tier 2 is displayed under “Beyond Detect” as planned and has no detector code. |
| Every displayed result must come from the actual file through the API | Complete | The dashboard starts a real `/api/demo` request and uses `/api/analyze`, `/api/spectrogram`, layer, envelope, and audio endpoints. It has explicit disconnected, pending, error, and empty states. |
| Do not imply demodulation or decoding | Complete | The breakdown contains the exact Phase 3 note. IQ layers have no audio URL. WAV audio is labeled as filtered/gated original audio. |
| Ask rather than guess missing sample metadata | Complete in the product flow | Raw IQ without sample rate/datatype receives an input-required error. Ambiguous stereo WAV requires a user choice. Conflicting metadata is rejected. |
| Build generator → pipeline/tests → API → frontend | Complete as delivered | All four layers exist and the frontend contract matches actual API responses. Git history records the backend stages followed by synchronous API/detail integration. |

## Backend contract

| Requirement | Status | Notes |
|---|---|---|
| Complex64 IQ plus sample rate input | Complete | Internal representation is `complex64`; integer and float formats are converted explicitly. |
| Optional SigMF metadata | Complete | Metadata is parsed and validated with the SigMF library. |
| WAV IQ-pair versus real-audio disambiguation | Complete with documented heuristic limit | Correlation, Hilbert quadrature correlation, and power balance are checked. Ambiguous stereo needs user input. |
| SigMF-like detection objects | Complete | Required fields are present, with additional `id`, `pulse_windows`, and `threshold_excess_db`. |
| Exclusive `end_sample` convention | Complete | Detection and SigMF export use end-exclusive sample intervals. |

## Tier 0 requirements

| Item | Status | Current behavior |
|---|---|---|
| Welch noise-floor estimate using median/low percentile | Complete | Hann, 1,024 samples, 50% overlap; median across PSD frequency bins. Large files estimate per block and report the median/range. |
| Adaptive CFAR-style threshold | Complete | Noise floor plus tunable 3–30 dB margin, default 8 dB. This is CFAR-style energy detection, not a statistically calibrated CFAR false-alarm design. |
| STFT/spectrogram time-frequency scan | Complete | Hann 1,024-point spectrogram, 75% overlap, 256-sample hop. |
| Pulse/burst envelope detection | Complete | Band isolation, smoothed power envelope, pulse windows, median width, and median PRI. One pulse correctly returns null PRI. |
| Fixed-threshold debug detector | Complete | `fixed_debug` requires an explicit finite PSD threshold and is never the default. |
| WAV disambiguation | Complete | Mono is real audio. Strong quadrature evidence can select IQ. Other stereo is rejected until explicitly interpreted. |

## Tier 1 requirements

| Item | Status | Reason/current state |
|---|---|---|
| Statistical “not noise” test such as kurtosis | Not built | No independent kurtosis or non-Gaussianity score exists. Energy evidence remains the only detection basis. |
| Coarse-to-fine frequency scan | Not built | The current block scan retains full frequency resolution. No profiling-driven need led to a coarse pass. |
| Confidence score and review flag | Complete | Score combines threshold excess and occupancy; `< 0.70` sets `needs_review`. It is explicitly labeled heuristic. |

## Tier 2 and later phases

Tier 2 remains excluded. Later stages now have the following independently qualified status:

| Feature | Status |
|---|---|
| Cyclostationary detection | Intentionally out of scope |
| Deep-learning spectrogram detector | Intentionally out of scope |
| Overlapping co-channel signal separation | Intentionally out of scope |
| Frequency-hopping tracking | Intentionally out of scope |
| Matched filtering | Intentionally out of scope |
| Real-time streaming detection | Intentionally out of scope |
| Estimate stage | Complete for the tested IQ contract and synchronous API/detail integration: center, both bandwidth definitions and full-band SNR; explicit unknown states. Synthetic center/SNR acceptance passes 12/12. No theoretical fixture half-power bandwidth is supplied by the generator. Async integration is not built. |
| Modulation classification | Complete for coarse family plus fine BPSK/QPSK — coarse family correct on all nine >=0 dB continuous fixtures. Refinement validated separately with mean absolute error 0.0627 Hz (down from 0.4041 Hz after matching periodogram resolution to segment length). Fine phase-cluster rule now passes 5/5 seeds at each of 20/10 dB for both BPSK and QPSK (previously QPSK passed only 2/5); pulsed candidates are explicitly excluded. Limited to BPSK/QPSK; no calibrated probability. |
| Symbol rate | Implemented and gated — estimated only with a confirmed BPSK/QPSK fine label and measured SNR ≥4.5 dB; validated 30/30 within 5% of the generator's 500 Hz truth across bpsk/qpsk × {20,10,5} dB × five seeds. Explicit null with reason below the gate; accuracy below 4.5 dB SNR is unverified. |
| FM/AM/PSK demodulation | Planned, not built |
| Decoded audio/data output | Planned, not built |
| Report stage | Planned, not built |

## Synthetic generator and validation data

| Requirement | Status | Detail |
|---|---|---|
| BPSK at 20, 10, 0, −5 dB | Complete | Four deterministic complex SigMF captures plus truth. |
| QPSK at 20, 10, 0, −5 dB | Complete | Four deterministic complex SigMF captures plus truth. |
| FM at 20, 10, 0, −5 dB | Complete | Four deterministic complex SigMF captures plus truth. |
| Pulsed signal with known PRI/width | Complete | 2,400-sample width, 12,000-sample PRI at 48 kHz. |
| Pure-noise file | Complete | Used for false-alarm checks. |
| Bundled default demo | Complete | Mixed BPSK/FM/pulse SigMF recording; dashboard runs it through the real API. |
| Audible WAV pack | Added beyond original minimum | Five validated mono PCM16 files: steady tone, two tones, pulse train, one burst, and noise. |

## API layer

| Original endpoint | Status | Detail |
|---|---|---|
| `POST /api/analyze` | Complete | Direct 200 response for files up to 1 MiB; asynchronous 202 job flow for larger files. |
| `GET /api/spectrogram/{job_id}` | Complete | Returns viewport-bounded measured power with explicit time/frequency edges. |
| `GET /api/detections/{job_id}/{detection_id}/layers` | Complete | Returns the specified ordered, applicability-aware Detect layers. |
| Real pipeline log | Complete | Logs measured file size, noise floor, STFT resolution, thresholds, candidates, pulse count, runtime, and no-decoding statement. |

Supporting endpoints provide job polling, health, demos, audio clips, pulse envelopes, and JSON/SigMF export. See [API reference](API_REFERENCE.md).

## Frontend requirements

| Area | Status | Detail |
|---|---|---|
| React + TypeScript + Vite | Complete | React 19, strict TypeScript, Vite 7. |
| Tailwind CSS | Complete | Tailwind 4 through Vite. |
| SCIFICN/UI via shadcn | Complete | Panel, badge, and alert source installed; panel/badge used in the app, alert retained but current error banners are app CSS. |
| Motion | Complete | Boot, scan line, numeric tweening, drawer/layer transitions, alert pulsing; reduced-motion behavior included. |
| WaveSurfer v7 + Regions/Timeline/Spectrogram | Complete for applicable WAV layers | Used for actual backend-produced real-audio clips. IQ intentionally produces no audio player. |
| Recharts | Complete | PSD, generic waveforms, and pulse envelope. |
| Canvas waterfall | Complete | Static precomputed array, Inferno color map, maximum-power pooling, region overlays. |
| React Query, no Redux | Complete | Queries and mutations are managed through TanStack React Query and component state. |
| Mission-control layout | Complete | Input/metadata/architecture left; waterfall center; analysis and contacts below; breakdown and export after selection. Responsive layouts exist. |
| All eight requested display features | Complete | Ingestion, waterfall, PSD, contacts, pulse detail, log, architecture, JSON export. SigMF export was also added. |
| All requested animation behaviors | Complete | Includes conditional scan line and review pulse. |
| Signal Breakdown exact scope note | Complete | Exact supplied sentence appears in the UI. |
| Inapplicable layers disabled rather than hidden | Complete | Envelope-gated/audio pulse layers and IQ envelope applicability are represented explicitly. |

## Verification evidence currently stored

- Synchronous integration verification on 2026-09-11: 120 backend tests passed with the same two strict expected failures. New HTTP tests compare all 21 downstream fields across all 12 continuous fixtures to the pre-integration measured JSON, preserve nulls in export, cover IQ/audio demos, pulsed SigMF absolute frequency, and exercise a real two-block 5,376,000-byte async upload. The async result deliberately has no downstream stage fields.
- Live dashboard IQ demo: all three candidates show measured fields, inline FM caveat and explicit fine/symbol null states. Six frontend adapter/detail-render tests cover signed/zero values, refined RF precision, missing fields and real-audio reasons. See [integration verification](INTEGRATION_VALIDATION.md) for build evidence and the measured latency increase.

- Downstream verification after the refinement-resolution and symbol-rate fixes: all 133 backend tests pass, including the previously-strict-expected-failure QPSK fine-classification majority checks, which now pass rather than being retained as documented failures. See [downstream methods and measurements](ESTIMATE_CLASSIFY.md) and [reproducible measured JSON](estimate-classify-validation.json).
- All 12 BPSK/QPSK/FM continuous fixtures were re-run after the approved centroid and band-isolation changes: worst center error 0.2375% against the unchanged 2% target; worst SNR error 0.084 dB against the 3 dB target. Coarse family correct for all nine fixtures at >=0 dB. Bandwidth helper tested against analytical Gaussian half-power width; the generator's nominal detection bands are not theoretical half-power truth.
- The separate Mth-power/log-parabolic path was re-tested after the centroid change and again after matching its periodogram resolution to segment length: ten 150 kHz-offset BPSK fixtures at 10 dB, seeds 47–56, 1 MHz sample rate. Mean absolute error 5.6533 Hz for the direct centroid (unchanged), 0.4041 Hz for the raised-tone peak under the old fixed 1,024-point Welch average, and 0.0627 Hz after the resolution fix.
- Fine phase-cluster rule (circular spread <0.8 rad): BPSK and QPSK both now pass 5/5 at 20 dB and 5/5 at 10 dB (20/20 trials), where QPSK previously passed only 2/5 — the residual-frequency accumulation that caused the QPSK failures was the refinement resolution mismatch above. Published `fine_modulation_label`/`fine_modulation_confidence` are non-null whenever the rule is met; pulsed candidates are explicitly excluded. Symbol rate is implemented and gated to a confirmed PSK label plus ≥4.5 dB SNR: validated 30/30 within 5% of truth across bpsk/qpsk × {20,10,5} dB × five seeds, with explicit null-and-reason behavior tested at 20/10/5/0/-5 dB.
- Fresh documentation-audit verification on 2026-09-10: 42 backend tests passed in 26.90 seconds; the only output was two upstream Starlette/AnyIO deprecation warnings.
- Fresh frontend verification on 2026-09-10: TypeScript and the Vite production build completed successfully; Vite reported a non-failing JavaScript chunk-size advisory for the 905.77 kB main bundle.
- Fresh synthetic validation on 2026-09-10: the report regenerated successfully with continuous-fixture recall 12/12.
- Synthetic continuous recall artifact: 12/12 target-containing fixtures detected.
- Synthetic pulsed artifact: measured width 2,374 versus truth 2,400; measured PRI 12,000 versus truth 12,000.
- Noise artifact: zero candidates for the recorded pure-noise fixture.
- Fresh 1 GiB artifact on 2026-09-10: 134,217,728 complex samples scanned; three planted bursts found; measured analysis time 67.953 seconds; wall time 80.341 seconds; peak backend working set 263.898 MiB on that run.
- WAV artifact: recorded candidate counts `[1, 2, 1, 1, 0]` across the five supplied files.

These measurements describe deterministic synthetic fixtures on one environment. They do not establish receiver operating characteristics, field recall, calibrated confidence, or a guaranteed false-alarm rate.

## Dashboard interactivity

Scope record: [DASHBOARD_INTERACTIVITY.md](DASHBOARD_INTERACTIVITY.md). Core
checklist, tracked as it ships:

- [x] Click-to-inspect readout on the spectrogram (live freq/power/time at cursor)
- [ ] Zoom/pan controls on the spectrogram
- [ ] Detection rows clickable → jump spectrogram viewport to that detection
- [ ] Sortable/filterable detection table (confidence, frequency, needs_review)
- [x] Confidence-threshold slider live-filtering the detection list + spectrogram
- [x] Adjustable CFAR margin control with live re-run
- [ ] Interactive accuracy-vs-SNR curve (hover for trial counts)
- [ ] Symbol-rate panel: reveal the FFT plot with the chosen harmonic marked
- [ ] Modulation panel: reveal cumulant features + decision-tree path
- [ ] "Explain this number" affordance on every estimated value
- [ ] Signal Breakdown: adjustable auto-play speed
- [ ] Signal Breakdown: per-layer download (waveform image + audio clip)
- [ ] Synced playhead — audio scrub position mirrored on the spectrogram
- [ ] SigMF export preview panel + copy-to-clipboard before download
- [ ] Session history panel — reload previously analyzed files
- [ ] Per-detection analyst notes field
- [ ] Distinct styling for "not reliably estimated" states
- [ ] Keyboard shortcuts + discoverable shortcuts overlay

## Remaining work by priority

1. Collect representative real RF captures with trustworthy annotations and define field metrics before tuning detector thresholds.
2. Add the optional Tier 1 independent statistical “not noise” test if it improves validated precision/recall.
3. Profile realistic long captures before deciding whether coarse-to-fine scanning is useful.
4. Add durable jobs, authentication, multi-worker coordination, configurable retention, and deployment hardening if moving beyond a local demonstration.
5. Fine PSK classification and gated symbol-rate estimation are implemented and validated for BPSK/QPSK; extend beyond those two constellations (8PSK, QAM, …), add real-capture and held-out evidence, and validate aggregation before adding downstream estimates to merged large-capture tracks. Report, demodulation and decoding remain separate unimplemented phases.
