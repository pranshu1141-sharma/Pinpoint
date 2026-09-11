# Backend detection pipeline

This document describes the implemented Phase 1 **Detect** signal-processing path. It explains what every stage measures, the units it uses, and where its conclusions stop. The implementation is in `backend/pipeline/` and is exposed by `backend/api/main.py`.

## Scope

The pipeline answers four questions:

1. Can the supplied capture be interpreted without guessing its encoding?
2. Which time and baseband-frequency regions contain energy above an estimated noise floor?
3. Does an isolated candidate have repeatable on/off timing?
4. What intermediate representations let an operator inspect the result?

It does not identify a modulation, recover symbols, demodulate, decode, separate co-channel emitters, or track frequency hopping.

## Units and indexing

| Quantity | Meaning |
|---|---|
| Power density | `dB re 1 sample-unit²/Hz`; it is not dBm because the capture has no impedance, gain, antenna, or ADC calibration. |
| Frequency | Baseband offset in hertz. If SigMF supplies an RF center frequency, it is retained as metadata and is not added to candidate bounds. |
| Time | Seconds from the first sample. |
| Sample range | `start_sample` is inclusive and `end_sample` is exclusive. |
| IQ spectrum | Two-sided, from `-sample_rate/2` to `+sample_rate/2`. |
| Real-audio spectrum | One-sided, from 0 to `sample_rate/2`. |

## Processing sequence

```mermaid
flowchart LR
    A[Validate format and metadata] --> B[Read or map samples]
    B --> C[Welch PSD and median noise estimate]
    C --> D[Time-frequency PSD]
    D --> E[Adaptive threshold and speckle removal]
    E --> F[Associate occupied frequency bins]
    F --> G[Band isolation and envelope timing]
    G --> H[Confidence and review flag]
    H --> I[JSON, plots, layers and SigMF annotations]
```

### 1. Input validation

`ingest.py` handles bounded in-memory captures. `large_capture.py` provides the corresponding disk-backed path. Both require a known sample rate and datatype, validate sample count and finite values, and reject unsafe magnitudes above `1e12`.

Raw IQ is never decoded from a filename alone. A `.iq` file needs explicit sample rate and datatype. A `.sigmf-data` file needs its paired metadata. WAV headers provide rate and numeric encoding, but two channels still need a justified IQ/audio interpretation. See [INPUT_FORMATS.md](INPUT_FORMATS.md).

### 2. Welch PSD and noise estimate

The detector computes a Welch power spectral density using:

- Hann windows;
- 1,024 samples per segment;
- 512-sample overlap;
- density scaling;
- no detrending.

For IQ, the result is FFT-shifted to a two-sided spectrum. For real audio, it remains one-sided. The noise-floor estimate is the median PSD across frequency:

```text
noise_floor = median(PSD[f])
noise_floor_db = 10 log10(max(noise_floor, 1e-30))
```

The frequency median prevents a minority of occupied bins from dominating the estimate. It assumes roughly stationary noise and that less than half of the observed band is occupied. A nearly full-band signal, colored interference, or strongly time-varying noise can bias it.

### 3. Time-frequency scan

The spectrogram uses:

- a 1,024-sample Hann window;
- 768 samples of overlap;
- a 256-sample hop;
- PSD density scaling;
- no detrending.

The nominal frequency resolution is `sample_rate / 1024`. The frame hop is `256 / sample_rate` seconds. Windowing spreads abrupt edges in both time and frequency. The later envelope pass refines time bounds for pulsed signals.

The pipeline deliberately does not subtract the mean or remove the DC bin. A real candidate at zero baseband frequency therefore remains visible.

### 4. Adaptive energy mask

The spectrogram power is averaged with a 3 × 3 uniform filter. In normal mode, the threshold is:

```text
threshold_db = noise_floor_db + margin_db
```

The margin defaults to 8 dB and must be between 3 and 30 dB. A 2 × 2 binary opening removes isolated time-frequency speckles. A retained band must contain at least:

- two adjacent frequency bins;
- three active time frames; and
- 12 active time-frequency cells.

This is an explainable adaptive energy detector. The project calls it **CFAR-style** because it adapts to measured noise, but it is not a statistically calibrated constant-false-alarm-rate algorithm with guard and reference cells around each cell under test.

`fixed_debug` mode accepts an explicit absolute PSD threshold. It exists for comparison and debugging; it is never presented as the normal detector.

### 5. Region association

