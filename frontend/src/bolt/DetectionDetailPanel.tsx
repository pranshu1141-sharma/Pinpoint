import { Fragment, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Info } from 'lucide-react';
import type { Detection } from './types';
import { formatFreq, formatTime, formatSamples, formatConfidence } from './format';
import { request, type SymbolRateDiagnostic } from '../api';

interface DetectionDetailPanelProps {
  detection: Detection | null;
  sampleRate: number;
  jobId?: string;
}

type Row = {
  key: string;
  value: string;
  color?: string;
  explain?: string;
  unreliable?: boolean;
};

const UNRELIABLE_PATTERN = /not reliably|not attempted|no phase|insufficient|unresolved/i;

function isUnreliable(text: string) {
  return UNRELIABLE_PATTERN.test(text);
}

const NOTES_KEY = 'detect-analyst-notes';

function loadNotes(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(NOTES_KEY) ?? '{}'); } catch { return {}; }
}

function saveNote(key: string, value: string) {
  try {
    const all = loadNotes();
    if (value.trim()) all[key] = value; else delete all[key];
    localStorage.setItem(NOTES_KEY, JSON.stringify(all));
  } catch { /* storage unavailable */ }
}

export function DetectionDetailPanel({ detection, sampleRate, jobId }: DetectionDetailPanelProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [symbolRateOpen, setSymbolRateOpen] = useState(false);
  const [modulationOpen, setModulationOpen] = useState(false);
  const noteKey = jobId && detection ? `${jobId}:${detection.id}` : null;
  const [note, setNote] = useState('');
  useEffect(() => { setNote(noteKey ? (loadNotes()[noteKey] ?? '') : ''); }, [noteKey]);

  const symbolRate = useQuery({
    queryKey: ['symbol-rate-diagnostic', jobId, detection?.id],
    queryFn: () => request<SymbolRateDiagnostic>(`/api/detections/${jobId}/${detection!.id}/symbol-rate-diagnostic`),
    enabled: symbolRateOpen && !!jobId && !!detection,
  });

  if (!detection) {
    return (
      <div className="flex items-center justify-center h-full text-rf-text-secondary text-[11px] p-4">
        Select a detection to view details.
      </div>
    );
  }

  const startTime = detection.start_sample / sampleRate;
  const endTime = detection.end_sample / sampleRate;
  const duration = endTime - startTime;
  const centerFreq = (detection.freq_lower_hz + detection.freq_upper_hz) / 2;
  const bandwidth = detection.freq_upper_hz - detection.freq_lower_hz;
  const sampleCount = detection.end_sample - detection.start_sample;
  const unavailable = detection.estimate_status === undefined
    ? 'Not attempted (this analysis)'
    : 'Not reliably estimated';
  const measurement = (value: number | null | undefined, unit: string) =>
    value == null ? unavailable : `${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${unit}`;
  const bandwidth99 = measurement(detection.bandwidth_99pct_hz, 'Hz');

  const rows: Row[] = [
    { key: 'ID', value: detection.id },
    { key: 'Method', value: detection.detection_method },
    { key: 'Confidence', value: `${formatConfidence(detection.confidence)} (heuristic)`,
      color: detection.confidence >= 0.7 ? '#5cb85c' : detection.confidence >= 0.5 ? '#d4d4d4' : '#cc3c34',
      explain: 'Heuristic score combining threshold excess and spectral occupancy. Not a calibrated probability; below 0.70 sets Needs Review.' },
    { key: 'Confidence (evidence-based)', value: detection.confidence_evidence_based == null ? unavailable : `${formatConfidence(detection.confidence_evidence_based)} (heuristic)`,
      explain: 'A second, independent heuristic: deviation of the power coefficient-of-variation from 1.0, the value expected for pure Gaussian noise. Not combined with Confidence above and does not affect Needs Review — the two can disagree, since they measure different things (amplitude threshold vs. distribution shape).' },
    { key: 'Needs Review', value: detection.needs_review ? 'Yes' : 'No', color: detection.needs_review ? '#cc3c34' : '#d4d4d4' },
    { key: 'Pulsed', value: detection.is_pulsed ? 'Yes' : 'No', color: detection.is_pulsed ? '#2a82da' : '#7f7f7f' },
    { key: 'Midpoint (Detect)', value: formatFreq(centerFreq),
      explain: 'Midpoint of the Detect-stage frequency band, before any downstream refinement.' },
    { key: 'Width (Detect)', value: formatFreq(bandwidth) },
    { key: 'Edges (Detect)', value: `${formatFreq(detection.freq_lower_hz)} to ${formatFreq(detection.freq_upper_hz)} (baseband)` },
    { key: 'Center (Estimate)', value: measurement(detection.center_frequency_hz, 'Hz'),
      explain: 'Power-weighted spectral centroid of the isolated segment’s Welch PSD.' },
    { key: 'Center (Refined)', value: measurement(detection.center_frequency_refined_hz, 'Hz'),
      explain: 'Sharpest of the M=2 (BPSK) / M=4 (QPSK) / M=8 (8PSK) raised-tone peaks on the Mth-power spectrum, divided by M. Only attempted for constant-envelope candidates.' },
    { key: 'Center reference', value: 'RF when tuning is known; otherwise baseband' },
    { key: 'Bandwidth (3 dB)', value: measurement(detection.bandwidth_3db_hz, 'Hz'),
      explain: 'Half-power width of the isolated segment’s measured spectrum around its centroid.' },
    { key: 'Bandwidth (99%)', value: detection.bandwidth_99pct_caveat ? `${bandwidth99} — ${detection.bandwidth_99pct_caveat}` : bandwidth99,
      explain: 'Width containing 99% of the isolated segment’s spectral energy; wider than 3 dB by definition.' },
    { key: 'SNR (full-band)', value: measurement(detection.snr_db, 'dB'),
      explain: '10·log₁₀((P_on−P_off)/P_off) over all raw occupied samples against the capture-level Welch noise density.' },
    { key: 'Estimate status', value: detection.estimate_status ?? unavailable },
    { key: 'Modulation family', value: detection.modulation_family ?? unavailable,
      explain: 'Constant vs. varying envelope from the isolated segment’s amplitude coefficient of variation; threshold 0.30.' },
    { key: 'Family confidence', value: detection.modulation_confidence == null ? unavailable : `${formatConfidence(detection.modulation_confidence)} (heuristic)`,
      explain: 'Heuristic distance from the 0.30 envelope-variation threshold, not a calibrated probability.' },
    { key: 'Refinement status', value: detection.refinement_status ?? unavailable },
    { key: 'Fine modulation', value: detection.fine_modulation_label ?? 'Not reliably estimated',
      explain: 'PSK (bpsk/qpsk/8psk) published only when the Mth-power phase-cluster circular spread clears an order-specific threshold. ASK/FSK use discrete-level clustering (envelope for ASK, instantaneous frequency for FSK) instead, since neither produces a PSK raised tone. QAM is published only as a low-confidence, order-unresolved flag — this project has no symbol-timing recovery to determine a specific QAM order. Pulsed candidates are excluded from all of these (a gated carrier has trivially perfect phase concentration).' },
    { key: 'Envelope levels', value: detection.envelope_level_count == null ? unavailable : String(detection.envelope_level_count),
      explain: 'Number of clustered amplitude levels found for ASK/QAM candidates (gap-to-within-cluster-spread heuristic).' },
    { key: 'Frequency levels', value: detection.frequency_level_count == null ? unavailable : String(detection.frequency_level_count),
      explain: 'Number of clustered instantaneous-frequency levels found for FSK candidates.' },
    { key: 'Symbol rate', value: detection.symbol_rate_hz == null ? (detection.symbol_rate_status == null || detection.symbol_rate_status.includes('not attempted') ? 'Not attempted' : 'Not reliably estimated') : measurement(detection.symbol_rate_hz, 'Hz'),
      explain: 'Lowest spectral peak within 3 dB of the differentiated-and-squared segment’s global maximum, excluding the first 4 DC-leakage bins. Requires a confirmed PSK or ASK fine label and SNR ≥ 4.5 dB — not published for FSK (this nonlinearity does not recover its rate) or QAM (no confirmed order).' },
    { key: 'Start Time', value: `${formatTime(startTime)} (${formatSamples(detection.start_sample)})` },
    { key: 'End Time', value: `${formatTime(endTime)} (${formatSamples(detection.end_sample)})` },
    { key: 'Duration', value: `${formatTime(duration)} (${formatSamples(sampleCount)})` },
  ];

  if (detection.is_pulsed && detection.pulse_width_samples !== null) {
    rows.push({ key: 'Pulse Width', value: `${formatSamples(detection.pulse_width_samples)} (${formatTime(detection.pulse_width_samples / sampleRate)})` });
  }
  if (detection.is_pulsed && detection.pri_samples !== null) {
    rows.push({ key: 'PRI', value: `${formatSamples(detection.pri_samples)} (${formatTime(detection.pri_samples / sampleRate)})` });
    const prf = sampleRate / detection.pri_samples;
    rows.push({ key: 'PRF', value: `${prf.toFixed(1)} Hz` });
  }

  const toggle = (key: string) => setExpanded((prev) => {
    const next = new Set(prev);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  return (
    <div className="overflow-auto h-full p-2">
      <table className="w-full text-[11px] border-collapse">
        <tbody>
          {rows.map((row) => {
            const unreliable = isUnreliable(row.value);
            const open = expanded.has(row.key);
            return (
              <Fragment key={row.key}>
                <tr className="border-b border-rf-border last:border-0">
                  <td className="py-1.5 pr-2 text-rf-text-secondary text-[10px] uppercase tracking-wide whitespace-nowrap align-top">
                    {row.key}
                  </td>
                  <td className={`py-1.5 font-mono tabular-nums break-words ${unreliable ? 'detail-unreliable' : ''}`} style={{ color: unreliable ? undefined : row.color ?? '#d4d4d4' }}>
                    <span>{row.value}</span>
                    {row.explain && (
                      <button
                        className="detail-explain-toggle"
                        aria-expanded={open}
                        aria-label={`Explain ${row.key}`}
                        title="Explain this number"
                        onClick={() => toggle(row.key)}
                      >
                        <Info size={11} />
                      </button>
                    )}
                  </td>
                </tr>
                {row.explain && open && (
                  <tr className="border-b border-rf-border last:border-0">
                    <td />
                    <td className="pb-2 pt-0 text-[10px] text-rf-text-secondary leading-relaxed">{row.explain}</td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>

      <div className="detail-notes">
        <label htmlFor="analyst-note">Analyst notes</label>
        <textarea
          id="analyst-note"
          placeholder="Notes for this candidate, saved in this browser…"
          value={note}
          disabled={!noteKey}
          onChange={(e) => { setNote(e.target.value); if (noteKey) saveNote(noteKey, e.target.value); }}
        />
      </div>

      <div className="detail-reveal">
        <button className="detail-reveal-toggle" aria-expanded={modulationOpen} onClick={() => setModulationOpen((v) => !v)}>
          {modulationOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          Modulation evidence: cumulant features + decision path
        </button>
        {modulationOpen && <ModulationEvidence detection={detection} />}
      </div>

      <div className="detail-reveal">
        <button className="detail-reveal-toggle" aria-expanded={symbolRateOpen} onClick={() => setSymbolRateOpen((v) => !v)}>
          {symbolRateOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          Symbol-rate evidence: spectral harmonic search
        </button>
        {symbolRateOpen && (
          <SymbolRateEvidence
            loading={symbolRate.isPending}
            error={symbolRate.isError ? (symbolRate.error as Error).message : null}
            data={symbolRate.data ?? null}
          />
        )}
      </div>
    </div>
  );
}

function DecisionStep({ label, measured, comparator, threshold, pass, unit }: {
  label: string; measured: string; comparator: string; threshold: string; pass: boolean | null; unit?: string;
}) {
  return (
    <div className={`decision-step ${pass === null ? 'skip' : pass ? 'pass' : 'fail'}`}>
      <span className="decision-step-mark">{pass === null ? '—' : pass ? '✓' : '✗'}</span>
      <span className="decision-step-label">{label}</span>
      <span className="decision-step-expr">{measured}{unit ? ` ${unit}` : ''} {comparator} {threshold}</span>
    </div>
  );
}

function ModulationEvidence({ detection }: { detection: Detection }) {
  const envelopeVariation = detection.envelope_variation;
  const spread = detection.phase_cluster_spread_rad;
  const order = detection.refinement_order;
  const isConstant = detection.modulation_family === 'constant-envelope';
  return (
    <div className="modulation-evidence">
      <p className="reveal-note">
        Cumulant-style measurements from the isolated, corrected segment. Real values behind the classification, not a re-derivation.
      </p>
      <div className="cumulant-grid">
        <div><span>Envelope variation (σ/μ)</span><strong>{envelopeVariation == null ? 'n/a' : envelopeVariation.toFixed(4)}</strong></div>
        <div><span>Phase-cluster spread</span><strong>{spread == null ? 'n/a' : `${spread.toFixed(4)} rad`}</strong></div>
        <div><span>Selected Mth-power order</span><strong>{order == null ? 'n/a' : `M = ${order}`}</strong></div>
      </div>
      <div className="decision-tree">
        <DecisionStep label="Envelope family" measured={envelopeVariation == null ? 'n/a' : envelopeVariation.toFixed(4)} comparator="<" threshold="0.30" pass={envelopeVariation == null ? null : envelopeVariation < 0.3} />
        <DecisionStep label="Constant-envelope gate" measured={detection.modulation_family ?? 'n/a'} comparator="==" threshold="constant-envelope" pass={detection.modulation_family == null ? null : isConstant} />
        <DecisionStep label="Phase concentration" measured={spread == null ? 'n/a' : spread.toFixed(4)} comparator="<" threshold="0.80 rad" pass={spread == null ? null : spread < 0.8} unit="" />
        <DecisionStep label="Pulsed exclusion" measured={detection.is_pulsed ? 'pulsed' : 'continuous'} comparator="==" threshold="continuous" pass={!detection.is_pulsed} />
      </div>
      <p className="reveal-note">Path result: <strong className={detection.fine_modulation_label ? 'text-rf-accent' : ''}>{detection.fine_modulation_label ?? detection.fine_modulation_status ?? 'not reliably classified'}</strong></p>
    </div>
  );
}

function SymbolRateEvidence({ loading, error, data }: { loading: boolean; error: string | null; data: SymbolRateDiagnostic | null }) {
  if (loading) return <p className="reveal-note">Loading spectral evidence…</p>;
  if (error) return <p className="reveal-note">{error}</p>;
  if (!data) return null;
  if (!data.applicable) return <p className="reveal-note">Not applicable: {data.reason}.</p>;

  const W = 280, H = 100, PAD_L = 34, PAD_R = 8, PAD_T = 8, PAD_B = 18;
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B;
  const freqs = data.frequencies_hz, power = data.power_db;
  const fMax = freqs[freqs.length - 1] || 1;
  const pMin = Math.min(...power), pMax = Math.max(...power);
  const pRange = pMax - pMin || 1;
  const x = (f: number) => PAD_L + (f / fMax) * plotW;
  const y = (p: number) => PAD_T + (1 - (p - pMin) / pRange) * plotH;
  const path = freqs.map((f, i) => `${i === 0 ? 'M' : 'L'}${x(f)},${y(power[i])}`).join(' ');
  const selectedX = x(data.selected_frequency_hz);
  const skipX = x(data.skip_frequency_hz);

  return (
    <div className="symbol-rate-evidence">
      <p className="reveal-note">
        Welch PSD of the differentiated, squared segment (the "delay-and-multiply" nonlinearity). The lowest peak within 3 dB of the maximum, past the DC-leakage region, is picked — not the raw maximum, since rectangular-NRZ transitions make every harmonic of the true rate nearly equal-strength.
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="symbol-rate-svg" role="img" aria-label="Symbol-rate harmonic search spectrum">
        <rect x={PAD_L} y={PAD_T} width={skipX - PAD_L} height={plotH} fill="#353535" opacity={0.5} />
        <line x1={PAD_L} x2={W - PAD_R} y1={y(data.threshold_power_db)} y2={y(data.threshold_power_db)} stroke="#7f7f7f" strokeDasharray="2,2" strokeWidth={1} />
        <path d={path} fill="none" stroke="#2a82da" strokeWidth={1.2} />
        <line x1={selectedX} x2={selectedX} y1={PAD_T} y2={H - PAD_B} stroke="#ed776c" strokeWidth={1.5} />
        <circle cx={selectedX} cy={y(power[freqs.findIndex((f) => f >= data.selected_frequency_hz)] ?? data.peak_power_db)} r={3} fill="#ed776c" />
        <text x={PAD_L} y={H - 4} textAnchor="start" className="accuracy-curve-axis">0 Hz</text>
        <text x={W - PAD_R} y={H - 4} textAnchor="end" className="accuracy-curve-axis">{fMax.toFixed(0)} Hz</text>
      </svg>
      <div className="symbol-rate-readout">
        Selected: <strong>{data.selected_frequency_hz.toFixed(2)} Hz</strong> · threshold within 3 dB of {data.peak_power_db.toFixed(1)} dB peak · DC-leakage region shaded to {data.skip_frequency_hz.toFixed(1)} Hz
      </div>
    </div>
  );
}
