import { useRef, useEffect, useState, useCallback } from 'react';
import type { Detection, SpectrogramResponse } from './types';
import { buildColormapLUT } from './colormap';
import { formatFreq, formatFreqShort, formatTime, formatDb } from './format';
import { ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';

interface WaterfallProps {
  spectrogram: SpectrogramResponse | null;
  detections: Detection[];
  selectedDetectionId: string | null;
  onSelectDetection: (id: string) => void;
  freqMin: number;
  freqMax: number;
  onCursorMove: (freqHz: number | null, timeS: number | null, powerDb: number | null) => void;
  sampleRate: number;
  totalSamples: number;
  jumpTo?: { id: string; token: number } | null;
}

type Pin = { x: number; y: number; freq: number; time: number; power: number | null };
type View = { freqLo: number; freqHi: number; timeLo: number; timeHi: number };
const MIN_SPAN_FRACTION = 0.01;

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
  jumpTo,
}: WaterfallProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [height, setHeight] = useState(400);
  const [cursorX, setCursorX] = useState<number | null>(null);
  const [cursorY, setCursorY] = useState<number | null>(null);
  const [pin, setPin] = useState<Pin | null>(null);
  const fullDuration = totalSamples / sampleRate;
  const [view, setView] = useState<View>({ freqLo: freqMin, freqHi: freqMax, timeLo: 0, timeHi: fullDuration });
  const panRef = useRef<{ x: number; y: number; view: View } | null>(null);
  const draggedRef = useRef(false);

  const PAD_LEFT = 48;
  const PAD_RIGHT = 8;
  const PAD_TOP = 4;
  const PAD_BOTTOM = 24;

  // A genuinely new capture resets the viewport; margin re-runs on the same
  // file (same freq/time bounds) keep whatever zoom/pan the analyst set.
  useEffect(() => {
    setView({ freqLo: freqMin, freqHi: freqMax, timeLo: 0, timeHi: fullDuration });
  }, [freqMin, freqMax, fullDuration]);

  const clampView = useCallback((next: View): View => {
    const minFreqSpan = (freqMax - freqMin) * MIN_SPAN_FRACTION;
    const minTimeSpan = fullDuration * MIN_SPAN_FRACTION;
    let { freqLo, freqHi, timeLo, timeHi } = next;
    if (freqHi - freqLo < minFreqSpan) { const c = (freqLo + freqHi) / 2; freqLo = c - minFreqSpan / 2; freqHi = c + minFreqSpan / 2; }
    if (timeHi - timeLo < minTimeSpan) { const c = (timeLo + timeHi) / 2; timeLo = c - minTimeSpan / 2; timeHi = c + minTimeSpan / 2; }
    if (freqHi - freqLo > freqMax - freqMin) { freqLo = freqMin; freqHi = freqMax; }
    else { if (freqLo < freqMin) { freqHi += freqMin - freqLo; freqLo = freqMin; } if (freqHi > freqMax) { freqLo -= freqHi - freqMax; freqHi = freqMax; } }
    if (timeHi - timeLo > fullDuration) { timeLo = 0; timeHi = fullDuration; }
    else { if (timeLo < 0) { timeHi -= timeLo; timeLo = 0; } if (timeHi > fullDuration) { timeLo -= timeHi - fullDuration; timeHi = fullDuration; } }
    return { freqLo, freqHi, timeLo, timeHi };
  }, [freqMin, freqMax, fullDuration]);

  const isZoomed = view.freqLo > freqMin + 1e-6 || view.freqHi < freqMax - 1e-6 || view.timeLo > 1e-9 || view.timeHi < fullDuration - 1e-9;

  const zoomAt = useCallback((freq: number, time: number, factor: number) => {
    setView(prev => {
      const freqSpan = (prev.freqHi - prev.freqLo) * factor;
      const timeSpan = (prev.timeHi - prev.timeLo) * factor;
      const freqFrac = (freq - prev.freqLo) / (prev.freqHi - prev.freqLo);
      const timeFrac = (time - prev.timeLo) / (prev.timeHi - prev.timeLo);
      return clampView({
        freqLo: freq - freqFrac * freqSpan, freqHi: freq + (1 - freqFrac) * freqSpan,
        timeLo: time - timeFrac * timeSpan, timeHi: time + (1 - timeFrac) * timeSpan,
      });
    });
  }, [clampView]);

  // A row/keyboard "jump" frames the candidate with generous padding, distinct
  // from clicking directly on the waterfall (which already shows where it is).
  useEffect(() => {
    if (!jumpTo) return;
    const det = detections.find(d => d.id === jumpTo.id);
    if (!det) return;
    const freqSpan = Math.max(det.freq_upper_hz - det.freq_lower_hz, (freqMax - freqMin) * 0.02);
    const timeLoSample = det.start_sample / sampleRate, timeHiSample = det.end_sample / sampleRate;
    const timeSpan = Math.max(timeHiSample - timeLoSample, fullDuration * 0.02);
    setView(clampView({
      freqLo: det.freq_lower_hz - freqSpan * 0.6, freqHi: det.freq_upper_hz + freqSpan * 0.6,
      timeLo: timeLoSample - timeSpan * 0.6, timeHi: timeHiSample + timeSpan * 0.6,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jumpTo]);

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
    (freq: number) => PAD_LEFT + ((freq - view.freqLo) / (view.freqHi - view.freqLo)) * plotWidth,
    [view, plotWidth],
  );

  const xToFreq = useCallback(
    (x: number) => view.freqLo + ((x - PAD_LEFT) / plotWidth) * (view.freqHi - view.freqLo),
    [view, plotWidth],
  );

  const timeToY = useCallback(
    (time: number) => PAD_TOP + ((time - view.timeLo) / (view.timeHi - view.timeLo)) * plotHeight,
    [view, plotHeight],
  );

  const yToTime = useCallback(
    (y: number) => view.timeLo + ((y - PAD_TOP) / plotHeight) * (view.timeHi - view.timeLo),
    [view, plotHeight],
  );

  // Nearest measured cell under the cursor; bins are irregular viewport
  // pooling, so this is a linear scan of the edge arrays, not an index formula.
  const powerAt = useCallback(
    (freqHz: number, timeS: number): number | null => {
      if (!spectrogram) return null;
      const fe = spectrogram.frequency_edges_hz, te = spectrogram.time_edges_seconds;
      let f = fe.findIndex((edge, i) => i < fe.length - 1 && freqHz >= edge && freqHz <= fe[i + 1]);
      let t = te.findIndex((edge, i) => i < te.length - 1 && timeS >= edge && timeS <= te[i + 1]);
      if (f === -1) f = freqHz < fe[0] ? 0 : fe.length - 2;
      if (t === -1) t = timeS < te[0] ? 0 : te.length - 2;
      return spectrogram.magnitude_2d[t]?.[f] ?? null;
    },
    [spectrogram],
  );

  useEffect(() => { setPin(null); }, [spectrogram]);

  useEffect(() => {
    if (!pin) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setPin(null); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [pin]);

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
        if (spectrogram.time_edges_seconds[t + 1] < view.timeLo || spectrogram.time_edges_seconds[t] > view.timeHi) continue;
        const y = timeToY(spectrogram.time_edges_seconds[t]);
        const yNext = timeToY(spectrogram.time_edges_seconds[t + 1]);
        const rowHeight = Math.ceil(yNext - y);

        for (let f = 0; f < freqBins; f++) {
          const freq = spectrogram.frequency_edges_hz[f];
          if (freq < view.freqLo || freq > view.freqHi) continue;
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
    const freqStep = (view.freqHi - view.freqLo) / 8;
    for (let i = 0; i <= 8; i++) {
      const freq = view.freqLo + freqStep * i;
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
      const timeS = view.timeLo + (i / 4) * (view.timeHi - view.timeLo);
      ctx.fillText(formatTime(timeS), PAD_LEFT - 6, y);
    }

    // Detection brackets
    for (const det of detections) {
      const x1 = freqToX(det.freq_lower_hz);
      const x2 = freqToX(det.freq_upper_hz);
      const isSelected = det.id === selectedDetectionId;

      // Time extent
      const tStart = timeToY(det.start_sample / sampleRate);
      const tEnd = timeToY(det.end_sample / sampleRate);

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
          const top = timeToY(pulse.start_sample / sampleRate);
          const bottom = timeToY(pulse.end_sample / sampleRate);
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

    // Pinned inspection point, independent of the transient hover crosshair.
    if (pin) {
      ctx.strokeStyle = '#2a82da';
      ctx.fillStyle = '#2a82da';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(pin.x, pin.y, 4, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(pin.x, pin.y, 1.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }, [
    width, height, spectrogram, detections, selectedDetectionId,
    freqToX, timeToY, view, plotWidth, plotHeight, cursorX, cursorY,
    sampleRate, pin,
  ]);

  // Non-passive so the wheel can zoom the viewport instead of scrolling the page.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const handler = (e: WheelEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left, y = e.clientY - rect.top;
      if (x < PAD_LEFT || x > width - PAD_RIGHT || y < PAD_TOP || y > height - PAD_BOTTOM) return;
      e.preventDefault();
      zoomAt(xToFreq(x), yToTime(y), e.deltaY > 0 ? 1.15 : 1 / 1.15);
    };
    canvas.addEventListener('wheel', handler, { passive: false });
    return () => canvas.removeEventListener('wheel', handler);
  }, [width, height, plotWidth, plotHeight, xToFreq, yToTime, zoomAt]);

  const handleMouseMove = (e: React.MouseEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setCursorX(x);
    setCursorY(y);

    if (panRef.current) {
      const dx = x - panRef.current.x, dy = y - panRef.current.y;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) draggedRef.current = true;
      const start = panRef.current.view;
      const freqShift = -(dx / plotWidth) * (start.freqHi - start.freqLo);
      const timeShift = -(dy / plotHeight) * (start.timeHi - start.timeLo);
      setView(clampView({
        freqLo: start.freqLo + freqShift, freqHi: start.freqHi + freqShift,
        timeLo: start.timeLo + timeShift, timeHi: start.timeHi + timeShift,
      }));
      return;
    }

    if (x >= PAD_LEFT && x <= width - PAD_RIGHT && y >= PAD_TOP && y <= height - PAD_BOTTOM) {
      const freq = xToFreq(x);
      const timeS = yToTime(y);
      onCursorMove(freq, timeS, powerAt(freq, timeS));
    } else {
      onCursorMove(null, null, null);
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    panRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top, view };
    draggedRef.current = false;
  };

  const handleClick = (e: React.MouseEvent) => {
    if (draggedRef.current) { draggedRef.current = false; return; }
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    for (const det of detections) {
      const x1 = freqToX(det.freq_lower_hz);
      const x2 = freqToX(det.freq_upper_hz);
      const tStart = timeToY(det.start_sample / sampleRate);
      const tEnd = timeToY(det.end_sample / sampleRate);
      if (x >= x1 - 3 && x <= x2 + 3 && y >= tStart - 3 && y <= tEnd + 3) {
        onSelectDetection(det.id);
        return;
      }
    }

    if (x >= PAD_LEFT && x <= width - PAD_RIGHT && y >= PAD_TOP && y <= height - PAD_BOTTOM) {
      const freq = xToFreq(x);
      const timeS = yToTime(y);
      setPin(prev => prev && Math.abs(prev.x - x) < 4 && Math.abs(prev.y - y) < 4
        ? null : { x, y, freq, time: timeS, power: powerAt(freq, timeS) });
    }
  };

  const handleMouseUp = () => { panRef.current = null; };

  const handleMouseLeave = () => {
    panRef.current = null;
    setCursorX(null);
    setCursorY(null);
    onCursorMove(null, null, null);
  };

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <canvas
        role="img" aria-label="Measured waterfall spectrogram. Scroll to zoom, drag to pan, double-click to reset. Use the detection table to select candidates by keyboard."
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
        onDoubleClick={() => setView({ freqLo: freqMin, freqHi: freqMax, timeLo: 0, timeHi: fullDuration })}
        style={{ cursor: 'crosshair' }}
      />
      <div className="waterfall-zoom-controls">
        <button onClick={() => zoomAt((view.freqLo + view.freqHi) / 2, (view.timeLo + view.timeHi) / 2, 1 / 1.4)} title="Zoom in" aria-label="Zoom in"><ZoomIn size={12} /></button>
        <button onClick={() => zoomAt((view.freqLo + view.freqHi) / 2, (view.timeLo + view.timeHi) / 2, 1.4)} title="Zoom out" aria-label="Zoom out"><ZoomOut size={12} /></button>
        <button onClick={() => setView({ freqLo: freqMin, freqHi: freqMax, timeLo: 0, timeHi: fullDuration })} disabled={!isZoomed} title="Reset zoom" aria-label="Reset zoom"><Maximize2 size={12} /></button>
      </div>
      {pin && (
        <div
          className="waterfall-pin-readout"
          style={{
            left: Math.min(pin.x + 10, width - 150),
            top: Math.min(pin.y + 10, height - 70),
          }}
        >
          <button onClick={() => setPin(null)} aria-label="Dismiss inspection readout">×</button>
          <div><span>Freq</span><strong>{formatFreq(pin.freq)}</strong></div>
          <div><span>Time</span><strong>{formatTime(pin.time)}</strong></div>
          <div><span>Power</span><strong>{pin.power !== null ? formatDb(pin.power) : '—'}</strong></div>
        </div>
      )}
    </div>
  );
}
