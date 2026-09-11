export interface Detection {
  id: string;
  start_sample: number;
  end_sample: number;
  freq_lower_hz: number;
  freq_upper_hz: number;
  confidence: number;
  detection_method: string;
  is_pulsed: boolean;
  pulse_width_samples: number | null;
  pri_samples: number | null;
  needs_review: boolean;
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
  filename: string;
  sampleRate: number;
  durationSeconds: number;
  totalSamples: number;
  fileSize: string;
  format: string;
}
