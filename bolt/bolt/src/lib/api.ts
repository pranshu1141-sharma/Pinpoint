import type {
  AnalyzeResponse,
  SpectrogramResponse,
  DetectionLayersResponse,
} from './types';

const API_BASE = '/api';

export async function analyzeFile(file: File): Promise<AnalyzeResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API_BASE}/analyze`, {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Analyze failed (${res.status}): ${text || res.statusText}`);
  }

  return res.json();
}

export async function fetchSpectrogram(jobId: string): Promise<SpectrogramResponse> {
  const res = await fetch(`${API_BASE}/spectrogram/${jobId}`);

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Spectrogram fetch failed (${res.status}): ${text || res.statusText}`);
  }

  return res.json();
}

export async function fetchDetectionLayers(
  jobId: string,
  detectionId: string,
): Promise<DetectionLayersResponse> {
  const res = await fetch(`${API_BASE}/detections/${jobId}/${detectionId}/layers`);

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Layers fetch failed (${res.status}): ${text || res.statusText}`);
  }

  return res.json();
}
