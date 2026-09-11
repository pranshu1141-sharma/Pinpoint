# HTTP API reference

The FastAPI service listens on `http://127.0.0.1:8000` in the documented local setup. The Vite development server proxies browser requests from `/api` to this service. Interactive OpenAPI documentation is available at `/docs` while the backend is running.

## Conventions

- Small uploads (≤1 MiB) return a completed result synchronously with HTTP 200, including Estimate, coarse envelope classification and frequency refinement for usable IQ candidates.
- Uploads larger than 1 MiB return an asynchronous job with HTTP 202.
- Async merged candidates remain Detect-only: downstream fields are absent. Both bundled demos use the synchronous path regardless of asset size; real audio returns explicit null IQ measurements and reasons.
- A job identifier is an opaque 32-character hexadecimal string.
- Completed jobs expire 30 minutes after completion. The service keeps the newest three finished jobs.
- Only one analysis may compute at a time.
- Candidate IDs are zero-based and valid only within their job.
- Errors use FastAPI's `detail` field. Validation details may be a string or an object with `code` and `message`.

## Health

### `GET /api/health`

Returns backend reachability and upload capacity. The existing `stage: "detect"` identifier is retained for compatibility; it is not a downstream capability inventory.

```json
{
  "status": "connected",
  "stage": "detect",
  "max_upload_bytes": 2147483648
}
```

## Analyze an upload

### `POST /api/analyze`

Content type: `multipart/form-data`.

| Field | Type | Required | Default | Meaning |
|---|---|---:|---:|---|
| `file` | file | yes | — | `.iq`, `.sigmf-data`, or `.wav` capture. |
| `metadata` | file | no | — | Matching `.sigmf-meta`, maximum 1 MiB. |
| `sample_rate` | number | raw `.iq` without metadata | — | Samples per second. |
| `datatype` | string | raw `.iq` without metadata | — | Supported datatype from [INPUT_FORMATS.md](INPUT_FORMATS.md). |
| `wav_mode` | string | no | `auto` | `auto`, `iq`, `audio_left`, or `audio_right`. |
| `margin_db` | number | no | `8` | Adaptive threshold margin from 3 to 30 dB. |
| `mode` | string | no | `adaptive` | `adaptive` or `fixed_debug`. |
| `fixed_threshold_db` | number | fixed mode | — | Finite absolute PSD threshold for debug comparison. |

Small response: HTTP 200 with the analysis result described below.

Large response: HTTP 202.

```json
{
  "job_id": "0123456789abcdef0123456789abcdef",
  "status": "queued",
  "status_url": "/api/jobs/0123456789abcdef0123456789abcdef"
}
```

## Poll a large job

### `GET /api/jobs/{job_id}`

Queued or processing response:

```json
{
  "job_id": "…",
  "status": "processing",
  "processed_samples": 524288,
  "total_samples": 134217728,
  "progress": 0.00390625,
  "message": "Scanning the complete capture in overlapping blocks."
}
```

When `status` is `complete`, the response adds `result`. When `status` is `failed`, it adds `error` and never publishes a partial result.

## Analysis result

The completed result has this top-level shape:

```json
{
  "job_id": "…",
  "expires_in_seconds": 1800,
  "detections": [],
  "noise_floor_db": -53.2,
  "threshold_db": -45.2,
  "pipeline_log": [],
  "metadata": {},
  "elapsed_ms": 84.1,
  "settings": {
    "margin_db": 8,
    "mode": "adaptive",
    "nfft": 1024,
    "hop_samples": 256,
    "review_threshold": 0.7
  },
  "psd": [
    {"frequency_hz": -24000, "power_db": -55.1}
  ]
}
```

Metadata includes filename, sample rate/count, duration, source kind, datatype, optional center frequency, WAV diagnostic, power unit, and frequency reference.

Candidate Detect fields (present on both synchronous and async results):

```json
{
  "id": 0,
  "start_sample": 4800,
  "end_sample": 91200,
  "freq_lower_hz": 12562.5,
  "freq_upper_hz": 15421.875,
  "confidence": 0.9174,
  "detection_method": "adaptive_threshold",
  "is_pulsed": true,
  "pulse_width_samples": 2374,
  "pri_samples": 12000,
  "pulse_windows": [
    {"start_sample": 4813, "end_sample": 7187}
  ],
  "needs_review": false,
  "threshold_excess_db": 13.28
}
```

Numeric examples are illustrative; use the returned values for a particular capture.

### Synchronous candidate additions

Every synchronous candidate also contains the following exact keys. Unknown numeric values are JSON `null`, never zero. These keys are optional for consumers because async and older results omit them. No Pydantic response model filters the returned dictionary.

