import type { FileInfo } from './types';
import { formatFreq, formatTime, formatSamples } from './format';

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
    ['Sample Rate', `${fileInfo.sampleRate.toLocaleString()} samples/s`],
    ['Interpretation', fileInfo.interpretation],
    ['RF Center', fileInfo.center === null ? 'Not supplied' : formatFreq(fileInfo.center)],
    ['Duration', formatTime(fileInfo.durationSeconds)],
    ['Total Samples', formatSamples(fileInfo.totalSamples)],
    ['Nyquist limit', formatFreq(fileInfo.sampleRate / 2)],
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
