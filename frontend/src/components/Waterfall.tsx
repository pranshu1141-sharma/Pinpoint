import { useEffect, useRef } from "react";
import { motion } from "motion/react";
import type { Analysis, Detection, Spectrogram } from "../api";
import { contactName, khz } from "../api";

// Inferno control points map only measured PSD magnitude to color. Cyan is
// reserved for interaction; the multicolor scale encodes power, not categories.
const inferno = [
  [0, 0, 4],
  [31, 12, 72],
  [85, 15, 109],
  [136, 34, 106],
  [186, 54, 85],
  [227, 89, 51],
  [249, 140, 10],
  [249, 201, 50],
  [252, 255, 164],
];
function color(value: number) {
  const p = Math.max(0, Math.min(0.99999, value)) * (inferno.length - 1),
    i = Math.floor(p),
    q = p - i;
  return inferno[i].map((v, k) => Math.round(v + (inferno[i + 1][k] - v) * q));
}
export default function Waterfall({
  data,
  analysis,
  selected,
  onSelect,
  busy,
}: {
  data?: Spectrogram;
  analysis: Analysis | null;
  selected: number | null;
  onSelect: (d: Detection) => void;
  busy: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  useEffect(() => {
    const el = canvas.current;
    if (!el || !data || !analysis) return;
    const render = () => {
      const rect = el.getBoundingClientRect(),
        dpr = window.devicePixelRatio || 1;
      el.width = rect.width * dpr;
      el.height = rect.height * dpr;
      const ctx = el.getContext("2d")!;
      ctx.scale(dpr, dpr);
      const w = rect.width,
        h = rect.height,
        fe = data.frequency_edges_hz,
        te = data.time_edges_seconds;
      const fx = (v: number) => ((v - fe[0]) / (fe.at(-1)! - fe[0])) * w;
      const ty = (v: number) => (v / te.at(-1)!) * h;
      ctx.fillStyle = "#090d11";
      ctx.fillRect(0, 0, w, h);
      // Render static precomputed cells. Nonuniform pooled edge coordinates
      // keep boxes aligned even when viewport dimensions do not divide STFT bins.
      data.magnitude_db.forEach((row, y) =>
        row.forEach((v, x) => {
          const rgb = color(
            (v - data.min_db) / Math.max(1, data.max_db - data.min_db),
          );
          ctx.fillStyle = `rgb(${rgb.join(",")})`;
          ctx.fillRect(
            fx(fe[x]),
            ty(te[y]),
            fx(fe[x + 1]) - fx(fe[x]) + 0.5,
            ty(te[y + 1]) - ty(te[y]) + 0.5,
          );
        }),
      );
      ctx.strokeStyle = "rgba(220,235,245,.12)";
      ctx.lineWidth = 1;
      for (let i = 1; i < 8; i++) {
        ctx.beginPath();
        ctx.moveTo((w * i) / 8, 0);
        ctx.lineTo((w * i) / 8, h);
        ctx.stroke();
      }
      for (let i = 1; i < 5; i++) {
        ctx.beginPath();
        ctx.moveTo(0, (h * i) / 5);
        ctx.lineTo(w, (h * i) / 5);
        ctx.stroke();
      }
      analysis.detections.forEach((d) => {
        const active = d.id === selectedRef.current;
        ctx.strokeStyle = d.needs_review ? "#efb257" : "#70d8f5";
        ctx.lineWidth = active ? 2 : 1;
        ctx.shadowColor = ctx.strokeStyle;
        ctx.shadowBlur = active ? 9 : 0;
        // A pulse train's aggregate interval is not continuously occupied; show
        // individual measured pulse windows with a dashed outer candidate extent.
        const x = fx(d.freq_lower_hz),
          bw = fx(d.freq_upper_hz) - x;
        const a = ty(d.start_sample / analysis.metadata.sample_rate),
          b = ty(d.end_sample / analysis.metadata.sample_rate);
        ctx.setLineDash(d.is_pulsed ? [4, 4] : []);
        ctx.strokeRect(x + 0.5, a + 0.5, bw - 1, b - a - 1);
        ctx.setLineDash([]);
        d.pulse_windows.forEach((p) =>
          ctx.strokeRect(
            x + 0.5,
            ty(p.start_sample / analysis.metadata.sample_rate),
            bw - 1,
            Math.max(
              1,
              ty(p.end_sample / analysis.metadata.sample_rate) -
                ty(p.start_sample / analysis.metadata.sample_rate),
            ),
          ),
        );
        ctx.shadowBlur = 0;
        ctx.font = '11px "IBM Plex Mono",monospace';
        const label = contactName(d);
        ctx.fillStyle = "#091218";
        ctx.fillRect(x + 2, Math.max(2, a + 3), 35, 19);
        ctx.fillStyle = d.needs_review ? "#efb257" : "#9be6fb";
        ctx.fillText(label, x + 7, Math.max(15, a + 16));
      });
    };
    render();
    const observer = new ResizeObserver(render);
    observer.observe(el);
    return () => observer.disconnect();
  }, [data, analysis, selected]);
  const pick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!data || !analysis) return;
    const rect = event.currentTarget.getBoundingClientRect(),
      fe = data.frequency_edges_hz;
    const frequency =
      fe[0] + ((event.clientX - rect.left) / rect.width) * (fe.at(-1)! - fe[0]);
    const sample =
      ((event.clientY - rect.top) / rect.height) *
      analysis.metadata.sample_count;
    const d = analysis.detections.find(
      (d) =>
        frequency >= d.freq_lower_hz &&
        frequency <= d.freq_upper_hz &&
        sample >= d.start_sample &&
        sample <= d.end_sample,
    );
    if (d) onSelect(d);
  };
  return (
    <div className="waterfall-shell">
      <div className="time-axis">
        <span>TIME / s</span>
        {data &&
          Array.from({ length: 6 }, (_, i) => (
            <b key={i} style={{ top: `${i * 20}%` }}>
              {((data.time_edges_seconds.at(-1)! * i) / 5).toFixed(2)}
            </b>
          ))}
      </div>
      <div className="waterfall-view">
        {data ? (
          <canvas
            ref={canvas}
            onClick={pick}
            role="img"
            aria-label="Measured waterfall spectrogram. Select a candidate with the contact list buttons for keyboard access."
          />
        ) : (
          <div className="plot-empty">
            {busy
              ? "Computing the capture’s time–frequency map…"
              : "No capture analyzed"}
          </div>
        )}
        {busy && (
          <motion.div
            className="scan-line"
            animate={{ top: ["0%", "100%"] }}
            transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
          />
        )}
      </div>
      <div className="frequency-axis">
        {data &&
          Array.from({ length: 7 }, (_, i) => (
            <span key={i}>
              {khz(
                data.frequency_edges_hz[0] +
                  ((data.frequency_edges_hz.at(-1)! -
                    data.frequency_edges_hz[0]) *
                    i) /
                    6,
              )}
            </span>
          ))}
      </div>
      <span className="axis-caption">BASEBAND FREQUENCY / kHz</span>
      <div className="scale-key">
        <span>{data ? data.min_db.toFixed(1) : "—"}</span>
        <div />
        <span>{data ? data.max_db.toFixed(1) : "—"} dB</span>
      </div>
    </div>
  );
}