The detector reduces the binary time-frequency mask to occupied frequency bands. It bridges at most two missing bins between otherwise adjacent occupied bands. Multiple bursts in the same associated band become one candidate with an enclosing time/frequency box and separate `pulse_windows`.

The candidate rectangle is an extent. It does not assert that every point within the rectangle contains signal. The dashboard distinguishes the dashed aggregate rectangle from individual pulse windows.

### 6. Band isolation

Each candidate is isolated before pulse timing:

- IQ is mixed from the candidate center to zero frequency, then low-pass filtered.
- Real audio uses a low-pass, high-pass, or band-pass filter depending on whether the candidate touches an edge of the one-sided spectrum.
- Filters use 257 FIR taps and centered FFT convolution.
- The IQ low-pass cutoff is the larger of half the detected bandwidth and `sample_rate / 1024`, capped below Nyquist.

Centered convolution removes the linear-phase group delay from the returned signal, but the filter transition band still limits separation between close candidates.

### 7. Envelope and pulse timing

The isolated signal is converted to power and smoothed over 1 ms:

```text
envelope[n] = moving_average(|isolated[n]|², 1 ms)
```

The detector estimates:

- `high`: the median of the strongest 1 ms of envelope samples;
- `low`: the 10th percentile of the envelope;
- a band-noise estimate from the PSD floor and candidate bandwidth.

The envelope threshold is:

```text
max(4 × band_noise_power, low + 0.45 × (high - low))
```

Gaps shorter than 1 ms inside an active interval are filled. Windows shorter than 2 ms are discarded. A candidate is marked pulsed only when there is at least one retained window, high-to-background contrast exceeds 8, and duty cycle is below 0.75.

`pulse_width_samples` is the median retained window width. `pri_samples` is the median difference between pulse start indices and is `null` for a single pulse. These are descriptive timing measurements, not a waveform classification.

### 8. Confidence and review

For each candidate, the detector computes threshold excess from the 90th percentile of its smoothed evidence and measures occupancy in the candidate mask. Its confidence is:

```text
0.48 + 0.38 × (1 - exp(-max(0, excess_db) / 10)) + 0.12 × occupancy
```

The score is clipped to `[0, 0.99]` and rounded to four decimals. Scores below 0.70 set `needs_review: true`.

Confidence is a bounded heuristic evidence score. It is not a probability, a calibrated false-alarm estimate, or a statement about modulation identity.

## Small and large captures

Captures at or below 1 MiB use the in-memory pipeline. Larger uploads use a disk-backed pipeline with overlapping blocks. The two paths use the same detector concepts, units, review threshold, and output schema. Their noise estimation differs:

- the in-memory path uses one capture-wide estimate;
- the large path estimates noise within each overlapping block and merges adjacent block results.

See [LARGE_FILE_PROCESSING.md](LARGE_FILE_PROCESSING.md) for block boundaries, overview pooling, merge rules, progress, retention, and the verified 1 GiB run.

## Output semantics

Each candidate contains:

| Field | Meaning |
|---|---|
| `id` | Zero-based candidate index within the result. |
| `start_sample`, `end_sample` | Inclusive/exclusive candidate extent. |
| `freq_lower_hz`, `freq_upper_hz` | Baseband frequency edges. |
| `confidence` | Heuristic evidence score. |
| `needs_review` | Whether confidence is below 0.70. |
| `threshold_excess_db` | Candidate evidence above the applied threshold. |
| `detection_method` | `adaptive_threshold` or `fixed_threshold_debug`. |
| `is_pulsed` | Whether the envelope rule accepted a pulse train or isolated burst. |
| `pulse_windows` | Measured individual on-windows. |
| `pulse_width_samples` | Median window width, or `null`. |
| `pri_samples` | Median pulse-start interval, or `null`. |

The response also contains capture metadata, the Welch PSD, detector settings, timing, threshold/noise summaries, and a human-readable pipeline log. The detector never reads fixture ground truth when producing these fields.

## Known failure modes

- Nearly full-band occupancy can raise the median noise estimate.
- Narrow single-bin signals can fail the minimum-band rule.
- Pulses near or below the 1 ms smoothing scale can be lost or broadened.
- Signals shorter than the minimum surviving time-frequency evidence can be removed.
- Two emitters in the same band can become one aggregate candidate.
- Frequency hopping is represented as separate or broad energy regions rather than one tracked emitter.
- Very weak signals below the chosen margin remain undetected.
- A candidate near a block edge may inherit conservative merged confidence in the large-file path.

These limitations are surfaced in the dashboard and roadmap rather than hidden behind a stronger claim.
