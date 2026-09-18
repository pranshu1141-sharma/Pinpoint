# SIH26147 — PinPoint

An offline RF capture detector and dashboard for the Smart India Hackathon NTRO software track. It locates candidate time/frequency regions, measures pulse timing, and exposes inspectable isolation layers. **Synchronous uploads (≤1 MiB), demos, and now async large uploads (per-track, bounded to 2,000,000 samples) all include Estimate, coarse envelope classification, Mth-power carrier refinement, fine PSK classification (BPSK/QPSK) and symbol-rate estimation in the API, detail table and JSON export.** Fine labels and symbol rate are gated to their validated SNR ranges — see [Estimate and Classify](docs/ESTIMATE_CLASSIFY.md) for exact conditions; no demodulation or decoding exists. See [integration verification](docs/INTEGRATION_VALIDATION.md).

## Complete project documentation

The structured documentation starts at [`docs/README.md`](docs/README.md). It includes requirement-by-requirement completion status, architecture, every authored file and artifact family, detector formulas, input rules, the full API contract, dashboard behavior, Signal Breakdown provenance, 1 GiB processing evidence, tests, operations, limitations, roadmap, judge-defense answers, and a glossary.

For a fast audit, read [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), and [`docs/LIMITATIONS_AND_ROADMAP.md`](docs/LIMITATIONS_AND_ROADMAP.md). The documentation distinguishes **complete**, **partial**, **planned**, and **not built** behavior and treats source/tests/measured artifacts as the authority when implementation changes.

## Run locally

Requirements: Python 3.11–3.13, Node.js 20.19+ or 22.12+, and npm. Tested here with Python 3.13 and Node 24. Install dependencies once, then run the two servers in separate terminals from the project root.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
```

Terminal 1:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
npm --prefix frontend run dev
```

