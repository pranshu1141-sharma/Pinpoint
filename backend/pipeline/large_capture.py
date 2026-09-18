"""Bounded-memory file input and offline block processing (not live streaming)."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from time import perf_counter
import numpy as np
from scipy.io import wavfile
from .ingest import Capture, load_capture
from .sigmf_io import DTYPES
from .detect import analyze_capture, estimate_noise_floor, DetectionResult, db
from .classify import analyze_candidate
from .layers import waveform, build_layers

BLOCK_SAMPLES = 524288
GUARD_SAMPLES = 4096
DISPLAY_ROWS = 768


class DiskSamples:
    """Slice-only reader: an accidental whole-file NumPy conversion is forbidden."""
    # A single bounded read's sample cap. enrich_track (below) reads this same
    # attribute for its own per-track limit, so the two can never drift apart.
    MAX_READ_SAMPLES = 2_000_000

    def __init__(self, path, count, dtype, channels, offset=0, wav=False, source="iq", choice="auto"):
        self.path, self.count, self.dtype = Path(path), count, np.dtype(dtype)
        self.channels, self.offset, self.wav = channels, offset, wav
        self.source, self.choice = source, choice

    def __len__(self):
        return self.count

    def __getitem__(self, key):
        if not isinstance(key, slice) or key.step not in (None, 1):
            raise ValueError("Disk captures must be read in contiguous bounded slices.")
        start, stop, _ = key.indices(self.count)
        if stop-start > self.MAX_READ_SAMPLES:
            raise ValueError("A processing window cannot exceed two million samples.")
        with self.path.open("rb") as source:
            source.seek(self.offset+start*self.dtype.itemsize*self.channels)
            raw = source.read((stop-start)*self.dtype.itemsize*self.channels)
        if len(raw) != (stop-start)*self.dtype.itemsize*self.channels:
            raise ValueError("Capture ended unexpectedly during analysis.")
        values = np.frombuffer(raw, dtype=self.dtype).reshape(-1, self.channels).astype(np.float32)
        if self.dtype.kind in "iu":
            info = np.iinfo(self.dtype)
            values = (values-(128 if self.dtype == np.uint8 else 0))/max(abs(info.min), info.max)
        if self.source == "iq":
            x = values[:, 0]+1j*values[:, 1]
        else:
            x = values[:, 1 if self.choice == "audio_right" and self.channels == 2 else 0].astype(np.complex64)
        if not np.isfinite(x).all():
            raise ValueError(f"Capture contains NaN or infinite samples in [{start}, {stop}).")
        if x.size and np.max(np.abs(x)) > 1e12:
            raise ValueError("Sample magnitude is too large; verify the datatype.")
        return x.astype(np.complex64, copy=False)


def open_disk_capture(path, filename, sample_rate=None, datatype=None, metadata=None, wav_mode="auto"):
    path = Path(path)
    if Path(filename).suffix.lower() == ".wav":
        # SciPy reads the WAV header and maps sample bytes without allocating the
        # recording. Close that map immediately; subsequent reads use bounded I/O.
        try:
            rate, mapped = wavfile.read(path, mmap=True)
        except ValueError as exc:
            raise ValueError("Large WAV must use memory-mappable PCM (8/16/32/64-bit) or float samples. Convert packed 24-bit WAV to 32-bit WAV first.") from exc
        try:
            count, dtype, offset = len(mapped), mapped.dtype, mapped.offset
            channels = 1 if mapped.ndim == 1 else mapped.shape[1]
            preview = BytesIO()
            wavfile.write(preview, rate, np.array(mapped[:131072]))
        finally:
            mapped._mmap.close()
        c = load_capture(filename, preview.getvalue(), sample_rate, datatype, metadata, wav_mode)
        reader = DiskSamples(path, count, dtype, channels, offset, True, c.metadata["source_kind"], wav_mode)
        c.metadata["wav_disambiguation"]["reason"] += " Channel evidence sampled from the first 131,072 frames; all sample values are validated during the full scan."
    else:
        with path.open("rb") as source:
            prefix = source.read(131072*8)
        c = load_capture(filename, prefix, sample_rate, datatype, metadata, wav_mode)
        dtype, complex_data = DTYPES[c.metadata["datatype"]]
        channels = 2 if complex_data else 1
        stride = np.dtype(dtype).itemsize*channels
        if path.stat().st_size % stride:
            raise ValueError("Data contains an incomplete sample; check the selected datatype.")
        count = path.stat().st_size//stride
        reader = DiskSamples(path, count, dtype, channels, source=c.metadata["source_kind"])
    c.iq = reader
    c.metadata.update(sample_count=count, duration_seconds=count/c.sample_rate,
                      processing="overlapping_blocks", file_size_bytes=path.stat().st_size)
    return c


# A track longer than DiskSamples.MAX_READ_SAMPLES has no way to become one
# contiguous in-memory buffer through a single bounded re-read, so downstream
# enrichment is skipped for it rather than attempted on a partial/reassembled
# buffer. Reading the limit from DiskSamples itself (not a separate literal)
# means the two can never silently drift apart.
TRACK_ENRICHMENT_MAX_SAMPLES = DiskSamples.MAX_READ_SAMPLES

# Every field estimate_candidate/classify_* ever add, so a track that skips
# enrichment still has the exact same key set as one that didn't -- API
# consumers never have to branch on whether a field is merely absent.
_TRACK_TOO_LONG_STATUS = "not reliably estimated (track exceeds the bounded re-analysis limit for large-capture blocks)"
_NULL_DOWNSTREAM_FIELDS = {
    "center_frequency_hz": None, "bandwidth_3db_hz": None, "bandwidth_99pct_hz": None,
    "bandwidth_99pct_caveat": None, "snr_db": None, "estimate_status": _TRACK_TOO_LONG_STATUS,
    "modulation_family": None, "modulation_confidence": None,
    "modulation_confidence_kind": None, "modulation_status": _TRACK_TOO_LONG_STATUS,
    "envelope_variation": None, "center_frequency_refined_hz": None,
    "refinement_order": None, "refinement_sharpness": None, "refinement_status": _TRACK_TOO_LONG_STATUS,
    "fine_modulation_label": None, "fine_modulation_confidence": None,
    "phase_cluster_spread_rad": None, "fine_modulation_status": _TRACK_TOO_LONG_STATUS,
    "symbol_rate_hz": None, "symbol_rate_status": _TRACK_TOO_LONG_STATUS,
}


def enrich_track(capture, track):
    """Bounded per-track re-read plus the existing Estimate/Classify pipeline.

    A block-merged track has no contiguous in-memory buffer and no per-block
    noise floor is trustworthy for it specifically. Rather than reassembling
    per-block segments (which would need to reconcile independent per-block
    detector state), re-read the track's own span directly from disk in one
    bounded slice -- the underlying file is genuinely contiguous, so this is
    real phase-continuous IQ, not a reconstruction. The existing, unmodified
    analyze_candidate then runs on it exactly as the synchronous upload path
    already does. Tracks longer than DiskSamples' own bounded-read limit are
    an explicit unresolved status, never a partial or reassembled result.
    """
    span = track["end_sample"]-track["start_sample"]
    if not (1 <= span <= TRACK_ENRICHMENT_MAX_SAMPLES):
        return {**track, **_NULL_DOWNSTREAM_FIELDS}
    local_iq = capture.iq[track["start_sample"]:track["end_sample"]]
    local_capture = Capture(local_iq, capture.sample_rate, capture.metadata)
    # Clamped at both ends of both fields, not just the expected side: current
    # merge logic never produces a window straddling a track's own bounds, but
    # if that ever changed, an unclamped window could translate to start>=end
    # here, and occupied_windows' bounds check would then reject the *whole*
    # track's enrichment over one bad window rather than just that window.
    local_track = {**track, "start_sample": 0, "end_sample": span,
                   "pulse_windows": [{"start_sample": max(0, min(span, w["start_sample"]-track["start_sample"])),
                                      "end_sample": max(0, min(span, w["end_sample"]-track["start_sample"]))}
                                     for w in track["pulse_windows"]]}
    try:
        _, _, floor = estimate_noise_floor(local_iq, capture.sample_rate)
        enriched = analyze_candidate(local_capture, local_track, noise_floor=floor)
    except ValueError:
        return {**track, **_NULL_DOWNSTREAM_FIELDS}
    # Only genuinely new (downstream) fields are merged back; track's own
    # Detect-stage fields (global sample coordinates, confidence, etc.) must
    # survive untouched, not the local re-read's 0-based translated copies.
    new_fields = {k: v for k, v in enriched.items() if k not in track}
    # If a future Estimate/Classify field ever reused a Detect-stage key name,
    # the filter above would silently drop it instead of merging it in -- this
    # would fail loudly here (in tests) rather than silently losing a field.
    assert new_fields.keys() == _NULL_DOWNSTREAM_FIELDS.keys(), (
        f"analyze_candidate's field set changed: {new_fields.keys() ^ _NULL_DOWNSTREAM_FIELDS.keys()}")
    return {**track, **new_fields}


def analyze_disk_capture(capture, margin_db=8, mode="adaptive", fixed_threshold_db=None, progress=None,
                         block_samples=BLOCK_SAMPLES):
    started = perf_counter()
    n, fs = len(capture.iq), capture.sample_rate
    if block_samples % 256 or block_samples < 4096:
        raise ValueError("Block size must be a multiple of the STFT hop, at least 4096.")
    rows = min(DISPLAY_ROWS, max(1, (n-1024)//256+1))
    edges = np.linspace(0, n/fs, rows+1)
    overview = None
    tracks, envelopes, last_seen = [], {}, {}
    psd_sum, weight_sum, floors = None, 0, []
    base_response = None
    chunks = (n+block_samples-1)//block_samples
    # At high sample rates 1 ms spans more than 4096 samples. Supply enough
    # envelope context, bounded by half a core block and aligned to the STFT hop.
    guard = ((min(block_samples//2, max(GUARD_SAMPLES, int(fs*.001)))+255)//256)*256
    for index, core_start in enumerate(range(0, n, block_samples)):
        core_end = min(n, core_start+block_samples)
        # FIR/STFT context prevents a processing boundary from looking like a
        # pulse edge. Only core samples contribute to overview and annotations.
        left = max(0, core_start-guard)
        right = min(n, core_end+guard)
        local = Capture(capture.iq[left:right], fs, capture.metadata)
        r = analyze_capture(local, margin_db, mode, fixed_threshold_db)
        base_response = r.response
        times = r.times+left/fs
        keep = (times >= core_start/fs) & (times < core_end/fs)
        bins = np.minimum(rows-1, (times[keep]/(n/fs)*rows).astype(int))
        if overview is None:
            overview = np.zeros((len(r.frequencies), rows), dtype=np.float32)
            psd_sum = np.zeros(len(r.frequencies), dtype=float)
        # np.maximum.at keeps every core STFT frame in a bounded display map.
        # Detection itself always uses the full-resolution local spectrogram.
        np.maximum.at(overview.T, bins, r.power[:, keep].T)
        weight = core_end-core_start
        psd_sum += np.power(10, np.array([p["power_db"] for p in r.response["psd"]])/10)*weight
        weight_sum += weight
        floors.append(r.response["noise_floor_db"])
        used = set()
        for incoming in r.response["detections"]:
            d = deepcopy(incoming)
            a, b = max(core_start, d["start_sample"]+left), min(core_end, d["end_sample"]+left)
            if b <= a:
                continue
            d.update(start_sample=a, end_sample=b)
            windows = []
            for w in incoming["pulse_windows"]:
                wa, wb = max(core_start, w["start_sample"]+left), min(core_end, w["end_sample"]+left)
                if wb > wa:
                    windows.append({"start_sample": wa, "end_sample": wb})
            d["pulse_windows"] = windows
            target = None
            for previous in tracks:
                if previous["id"] in used or last_seen[previous["id"]] != index-1:
                    continue
                overlap = min(previous["freq_upper_hz"], d["freq_upper_hz"])-max(previous["freq_lower_hz"], d["freq_lower_hz"])
                narrow = min(previous["freq_upper_hz"]-previous["freq_lower_hz"], d["freq_upper_hz"]-d["freq_lower_hz"])
                if overlap >= .5*narrow:
                    target = previous
                    break
            if target is None:
                d["id"] = len(tracks)
                target = d
                tracks.append(target)
                envelopes[d["id"]] = {"values": np.zeros(rows), "threshold": 0.0}
            else:
                target["end_sample"] = max(target["end_sample"], b)
                target["freq_lower_hz"] = min(target["freq_lower_hz"], d["freq_lower_hz"])
                target["freq_upper_hz"] = max(target["freq_upper_hz"], d["freq_upper_hz"])
                # Use the least confident observed block: long captures must not
                # hide a weak interval behind stronger portions of the same band.
                target["confidence"] = min(target["confidence"], d["confidence"])
                target["needs_review"] |= d["needs_review"]
                target["is_pulsed"] |= d["is_pulsed"]
                for w in windows:
                    if target["pulse_windows"] and w["start_sample"] <= target["pulse_windows"][-1]["end_sample"]:
                        target["pulse_windows"][-1]["end_sample"] = max(w["end_sample"], target["pulse_windows"][-1]["end_sample"])
                    else:
                        target["pulse_windows"].append(w)
            tid = target["id"]
            used.add(tid)
            last_seen[tid] = index
            env = r.envelopes[incoming["id"]]
            points = waveform(env["values"][core_start-left:core_end-left], fs, core_start, points=rows)
            for point in points:
                bucket = min(rows-1, int(point["time_seconds"]/(n/fs)*rows))
                envelopes[tid]["values"][bucket] = max(envelopes[tid]["values"][bucket], point["value"])
            envelopes[tid]["threshold"] = max(envelopes[tid]["threshold"], env["threshold"])
            if len(tracks) > 4096 or sum(len(t["pulse_windows"]) for t in tracks) > 200000:
                raise ValueError("Capture exceeds 4,096 candidates or 200,000 pulse windows. Split it for review; results were not silently truncated.")
        if progress:
            progress(core_end, n, f"Analyzed block {index+1}/{chunks}; {core_end:,}/{n:,} samples scanned")
    for index, d in enumerate(tracks):
        windows = d["pulse_windows"]
        if windows:
            d["pulse_width_samples"] = int(round(np.median([w["end_sample"]-w["start_sample"] for w in windows])))
            d["pri_samples"] = int(round(np.median(np.diff([w["start_sample"] for w in windows])))) if len(windows)>1 else None
        else:
            d.update(is_pulsed=False, pulse_width_samples=None, pri_samples=None)
        env = envelopes[d["id"]]
        env["waveform"] = [{"time_seconds": float(t), "value": float(v)} for t, v in zip(edges[:-1], env.pop("values"))]
        tracks[index] = enrich_track(capture, d)
    floor = float(np.median(floors))
    elapsed = (perf_counter()-started)*1000
    base_response.update(detections=tracks, metadata=capture.metadata, elapsed_ms=elapsed,
                         noise_floor_db=floor, threshold_db=floor+margin_db if mode=="adaptive" else fixed_threshold_db,
                         psd=[{"frequency_hz": float(f), "power_db": float(p)} for f,p in zip(r.frequencies, db(psd_sum/weight_sum))],
                         noise_floor_range_db=[min(floors),max(floors)],
                         pipeline_log=[f"Read all {n:,} samples from disk in {chunks} overlapping blocks",
                                       f"Core block: {block_samples:,} samples; guard context: {guard:,} samples each side",
                                       f"Welch noise floor estimated separately per block; median {floor:.2f} dB, range {min(floors):.2f} to {max(floors):.2f} dB",
                                       "PSD and threshold lines summarize blocks; detection uses each block's actual noise floor",
                                       f"Full-resolution STFT scan merged {len(tracks)} candidate bands; display pooled to {rows} time rows",
                                       f"Validated and analyzed {n:,}/{n:,} samples; no samples skipped or file truncation",
                                       f"Detect complete in {elapsed:.1f} ms; isolation previews are bounded windows, no decoding"])
    base_response["settings"]["processing"] = "overlapping_blocks"
    result = DetectionResult(base_response, r.frequencies, (edges[:-1]+edges[1:])/2, overview, envelopes)
    result.time_edges = edges
    return result


def build_disk_layers(capture, result, detection):
    fs = capture.sample_rate
    start = max(0, detection["start_sample"]-min(4096, int(fs*.1)))
    stop = min(len(capture.iq), start+max(1024, min(1_000_000, int(fs*8))))
    # Inspection uses a bounded, explicitly labeled interval; detection above
    # has scanned the entire file. Never isolate gigabytes for an 8-second clip.
    local = Capture(capture.iq[start:stop], fs, capture.metadata)
    d = deepcopy(detection)
    d.update(start_sample=max(0, d["start_sample"]-start), end_sample=min(stop-start, d["end_sample"]-start))
    d["pulse_windows"] = [{"start_sample":max(0,w["start_sample"]-start), "end_sample":min(stop-start,w["end_sample"]-start)}
                          for w in d["pulse_windows"] if w["end_sample"]>start and w["start_sample"]<stop]
    from .detect import isolate_band, envelope_detect
    band = isolate_band(local.iq, fs, d["freq_lower_hz"], d["freq_upper_hz"], capture.metadata["source_kind"]=="audio")
    env = envelope_detect(band, fs, 10**(result.response["noise_floor_db"]/10)*(d["freq_upper_hz"]-d["freq_lower_hz"]))
    preview_result = DetectionResult(result.response, result.frequencies, result.times, result.power,
                                      {d["id"]:{"values":env["envelope"]}})
    layers, clips = build_layers(local, preview_result, d)
    for layer in layers:
        layer["description"] += f" Preview interval {start/fs:.3f}–{stop/fs:.3f} s of the full capture."
        layer["preview_start_sample"], layer["preview_end_sample"] = start, stop
        layer["audio_start_seconds"] = (start+(d["start_sample"] if layer["name"]=="Detected Region Only" else 0))/fs
        for point in layer["waveform"]:
            point["time_seconds"] += start/fs
    return layers, clips
