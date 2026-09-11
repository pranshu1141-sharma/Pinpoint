import type { Detection as ApiDetection } from '../api';

export interface Detection extends Omit<ApiDetection, 'id'> {
  id: string;
}

export interface AnalyzeResponse {
  job_id: string;
  detections: Detection[];
  noise_floor_db: number;
  pipeline_log: string[];
  sample_rate?: number;
  duration_seconds?: number;
  filename?: string;
}

export interface SpectrogramResponse {
  frequency_edges_hz: number[];
  time_edges_seconds: number[];
  min_db: number;
  max_db: number;
  time_bins: number[];
  freq_bins: number[];
  magnitude_2d: number[][];
}

export interface DetectionLayer {
  name: string;
  description: string;
  waveform: number[];
  audio_url: string | null;
  available: boolean;
}

export interface DetectionLayersResponse {
  layers: DetectionLayer[];
}

export interface CursorInfo {
  freqHz: number | null;
  magnitudeDb: number | null;
}

export interface FileInfo {
  interpretation: string;
  center: number | null;
  filename: string;
  sampleRate: number;
  durationSeconds: number;
  totalSamples: number;
  fileSize: string;
  format: string;
}
