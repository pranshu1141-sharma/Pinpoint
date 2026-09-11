import { useRef, useEffect, useCallback, useState } from 'react';
import type { Detection } from './types';
import { formatFreqShort } from './format';

interface FftPlotProps {
  psdData: { freqs: number[]; magnitudes: number[] } | null;
  noiseFloorDb: number | null;
  thresholdDb: number;
  thresholdLabel: string;
  onThresholdChange: (db: number) => void;
  detections: Detection[];
  selectedDetectionId: string | null;
  onSelectDetection: (id: string) => void;
  freqMin: number;
  freqMax: number;
  dbMin: number;
  dbMax: number;
  onCursorMove: (freqHz: number | null, magnitudeDb: number | null) => void;
  height: number;
}

export function FftPlot({
  psdData,
  noiseFloorDb,
  thresholdDb,
  thresholdLabel,
  onThresholdChange,
  detections,
  selectedDetectionId,
  onSelectDetection,
  freqMin,
  freqMax,
  dbMin,
  dbMax,
  onCursorMove,
  height,
}: FftPlotProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [cursorX, setCursorX] = useState<number | null>(null);
  const [draggingThreshold, setDraggingThreshold] = useState(false);
  const [hoveredThreshold, setHoveredThreshold] = useState(false);

  const PAD_LEFT = 48;
  const PAD_RIGHT = 8;
  const PAD_TOP = 8;
  const PAD_BOTTOM = 24;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const updateWidth = () => setWidth(container.clientWidth);
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  const plotWidth = width - PAD_LEFT - PAD_RIGHT;
  const plotHeight = height - PAD_TOP - PAD_BOTTOM;

  const freqToX = useCallback(
    (freq: number) => PAD_LEFT + ((freq - freqMin) / (freqMax - freqMin)) * plotWidth,
    [freqMin, freqMax, plotWidth],
  );

  const xToFreq = useCallback(
    (x: number) => freqMin + ((x - PAD_LEFT) / plotWidth) * (freqMax - freqMin),
    [freqMin, freqMax, plotWidth],
  );

  const dbToY = useCallback(
    (db: number) => PAD_TOP + (1 - (db - dbMin) / (dbMax - dbMin)) * plotHeight,
    [dbMin, dbMax, plotHeight],
  );

  const yToDb = useCallback(
    (y: number) => dbMin + (1 - (y - PAD_TOP) / plotHeight) * (dbMax - dbMin),
    [dbMin, dbMax, plotHeight],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#1e1e1e';
    ctx.fillRect(0, 0, width, height);

    // Grid — minor lines
    ctx.strokeStyle = '#2a2a2a';
    ctx.lineWidth = 1;
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.fillStyle = '#7f7f7f';

    const dbStep = 10;
    for (let db = Math.ceil(dbMin / dbStep) * dbStep; db <= dbMax; db += dbStep) {
      const y = dbToY(db);
      ctx.beginPath();
      ctx.moveTo(PAD_LEFT, y);
      ctx.lineTo(width - PAD_RIGHT, y);
      ctx.stroke();
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(`${db}`, PAD_LEFT - 6, y);
    }

    const freqStep = (freqMax - freqMin) / 8;
    for (let i = 0; i <= 8; i++) {
      const freq = freqMin + freqStep * i;
      const x = freqToX(freq);
      ctx.beginPath();
      ctx.moveTo(x, PAD_TOP);
      ctx.lineTo(x, height - PAD_BOTTOM);
      ctx.stroke();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(formatFreqShort(freq), x, height - PAD_BOTTOM + 4);
    }

    // Axis labels
    ctx.save();
    ctx.translate(12, PAD_TOP + plotHeight / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#7f7f7f';
    ctx.font = '10px Inter, sans-serif';
    ctx.fillText('PSD (dB/Hz)', 0, 0);
    ctx.restore();

    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText('Frequency (Hz)', PAD_LEFT + plotWidth / 2, height - 2);

    // Noise floor reference line
    if (noiseFloorDb !== null) {
      const y = dbToY(noiseFloorDb);
      ctx.strokeStyle = '#7f7f7f';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(PAD_LEFT, y);
      ctx.lineTo(width - PAD_RIGHT, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#7f7f7f';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'bottom';
      ctx.font = '9px "JetBrains Mono", monospace';
      ctx.fillText(`Noise Floor ${noiseFloorDb.toFixed(1)} dB`, PAD_LEFT + 4, y - 2);
    }

    // PSD line with fill
    if (psdData && psdData.freqs.length > 0) {
      // Fill under curve
      ctx.beginPath();
      for (let i = 0; i < psdData.freqs.length; i++) {
        const x = freqToX(psdData.freqs[i]);
        const y = dbToY(psdData.magnitudes[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.lineTo(freqToX(psdData.freqs[psdData.freqs.length - 1]), PAD_TOP + plotHeight);
      ctx.lineTo(freqToX(psdData.freqs[0]), PAD_TOP + plotHeight);
      ctx.closePath();
      ctx.fillStyle = 'rgba(42, 130, 218, 0.08)';
      ctx.fill();

      // Line
      ctx.strokeStyle = '#2a82da';
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let i = 0; i < psdData.freqs.length; i++) {
        const x = freqToX(psdData.freqs[i]);
        const y = dbToY(psdData.magnitudes[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Peak markers for detections
      for (const det of detections) {
        const centerFreq = (det.freq_lower_hz + det.freq_upper_hz) / 2;
        const centerIdx = psdData.freqs.reduce((best, f, i) =>
          Math.abs(f - centerFreq) < Math.abs(psdData.freqs[best] - centerFreq) ? i : best, 0);
        const peakMag = psdData.magnitudes[centerIdx];
        if (peakMag === undefined) continue;
        const px = freqToX(centerFreq);
        const py = dbToY(peakMag);
        const isSelected = det.id === selectedDetectionId;
        ctx.strokeStyle = isSelected ? '#2a82da' : '#4a4a4a';
        ctx.fillStyle = isSelected ? '#2a82da' : '#4a4a4a';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(px, py, 2, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Detection brackets
    for (const det of detections) {
      const x1 = freqToX(det.freq_lower_hz);
      const x2 = freqToX(det.freq_upper_hz);
      const isSelected = det.id === selectedDetectionId;
      ctx.strokeStyle = isSelected ? '#2a82da' : '#4a4a4a';
      ctx.lineWidth = isSelected ? 1.5 : 1;
      const bracketY = PAD_TOP + 2;
      const bracketH = 6;
      ctx.beginPath();
      ctx.moveTo(x1, bracketY + bracketH);
      ctx.lineTo(x1, bracketY);
      ctx.lineTo(x2, bracketY);
      ctx.lineTo(x2, bracketY + bracketH);
      ctx.stroke();
      if (det.needs_review) {
        ctx.fillStyle = '#cc3c34';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.font = 'bold 9px "JetBrains Mono", monospace';
        ctx.fillText('!', (x1 + x2) / 2, bracketY + bracketH + 1);
      }
      // Detection ID label for selected
      if (isSelected) {
        ctx.fillStyle = '#2a82da';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.font = '9px "JetBrains Mono", monospace';
        ctx.fillText(det.id, (x1 + x2) / 2, bracketY - 1);
      }
    }

    // Threshold line (draggable)
    const thresholdY = dbToY(thresholdDb);
    ctx.strokeStyle = '#cc3c34';
    ctx.lineWidth = hoveredThreshold || draggingThreshold ? 2 : 1;
    ctx.setLineDash([6, 3]);
    ctx.beginPath();
    ctx.moveTo(PAD_LEFT, thresholdY);
    ctx.lineTo(width - PAD_RIGHT, thresholdY);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = '#cc3c34';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillText(`${thresholdLabel} ${thresholdDb.toFixed(1)} dB`, width - PAD_RIGHT - 4, thresholdY - 2);

    ctx.fillStyle = '#cc3c34';
    ctx.fillRect(PAD_LEFT - 2, thresholdY - 3, 4, 6);

    // Cursor crosshair
    if (cursorX !== null && cursorX >= PAD_LEFT && cursorX <= width - PAD_RIGHT) {
      ctx.strokeStyle = '#7f7f7f';
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      ctx.moveTo(cursorX, PAD_TOP);
      ctx.lineTo(cursorX, height - PAD_BOTTOM);
      ctx.stroke();
      ctx.setLineDash([]);

      // Cursor readout label
      const freq = xToFreq(cursorX);
      let mag: number | null = null;
      if (psdData && psdData.freqs.length > 0) {
        const closestIdx = psdData.freqs.reduce((best, f, i) =>
          Math.abs(f - freq) < Math.abs(psdData.freqs[best] - freq) ? i : best, 0);
        mag = psdData.magnitudes[closestIdx] ?? null;
      }
      if (mag !== null) {
        const label = `${formatFreqShort(freq)} Hz | ${mag.toFixed(1)} dB`;
        ctx.font = '10px "JetBrains Mono", monospace';
        const labelWidth = ctx.measureText(label).width + 8;
        let labelX = cursorX + 8;
        if (labelX + labelWidth > width - PAD_RIGHT) labelX = cursorX - labelWidth - 4;
        ctx.fillStyle = '#353535';
        ctx.fillRect(labelX, PAD_TOP + 2, labelWidth, 16);
        ctx.strokeStyle = '#4a4a4a';
        ctx.lineWidth = 1;
        ctx.strokeRect(labelX, PAD_TOP + 2, labelWidth, 16);
        ctx.fillStyle = '#d4d4d4';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillText(label, labelX + 4, PAD_TOP + 4);
      }
    }
  }, [
    width, height, psdData, noiseFloorDb, thresholdDb, detections,
    selectedDetectionId, cursorX, freqToX, dbToY, xToFreq, freqMin, freqMax, dbMin, dbMax,
    hoveredThreshold, draggingThreshold, plotHeight, thresholdLabel,
  ]);

  const handleMouseMove = (e: React.MouseEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setCursorX(x);

    if (draggingThreshold) {
      const newDb = yToDb(y);
      const clamped = Math.max(dbMin, Math.min(dbMax, newDb));
      onThresholdChange(Math.round(clamped * 10) / 10);
      return;
    }

    const thresholdY = dbToY(thresholdDb);
    setHoveredThreshold(Math.abs(y - thresholdY) < 5);

    if (x >= PAD_LEFT && x <= width - PAD_RIGHT) {
      const freq = xToFreq(x);
      let mag: number | null = null;
      if (psdData && psdData.freqs.length > 0) {
        const closestIdx = psdData.freqs.reduce((best, f, i) =>
          Math.abs(f - freq) < Math.abs(psdData.freqs[best] - freq) ? i : best, 0);
        mag = psdData.magnitudes[closestIdx] ?? null;
      }
      onCursorMove(freq, mag);
    } else {
      onCursorMove(null, null);
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const y = e.clientY - rect.top;
    const thresholdY = dbToY(thresholdDb);
    if (Math.abs(y - thresholdY) < 5) {
      setDraggingThreshold(true);
    }
  };

  const handleMouseUp = () => setDraggingThreshold(false);

  const handleClick = (e: React.MouseEvent) => {
    if (draggingThreshold) return;
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;

    for (const det of detections) {
      const x1 = freqToX(det.freq_lower_hz);
      const x2 = freqToX(det.freq_upper_hz);
      if (x >= x1 - 3 && x <= x2 + 3) {
        onSelectDetection(det.id);
        return;
      }
    }
  };

  const handleMouseLeave = () => {
    setDraggingThreshold(false);
    setCursorX(null);
    setHoveredThreshold(false);
    onCursorMove(null, null);
  };

  return (
    <div ref={containerRef} className="relative w-full" style={{ height }}>
      <canvas
        role="img" aria-label="Measured Welch power spectrum. Drag the threshold to configure the next analysis."
        ref={canvasRef}
        onMouseMove={handleMouseMove}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
        style={{
          cursor: draggingThreshold ? 'ns-resize' : hoveredThreshold ? 'ns-resize' : 'crosshair',
        }}
      />
    </div>
  );
}
