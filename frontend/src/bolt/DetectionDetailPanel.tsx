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

  const rows: Array<[string, string, string?]> = [
    ['ID', detection.id],
    ['Method', detection.detection_method],
    ['Confidence', formatConfidence(detection.confidence), detection.confidence >= 0.7 ? '#5cb85c' : detection.confidence >= 0.5 ? '#d4d4d4' : '#cc3c34'],
    ['Needs Review', detection.needs_review ? 'Yes' : 'No', detection.needs_review ? '#cc3c34' : '#d4d4d4'],
    ['Pulsed', detection.is_pulsed ? 'Yes' : 'No', detection.is_pulsed ? '#2a82da' : '#7f7f7f'],
    ['Center Freq', formatFreq(centerFreq)],
    ['Bandwidth', formatFreq(bandwidth)],
    ['Freq Range', `${formatFreq(detection.freq_lower_hz)} to ${formatFreq(detection.freq_upper_hz)}`],
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
              <td className="py-1.5 font-mono tabular-nums break-all" style={{ color: color ?? '#d4d4d4' }}>
                {value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
