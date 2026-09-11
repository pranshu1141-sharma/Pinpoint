export type Detection = {
  id: number;
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
  pulse_windows: { start_sample: number; end_sample: number }[];
  threshold_excess_db: number;
};
export type Analysis = {
  job_id: string;
  detections: Detection[];
  noise_floor_db: number;
  threshold_db: number;
  pipeline_log: string[];
  elapsed_ms: number;
  expires_in_seconds: number;
  metadata: {
    filename: string;
    sample_rate: number;
    sample_count: number;
    duration_seconds: number;
    source_kind: "iq" | "audio";
    datatype: string;
    center_frequency_hz: number | null;
    power_unit: string;
    frequency_reference: string;
    wav_disambiguation: {
      result: string;
      reason: string;
      user_choice?: string;
      quadrature_correlation?: number;
    };
  };
  settings: {
    processing?: string;
    margin_db: number;
    mode: string;
    nfft: number;
    hop_samples: number;
    review_threshold: number;
  };
  psd: { frequency_hz: number; power_db: number }[];
};
export type Spectrogram = {
  magnitude_db: number[][];
  frequency_edges_hz: number[];
  time_edges_seconds: number[];
  min_db: number;
  max_db: number;
  aggregation: string;
  unit: string;
};
export type WavePoint = { time_seconds: number; value: number };
export type Layer = {
  audio_start_seconds?: number;
  id: number;
  name: string;
  description: string;
  enabled: boolean;
  disabled_reason: string | null;
  sample_rate: number;
  sample_count: number;
  waveform: WavePoint[];
  audio_url: string | null;
  audio_description: string;
  clip_duration_seconds: number | null;
};
export type Envelope = {
  threshold_description?: string;
  waveform: WavePoint[];
  threshold: number;
  pulse_windows: Detection["pulse_windows"];
  pulse_width_samples: number | null;
  pri_samples: number | null;
};
export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new Error(
      "Not connected — the Detect API is unreachable. Start the backend and reconnect.",
    );
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.message ||
            (response.status >= 500
              ? "The Detect API is unavailable. Check the backend, then retry."
              : `Request failed (${response.status}).`),
    );
  }
  return response.json();
}
export const khz = (v: number) => `${(v / 1000).toFixed(2)}`;
export const seconds = (v: number) => v.toFixed(3);
export const contactName = (d: Detection) =>
  `C${String(d.id + 1).padStart(2, "0")}`;

export type AnalysisProgress = {
  phase: "upload" | "analysis";
  fraction: number | null;
  message: string;
};
type JobState = {
  job_id: string;
  status: "queued" | "processing" | "complete" | "failed";
  progress: number;
  message: string;
  result?: Analysis;
  error?: string;
};

export async function waitForAnalysis(
  jobId: string,
  update: (p: AnalysisProgress) => void,
): Promise<Analysis> {
  sessionStorage.setItem("detect-active-job", jobId);
  for (;;) {
    let state: JobState;
    try {
      state = await request<JobState>(`/api/jobs/${jobId}`);
    } catch (error) {
      if (
        error instanceof Error &&
        error.message.includes("Job expired or missing")
      )
        sessionStorage.removeItem("detect-active-job");
      throw error;
    }
    if (state.status === "failed") {
      sessionStorage.removeItem("detect-active-job");
      throw new Error(state.error || "Analysis failed.");
    }
    if (state.status === "complete" && state.result) {
      sessionStorage.removeItem("detect-active-job");
      return state.result;
    }
    update({
      phase: "analysis",
      fraction: state.progress,
      message: state.message,
    });
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

export async function uploadCapture(
  body: FormData,
  update: (p: AnalysisProgress) => void,
): Promise<Analysis> {
  const response = await new Promise<{
    status: number;
    body: Analysis & {
      status_url?: string;
      detail?: string | { message: string };
    };
  }>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/analyze");
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) =>
      update({
        phase: "upload",
        fraction: e.lengthComputable ? e.loaded / e.total : null,
        message: `Uploading capture: ${(e.loaded / 1024 / 1024).toFixed(1)}${e.lengthComputable ? ` / ${(e.total / 1024 / 1024).toFixed(1)}` : ""} MiB`,
      });
    xhr.upload.onload = () =>
      update({
        phase: "analysis",
        fraction: null,
        message:
          "Upload transferred. Server is storing and validating the capture…",
      });
    xhr.onerror = () =>
      reject(
        new Error("Upload connection failed. Check the backend and retry."),
      );
    xhr.onload = () => resolve({ status: xhr.status, body: xhr.response });
    xhr.send(body);
  });
  if (response.status >= 400 || !response.body) {
    const detail = response.body?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.message || `Upload failed (${response.status}).`,
    );
  }
  if (response.status === 202)
    return waitForAnalysis(response.body.job_id, update);
  return response.body;
}
