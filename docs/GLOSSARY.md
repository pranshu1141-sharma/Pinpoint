# Glossary

| Term | Meaning in this project |
|---|---|
| Adaptive margin | Number of dB added to the measured noise-floor density to form the normal detection threshold. |
| Aggregate candidate | One enclosing time/frequency region that can contain separate pulse windows. |
| Baseband offset | Frequency relative to the recorder's tuned center, rather than an absolute RF frequency. |
| Candidate | A region with enough time-frequency energy evidence to pass the implemented rules. It is not a class or emitter identity. |
| CFAR | Constant false alarm rate. The current detector is described as CFAR-style because it adapts to noise, but it does not implement calibrated local CFAR reference/guard cells. |
| Complex IQ | Paired in-phase and quadrature samples representing amplitude and phase. |
| Confidence | A heuristic evidence score based on threshold excess and occupancy; not a probability. |
| Core block | The 524,288-sample large-file interval whose results and progress are retained. |
| Decode | Recover meaningful content or symbols from a signal. Not implemented. |
| Demodulate | Convert a modulated waveform into its baseband message representation. Not implemented for IQ. |
| Detect | Locate candidate energy in time and frequency and measure timing evidence. This is the implemented phase. |
| Duty cycle | Fraction of envelope samples considered on within the analyzed interval. |
| ENBW | Equivalent noise bandwidth; used to relate a windowed STFT bin to PSD density in the audio spectral gate. |
| End sample | Exclusive upper sample index of an interval. |
| Envelope | Smoothed isolated-band power, `|x|²`, used for pulse timing. |
| FFT shift | Reordering a complex spectrum so negative frequencies precede zero and positive frequencies. |
| Fixed-debug threshold | Explicit absolute PSD threshold used only for comparison/testing. |
| Frequency bin | One discrete spectral interval. Nominal width is sample rate divided by 1,024. |
| Guard context | Samples read before/after a large-file core to prevent filter/STFT boundary artifacts. |
| Hann window | Taper used by Welch, spectrogram, and audio STFT processing to reduce leakage. |
| Hop | Distance between consecutive spectrogram frames; 256 samples here. |
| IQ | In-phase and quadrature sample pair. |
| Isolation | Frequency-selective filtering, with frequency translation for IQ, around a detected candidate. |
| Job | Server-side analysis lifecycle identified by an opaque ID. Large uploads are queued/processed asynchronously. |
| Matched filter | Filter designed from a known signal template. Planned, not implemented. |
| Morphological opening | Binary erosion followed by dilation, used here to remove isolated 2D speckles. |
| Noise floor | Median Welch PSD across frequency for a small capture or block. |
| Occupancy | Fraction of a candidate's evaluated time-frequency cells that pass the mask. |
| PCM | Pulse-code modulation storage used by integer WAV files; unrelated to detecting pulsed RF candidates. |
| PRI | Pulse repetition interval, measured as the median distance between pulse start samples. |
| PSD | Power spectral density, expressed here in sample-unit²/Hz or its dB form. |
| Pulse window | Inclusive-start/exclusive-end interval where isolated envelope power passes the pulse rule. |
| Review flag | `needs_review: true` when heuristic confidence is below 0.70. |
| SigMF | Signal Metadata Format, pairing sample data with structured capture metadata and annotations. |
| Spectrogram | Power spectral density over both frequency and time. |
| Start sample | Inclusive lower sample index of an interval. |
| STFT | Short-time Fourier transform underlying spectrogram and audio gate operations. |
| Threshold excess | Candidate evidence level above the applied PSD threshold, in dB. |
| Waterfall | Time-frequency heat-map rendering of the spectrogram. |
| Welch PSD | Averaged windowed spectral-density estimate used for the noise floor and PSD chart. |
| WAV interpretation | Recorded choice/heuristic indicating mono audio, one stereo audio channel, or left/right IQ. |
