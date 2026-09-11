import { useRef, useEffect, useState, useCallback } from 'react';
import type { Detection, SpectrogramResponse } from './types';
import { buildColormapLUT } from './colormap';
import { formatFreqShort, formatTime } from './format';

interface WaterfallProps {
  spectrogram: SpectrogramResponse | null;
  detections: Detection[];
  selectedDetectionId: string | null;
  onSelectDetection: (id: string) => void;
  freqMin: number;
  freqMax: number;
  onCursorMove: (freqHz: number | null, timeS: number | null) => void;
  sampleRate: number;
  totalSamples: number;
}

const LUT = buildColormapLUT();

export function Waterfall({
  spectrogram,
  detections,
  selectedDetectionId,
  onSelectDetection,
  freqMin,
  freqMax,
  onCursorMove,
  sampleRate,
  totalSamples,
}: WaterfallProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [height, setHeight] = useState(400);
  const [cursorX, setCursorX] = useState<number | null>(null);
  const [cursorY, setCursorY] = useState<number | null>(null);

  const PAD_LEFT = 48;
  const PAD_RIGHT = 8;
  const PAD_TOP = 4;
  const PAD_BOTTOM = 24;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const updateSize = () => {
      setWidth(container.clientWidth);
      setHeight(container.clientHeight);
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
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

  // Draw waterfall
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

    // Clear
    ctx.fillStyle = '#1e1e1e';
    ctx.fillRect(0, 0, width, height);

    if (spectrogram && spectrogram.magnitude_2d.length > 0) {
      const timeBins = spectrogram.time_bins.length;
      const freqBins = spectrogram.freq_bins.length;
      const mag2d = spectrogram.magnitude_2d;

      // Use the same measured limits as the legend, never an invented scale.
      const minMag = spectrogram.min_db;
      const maxMag = spectrogram.max_db;
      const range = maxMag - minMag || 1;

      // Draw waterfall pixels
      for (let t = 0; t < timeBins; t++) {
        const y = PAD_TOP + spectrogram.time_edges_seconds[t] / (totalSamples / sampleRate) * plotHeight;
        const yNext = PAD_TOP + spectrogram.time_edges_seconds[t + 1] / (totalSamples / sampleRate) * plotHeight;
        const rowHeight = Math.ceil(yNext - y);

        for (let f = 0; f < freqBins; f++) {
          const freq = spectrogram.frequency_edges_hz[f];
          if (freq < freqMin || freq > freqMax) continue;
          const x = freqToX(freq);
          const xNext = freqToX(spectrogram.frequency_edges_hz[f + 1]);
          const colWidth = Math.max(1, Math.ceil(xNext - x));

          const normalized = (mag2d[t][f] - minMag) / range;
          const lutIdx = Math.max(0, Math.min(255, Math.floor(normalized * 255)));
          const r = LUT[lutIdx * 3];
          const g = LUT[lutIdx * 3 + 1];
          const b = LUT[lutIdx * 3 + 2];
          ctx.fillStyle = `rgb(${r},${g},${b})`;
          ctx.fillRect(Math.floor(x), Math.floor(y), colWidth, rowHeight);
        }
      }
    } else {
      // Empty state
      ctx.fillStyle = '#7f7f7f';
      ctx.font = '11px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('No spectrogram data', PAD_LEFT + plotWidth / 2, PAD_TOP + plotHeight / 2);
    }

    // X-axis labels (frequency, shared with FFT)
    ctx.strokeStyle = '#2a2a2a';
    ctx.lineWidth = 1;
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.fillStyle = '#7f7f7f';
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

    // Y-axis labels (time)
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    const timeStep = (height - PAD_TOP - PAD_BOTTOM) / 4;
    for (let i = 0; i <= 4; i++) {
      const y = PAD_TOP + timeStep * i;
      const timeProgress = i / 4;
      const timeS = timeProgress * (totalSamples / sampleRate);
      ctx.fillText(formatTime(timeS), PAD_LEFT - 6, y);
    }

    // Detection brackets
    for (const det of detections) {
      const x1 = freqToX(det.freq_lower_hz);
      const x2 = freqToX(det.freq_upper_hz);
      const isSelected = det.id === selectedDetectionId;

      // Time extent
      const tStart = (det.start_sample / totalSamples) * plotHeight + PAD_TOP;
      const tEnd = (det.end_sample / totalSamples) * plotHeight + PAD_TOP;

      ctx.strokeStyle = isSelected ? '#2a82da' : '#9a9a9a';
      ctx.lineWidth = isSelected ? 1.5 : 1;
      ctx.setLineDash(det.is_pulsed || !isSelected ? [3, 2] : []);

      // Top bracket
      ctx.beginPath();
      ctx.moveTo(x1, tStart);
      ctx.lineTo(x1, tStart + 5);
      ctx.moveTo(x2, tStart);
      ctx.lineTo(x2, tStart + 5);
      ctx.moveTo(x1, tStart);
      ctx.lineTo(x2, tStart);
      ctx.stroke();

      // Bottom bracket
      ctx.beginPath();
      ctx.moveTo(x1, tEnd);
      ctx.lineTo(x1, tEnd - 5);
      ctx.moveTo(x2, tEnd);
      ctx.lineTo(x2, tEnd - 5);
      ctx.moveTo(x1, tEnd);
      ctx.lineTo(x2, tEnd);
      ctx.stroke();

      // Side lines
      ctx.beginPath();
      ctx.moveTo(x1, tStart);
      ctx.lineTo(x1, tEnd);
      ctx.moveTo(x2, tStart);
      ctx.lineTo(x2, tEnd);
      ctx.stroke();
      ctx.setLineDash([]);
      // Solid windows distinguish on-pulses from the dashed aggregate extent.
      if (det.is_pulsed) {
        for (const pulse of det.pulse_windows) {
          const top = PAD_TOP + pulse.start_sample / totalSamples * plotHeight;
          const bottom = PAD_TOP + pulse.end_sample / totalSamples * plotHeight;
          ctx.strokeRect(x1, top, x2 - x1, Math.max(1, bottom - top));
        }
      }
    }

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
    }
    if (cursorY !== null && cursorY >= PAD_TOP && cursorY <= height - PAD_BOTTOM) {
      ctx.strokeStyle = '#7f7f7f';
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      ctx.moveTo(PAD_LEFT, cursorY);
      ctx.lineTo(width - PAD_RIGHT, cursorY);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }, [
    width, height, spectrogram, detections, selectedDetectionId,
    freqToX, freqMin, freqMax, plotWidth, plotHeight, cursorX, cursorY,
    sampleRate, totalSamples,
  ]);

  const handleMouseMove = (e: React.MouseEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setCursorX(x);
    setCursorY(y);

    if (x >= PAD_LEFT && x <= width - PAD_RIGHT && y >= PAD_TOP && y <= height - PAD_BOTTOM) {
      const freq = xToFreq(x);
      const timeProgress = (y - PAD_TOP) / plotHeight;
      const timeS = timeProgress * (totalSamples / sampleRate);
      onCursorMove(freq, timeS);
    } else {
      onCursorMove(null, null);
    }
  };

  const handleClick = (e: React.MouseEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    for (const det of detections) {
      const x1 = freqToX(det.freq_lower_hz);
      const x2 = freqToX(det.freq_upper_hz);
      const tStart = (det.start_sample / totalSamples) * plotHeight + PAD_TOP;
      const tEnd = (det.end_sample / totalSamples) * plotHeight + PAD_TOP;
      if (x >= x1 - 3 && x <= x2 + 3 && y >= tStart - 3 && y <= tEnd + 3) {
        onSelectDetection(det.id);
        return;
      }
    }
  };

  const handleMouseLeave = () => {
    setCursorX(null);
    setCursorY(null);
    onCursorMove(null, null);
  };

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <canvas
        role="img" aria-label="Measured waterfall spectrogram. Use the detection table to select candidates by keyboard."
        ref={canvasRef}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
        style={{ cursor: 'crosshair' }}
      />
    </div>
  );
}
