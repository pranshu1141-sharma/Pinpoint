import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ArrowLeft, Check, Copy, Download } from 'lucide-react';
import { request, type Analysis, type Envelope } from '../api';
import type { Detection } from './types';
import { PulsePlot } from '../components/Plots';
import { formatFreq, formatTime, formatSamples, formatConfidence } from './format';

function buildLog(analysis: Analysis, detection: Detection): string[] {
  const base = analysis.pipeline_log.slice(-6);
  return [
    ...base,
    `decode: candidate C${Number(detection.id) + 1} selected for symbol readout`,
    `decode: modulation family = ${detection.modulation_family ?? 'unresolved'}`,
    `decode: fine label = ${detection.fine_modulation_label ?? detection.fine_modulation_status ?? 'not reliably classified'}`,
    detection.symbol_rate_hz != null
      ? `decode: symbol rate = ${detection.symbol_rate_hz.toFixed(2)} Hz`
      : `decode: symbol rate — ${detection.symbol_rate_status ?? 'not attempted'}`,
    'decode: assembling summary from Detect/Estimate/Classify results',
  ];
}

export function DecodeScreen({ analysis, detection, sampleRate, onBack }: {
  analysis: Analysis; detection: Detection; sampleRate: number; onBack: () => void;
}) {
  const log = useRef(buildLog(analysis, detection)).current;
  const [shown, setShown] = useState(0);
  const [copied, setCopied] = useState(false);
  const done = shown >= log.length;
  const envelope = useQuery({
    queryKey: ['envelope', analysis.job_id, detection.id],
    queryFn: () => request<Envelope>(`/api/detections/${analysis.job_id}/${detection.id}/envelope`),
    enabled: !!detection.is_pulsed && done,
  });

  useEffect(() => {
    if (done) return;
    const t = setTimeout(() => setShown((v) => v + 1), 320);
    return () => clearTimeout(t);
  }, [shown, done]);

  const summary = {
    candidate: `C${Number(detection.id) + 1}`,
    modulation_family: detection.modulation_family,
    fine_modulation_label: detection.fine_modulation_label,
    fine_modulation_status: detection.fine_modulation_status,
    symbol_rate_hz: detection.symbol_rate_hz,
    symbol_rate_status: detection.symbol_rate_status,
    confidence: detection.confidence,
    center_frequency_hz: detection.center_frequency_refined_hz ?? detection.center_frequency_hz,
    freq_lower_hz: detection.freq_lower_hz,
    freq_upper_hz: detection.freq_upper_hz,
    start_sample: detection.start_sample,
    end_sample: detection.end_sample,
    is_pulsed: detection.is_pulsed,
    pulse_width_samples: detection.pulse_width_samples,
    pri_samples: detection.pri_samples,
  };

  function save() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(summary, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url; a.download = `${analysis.job_id}-C${Number(detection.id) + 1}-decode.json`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="decode-screen">
      <div className="decode-topbar">
        <button onClick={onBack}><ArrowLeft size={13} />Back to Analysis</button>
        <span>Decode — C{Number(detection.id) + 1}</span>
      </div>
      <div className="scope-note"><AlertTriangle size={12} /><span>Mock preview: assembles existing Detect/Estimate/Classify results. Real demodulation is not implemented in this version.</span></div>

      {!done ? (
        <div className="decode-loading">
          <div className="decode-status">Decoding candidate C{Number(detection.id) + 1}…</div>
          <div className="decode-progress"><div className="decode-progress-fill" style={{ width: `${(shown / log.length) * 100}%` }} /></div>
          <div className="decode-console">
            {log.slice(0, shown).map((line, i) => <div key={i} className="decode-console-line">{line}</div>)}
            <div className="decode-console-cursor">▋</div>
          </div>
        </div>
      ) : (
        <div className="decode-output">
          <div className="decode-cards">
            <div className="decode-card"><span>Modulation</span><strong>{summary.fine_modulation_label ?? summary.fine_modulation_status ?? 'not reliably classified'}</strong></div>
            <div className="decode-card"><span>Symbol Rate</span><strong>{summary.symbol_rate_hz != null ? `${summary.symbol_rate_hz.toFixed(2)} Hz` : (summary.symbol_rate_status ?? 'not attempted')}</strong></div>
            <div className="decode-card"><span>Confidence</span><strong>{formatConfidence(summary.confidence)}</strong></div>
            <div className="decode-card"><span>Center Frequency</span><strong>{summary.center_frequency_hz != null ? formatFreq(summary.center_frequency_hz) : 'n/a'}</strong></div>
            <div className="decode-card"><span>Frequency Bounds</span><strong>{formatFreq(summary.freq_lower_hz)} – {formatFreq(summary.freq_upper_hz)}</strong></div>
            <div className="decode-card"><span>Samples</span><strong>{formatSamples(summary.start_sample)} – {formatSamples(summary.end_sample)}</strong></div>
            {detection.is_pulsed && <div className="decode-card"><span>Pulse Width / PRI</span><strong>{detection.pulse_width_samples ?? '—'} / {detection.pri_samples ?? '—'} samples</strong></div>}
          </div>

          {detection.is_pulsed && envelope.data && (
            <div className="wave-panel decode-envelope">
              <div className="plot-title">Envelope<span>PW {formatSamples(detection.pulse_width_samples ?? 0)} · PRI {formatSamples(detection.pri_samples ?? 0)}</span></div>
              <PulsePlot data={envelope.data} detection={detection} rate={sampleRate} />
            </div>
          )}

          <div className="wave-panel decode-json">
            <div className="plot-title">Decode Summary — JSON
              <button onClick={async () => { try { await navigator.clipboard.writeText(JSON.stringify(summary, null, 2)); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard unavailable */ } }}>{copied ? <Check size={11} /> : <Copy size={11} />}Copy</button>
              <button onClick={save}><Download size={11} />Download</button>
            </div>
            <pre>{JSON.stringify(summary, null, 2)}</pre>
          </div>

          <div className="decode-actions">
            <button onClick={onBack}><ArrowLeft size={13} />Back to Analysis</button>
            <button className="primary" onClick={save}><Download size={13} />Export decode.json</button>
          </div>
        </div>
      )}
    </div>
  );
}
