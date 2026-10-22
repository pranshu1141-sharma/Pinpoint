import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ArrowLeft, Check, Copy, Download } from 'lucide-react';
import { request, type Analysis, type DecodeResult, type Envelope } from '../api';
import type { Detection } from './types';
import { PulsePlot } from '../components/Plots';
import { formatFreq, formatSamples } from './format';

// Rendering 20,000 spans is slow and unreadable; the download carries every returned symbol.
const DISPLAY_LIMIT = 4096;
const ROW = 64;

export function formatSymbolRows(indices: number[], limit = DISPLAY_LIMIT): string[] {
  const rows: string[] = [];
  const shown = indices.slice(0, limit);
  for (let i = 0; i < shown.length; i += ROW) {
    const row = shown.slice(i, i + ROW).join('');
    rows.push(`${String(i).padStart(6, ' ')}  ${row.replace(/(.{8})(?=.)/g, '$1 ')}`);
  }
  return rows;
}

export function decodeSummary(detection: Detection, result: DecodeResult) {
  return {
    candidate: `C${Number(detection.id) + 1}`,
    modulation_label: detection.modulation_label ?? null,
    verify_status: detection.verify_status ?? null,
    symbol_rate_hz: detection.symbol_rate_hz ?? null,
    center_frequency_hz: detection.center_frequency_refined_hz ?? detection.center_frequency_hz ?? null,
    freq_lower_hz: detection.freq_lower_hz,
    freq_upper_hz: detection.freq_upper_hz,
    start_sample: detection.start_sample,
    end_sample: detection.end_sample,
    ...result,
  };
}

export function DecodeResultView({ detection, result }: { detection: Detection; result: DecodeResult }) {
  const decoded = result.decoded_symbol_indices !== null;
  const indices = result.decoded_symbol_indices ?? [];
  const returned = indices.length;
  const modulus = result.decode_rotation_ambiguity_modulus;
  const unit = result.decode_label === 'fsk2' || result.decode_label === 'ask2' ? 'bits' : 'symbols';
  const preview = { ...decodeSummary(detection, result),
    decoded_symbol_indices: decoded ? `[${returned} values — use Download]` : null };

  return (
    <>
      <div className={`decode-verdict ${decoded ? 'ok' : 'declined'}`}>
        <strong>{decoded ? `Decoded ${result.decoded_symbol_count?.toLocaleString()} ${unit}` : 'Not decoded'}</strong>
        <span>{result.decode_status}</span>
      </div>
      <div className="decode-cards">
        <div className="decode-card"><span>Published label</span><strong>{detection.modulation_label ?? detection.verify_status ?? 'not reliably estimated'}</strong></div>
        <div className="decode-card"><span>Decoder</span><strong>{result.decode_label?.toUpperCase() ?? 'none'}</strong></div>
        <div className="decode-card"><span>Symbol rate</span><strong>{detection.symbol_rate_hz != null ? `${detection.symbol_rate_hz.toFixed(2)} Hz` : (detection.symbol_rate_status ?? 'not published')}</strong></div>
        <div className="decode-card"><span>Decode confidence</span><strong>{result.decode_confidence != null ? result.decode_confidence.toFixed(3) : '—'}</strong></div>
        <div className="decode-card"><span>Ambiguity</span><strong>{modulus != null ? `rotation mod ${modulus} + start offset` : '—'}</strong></div>
        <div className="decode-card"><span>Frequency bounds</span><strong>{formatFreq(detection.freq_lower_hz)} – {formatFreq(detection.freq_upper_hz)}</strong></div>
        <div className="decode-card"><span>Samples</span><strong>{formatSamples(detection.start_sample)} – {formatSamples(detection.end_sample)}</strong></div>
      </div>
      {decoded && (
        <div className="wave-panel decode-stream">
          <div className="plot-title">Recovered {unit}
            <span>{Math.min(returned, DISPLAY_LIMIT).toLocaleString()} of {result.decoded_symbol_count?.toLocaleString()} shown{result.decoded_symbols_truncated ? ` · download holds the first ${returned.toLocaleString()}` : ''}</span>
          </div>
          <pre>{formatSymbolRows(indices).join('\n')}</pre>
        </div>
      )}
      <div className="wave-panel decode-json">
        <div className="plot-title">Decode result — JSON</div>
        <pre>{JSON.stringify(preview, null, 2)}</pre>
      </div>
    </>
  );
}

export function DecodeScreen({ analysis, detection, sampleRate, onBack }: {
  analysis: Analysis; detection: Detection; sampleRate: number; onBack: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const decode = useQuery({
    queryKey: ['decode', analysis.job_id, detection.id],
    queryFn: () => request<DecodeResult>(`/api/detections/${analysis.job_id}/${detection.id}/decode`, { method: 'POST' }),
    staleTime: Infinity,
    retry: false,
  });
  const envelope = useQuery({
    queryKey: ['envelope', analysis.job_id, detection.id],
    queryFn: () => request<Envelope>(`/api/detections/${analysis.job_id}/${detection.id}/envelope`),
    enabled: !!detection.is_pulsed,
  });
  const summaryText = decode.data ? JSON.stringify(decodeSummary(detection, decode.data), null, 2) : '';

  function save() {
    const url = URL.createObjectURL(new Blob([summaryText], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url; a.download = `${analysis.job_id}-C${Number(detection.id) + 1}-decode.json`; a.click();
    URL.revokeObjectURL(url);
  }

  async function copy() {
    try { await navigator.clipboard.writeText(summaryText); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { /* clipboard unavailable */ }
  }

  return (
    <div className="decode-screen">
      <div className="decode-topbar">
        <button onClick={onBack}><ArrowLeft size={13} />Back to Analysis</button>
        <span>Decode — C{Number(detection.id) + 1}</span>
      </div>
      <div className="scope-note"><AlertTriangle size={12} /><span>Symbol/bit recovery only, from the verify estimator's published label. The stream is relative: correct up to an unknown rotation (or polarity) and an unknown start offset. No framing, protocol or message decoding. Validated on synthetic signals only.</span></div>

      {decode.isPending ? (
        <div className="decode-loading">
          <div className="decode-status">Recovering symbol timing for C{Number(detection.id) + 1}…</div>
          <div className="decode-progress"><div className="decode-progress-fill indeterminate" /></div>
        </div>
      ) : decode.isError ? (
        <div className="decode-output">
          <div className="decode-verdict declined"><strong>Decode request failed</strong><span>{decode.error.message}</span></div>
          <div className="decode-actions"><button onClick={() => decode.refetch()}>Retry</button></div>
        </div>
      ) : (
        <div className="decode-output">
          <DecodeResultView detection={detection} result={decode.data} />
          {detection.is_pulsed && envelope.data && (
            <div className="wave-panel decode-envelope">
              <div className="plot-title">Envelope<span>PW {formatSamples(detection.pulse_width_samples ?? 0)} · PRI {formatSamples(detection.pri_samples ?? 0)}</span></div>
              <PulsePlot data={envelope.data} detection={detection} rate={sampleRate} />
            </div>
          )}
          <div className="decode-actions">
            <button onClick={onBack}><ArrowLeft size={13} />Back to Analysis</button>
            <button onClick={copy}>{copied ? <Check size={13} /> : <Copy size={13} />}Copy JSON</button>
            <button className="primary" onClick={save}><Download size={13} />Export decode.json</button>
          </div>
        </div>
      )}
    </div>
  );
}
