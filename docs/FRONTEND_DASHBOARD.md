# Frontend dashboard

The frontend is an operator-facing React dashboard for submitting a capture and inspecting Phase 1 detection evidence. It displays backend results; it does not synthesize detections or decode signal content in the browser.

## Runtime and libraries

- React 19 with TypeScript strict mode
- Vite 7 development/build tooling
- Tailwind CSS 4
- TanStack React Query for server state
- Recharts for the PSD plot
- WaveSurfer 7 with Regions, Timeline, and Spectrogram plugins for audio review
- Motion for transitions
- Lucide icons
- locally installed IBM Plex Mono and Inter font packages

`frontend/package.json` declares direct dependency ranges. `frontend/package-lock.json` is the authoritative resolved dependency graph.

## Page structure

The page is organized as an investigation workspace:

1. **Header and stage identity** — names SIH26147 and keeps the active scope visibly on Detect.
2. **Connection and upload state** — shows backend health, errors, upload bytes, and processing progress.
3. **Capture input** — accepts a capture plus optional SigMF metadata, raw IQ settings, WAV interpretation, threshold margin, and debug threshold controls.
4. **Pipeline architecture** — explains the implemented flow from ingestion through candidate output.
5. **Capture readouts** — shows sample rate, duration, sample count, source interpretation, noise floor, threshold, and elapsed time.
6. **Waterfall** — renders the server spectrogram and candidate geometry.
7. **PSD and pipeline log** — exposes measured spectrum, units, settings, and textual processing evidence.
8. **Candidate contact list** — summarizes each candidate and lets the operator choose one.
9. **Signal Breakdown** — loads on-demand inspection layers, envelope measurements, and applicable audio.
10. **Export** — downloads candidate JSON or SigMF annotations.
11. **Beyond Detect** — labels later capabilities as planned rather than presenting mock output as working analysis.

## Startup and demo behavior

The frontend checks `/api/health` every 15 seconds. Once the backend becomes reachable, it automatically submits the bundled IQ demo unless the current browser tab already has an active job ID in `sessionStorage`.

If a stored large-capture job exists, the page resumes polling it after refresh. Polling occurs approximately every 1.5 seconds and stops on completion or failure. A backend restart invalidates the stored ID; the UI then reports the missing job and lets the operator submit again.

The **IQ demo** and **Audio demo** controls invoke `/api/demo`; both run actual bundled files through the production pipeline. No result is hard-coded in React.

## Upload flow

The file picker enforces the user-facing selection model:

- one `.iq`, `.sigmf-data`, or `.wav` capture;
- no more than one `.sigmf-meta` companion;
- matching stems for a SigMF pair.

Raw IQ fields appear when needed. Two-channel WAV interpretation can be set explicitly. If automatic WAV analysis returns `input_required`, the error state preserves the file context and prompts for an explicit choice.

An `XMLHttpRequest` reports actual uploaded bytes. A completed small result is displayed immediately. A 202 response switches the UI to completed-sample progress from the job endpoint. The progress bar therefore has two honest phases: network transfer followed by DSP scanning.

Only one analysis can run in the backend, so a 429 response is shown as a busy state instead of silently queueing unlimited work.

## Waterfall behavior

`Waterfall.tsx` paints an Inferno-style color map on a canvas from `magnitude_db`. It uses the returned time and frequency edge arrays, so axes reflect actual server bins rather than guessed dimensions.

Interaction includes:

- hit testing candidates on pointer input;
- selected-candidate highlighting;
- individual solid pulse-window boxes for pulsed candidates;
- a dashed aggregate candidate extent;
- a scan animation while processing;
- data-derived color limits from the backend response.

Maximum-power viewport pooling keeps a brief event visible when many STFT cells map to one screen pixel. The display is an overview; detection already ran against the full analysis grid.

## PSD and candidate evidence

`PSDChart.tsx` plots the Welch PSD values returned by the backend. The noise and threshold lines use the same uncalibrated density unit as the series. For large captures, these lines summarize block estimates; local block thresholds drive detection.

The candidate list exposes:

- baseband frequency range;
- sample/time extent;
- confidence;
- review flag;
- threshold excess;
- pulsed/continuous status;
- pulse width and PRI when measured.

Confidence is labeled as heuristic evidence. A review badge appears below 0.70. The UI does not translate this score into a probability or modulation class.

## Signal Breakdown behavior

Selecting a candidate requests its layers. The panel automatically steps through non-audio visual layers every 3.2 seconds to make the transformation understandable. Audio playback stays under manual operator control.

For real-audio candidates, WaveSurfer displays and plays applicable server-generated WAV clips. Regions mark the candidate or pulse intervals, Timeline supplies time context, and Spectrogram supplies a layer-local spectral view. All comparable clips share one gain so that processing changes are not hidden by per-layer normalization.

For IQ, the panel shows baseband magnitude and isolated/thresholded representations without an audio player. Complex RF samples are not meaningful audio until a demodulation choice is made, and demodulation is outside Detect.

Large-capture layers are bounded previews around the selected onset. Each layer description includes its exact preview interval. This limit affects breakdown display only; it does not limit full-file detection.

See [SIGNAL_BREAKDOWN.md](SIGNAL_BREAKDOWN.md) for every layer and its provenance.

## State ownership

TanStack React Query owns remote health and job data. Component state owns file selection, detector controls, selected candidate, current layer, and local playback state. `sessionStorage` stores only the active job identifier needed for same-tab recovery.

There is no Redux store and no durable browser-side result database. The backend remains the source of truth.

## Error and empty states

The dashboard distinguishes:

- backend disconnected;
- invalid or ambiguous input;
- upload too large;
- compute slot busy;
- background analysis failed;
- job expired after a refresh;
- no candidates detected;
- candidate layer without audio.

Computed panels remain hidden when there is no valid backend result. An empty candidate result is a successful analysis, not a failed request.

## Responsive and accessibility behavior

The layout collapses from multi-column investigation panels to a vertical flow on narrow screens. Buttons and selectors use native focus behavior, controls carry visible labels, semantic headings structure the page, and motion styles honor reduced-motion preferences in CSS.

Canvas content has adjacent textual candidate evidence; the waterfall is not the only way to read a result. Audio controls are manual and no sound autoplays.

## Current maintainability notes

`frontend/src/App.tsx` currently contains most orchestration and is the largest authored frontend file. It is functional, but future feature growth should extract upload/job management, detector controls, result summary, and candidate selection into dedicated components or hooks.

The installed SCIFICN `Alert` component is currently unused because the app renders its own connection/error banners. It can be removed or adopted during a UI cleanup. These are maintainability items, not blockers for the current Detect workflow.
