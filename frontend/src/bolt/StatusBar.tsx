import { formatFreq, formatDb } from './format';

interface StatusBarProps {
  sampleRate: number | null;
  durationSeconds: number | null;
  cursorFreq: number | null;
  cursorPower: number | null;
  cursorTime: number | null;
  detectionCount: number;
  thresholdDb: number;
  noiseFloorDb: number | null;
  selectedDetectionId: string | null;
}

export function StatusBar({
  sampleRate,
  durationSeconds,
  cursorFreq,
  cursorPower,
  cursorTime,
  detectionCount,
  thresholdDb,
  noiseFloorDb,
  selectedDetectionId,
}: StatusBarProps) {
  return (
    <div className="flex items-center h-6 px-3 bg-rf-panel border-t border-rf-border text-[11px] font-mono shrink-0 gap-4">
      {sampleRate && (
        <div className="flex items-center gap-1.5">
          <span className="text-rf-text-secondary">SR:</span>
            <span className="text-rf-text-primary tabular-nums">{sampleRate.toLocaleString()} samples/s</span>
        </div>
      )}
      {durationSeconds && (
        <div className="flex items-center gap-1.5">
          <span className="text-rf-text-secondary">Dur:</span>
          <span className="text-rf-text-primary tabular-nums">{durationSeconds.toFixed(3)} s</span>
        </div>
      )}
      {noiseFloorDb !== null && (
        <div className="flex items-center gap-1.5">
          <span className="text-rf-text-secondary">NF:</span>
          <span className="text-rf-text-primary tabular-nums">{noiseFloorDb.toFixed(1)} dB</span>
        </div>
      )}
      <div className="flex items-center gap-1.5">
        <span className="text-rf-text-secondary">Thr:</span>
        <span className="text-rf-text-primary tabular-nums">{thresholdDb.toFixed(1)} dB</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-rf-text-secondary">Det:</span>
        <span className="text-rf-text-primary tabular-nums">{detectionCount}</span>
      </div>
      {selectedDetectionId && (
        <div className="flex items-center gap-1.5">
          <span className="text-rf-text-secondary">Sel:</span>
          <span className="text-rf-accent tabular-nums">{selectedDetectionId}</span>
        </div>
      )}
      <div className="flex-1" />
      {cursorFreq !== null && (
        <div className="flex items-center gap-1.5">
          <span className="text-rf-text-secondary">Freq:</span>
          <span className="text-rf-accent tabular-nums">{formatFreq(cursorFreq)}</span>
        </div>
      )}
      {cursorTime !== null && (
        <div className="flex items-center gap-1.5">
          <span className="text-rf-text-secondary">Time:</span>
          <span className="text-rf-accent tabular-nums">{cursorTime.toFixed(6)} s</span>
        </div>
      )}
      {cursorPower !== null && (
        <div className="flex items-center gap-1.5">
          <span className="text-rf-text-secondary">Pwr:</span>
          <span className="text-rf-accent tabular-nums">{formatDb(cursorPower)}</span>
        </div>
      )}
      {cursorFreq === null && cursorPower === null && cursorTime === null && (
        <div className="text-rf-text-secondary">Hover plot for cursor readout</div>
      )}
    </div>
  );
}
