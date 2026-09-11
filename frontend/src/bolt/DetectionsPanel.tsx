import type { Detection } from './types';
import { formatFreq, formatConfidence, formatSamples } from './format';
import { cn } from '@/lib/utils';
import { Download } from 'lucide-react';

interface DetectionsPanelProps {
  detections: Detection[];
  selectedDetectionId: string | null;
  onSelectDetection: (id: string) => void;
  sampleRate: number;
}

function exportCsv(detections: Detection[], sampleRate: number) {
  const header = [
    'id', 'start_sample', 'end_sample', 'freq_lower_hz', 'freq_upper_hz',
    'confidence', 'detection_method', 'is_pulsed', 'pulse_width_samples',
    'pri_samples', 'needs_review', 'start_time_s', 'end_time_s', 'duration_s',
    'center_freq_hz', 'bandwidth_hz',
  ];
  const rows = detections.map((d) => {
    const startTime = d.start_sample / sampleRate;
    const endTime = d.end_sample / sampleRate;
    const center = (d.freq_lower_hz + d.freq_upper_hz) / 2;
    const bw = d.freq_upper_hz - d.freq_lower_hz;
    return [
      d.id, d.start_sample, d.end_sample, d.freq_lower_hz, d.freq_upper_hz,
      d.confidence, d.detection_method, d.is_pulsed,
      d.pulse_width_samples ?? '', d.pri_samples ?? '', d.needs_review,
      startTime.toFixed(6), endTime.toFixed(6), (endTime - startTime).toFixed(6),
      center.toFixed(1), bw.toFixed(1),
    ];
  });
  const csv = [header, ...rows].map((r) => r.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'detections.csv';
  a.click();
  URL.revokeObjectURL(url);
}

export function DetectionsPanel({
  detections,
  selectedDetectionId,
  onSelectDetection,
  sampleRate,
}: DetectionsPanelProps) {
  const total = detections.length;
  const pulsed = detections.filter((d) => d.is_pulsed).length;
  const review = detections.filter((d) => d.needs_review).length;
  const avgConf = total > 0
    ? (detections.reduce((s, d) => s + d.confidence, 0) / total * 100).toFixed(0)
    : '0';

  return (
    <div className="flex flex-col h-full">
      {/* Stats header */}
      {total > 0 && (
        <div className="flex items-center gap-3 px-2 py-1.5 border-b border-rf-border bg-rf-recessed text-[10px] font-mono">
          <span className="text-rf-text-secondary">Total: <span className="text-rf-text-primary tabular-nums">{total}</span></span>
          <span className="text-rf-text-secondary">Pulsed: <span className="text-rf-text-primary tabular-nums">{pulsed}</span></span>
          <span className="text-rf-text-secondary">Review: <span className="text-rf-alert tabular-nums">{review}</span></span>
          <span className="text-rf-text-secondary">Avg Conf: <span className="text-rf-text-primary tabular-nums">{avgConf}%</span></span>
          <button
            onClick={() => exportCsv(detections, sampleRate)}
            className="ml-auto flex items-center gap-1 px-1.5 py-0.5 text-[10px] text-rf-text-secondary hover:text-rf-text-primary border border-rf-border-light hover:border-rf-accent transition-colors"
            style={{ borderRadius: '2px' }}
            title="Export detections as CSV"
          >
            <Download className="w-3 h-3" />
            CSV
          </button>
        </div>
      )}

      {total === 0 ? (
        <div className="flex items-center justify-center flex-1 text-rf-text-secondary text-[11px] p-4">
          Analysis complete. No candidates passed the selected threshold.
        </div>
      ) : (
        <div className="overflow-auto flex-1">
          <table className="w-full text-[11px] border-collapse">
            <thead>
              <tr className="sticky top-0 bg-rf-panel border-b border-rf-border">
                <th className="text-left px-2 py-1.5 font-medium text-rf-text-secondary uppercase tracking-wide text-[10px]">Freq Range</th>
                <th className="text-left px-2 py-1.5 font-medium text-rf-text-secondary uppercase tracking-wide text-[10px]">Time Range</th>
                <th className="text-right px-2 py-1.5 font-medium text-rf-text-secondary uppercase tracking-wide text-[10px]">Conf</th>
                <th className="text-center px-2 py-1.5 font-medium text-rf-text-secondary uppercase tracking-wide text-[10px]">Pulsed</th>
                <th className="text-center px-2 py-1.5 font-medium text-rf-text-secondary uppercase tracking-wide text-[10px] w-6">!</th>
              </tr>
            </thead>
            <tbody>
              {detections.map((det) => {
                const isSelected = det.id === selectedDetectionId;
                const startTime = det.start_sample / sampleRate;
                const endTime = det.end_sample / sampleRate;
                const confColor =
                  det.confidence >= 0.7 ? '#5cb85c' :
                  det.confidence >= 0.5 ? '#d4d4d4' :
                  '#cc3c34';

                return (
                  <tr tabIndex={0} aria-selected={isSelected} aria-label={`Candidate ${det.id}: ${formatFreq(det.freq_lower_hz)} to ${formatFreq(det.freq_upper_hz)}`}
                    onKeyDown={(e) => { if (e.key === 'Enter') onSelectDetection(det.id); }}
                    key={det.id}
                    onClick={() => onSelectDetection(det.id)}
                    className={cn(
                      'cursor-pointer border-b border-rf-border transition-colors',
                      isSelected ? 'bg-rf-accent/20' : 'hover:bg-rf-recessed',
                    )}
                  >
                    <td className="px-2 py-1.5 font-mono text-rf-text-primary tabular-nums whitespace-nowrap">
                      {formatFreq(det.freq_lower_hz)}
                      <span className="text-rf-text-secondary mx-0.5">–</span>
                      {formatFreq(det.freq_upper_hz)}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-rf-text-secondary tabular-nums whitespace-nowrap">
                      {startTime.toFixed(2)}–{endTime.toFixed(2)} s
                    </td>
                    <td className="px-2 py-1.5 font-mono text-right tabular-nums" style={{ color: confColor }}>
                      {formatConfidence(det.confidence)}
                    </td>
                    <td className="px-2 py-1.5 text-center font-mono text-rf-text-secondary">
                      {det.is_pulsed ? (
                        <span className="text-rf-text-primary">Y</span>
                      ) : (
                        <span className="text-rf-text-secondary">N</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-center font-mono w-6">
                      {det.needs_review && (
                        <span className="text-rf-alert font-bold">!</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
