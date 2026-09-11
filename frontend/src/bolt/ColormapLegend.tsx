import { useEffect, useRef } from 'react';
import { colormap } from './colormap';

interface ColormapLegendProps {
  minDb: number;
  maxDb: number;
  height: number;
}

export function ColormapLegend({ minDb, maxDb, height }: ColormapLegendProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const w = 16;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    for (let y = 0; y < height; y++) {
      const normalized = 1 - y / height;
      const [r, g, b] = colormap(normalized);
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.fillRect(0, y, w, 1);
    }
  }, [height]);

  return (
    <div className="flex flex-col items-center shrink-0">
      <span className="text-[9px] font-mono text-rf-text-secondary tabular-nums pb-1">
        {maxDb.toFixed(0)}
      </span>
      <canvas ref={canvasRef} />
      <span className="text-[9px] font-mono text-rf-text-secondary tabular-nums pt-1">
        {minDb.toFixed(0)}
      </span>
      <span className="text-[8px] text-rf-text-secondary mt-0.5">dB</span>
    </div>
  );
}
