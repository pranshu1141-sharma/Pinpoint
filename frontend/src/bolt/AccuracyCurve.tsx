import { useState } from 'react';
import type { AccuracyCurve as AccuracyCurveData, AccuracyCurvePoint } from '../api';

interface AccuracyCurveProps {
  data: AccuracyCurveData | null;
  loading: boolean;
}

const COLORS: Record<string, string> = { bpsk: '#2a82da', qpsk: '#ed776c' };
const W = 280, H = 120, PAD_L = 32, PAD_R = 10, PAD_T = 10, PAD_B = 22;

export function AccuracyCurve({ data, loading }: AccuracyCurveProps) {
  const [hover, setHover] = useState<AccuracyCurvePoint | null>(null);

  if (loading) return <div className="accuracy-curve-empty">Loading validation evidence…</div>;
  if (!data || data.curve.length === 0) return <div className="accuracy-curve-empty">Validation evidence unavailable.</div>;

  const snrValues = [...new Set(data.curve.map((p) => p.snr_db))].sort((a, b) => a - b);
  const kinds = [...new Set(data.curve.map((p) => p.kind))];
  const snrMin = snrValues[0], snrMax = snrValues[snrValues.length - 1];
  const snrSpan = snrMax - snrMin || 1;
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B;

  const x = (snr: number) => PAD_L + ((snr - snrMin) / snrSpan) * plotW;
  const y = (acc: number) => PAD_T + (1 - acc) * plotH;

  return (
    <div className="accuracy-curve">
      <svg viewBox={`0 0 ${W} ${H}`} className="accuracy-curve-svg" role="img" aria-label={data.measure}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={PAD_L} x2={W - PAD_R} y1={y(f)} y2={y(f)} stroke="#353535" strokeWidth={1} />
            <text x={PAD_L - 4} y={y(f)} textAnchor="end" dominantBaseline="middle" className="accuracy-curve-axis">{Math.round(f * 100)}%</text>
          </g>
        ))}
        {snrValues.map((snr) => (
          <text key={snr} x={x(snr)} y={H - PAD_B + 12} textAnchor="middle" className="accuracy-curve-axis">{snr} dB</text>
        ))}
        {kinds.map((kind) => {
          const points = data.curve.filter((p) => p.kind === kind).sort((a, b) => a.snr_db - b.snr_db);
          const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.snr_db)},${y(p.accuracy)}`).join(' ');
          return (
            <g key={kind}>
              <path d={path} fill="none" stroke={COLORS[kind] ?? '#a0a0a0'} strokeWidth={1.5} />
              {points.map((p) => (
                <circle
                  key={p.snr_db}
                  cx={x(p.snr_db)} cy={y(p.accuracy)} r={hover === p ? 4.5 : 3}
                  fill={COLORS[kind] ?? '#a0a0a0'}
                  stroke="#252525" strokeWidth={1}
                  onMouseEnter={() => setHover(p)}
                  onMouseLeave={() => setHover((h) => (h === p ? null : h))}
                  style={{ cursor: 'pointer' }}
                />
              ))}
            </g>
          );
        })}
      </svg>
      <div className="accuracy-curve-legend">
        {kinds.map((kind) => (
          <span key={kind}><i style={{ background: COLORS[kind] ?? '#a0a0a0' }} />{kind.toUpperCase()}</span>
        ))}
      </div>
      <div className="accuracy-curve-readout">
        {hover
          ? `${hover.kind.toUpperCase()} @ ${hover.snr_db} dB — ${(hover.accuracy * 100).toFixed(0)}% (${hover.passed}/${hover.trials} trials)`
          : 'Hover a point for trial counts'}
      </div>
      <p className="accuracy-curve-note">{data.measure}. Source: {data.source}.</p>
    </div>
  );
}
