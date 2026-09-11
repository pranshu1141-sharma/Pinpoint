# Input formats and capture interpretation

The application accepts offline raw IQ, SigMF, and WAV captures. It refuses to guess information that cannot be established from the file or explicit operator input.

## Accepted files

| Capture | Companion data | Supported encodings | Interpretation |
|---|---|---|---|
| `.iq` | Sample rate and datatype entered in the dashboard, or a selected SigMF metadata file | `cf32_le`, `cf32_be`, `ci16_le`, `ci16_be` | Complex IQ. Real and imaginary values are interleaved. |
| `.sigmf-data` | Matching `.sigmf-meta` selected at the same time | `cf32_le`, `cf32_be`, `ci16_le`, `ci16_be`, `rf32_le`, `ri16_le` | Determined by validated SigMF metadata. |
| Mono `.wav` | None | WAV encodings accepted by SciPy; large packed 24-bit files are excluded | One-channel real audio. |
| Two-channel `.wav` | Explicit choice if automatic evidence is inconclusive | WAV encodings accepted by SciPy; large packed 24-bit files are excluded | Either I=left/Q=right or one selected real-audio channel. |

Extensions are matched case-insensitively. One capture and at most one metadata file may be selected. When two files are selected, their filename stems must match.

## Raw IQ fields

Raw `.iq` files do not carry a standard header, so the operator must provide:

- a finite positive sample rate in samples per second; and
- one of the four supported complex datatypes.

| Datatype | Storage |
|---|---|
| `cf32_le` | Little-endian 32-bit float I followed by Q. |
| `cf32_be` | Big-endian 32-bit float I followed by Q. |
| `ci16_le` | Little-endian signed 16-bit integer I followed by Q. |
| `ci16_be` | Big-endian signed 16-bit integer I followed by Q. |

Integer samples are normalized by 32768. An incomplete trailing complex sample is rejected. The application does not infer byte order or numeric type from amplitude appearance.

## SigMF rules

The metadata parser validates the document with the `sigmf` package and then enforces the subset implemented by this pipeline:

- sample rate must be finite and positive;
- datatype must be in the supported table above;
- the capture must describe one channel;
- byte offsets and header bytes are not accepted;
- multiple tuning frequencies are rejected rather than silently combined;
- explicit form fields must agree with SigMF values when both are supplied.

The first capture frequency, when present and unambiguous, is retained as `center_frequency_hz`. Candidate frequency fields remain baseband offsets.

SigMF export adds candidate annotations and keeps detector-specific values such as confidence, method, pulse status, and review status in a JSON `core:comment`. The exported metadata is validated before it is returned.

## WAV disambiguation

Mono WAV has only one recorded component and is always treated as real audio. Selecting IQ for a mono WAV returns an error because a Q component cannot be invented.

For a two-channel WAV, automatic mode examines up to the first 131,072 frames after removing each channel mean. It computes:

- ordinary channel correlation;
- the correlation between the Hilbert quadrature of the left channel and the right channel; and
- the ratio of weaker to stronger channel power.

Automatic IQ evidence requires:

```text
quadrature correlation > 0.90
absolute ordinary correlation < 0.20
power balance > 0.50
```

If the evidence passes, left is interpreted as I and right as Q. Otherwise the upload returns `input_required`, and the dashboard asks the operator to choose one of:

- confirm left=I and right=Q;
- analyze left as real audio; or
- analyze right as real audio.

The evidence is a heuristic, not proof of recording provenance. Random wideband IQ can be inconclusive, and deliberately quadrature stereo audio can pass. Known acquisition metadata should take priority over the heuristic.

Integer PCM WAV values are centered and normalized to approximately `[-1, 1]`. Floating-point WAV samples keep their original scale. This difference matters when comparing absolute uncalibrated PSD values across files.

## Size and content limits

| Limit | Value | Behavior |
|---|---:|---|
| Capture upload | 2 GiB / 2,147,483,648 bytes | Larger uploads return HTTP 413. |
| Metadata upload | 1 MiB | Larger metadata returns HTTP 413. |
| Minimum samples | 1,024 | Shorter captures return HTTP 422. |
| In-memory loader maximum | 2,000,000 samples | Internal safety guard for the bounded loader. Uploaded files above 1 MiB use the disk path and are not truncated by this guard. |
| Large packed 24-bit WAV | Unsupported | Convert to 32-bit PCM or float WAV so it can be memory-mapped. |

All samples are checked for NaN and infinity. Magnitudes above `1e12` are rejected as a likely datatype mismatch. Large captures are checked throughout the scan, including late blocks; validation is not limited to the beginning of the file.

## Selection and submission examples

### Raw complex float capture

Select `capture.iq`, enter its sample rate, and choose `cf32_le`. The request sends those values as multipart form fields.

### SigMF pair

Select `capture.sigmf-data` and `capture.sigmf-meta` together. Do not enter conflicting rate or datatype values. The metadata supplies them.

### Stereo WAV with known IQ provenance

Select the WAV and choose **Confirm I=left / Q=right** if automatic mode asks for a decision. The result records both the diagnostic measurements and the explicit choice.

### Stereo audio

Choose left or right real audio. The detector uses a one-sided spectrum and audio-capable breakdown layers.

## Common rejection messages

| Message or code | Resolution |
|---|---|
| `input_required` for raw IQ | Enter sample rate and datatype or add matching SigMF metadata. |
| `input_required` for WAV | Choose IQ, left audio, or right audio. |
| Conflicting sample rate/datatype | Remove the manual override or correct the metadata. |
| Incomplete complex sample | Repair or re-export the raw file with complete I/Q pairs. |
| Multiple tuning frequencies | Split the recording into captures with one tuning context. |
| Unsupported datatype | Convert to a supported SigMF/raw encoding. |
| NaN, infinite, or extreme sample | Verify exporter, byte order, and datatype. |
| Capture too short | Supply at least 1,024 samples. |
| Maximum capture size exceeded | Split the capture into files no larger than 2 GiB. |
