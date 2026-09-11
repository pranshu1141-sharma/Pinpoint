from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import numpy as np
from scipy import signal
from scipy.io import wavfile
from .sigmf_io import decode_samples, parse_metadata

MAX_SAMPLES = 2_000_000


class AmbiguousCapture(ValueError):
    pass


@dataclass
class Capture:
    iq: np.ndarray
    sample_rate: float
    metadata: dict


def disambiguate_iq_vs_audio(channels):
    if channels.ndim == 1:
        return {"result": "real_audio", "reason": "Single real channel; no recorded Q channel."}
    if channels.shape[1] != 2:
        raise ValueError("Only mono or two-channel WAV captures are supported.")
    x = channels[:min(len(channels), 131072)].astype(float)
    x -= x.mean(axis=0)
    energy = np.mean(x*x, axis=0)
    if np.min(energy) < 1e-15:
        return {"result": "ambiguous", "reason": "One or both channels have no measurable variance."}
    # Near-zero correlation alone is NOT proof of IQ: stereo audio can also be
    # uncorrelated. Require a strong Hilbert quadrature relationship as evidence.
    corr = float(np.corrcoef(x.T)[0, 1])
    quad = float(abs(np.corrcoef(signal.hilbert(x[:, 0]).imag, x[:, 1])[0, 1]))
    balance = float(min(energy)/max(energy))
    result = "iq_pair_evidence" if quad > .90 and abs(corr) < .2 and balance > .5 else "ambiguous"
    return {"result": result, "correlation": corr, "quadrature_correlation": quad,
            "power_balance": balance, "reason": "Quadrature evidence is a heuristic, not proof of recording provenance."}


def load_capture(filename, data, sample_rate=None, datatype=None, sigmf_meta=None, wav_mode="auto"):
    if wav_mode not in ("auto", "iq", "audio_left", "audio_right"):
        raise ValueError("Unknown WAV interpretation; choose auto, iq, audio_left, or audio_right.")
    suffix = Path(filename).suffix.lower()
    center = None
    diagnostic = {"result": "declared_iq", "reason": "Raw datatype explicitly provided."}
    if suffix == ".wav":
        try:
            rate, channels = wavfile.read(BytesIO(data))
        except Exception as exc:
            raise ValueError("Malformed or unsupported WAV file.") from exc
        if sample_rate is not None and sample_rate != rate:
            raise ValueError("Provided sample rate conflicts with the WAV header.")
        if channels.dtype.kind in "iu":
            info = np.iinfo(channels.dtype)
            # Unsigned PCM has a midpoint bias; signed PCM is centered on zero.
            channels = (channels.astype(float) - (128 if channels.dtype == np.uint8 else 0)) / max(abs(info.min), info.max)
        channels = channels.astype(np.float32)
        diagnostic = disambiguate_iq_vs_audio(channels)
        if channels.ndim == 1:
            if wav_mode == "iq":
                raise ValueError("Mono WAV cannot supply an IQ pair.")
            iq, source = channels.astype(np.complex64), "audio"
        elif wav_mode == "iq" or (wav_mode == "auto" and diagnostic["result"] == "iq_pair_evidence"):
            iq, source = (channels[:, 0] + 1j*channels[:, 1]).astype(np.complex64), "iq"
        elif wav_mode in ("audio_left", "audio_right"):
            iq, source = channels[:, 0 if wav_mode == "audio_left" else 1].astype(np.complex64), "audio"
        else:
            raise AmbiguousCapture("WAV channels are ambiguous. Confirm I=left/Q=right, or select left/right real audio; no interpretation was assumed.")
        diagnostic["interpretation"] = source
        diagnostic["user_choice"] = wav_mode
        datatype = "cf32_le" if source == "iq" else "rf32_le"
    elif suffix in (".iq", ".sigmf-data"):
        if sigmf_meta is not None:
            _, rate, meta_datatype, center = parse_metadata(sigmf_meta)
            if sample_rate is not None and float(sample_rate) != rate:
                raise ValueError("Provided sample rate conflicts with SigMF metadata.")
            if datatype is not None and datatype != meta_datatype:
                raise ValueError("Provided datatype conflicts with SigMF metadata.")
            datatype = meta_datatype
            diagnostic = {"result": "sigmf_metadata", "reason": "Validated SigMF datatype and sampling metadata."}
        else:
            if suffix == ".sigmf-data" or sample_rate is None or datatype is None:
                raise AmbiguousCapture("Supply the paired .sigmf-meta, or for raw .iq explicitly enter sample rate and datatype.")
            rate = sample_rate
        iq, source = decode_samples(data, datatype)
    else:
        raise ValueError("Upload .iq, .wav, or a .sigmf-data + .sigmf-meta pair.")
    if not np.isfinite(rate) or rate <= 0:
        raise ValueError("Sample rate must be finite and positive.")
    if not 1024 <= len(iq) <= MAX_SAMPLES:
        raise ValueError(f"Capture must contain 1,024 to {MAX_SAMPLES:,} samples. Split larger captures first.")
    if not np.isfinite(iq).all():
        raise ValueError("Capture contains NaN or infinite samples.")
    if np.max(np.abs(iq)) > 1e12:
        raise ValueError("Sample magnitude is too large for stable processing; verify the datatype.")
    metadata = {"filename": Path(filename).name, "sample_rate": float(rate), "sample_count": len(iq),
                "duration_seconds": len(iq)/float(rate), "source_kind": source, "datatype": datatype,
                "center_frequency_hz": center, "wav_disambiguation": diagnostic,
                "power_unit": "dB re 1 sample-unit²/Hz", "frequency_reference": "baseband offset"}
    return Capture(iq, float(rate), metadata)
