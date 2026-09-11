import type {
  AnalyzeResponse,
  Detection,
  SpectrogramResponse,
  DetectionLayersResponse,
  FileInfo,
} from './types';

const SAMPLE_RATE = 2_000_000;
const DURATION_S = 0.5;
const TOTAL_SAMPLES = SAMPLE_RATE * DURATION_S;
const FFT_SIZE = 512;
const TIME_BINS = 256;

export function generateMockAnalyze(file: File): AnalyzeResponse {
  const detections: Detection[] = [
    {
      id: 'det-001',
      start_sample: 120_000,
      end_sample: 340_000,
      freq_lower_hz: -125_000,
      freq_upper_hz: -75_000,
      confidence: 0.87,
      detection_method: 'adaptive_threshold',
      is_pulsed: false,
      pulse_width_samples: null,
      pri_samples: null,
      needs_review: false,
    },
    {
      id: 'det-002',
      start_sample: 480_000,
      end_sample: 520_000,
      freq_lower_hz: 40_000,
      freq_upper_hz: 60_000,
      confidence: 0.62,
      detection_method: 'adaptive_threshold',
      is_pulsed: true,
      pulse_width_samples: 200,
      pri_samples: 10_000,
      needs_review: false,
    },
    {
      id: 'det-003',
      start_sample: 700_000,
      end_sample: 950_000,
      freq_lower_hz: 150_000,
      freq_upper_hz: 200_000,
      confidence: 0.41,
      detection_method: 'adaptive_threshold',
      is_pulsed: false,
      pulse_width_samples: null,
      pri_samples: null,
      needs_review: true,
    },
    {
      id: 'det-004',
      start_sample: 15_000,
      end_sample: 45_000,
      freq_lower_hz: 300_000,
      freq_upper_hz: 340_000,
      confidence: 0.73,
      detection_method: 'adaptive_threshold',
      is_pulsed: false,
      pulse_width_samples: null,
      pri_samples: null,
      needs_review: false,
    },
    {
      id: 'det-005',
      start_sample: 600_000,
      end_sample: 610_000,
      freq_lower_hz: -200_000,
      freq_upper_hz: -180_000,
      confidence: 0.55,
      detection_method: 'adaptive_threshold',
      is_pulsed: true,
      pulse_width_samples: 500,
      pri_samples: 5_000,
      needs_review: false,
    },
    {
      id: 'det-006',
      start_sample: 850_000,
      end_sample: 990_000,
      freq_lower_hz: -50_000,
      freq_upper_hz: -10_000,
      confidence: 0.34,
      detection_method: 'adaptive_threshold',
      is_pulsed: false,
      pulse_width_samples: null,
      pri_samples: null,
      needs_review: true,
    },
  ];

  return {
    job_id: 'mock-job-' + Date.now(),
    detections,
    noise_floor_db: -92.3,
    pipeline_log: [
      `[${new Date().toISOString()}] Pipeline started`,
      `Loaded file: ${file.name}`,
      `File size: ${(file.size / 1e6).toFixed(2)} MB`,
      `Sample rate: ${SAMPLE_RATE} Hz`,
      `Duration: ${DURATION_S} s (${TOTAL_SAMPLES.toLocaleString()} samples)`,
      '---',
      '[Stage 1] Preprocessing',
      '  DC offset removal: -0.0021 (I), +0.0003 (Q)',
      '  IQ balance correction applied',
      '---',
      '[Stage 2] Spectral Estimation',
      `  Computing FFT (N=${FFT_SIZE}, window=Hamming)...`,
      '  Overlap: 75%',
  `  Time resolution: ${(DURATION_S / TIME_BINS * 1000).toFixed(2)} ms/bin`,
  `  Freq resolution: ${(SAMPLE_RATE / FFT_SIZE).toFixed(0)} Hz/bin`,
      '---',
      '[Stage 3] Noise Floor Estimation',
      '  Method: median absolute deviation (MAD)',
      '  Estimated noise floor: -92.3 dBm',
      '  Noise variance: 4.2 dB',
      '---',
      '[Stage 4] Adaptive Thresholding',
      '  Base threshold: noise_floor + 15 dB = -77.3 dBm',
      '  CFAR window: 32 bins (guard), 64 bins (reference)',
      '  Effective threshold: -75.0 dBm',
      '---',
      '[Stage 5] Detection & Clustering',
      '  Scanning for candidate regions above threshold...',
      '  det-001: freq=[-125.0k, -75.0k] Hz, time=[0.060, 0.170] s, conf=0.87',
      '  det-002: freq=[40.0k, 60.0k] Hz, time=[0.240, 0.260] s, conf=0.62, PULSED (pw=200, pri=10000)',
      '  det-003: freq=[150.0k, 200.0k] Hz, time=[0.350, 0.475] s, conf=0.41, NEEDS REVIEW',
      '  det-004: freq=[300.0k, 340.0k] Hz, time=[0.008, 0.023] s, conf=0.73',
      '  det-005: freq=[-200.0k, -180.0k] Hz, time=[0.300, 0.305] s, conf=0.55, PULSED (pw=500, pri=5000)',
      '  det-006: freq=[-50.0k, -10.0k] Hz, time=[0.425, 0.495] s, conf=0.34, NEEDS REVIEW',
      '---',
      '[Stage 6] Post-processing',
      '  Merging adjacent detections (gap < 8 bins)...',
      '  Pruning detections below min_duration (4 bins)...',
      '  Final detection count: 6',
      '---',
      `Pipeline complete in 847 ms. 6 detections found (2 pulsed, 2 needs review).`,
    ],
    sample_rate: SAMPLE_RATE,
    duration_seconds: DURATION_S,
    filename: file.name,
  };
}