| Fields | JSON types | Meaning |
|---|---|---|
| `center_frequency_hz` | number or null | Noise-subtracted centroid plus tuning frequency if supplied; otherwise baseband offset. Detect bounds stay baseband. |
| `bandwidth_3db_hz`, `bandwidth_99pct_hz` | number or null | Strongest half-power lobe and shortest 99% in-band power interval. |
| `bandwidth_99pct_caveat` | string or null | `unshaped-pulse-sidelobes` when the width ratio exceeds five; also possible for FM, not proof of shaping. |
| `snr_db` | number or null | Full-band occupied-sample excess power relative to Welch noise density × sample rate. Other simultaneous emitters contribute; this is not isolated per-emitter SNR. |
| `estimate_status` | string | Estimated, partial or explicit unavailable reason, including real-audio input. |
| `modulation_family` | string or null | `constant-envelope` or `varying-envelope`; no fine modulation claim. |
| `modulation_confidence`, `envelope_variation` | number or null | Heuristic distance-from-threshold score and envelope coefficient of variation. |
| `modulation_confidence_kind`, `modulation_status` | string | Explicit heuristic qualification and availability reason. |
| `center_frequency_refined_hz` | number or null | Mth-power raised-tone peak estimate, separate from the direct centroid. Same frequency reference; not guaranteed to improve FM. |
| `refinement_order`, `refinement_sharpness` | number or null | Selected power order (2 or 4) and peak/median ratio. |
| `refinement_status` | string | Refined heuristic or unavailable reason. |
| `fine_modulation_label`, `fine_modulation_confidence` | null | Always null at DSP fallback rung 2. |
| `phase_cluster_spread_rad` | number or null | Diagnostic only; does not enable a fine label. |
| `fine_modulation_status` | string | Explains that fine-classification acceptance was not met. |
| `symbol_rate_hz` | null | Not attempted. |
| `symbol_rate_status` | string | `not reliably estimated (not attempted: fallback rung 2)`. |

Synchronous `elapsed_ms` includes Detect and these downstream stages. Ingest and HTTP serialization are excluded. The unchanged pipeline log reports Detect's own duration. See [measurement conventions](ESTIMATE_CLASSIFY.md) and [verified integration results](INTEGRATION_VALIDATION.md).

## Bundled demos

### `POST /api/demo?kind=iq&margin_db=8`

Analyzes a bundled capture through the same path as an upload. `kind` is `iq` or `audio`. The margin is constrained to 3–30 dB. The endpoint returns a normal completed result.

### `GET /api/demo/files/{filename}`

Returns one of four allowlisted assets:

- `demo.sigmf-data`
- `demo.sigmf-meta`
- `demo.truth.json`
- `audio_demo.wav`

## Spectrogram viewport

### `GET /api/spectrogram/{job_id}?width=600&height=360`

| Parameter | Range | Default |
|---|---:|---:|
| `width` | 32–1024 frequency cells | 600 |
| `height` | 32–768 time cells | 360 |

The response contains maximum-power-pooled cells so brief peaks survive display reduction:

```json
{
  "magnitude_db": [[-51.2, -49.8]],
  "frequency_edges_hz": [-24000, -23953.125, -23906.25],
  "time_edges_seconds": [0, 0.005333, 0.010667],
  "min_db": -58.9,
  "max_db": -20.4,
  "aggregation": "maximum power per viewport cell",
  "unit": "dB re 1 sample-unit²/Hz"
}
```

The matrix is indexed as time rows by frequency columns. Edge arrays have one more entry than the corresponding matrix dimension.

## Candidate breakdown

### `GET /api/detections/{job_id}/{detection_id}/layers`

Returns an ordered layer array. Typical layer fields are:

```json
{
  "id": 1,
  "name": "Isolated Band",
  "description": "…",
  "waveform": [{"time": 0.0, "min": -0.1, "max": 0.12}],
  "sample_rate": 48000,
  "audio_url": "/api/detections/…/audio/1"
}
```

Layer names differ for IQ and audio. Audio URLs exist only where listening is meaningful. At most four candidates' generated layer data is retained per job; older layer entries are regenerated on demand.

### `GET /api/detections/{job_id}/{detection_id}/audio/{layer_id}`

Returns `audio/wav` for an audio-capable layer. IQ layers return HTTP 404 because complex baseband is not silently converted into audible sound. Clips are float32 WAV at 48 kHz, share a common gain for fair comparison, and are capped to a bounded preview.

### `GET /api/detections/{job_id}/{detection_id}/envelope`

Returns a pooled waveform, envelope threshold, threshold description, individual pulse windows, median pulse width, and median PRI. Large-capture threshold text explicitly says it is a maximum block summary.

## Export

### `GET /api/export/{job_id}?format=json`

With `json`, returns the candidate array, preserving every downstream key and null exactly as in that job's response. With `sigmf`, returns validated SigMF metadata containing Detect candidate annotations; downstream measurements are not added to SigMF annotations in this pass. It does not return a decoded audio file or a modified capture.

## HTTP status behavior

| Status | Meaning |
|---:|---|
| 200 | Synchronous success or completed read. |
| 202 | Large upload accepted for background analysis. |
| 404 | Missing/expired job, unknown demo, candidate, or non-audio layer. |
| 409 | A result-dependent endpoint was requested while analysis is running. |
| 413 | Capture or metadata exceeds its byte limit. |
| 422 | Invalid, ambiguous, conflicting, or unsupported capture; failed background analysis is also reported here on result access. |
| 429 | Another analysis already owns the single compute slot. |
| 503 | Bundled demo assets are missing. |

## Lifecycle and security boundary

The service is designed for one local operator. CORS allows only local Vite origins, but the API has no authentication. Run it on loopback with one Uvicorn worker. Job state is in memory; restarting the backend loses job IDs and recovery state. Uploaded copies are deleted on failure, expiry, or eviction.
