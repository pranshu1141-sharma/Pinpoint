"""Inspectable Detect-stage transforms, with no demodulators or decoders."""
from io import BytesIO
from fractions import Fraction
import numpy as np
from scipy import signal
from scipy.io import wavfile
from .detect import isolate_band, EPS


def waveform(values, fs, offset=0, points=700):
    values = np.asarray(values)
    # Peak pooling preserves brief pulses in a viewport-sized envelope; point
    # subsampling would silently miss transients between selected indices.
    edges = np.linspace(0, len(values), min(points, len(values))+1, dtype=int)
    return [{"time_seconds": float((a+offset)/fs), "value": float(np.max(np.abs(values[a:b])))}
            for a, b in zip(edges[:-1], edges[1:]) if b > a]


def spectral_gate(audio, fs, floor):
    # PSD and STFT magnitudes have different units. Scale the measured one-sided
    # noise density by the Hann window equivalent noise bandwidth before gating.
    _, _, z = signal.stft(audio, fs=fs, nperseg=512, noverlap=384)
    window = signal.get_window("hann", 512)
    enbw = fs*np.sum(window**2)/np.sum(window)**2
    threshold = floor*enbw/2
    gain = np.clip(1-threshold/(np.abs(z)**2+EPS), 0, 1)
    _, clean = signal.istft(z*gain, fs=fs, nperseg=512, noverlap=384)
    return clean[:len(audio)]


def build_layers(capture, result, detection):
    x, fs = capture.iq, capture.sample_rate
    d = detection
    audio_source = capture.metadata["source_kind"] == "audio"
    # Browser clips are capped, while waveform previews represent each complete
    # layer. Clip lengths and resampling are returned explicitly to the UI.
    isolated = isolate_band(x, fs, d["freq_lower_hz"], d["freq_upper_hz"], audio_source)
    mask = np.zeros(len(x), dtype=bool)
    mask[d["start_sample"]:d["end_sample"]] = True
    pulse_mask = np.zeros(len(x), dtype=bool)
    for w in d["pulse_windows"]:
        pulse_mask[w["start_sample"]:w["end_sample"]] = True
    entries = []
    if audio_source:
        clean = spectral_gate(isolated, fs, 10**(result.response["noise_floor_db"]/10))
        entries = [
            ("Raw Capture", "Original real-audio channel; preview is resampled if needed.", x.real, fs, True, 0, True),
            ("Isolated Band", "Linear-phase FIR bandpass within the candidate frequency bounds.", isolated, fs, True, 0, True),
            ("Noise-Referenced", "Soft spectral gate referenced to the measured Welch noise density.", clean, fs, True, 0, True),
            ("Envelope-Gated", "Audio silenced outside measured pulse windows.", clean*pulse_mask, fs, d["is_pulsed"], 0, True),
            ("Detected Region Only", "Band-isolated, noise-referenced audio trimmed to the candidate sample interval.", clean[d["start_sample"]:d["end_sample"]], fs, True, d["start_sample"], True)]
    else:
        bandwidth = d["freq_upper_hz"]-d["freq_lower_hz"]
        factor = max(1, int(fs/max(2*bandwidth, fs/64)))
        # Polyphase resampling adds an anti-alias filter before decimation. A
        # complex baseband waveform is still IQ and is not decoded audio.
        tuned = signal.resample_poly(isolated, 1, factor) if factor > 1 else isolated
        accepted = mask if not d["needs_review"] else np.zeros(len(x), dtype=bool)
        thresholded = signal.resample_poly(isolated*accepted, 1, factor) if factor > 1 else isolated*accepted
        env = result.envelopes[d["id"]]["values"]
        entries = [
            ("Raw Baseband Magnitude", "Magnitude |IQ|; not natively audio or meaningful sound.", x, fs, True, 0, False),
            ("Isolated & Downconverted", f"Band-isolated, shifted to baseband and decimated by {factor}; no demodulation.", tuned, fs/factor, True, 0, False),
            ("Thresholded", "Zeroed outside the candidate interval; entirely zero when the candidate needs review.", thresholded, fs/factor, True, 0, False),
            ("Envelope View", "Smoothed |IQ|² in the isolated band, showing measured pulse timing.", env, fs, d["is_pulsed"], 0, False)]
    layers, clips = [], {}
    # A common scale across audio layers keeps filtering changes audible without
    # disguising them through independent loudness normalization.
    gain = min(1.0, .95/max(float(np.max(np.abs(x.real))), EPS))
    for idx, (name, desc, values, rate, enabled, offset, playable) in enumerate(entries):
        layer = {"id": idx, "name": name, "description": desc, "enabled": bool(enabled),
                 "disabled_reason": None if enabled else "Not applicable: this candidate has no detected pulse train.",
                 "sample_rate": float(rate), "sample_count": len(values),
                 "waveform": waveform(values, rate, offset) if enabled else [],
                 "audio_url": None, "audio_description": "IQ magnitude visualization only; no audio produced.",
                 "clip_duration_seconds": None}
        if playable and enabled:
            # WAV headers need integer rates. Rational resampling preserves pitch
            # for sources outside browser-supported sample rates.
            preview_rate = 48000
            clip = np.asarray(values[:max(1, int(rate*8))]).real * gain
            ratio = Fraction(preview_rate/rate).limit_denominator(10000)
            clip = signal.resample_poly(clip, ratio.numerator, ratio.denominator)
            payload = BytesIO()
            wavfile.write(payload, preview_rate, clip.astype(np.float32))
            clips[idx] = payload.getvalue()
            layer["clip_duration_seconds"] = len(clip)/preview_rate
            layer["audio_description"] = "Real audio, preview up to 8 seconds, resampled to 48 kHz with common headroom scaling."
        layers.append(layer)
    return layers, clips
