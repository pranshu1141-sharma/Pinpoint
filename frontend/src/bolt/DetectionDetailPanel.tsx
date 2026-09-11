import type { Detection } from './types';
import { formatFreq, formatTime, formatSamples, formatConfidence } from './format';

interface DetectionDetailPanelProps {
  detection: Detection | null;
  sampleRate: number;
}

export function DetectionDetailPanel({ detection, sampleRate }: DetectionDetailPanelProps) {
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

  const rows: Array<[string, string, string?]> = [
    ['ID', detection.id],
    ['Method', detection.detection_method],
    ['Confidence', `${formatConfidence(detection.confidence)} (heuristic)`, detection.confidence >= 0.7 ? '#5cb85c' : detection.confidence >= 0.5 ? '#d4d4d4' : '#cc3c34'],
    ['Needs Review', detection.needs_review ? 'Yes' : 'No', detection.needs_review ? '#cc3c34' : '#d4d4d4'],
    ['Pulsed', detection.is_pulsed ? 'Yes' : 'No', detection.is_pulsed ? '#2a82da' : '#7f7f7f'],
    ['Midpoint (Detect)', formatFreq(centerFreq)],
    ['Width (Detect)', formatFreq(bandwidth)],
    ['Edges (Detect)', `${formatFreq(detection.freq_lower_hz)} to ${formatFreq(detection.freq_upper_hz)} (baseband)`],
    ['Center (Estimate)', measurement(detection.center_frequency_hz, 'Hz')],
    ['Center (Refined)', measurement(detection.center_frequency_refined_hz, 'Hz')],
    ['Center reference', 'RF when tuning is known; otherwise baseband'],
    ['Bandwidth (3 dB)', measurement(detection.bandwidth_3db_hz, 'Hz')],
    ['Bandwidth (99%)', detection.bandwidth_99pct_caveat ? `${bandwidth99} — ${detection.bandwidth_99pct_caveat}` : bandwidth99],
    ['SNR (full-band)', measurement(detection.snr_db, 'dB')],
    ['Estimate status', detection.estimate_status ?? unavailable],
    ['Modulation family', detection.modulation_family ?? unavailable],
    ['Family confidence', detection.modulation_confidence == null ? unavailable : `${formatConfidence(detection.modulation_confidence)} (heuristic)`],
    ['Refinement status', detection.refinement_status ?? unavailable],
    ['Fine modulation', detection.fine_modulation_label ?? 'Not reliably estimated'],
    ['Symbol rate', detection.symbol_rate_hz == null ? (detection.symbol_rate_status == null || detection.symbol_rate_status.includes('not attempted') ? 'Not attempted' : 'Not reliably estimated') : measurement(detection.symbol_rate_hz, 'Hz')],
    ['Start Time', `${formatTime(startTime)} (${formatSamples(detection.start_sample)})`],
    ['End Time', `${formatTime(endTime)} (${formatSamples(detection.end_sample)})`],
    ['Duration', `${formatTime(duration)} (${formatSamples(sampleCount)})`],
  ];

  if (detection.is_pulsed && detection.pulse_width_samples !== null) {
    rows.push(['Pulse Width', `${formatSamples(detection.pulse_width_samples)} (${formatTime(detection.pulse_width_samples / sampleRate)})`]);
  }
  if (detection.is_pulsed && detection.pri_samples !== null) {
    rows.push(['PRI', `${formatSamples(detection.pri_samples)} (${formatTime(detection.pri_samples / sampleRate)})`]);
    const prf = sampleRate / detection.pri_samples;
    rows.push(['PRF', `${prf.toFixed(1)} Hz`]);
  }

  return (
    <div className="overflow-auto h-full p-2">
      <table className="w-full text-[11px] border-collapse">
        <tbody>
          {rows.map(([key, value, color]) => (
            <tr key={key} className="border-b border-rf-border last:border-0">
              <td className="py-1.5 pr-2 text-rf-text-secondary text-[10px] uppercase tracking-wide whitespace-nowrap">
                {key}
              </td>
              <td className="py-1.5 font-mono tabular-nums break-words" style={{ color: color ?? '#d4d4d4' }}>
                {value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
