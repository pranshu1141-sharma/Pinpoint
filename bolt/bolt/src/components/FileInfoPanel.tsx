import type { FileInfo } from '@/lib/types';
import { formatFreq, formatTime, formatSamples } from '@/lib/format';

interface FileInfoPanelProps {
  fileInfo: FileInfo | null;
}

export function FileInfoPanel({ fileInfo }: FileInfoPanelProps) {
  if (!fileInfo) {
    return (
      <div className="flex items-center justify-center h-full text-rf-text-secondary text-[11px] p-4">
        No file loaded.
      </div>
    );
  }

  const rows: Array<[string, string]> = [
    ['File', fileInfo.filename],
    ['Format', fileInfo.format],
    ['Size', fileInfo.fileSize],
    ['Sample Rate', `${(fileInfo.sampleRate / 1e6).toFixed(2)} Msps`],
    ['Duration', formatTime(fileInfo.durationSeconds)],
    ['Total Samples', formatSamples(fileInfo.totalSamples)],
    ['Nyquist BW', formatFreq(fileInfo.sampleRate / 2)],
  ];

  return (
    <div className="overflow-auto h-full p-2">
      <table className="w-full text-[11px] border-collapse">
        <tbody>
          {rows.map(([key, value]) => (
            <tr key={key} className="border-b border-rf-border last:border-0">
              <td className="py-1.5 pr-2 text-rf-text-secondary text-[10px] uppercase tracking-wide whitespace-nowrap">
                {key}
              </td>
              <td className="py-1.5 font-mono text-rf-text-primary tabular-nums break-all">
                {value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