export function generateMockSpectrogram(): SpectrogramResponse {
  const freqBins: number[] = [];
  for (let i = 0; i < FFT_SIZE; i++) {
    freqBins.push(-SAMPLE_RATE / 2 + (i / FFT_SIZE) * SAMPLE_RATE);
  }

  const timeBins: number[] = [];
  for (let i = 0; i < TIME_BINS; i++) {
    timeBins.push((i / TIME_BINS) * DURATION_S);
  }

  const magnitude2d: number[][] = [];
  for (let t = 0; t < TIME_BINS; t++) {
    const row: number[] = [];
    const timeProgress = t / TIME_BINS;

    for (let f = 0; f < FFT_SIZE; f++) {
      let mag = -92 + Math.random() * 6;

      // Detection 1: -125kHz to -75kHz, time 0.06 - 0.17
      if (freqBins[f] >= -125_000 && freqBins[f] <= -75_000) {
        if (timeProgress >= 0.06 && timeProgress <= 0.17) {
          const centerF = (-125_000 + -75_000) / 2;
          const distF = Math.abs(freqBins[f] - centerF) / 25_000;
          mag = -40 - distF * 15 + Math.random() * 3;
        }
      }

      // Detection 2: 40kHz-60kHz, time 0.24 - 0.26, pulsed
      if (freqBins[f] >= 40_000 && freqBins[f] <= 60_000) {
        if (timeProgress >= 0.24 && timeProgress <= 0.26) {
          const pulsePhase = (t % 10) / 10;
          if (pulsePhase < 0.3) {
            mag = -35 + Math.random() * 3;
          }
        }
      }

      // Detection 3: 150kHz-200kHz, time 0.35 - 0.475
      if (freqBins[f] >= 150_000 && freqBins[f] <= 200_000) {
        if (timeProgress >= 0.35 && timeProgress <= 0.475) {
          mag = -55 + Math.random() * 5;
        }
      }

      // Detection 4: 300kHz-340kHz, time 0.008 - 0.023
      if (freqBins[f] >= 300_000 && freqBins[f] <= 340_000) {
        if (timeProgress >= 0.008 && timeProgress <= 0.023) {
          const centerF = 320_000;
          const distF = Math.abs(freqBins[f] - centerF) / 20_000;
          mag = -45 - distF * 10 + Math.random() * 3;
        }
      }

      // Detection 5: -200kHz to -180kHz, time 0.300 - 0.305, pulsed
      if (freqBins[f] >= -200_000 && freqBins[f] <= -180_000) {
        if (timeProgress >= 0.30 && timeProgress <= 0.305) {
          mag = -38 + Math.random() * 3;
        }
      }

      // Detection 6: -50kHz to -10kHz, time 0.425 - 0.495
      if (freqBins[f] >= -50_000 && freqBins[f] <= -10_000) {
        if (timeProgress >= 0.425 && timeProgress <= 0.495) {
          const centerF = -30_000;
          const distF = Math.abs(freqBins[f] - centerF) / 20_000;
          mag = -60 - distF * 8 + Math.random() * 4;
        }
      }

      row.push(mag);
    }
    magnitude2d.push(row);
  }

  return { time_bins: timeBins, freq_bins: freqBins, magnitude_2d: magnitude2d };
}