Open [the dashboard](http://127.0.0.1:5173/) and [the interactive API contract](http://127.0.0.1:8000/docs). On macOS/Linux use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`. The Vite server proxies `/api` to FastAPI. `npm --prefix frontend run build` checks TypeScript and creates the frontend production bundle; it does not bundle the Python server. This is a local full-stack deliverable, not a standalone hosted frontend.

The dashboard automatically analyzes the bundled `backend/data/demo/demo.sigmf-data` with its metadata. Nothing is generated in the frontend. The **IQ demo** and **Audio demo** buttons each submit a real bundled file to the same analysis pipeline used for uploads. Fonts are bundled for offline use after installation. If FastAPI is unavailable the dashboard shows **Not connected** and hides computed result panels.

## Generate and verify

```powershell
.\.venv\Scripts\python.exe -m backend.pipeline.synth_gen
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m backend.validate
npm --prefix frontend run build
```

The generator writes continuous BPSK, QPSK, and FM at 20, 10, 0, and −5 dB SNR, an eight-pulse capture, pure noise, a mixed demo, and an audio WAV under `backend/data/generated/`. Ground truth is stored in separate `.truth.json` files. The detector never reads ground truth. SNR is total signal power divided by full-band complex noise power; pulsed SNR is measured during the pulse. This differs from narrowband receiver SNR.

The included suite checks detection recall and frequency/time bounds for all 12 continuous fixtures; pulse width, PRI and pulse count; ten independent noise seeds; a 40 dB input-amplitude power shift; agreement with the fixed-threshold debug detector; 20–300 ms isolated bursts with no invented PRI; continuous signals not mislabeled as pulses; malformed input; WAV ambiguity; real upload/API/clip contracts; bounded spectrogram dimensions; and validated SigMF export. See `backend/validation-report.json` for measurements from an actual pipeline run. These are synthetic checks, not field-performance claims or proof of a specified probability of false alarm.

## Inputs and error policy

| Input | Required information | Handling |
|---|---|---|
| `.iq` / `.IQ` | Explicit sample rate and datatype, or matching SigMF metadata | Supported complex formats: `cf32_le`, `cf32_be`, `ci16_le`, `ci16_be`. No guessed rate, endianness, or numeric representation. |
| `.sigmf-data` | The matching `.sigmf-meta`, selected together | Validated with the `sigmf` package. Also supports real `rf32_le` / `ri16_le`. Retuned, multi-channel, offset/header-bearing, and unsupported datatype recordings are rejected. |
| Mono `.wav` | Header sample rate | Real-audio analysis with a one-sided PSD; a missing Q channel is never invented. |
| Two-channel `.wav` | Quadrature check; explicit interpretation if ambiguous | Uses channel correlation, Hilbert quadrature correlation, and power balance. Strong evidence selects I=left/Q=right, with the heuristic recorded in metadata. Otherwise the UI asks the user to confirm IQ or select one real-audio channel. |

A quadrature relationship is **evidence, not proof of provenance**. Wideband/random IQ can be inconclusive, and intentionally quadrature stereo audio can pass the check. The user may override using known recording metadata. PCM WAV values are normalized; float WAV values retain their scale. NaN/Inf, incomplete samples, invalid rates, conflicting metadata, malformed files, and captures shorter than 1,024 samples are rejected with descriptive 422 responses.

Per capture: maximum **2 GiB (2,147,483,648 bytes)**, including 1 GB and 1 GiB captures. Metadata: maximum 1 MiB. Uploads are copied to temporary disk storage in bounded pieces. Files above 1 MiB use a background job, disk-backed sample reads, and 524,288-sample processing blocks with 4,096 samples of context on each side. Every sample is validated and every block is analyzed; neither the old two-million-sample cap nor silent truncation applies to this path. The existing in-memory loader retains its two-million-sample guard for internal bounded uses. Large packed 24-bit WAV files must be converted to 32-bit WAV because SciPy cannot memory-map that encoding.

The UI displays actual upload-byte progress followed by completed-sample progress, polls the job to completion, and can resume polling after a page refresh in the same tab. It does not keep a single HTTP analysis request open for the whole scan. The API retains the newest three finished jobs, expiring 30 minutes after completion, and allows one analysis at a time (429 if busy). Uploaded copies are removed on failure, expiry or eviction; restarting the server clears the in-memory job registry. Temporary copies left by an interrupted server can be removed from `backend/data/jobs/` when the server is stopped. Allow disk space for both the multipart spool and retained upload (temporarily roughly twice the upload size). Run one Uvicorn worker on loopback; this is a local app without authentication or durable job recovery.

Large-capture detections use full-resolution STFTs within each block. The overview is pooled to at most 768 time rows while scanning, so retained plot memory does not grow with the recording duration. Neighboring-block candidates merge when their frequency overlap is at least half the narrower band; pulse windows crossing a boundary are joined. Confidence conservatively keeps the weakest constituent block. There is no frequency-hopping tracking or co-channel separation. Noise/threshold lines summarize the block estimates; local thresholds, rather than that summary line, drive each block's detection. Very complex captures exceeding 4,096 candidates or 200,000 pulse windows fail explicitly and should be split for review.

Signal Breakdown on large captures reads a bounded window around the candidate onset (up to eight seconds or one million samples), with the exact preview interval shown in every layer description. This preview limit does not limit full-file detection. The envelope plot is a pooled full-capture view; its threshold line summarizes the maximum observed block threshold.

For an opt-in real 1 GiB upload/integration check, run `.\.venv\Scripts\python.exe -m backend.tests.run_gib_check --backend-pid <running-python-process-id>` on Windows while both servers run. It writes a full file in temporary storage, uploads it through Vite/FastAPI, verifies bursts at a block boundary, the middle and the tail, checks final sample coverage and layers, and records peak backend working set in `backend/large-file-validation.json`. The test source file is deleted on exit; its server upload follows normal job retention.

## Detector and units

1. **Welch noise floor:** Hann windows, 1,024 samples, 50% overlap, PSD scaling in sample-unit²/Hz. A frequency median estimates noise without letting a minority of occupied bins dominate the estimate.
2. **Time-frequency scan:** `scipy.signal.spectrogram`, 1,024-point Hann windows and 256-sample hop. IQ is two-sided and FFT-shifted; audio is one-sided. No DC subtraction silently erases a zero-frequency candidate.
3. **Adaptive energy threshold:** frequency-median noise density + tunable margin (8 dB initially). A 3×3 power average and 2×2 morphological opening reduce speckle. Accepted bands need at least three time frames and 12 surviving time-frequency cells. This is **CFAR-style**, not a calibrated constant-false-alarm-rate implementation.
4. **Region association:** adjacent frequency bins are grouped, bridging at most two missing bins. Multiple bursts in a band are represented by one enclosing candidate with individual `pulse_windows`. A candidate box is an extent, not a claim that every pixel inside is occupied. The waterfall draws pulse windows inside a dashed aggregate box.
5. **Pulse timing:** mix each IQ band to baseband and use a 257-tap FIR to isolate it; smooth `|x|²` over 1 ms. Estimate on-pulse power from the strongest 1 ms, compare to measured band noise and the low envelope percentile, then find edges. Pulse width and PRI are medians across measured windows. A single pulse has `pri_samples: null`. Broad width/PRI distributions are not summarized as a classifier.
6. **Confidence:** a bounded, documented heuristic combining threshold excess and occupancy. Scores below 0.70 set `needs_review`. It is not a calibrated probability. Fixed-threshold mode requires an explicit absolute density threshold and is labeled debug everywhere.

Power is **dB re 1 sample-unit²/Hz**, never dBm: no gain, impedance, antenna, or ADC calibration was supplied. Frequency bounds in analysis JSON are **baseband offsets**, even when an RF center is known. Start samples are inclusive and end samples are exclusive. Frequency resolution is `sample_rate / 1024`, hop is `256 / sample_rate` seconds, and energy edges are window-smeared before envelope refinement.

### Practical limits to explain to judges

The median noise assumption works best with roughly stationary noise and fewer than half the frequency bins occupied. Strongly colored/time-varying noise or a nearly full-band signal can bias it. Small captures use one capture-level noise estimate; disk-backed captures estimate noise separately in each overlapping block. Neither path uses local per-cell CFAR reference cells. It cannot guarantee finding every weak, sub-resolution, overlapping, or nonstationary signal. Narrow single-bin features and very short pulses may be removed by the speckle rules. The 257-tap isolation filter and 1 ms envelope smoothing limit pulse-edge precision. Pulse width/PRI describe an aggregate train in a band; independent co-channel emitters are not separated.

Tier 0 is built. Tier 1 confidence/review is built. Statistical non-Gaussianity checks are not built. Coarse-to-fine scanning is not built; the bounded test captures do not justify that optimization. All six Tier 2 features remain visibly labeled **planned, not built**, with no implementation behind them.

## Signal Breakdown

For real audio: raw channel → FIR-isolated band → soft spectral gate using the computed noise density → pulse-window gate when applicable → candidate interval only. Each clip is real processed audio, capped at eight seconds and resampled to 48 kHz for browser playback. A common headroom scale preserves relative loudness across layers. WaveSurfer v7 uses Regions, Timeline, and Spectrogram plugins on those returned WAV clips.

For IQ: baseband magnitude → FIR-isolated/frequency-shifted/polyphase-decimated magnitude → thresholded magnitude → power envelope for pulsed regions. IQ is not natively audio, so these layers deliberately have no audio clip. The thresholded layer is all zero if the candidate needs review, and otherwise zero outside its sample interval. No FM/AM/PSK demodulator exists. Inapplicable layers remain disabled and labeled. The exact Phase 3 demodulation note is visible above the layer stepper.

Waveforms are peak-pooled previews of the actual layer arrays. The waterfall is maximum-power-pooled to a bounded viewport with explicit frequency/time cell edges; it is not a live radio stream. PSD and pulse plots use Recharts. The console replays actual completed backend logs and labels that replay honestly. Motion animates loading/selection and real-valued readouts. Reduced-motion preferences disable CSS motion and numeric tweening.

## API

| Endpoint | Result |
|---|---|
| `POST /api/analyze` | Multipart `file`, optional `metadata`, `sample_rate`, `datatype`, `wav_mode`, `margin_db`, `mode`, `fixed_threshold_db`. Small files return the analysis JSON with HTTP 200. Files above 1 MiB return HTTP 202 with `job_id`, `status`, and `status_url`. |
| `GET /api/jobs/{job_id}` | Queued/processing/completed/failed state, real processed/total sample counts, progress and message. Completed jobs include the full analysis as `result`; failures include `error` and never publish partial results. |
| `POST /api/demo?kind=iq` or `kind=audio` | Runs the bundled capture through actual ingest and Detect. |
| `GET /api/spectrogram/{job_id}?width=640&height=380` | Bounded `magnitude_db[time][frequency]`, cell edges, measured color limits, units, aggregation method. |
| `GET /api/detections/{job_id}/{detection_id}/layers` | Ordered layer array: descriptions, waveform previews, applicability, and audio URLs where meaningful. |
| `GET /api/detections/{job_id}/{detection_id}/envelope` | Measured power envelope, threshold, pulse windows and timing. |
| `GET /api/detections/{job_id}/{detection_id}/audio/{layer_id}` | A real processed WAV, or 404 when audio does not apply. |
| `GET /api/export/{job_id}?format=json` | Detection objects. |
| `GET /api/export/{job_id}?format=sigmf` | Metadata validated with `SigMFFile`, using `core:sample_count` and standard annotation keys. |
| `GET /api/health` | Actual API connection status. |

The required detection fields are retained with additional `id`, `pulse_windows`, and `threshold_excess_db`. SigMF export converts baseband bounds to absolute frequency if a center exists; otherwise the reference is zero. Confidence/review/method are serialized in `core:comment`, avoiding an unregistered extension. For WAV imports the exported datatype describes the normalized internal sample representation, so do not attach this metadata to the original WAV or unconverted PCM bytes.

## Panel-to-problem-statement mapping

| Dashboard panel | SIH26147 Detect requirement it demonstrates |
|---|---|
| Capture input and metadata | Ingest raw IQ/WAV; validate sample rate, numeric format, and IQ versus real-audio interpretation. |
| Time–frequency waterfall | Find where signals exist in frequency **and** time; show candidate boundaries and burst windows. |
| Averaged PSD with noise/threshold | Explain why adaptive energy detection changes with the actual capture noise floor. |
| Contact list and review flags | Produce structured candidates with explicit uncertainty, rather than inventing signal identities. |
| Pulse timing | Recover the explicitly requested pulse width and pulse repetition interval in samples. |
| Signal Breakdown | Demonstrate real Detect-stage band isolation and time gating, with inspectable transformations. |
| Pipeline Log | Show the exact processing steps and measured values used to generate the visible evidence. |
| JSON/SigMF export | Make sample/frequency annotations reusable for subsequent analysis. |
| Four-stage architecture and roadmap | Distinguish the implemented Detect stage from planned Estimate, Classify, Report and Tier 2 work. |

## Structure and reference acknowledgments

`backend/pipeline/`: generator, ingest, SigMF, detection, isolation layers. `backend/api/`: FastAPI and bounded session cache. `backend/tests/`: synthetic and real API tests. `frontend/src/`: React/TypeScript interface with React Query, Motion, canvas, Recharts and WaveSurfer. SCIFICN panel/badge/alert source was installed through the shadcn registry; the shared theme was adapted to cyan-on-black and locally bundled fonts.

Studied references: [IQEngine](https://github.com/IQEngine/IQEngine) for the frequency/time workspace and linked annotations; [NASA Eyes](https://science.nasa.gov/eyes/) for data-led motion; [SCIFICN/UI](https://github.com/baxy5/scificn-ui) for panel composition and terminal typography. Method/API references: [SciPy spectrogram](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.spectrogram.html), [SigMF](https://sigmf.readthedocs.io/en/latest/), [WaveSurfer v7](https://wavesurfer.xyz/docs/). No reference screenshots or fabricated RF data are embedded in the frontend.
