import type { Analysis, Detection, Spectrogram } from '../api';

// Bolt uses string selection IDs; preserve all measurements from the API.
export const adaptDetections = (detections: Detection[]) =>
  detections.map(d => ({ ...d, id: String(d.id) }));

export function adaptSpectrogram(data: Spectrogram) {
  return {
    ...data,
    magnitude_2d: data.magnitude_db,
    freq_bins: data.frequency_edges_hz.slice(0, -1).map((v, i) => (v + data.frequency_edges_hz[i + 1]) / 2),
    time_bins: data.time_edges_seconds.slice(0, -1).map((v, i) => (v + data.time_edges_seconds[i + 1]) / 2),
  };
}

export function describeFile(metadata: Analysis['metadata'] | null, bytes?: number) {
  if (!metadata) return null;
  return {
    filename: metadata.filename, sampleRate: metadata.sample_rate,
    durationSeconds: metadata.duration_seconds, totalSamples: metadata.sample_count,
    format: metadata.datatype,
    fileSize: bytes === undefined ? 'Not reported' : `${(bytes / 1024 ** 2).toFixed(2)} MiB`,
    interpretation: metadata.source_kind === 'iq' ? 'Complex IQ' : 'Real audio',
    center: metadata.center_frequency_hz,
  };
}