export function generateMockLayers(detectionId: string): DetectionLayersResponse {
  const detectionMap: Record<string, Array<{ name: string; description: string; available: boolean; freq: number; bw: number }>> = {
    'det-001': [
      { name: 'Raw Baseband Capture', description: 'Original IQ samples for the detection region', available: true, freq: -100_000, bw: 50_000 },
      { name: 'Isolated Band', description: 'Bandpass-filtered to detection frequency range (-125 kHz to -75 kHz)', available: true, freq: -100_000, bw: 50_000 },
      { name: 'Magnitude Envelope', description: 'AM-demodulated envelope of isolated signal', available: true, freq: -100_000, bw: 50_000 },
      { name: 'Instantaneous Frequency', description: 'FM-demodulated frequency trace', available: false, freq: -100_000, bw: 50_000 },
    ],
    'det-002': [
      { name: 'Raw Baseband Capture', description: 'Original IQ samples for the detection region', available: true, freq: 50_000, bw: 20_000 },
      { name: 'Isolated Band', description: 'Bandpass-filtered to detection frequency range (40 kHz to 60 kHz)', available: true, freq: 50_000, bw: 20_000 },
      { name: 'Pulse Profile', description: 'Individual pulse extraction and PRI measurement (pw=200 samples, pri=10000 samples)', available: true, freq: 50_000, bw: 20_000 },
      { name: 'Magnitude Envelope', description: 'AM-demodulated envelope of isolated signal', available: false, freq: 50_000, bw: 20_000 },
    ],
    'det-003': [
      { name: 'Raw Baseband Capture', description: 'Original IQ samples for the detection region', available: true, freq: 175_000, bw: 50_000 },
      { name: 'Isolated Band', description: 'Bandpass-filtered to detection frequency range (150 kHz to 200 kHz)', available: true, freq: 175_000, bw: 50_000 },
      { name: 'Magnitude Envelope', description: 'AM-demodulated envelope of isolated signal', available: false, freq: 175_000, bw: 50_000 },
      { name: 'Instantaneous Frequency', description: 'FM-demodulated frequency trace', available: false, freq: 175_000, bw: 50_000 },
    ],
    'det-004': [
      { name: 'Raw Baseband Capture', description: 'Original IQ samples for the detection region', available: true, freq: 320_000, bw: 40_000 },
      { name: 'Isolated Band', description: 'Bandpass-filtered to detection frequency range (300 kHz to 340 kHz)', available: true, freq: 320_000, bw: 40_000 },
      { name: 'Magnitude Envelope', description: 'AM-demodulated envelope of isolated signal', available: true, freq: 320_000, bw: 40_000 },
      { name: 'Instantaneous Frequency', description: 'FM-demodulated frequency trace', available: false, freq: 320_000, bw: 40_000 },
    ],
    'det-005': [
      { name: 'Raw Baseband Capture', description: 'Original IQ samples for the detection region', available: true, freq: -190_000, bw: 20_000 },
      { name: 'Isolated Band', description: 'Bandpass-filtered to detection frequency range (-200 kHz to -180 kHz)', available: true, freq: -190_000, bw: 20_000 },
      { name: 'Pulse Profile', description: 'Individual pulse extraction and PRI measurement (pw=500 samples, pri=5000 samples)', available: true, freq: -190_000, bw: 20_000 },
      { name: 'Magnitude Envelope', description: 'AM-demodulated envelope of isolated signal', available: false, freq: -190_000, bw: 20_000 },
    ],
    'det-006': [
      { name: 'Raw Baseband Capture', description: 'Original IQ samples for the detection region', available: true, freq: -30_000, bw: 40_000 },
      { name: 'Isolated Band', description: 'Bandpass-filtered to detection frequency range (-50 kHz to -10 kHz)', available: true, freq: -30_000, bw: 40_000 },
      { name: 'Magnitude Envelope', description: 'AM-demodulated envelope of isolated signal', available: false, freq: -30_000, bw: 40_000 },
      { name: 'Instantaneous Frequency', description: 'FM-demodulated frequency trace', available: false, freq: -30_000, bw: 40_000 },
    ],
  };

  const layerDefs = detectionMap[detectionId] || detectionMap['det-001'];

  const layers = layerDefs.map((def) => {
    const sampleCount = 2000;
    const waveform: number[] = [];
    for (let i = 0; i < sampleCount; i++) {
      const t = i / sampleCount;
      let val: number;
      if (def.name === 'Raw Baseband Capture') {
        val = Math.sin(t * Math.PI * 20 * Math.abs(def.freq) / 50_000) * 0.6 + (Math.random() - 0.5) * 0.3;
      } else if (def.name === 'Isolated Band') {
        val = Math.sin(t * Math.PI * 16) * 0.7 + (Math.random() - 0.5) * 0.15;
      } else if (def.name === 'Pulse Profile') {
        const pulseT = (t * 5) % 1;
        val = pulseT < 0.2 ? Math.sin(pulseT * Math.PI * 5) * 0.8 : 0;
      } else if (def.name === 'Magnitude Envelope') {
        val = Math.abs(Math.sin(t * Math.PI * 4)) * 0.6 + (Math.random() - 0.5) * 0.1;
      } else {
        val = Math.sin(t * Math.PI * 8) * 0.5 + (Math.random() - 0.5) * 0.2;
      }
      waveform.push(val);
    }

    return {
      name: def.name,
      description: def.description,
      waveform: def.available ? waveform : [],
      audio_url: null,
      available: def.available,
    };
  });

  return { layers };
}

export function getMockFileInfo(file: File): FileInfo {
  return {
    filename: file.name,
    sampleRate: SAMPLE_RATE,
    durationSeconds: DURATION_S,
    totalSamples: TOTAL_SAMPLES,
    fileSize: `${(file.size / 1e6).toFixed(2)} MB`,
    format: file.name.endsWith('.wav') ? 'WAV IQ' : file.name.endsWith('.cf32') ? 'Complex Float32' : file.name.endsWith('.iq') ? 'Raw IQ' : 'Unknown',
  };
}
