import { useState } from 'react';
import { ArrowLeft, Cpu } from 'lucide-react';
import type { Analysis } from '../api';
import type { Detection, SpectrogramResponse } from './types';
import { FftPlot } from './FftPlot';
import { Waterfall } from './Waterfall';
import { DetectionDetailPanel } from './DetectionDetailPanel';
import { DecodeScreen } from './DecodeScreen';
import { formatFreq, formatTime, formatConfidence } from './format';

type Spectrum = SpectrogramResponse | null;

export function AnalysisPage({ analysis, detection, spectrum, psd, freqMin, freqMax, dbMin, dbMax, sampleRate, onBack }: {
  analysis: Analysis;
  detection: Detection;
  spectrum: Spectrum;
  psd: { freqs: number[]; magnitudes: number[] } | null;
  freqMin: number; freqMax: number; dbMin: number; dbMax: number;
  sampleRate: number;
  onBack: () => void;
}) {
  const [decoding, setDecoding] = useState(false);
  if (decoding) return <DecodeScreen analysis={analysis} detection={detection} sampleRate={sampleRate} onBack={() => setDecoding(false)} />;

  const cf = (detection.freq_lower_hz + detection.freq_upper_hz) / 2;
  const bw = detection.freq_upper_hz - detection.freq_lower_hz;

  return (
    <div className="analysis-page">
      <div className="analysis-topbar">
        <button onClick={onBack}><ArrowLeft size={13} />Back to Dashboard</button>
        <div className="analysis-summary">
          <span>C{Number(detection.id) + 1}</span>
          <span>{formatFreq(cf)} · {formatFreq(bw)}</span>
          <span>{formatTime(detection.start_sample / sampleRate)}–{formatTime(detection.end_sample / sampleRate)}</span>
          <span>{formatConfidence(detection.confidence)} confidence</span>
          {detection.needs_review && <span className="analysis-flag">Needs review</span>}
        </div>
        <button className="primary" onClick={() => setDecoding(true)}><Cpu size={13} />Decode</button>
      </div>
      <div className="analysis-body">
        <div className="analysis-plots">
          <section className="fft-section"><div className="plot-title">FFT / PSD<span>Welch · {analysis.metadata.power_unit}</span></div>
            <FftPlot psdData={psd} noiseFloorDb={analysis.noise_floor_db} thresholdDb={analysis.threshold_db} thresholdLabel="Applied threshold" onThresholdChange={() => {}} detections={[detection]} selectedDetectionId={detection.id} onSelectDetection={() => {}} freqMin={freqMin} freqMax={freqMax} dbMin={dbMin} dbMax={dbMax} onCursorMove={() => {}} height={220} />
          </section>
          <section className="waterfall-section analysis-waterfall"><div className="waterfall-main">
            <div className="plot-title">Waterfall<span>{analysis.settings.nfft} FFT · {(sampleRate / analysis.settings.nfft).toFixed(3)} Hz/bin</span></div>
            <div className="waterfall-canvas"><Waterfall spectrogram={spectrum} detections={[detection]} selectedDetectionId={detection.id} onSelectDetection={() => {}} freqMin={freqMin} freqMax={freqMax} onCursorMove={() => {}} sampleRate={sampleRate} totalSamples={analysis.metadata.sample_count} jumpTo={null} playheadTime={null} /></div>
          </div></section>
        </div>
        <aside className="analysis-side">
          <div className="dock-toggle" style={{ pointerEvents: 'none' }}>Detection Parameters</div>
          <DetectionDetailPanel detection={detection} sampleRate={sampleRate} jobId={analysis.job_id} />
        </aside>
      </div>
    </div>
  );
}
