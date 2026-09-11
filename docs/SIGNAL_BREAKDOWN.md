# Signal Breakdown and audio behavior

Signal Breakdown is an inspection view for a selected candidate. It makes the Detect-stage transformations visible. It is not a decoder, modulation classifier, source separator, or signal-restoration claim.

## Shared behavior

The backend builds layers only when a candidate is selected. Each layer includes a name, description, enabled state, sample rate/count, peak-pooled waveform, and optional audio URL. Waveforms use maximum absolute value in up to 700 display buckets so a short transient is not lost through point subsampling.

For captures processed from disk, the backend reads a bounded window around the selected candidate:

- starts up to 0.1 seconds or 4,096 samples before the detected onset;
- ends after at most eight seconds or one million samples;
- never reads beyond the capture;
- records `preview_start_sample`, `preview_end_sample`, and an exact interval in the layer description.

That bounded window is a review preview. The detector has already scanned every sample in the file.

## Real-audio layers

| Order | Layer | Operation | Audio |
|---:|---|---|---|
| 0 | Raw Capture | Original selected real channel. | Yes |
| 1 | Isolated Band | 257-tap linear-phase FIR within candidate frequency bounds. | Yes |
| 2 | Noise-Referenced | Soft STFT spectral gate referenced to the measured Welch noise density. | Yes |
| 3 | Envelope-Gated | Noise-referenced audio set to zero outside measured pulse windows. | Only for a pulsed candidate |
| 4 | Detected Region Only | Noise-referenced isolated audio trimmed to the candidate sample range. | Yes |

The spectral gate uses a 512-sample Hann STFT with 384 samples of overlap. It converts PSD density to a comparable bin-noise value with the Hann equivalent noise bandwidth, then applies:

```text
gain = clip(1 - threshold / STFT_power, 0, 1)
```

This is a soft noise-referenced gate. It can introduce spectral-gating artifacts and does not reconstruct information below the measured noise.

All playable layers use a common gain derived from the original real channel. This preserves audible differences between layers instead of independently normalizing each one. Browser clips are resampled with polyphase filtering to 48 kHz, stored as float32 WAV, and capped at eight seconds.

The audio URL points to a derived preview. The export endpoint does not return this clip; JSON and SigMF exports contain detection data and annotations.

## IQ layers

| Order | Layer | Operation | Audio |
|---:|---|---|---|
| 0 | Raw Baseband Magnitude | Peak-pooled `|IQ|` over the capture or preview. | No |
| 1 | Isolated & Downconverted | Mix candidate center to zero, FIR-isolate it, and polyphase-decimate according to bandwidth. | No |
| 2 | Thresholded | Zero samples outside the candidate extent; zero the whole layer when the candidate requires review. | No |
| 3 | Envelope View | Smoothed isolated-band `|IQ|²` used for pulse timing. | Only enabled for pulsed candidates; still visual, not audio |

IQ decimation keeps a rate appropriate to the detected bandwidth and applies an anti-alias filter through `resample_poly`. The result is still complex baseband. Playing it as ordinary mono audio would require an arbitrary mapping and could be mistaken for demodulation, so the API supplies no audio URL.

## What “decoded sound file” means here

The project does **not** produce a decoded sound file from RF IQ. Decoding would require at least a modulation or waveform hypothesis, demodulator, symbol/timing recovery where applicable, and a codec/content interpretation. Those belong to later phases.

For a WAV already known to be real audio, the project can return filtered review clips. Those clips are transformations of the supplied audio channel, not decoded RF content.

## Pulse overlay provenance

Pulse windows come from the 1 ms-smoothed isolated-band power envelope. The UI marks them on the waveform and waterfall. `pulse_width_samples` and `pri_samples` are medians over those measured windows. A single accepted burst has a width and `pri_samples: null`; the application does not invent a repetition interval.

## Disabled states

The backend returns a disabled layer with a reason when a transform does not apply. For example, Envelope-Gated audio and Envelope View are disabled when the selected candidate has no detected pulse train. A missing audio URL is expected for IQ and disabled layers and maps to HTTP 404 if requested directly.

## Interpretation limits

- Isolation reduces out-of-band content but cannot separate two sources occupying the same band and time.
- The 257-tap FIR has finite transition width.
- Spectral gating can suppress weak desired components and create musical-noise artifacts.
- Common gain can make quiet layers sound quiet; that is intentional for fair comparison.
- The eight-second clip cap limits listening duration, while full candidate/sample bounds remain in the result.
- An envelope is energy evidence, not recovered data or a modulation label.
