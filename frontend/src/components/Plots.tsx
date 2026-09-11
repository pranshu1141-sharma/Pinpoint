import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
} from "recharts";
import type { Analysis, Detection, Envelope, WavePoint } from "../api";

const grid = "#253039",
  muted = "#8e9ca8",
  accent = "#72d8ef";
const tooltip = {
  background: "#111b22",
  border: "1px solid #34414c",
  fontFamily: "IBM Plex Mono",
  fontSize: 12,
};
export function PSD({ analysis }: { analysis: Analysis }) {
  return (
    <ResponsiveContainer width="100%" height={185}>
      <LineChart
        data={analysis.psd}
        margin={{ top: 16, right: 16, bottom: 0, left: 0 }}
      >
        <CartesianGrid stroke={grid} vertical={false} />
        <XAxis
          dataKey="frequency_hz"
          type="number"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(v) => (Number(v) / 1000).toFixed(0)}
          tick={{ fill: muted, fontSize: 11 }}
          minTickGap={40}
        />
        <YAxis
          tick={{ fill: muted, fontSize: 11 }}
          domain={["auto", "auto"]}
          width={45}
        />
        <Tooltip
          contentStyle={tooltip}
          labelFormatter={(v) => `${(Number(v) / 1000).toFixed(2)} kHz`}
          formatter={(v) => [`${Number(v).toFixed(2)} dB`, "PSD"]}
        />
        <ReferenceLine
          y={analysis.noise_floor_db}
          stroke="#7a8b98"
          strokeDasharray="3 4"
        />
        <ReferenceLine
          y={analysis.threshold_db}
          stroke={accent}
          strokeDasharray="7 4"
        />
        <Line
          dataKey="power_db"
          stroke="#a5bbc9"
          dot={false}
          strokeWidth={1.1}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
export function Waveform({ points }: { points: WavePoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={175}>
      <LineChart
        data={points}
        margin={{ top: 12, right: 20, bottom: 0, left: 0 }}
      >
        <CartesianGrid stroke={grid} vertical={false} />
        <XAxis
          dataKey="time_seconds"
          type="number"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(v) => `${Number(v).toFixed(2)}s`}
          tick={{ fill: muted, fontSize: 11 }}
        />
        <YAxis
          width={48}
          tickFormatter={(v) => Number(v).toPrecision(2)}
          tick={{ fill: muted, fontSize: 11 }}
        />
        <Tooltip contentStyle={tooltip} />
        <Line
          dataKey="value"
          stroke={accent}
          dot={false}
          strokeWidth={1.2}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
export function PulsePlot({
  data,
  detection,
  rate,
}: {
  data: Envelope;
  detection: Detection;
  rate: number;
}) {
  const first = data.pulse_windows[0],
    second = data.pulse_windows[1];
  return (
    <ResponsiveContainer width="100%" height={205}>
      <LineChart
        data={data.waveform}
        margin={{ top: 24, right: 25, bottom: 0, left: 0 }}
      >
        <CartesianGrid stroke={grid} vertical={false} />
        <XAxis
          dataKey="time_seconds"
          type="number"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(v) => `${Number(v).toFixed(2)}s`}
          tick={{ fill: muted, fontSize: 11 }}
        />
        <YAxis
          width={48}
          tickFormatter={(v) => Number(v).toPrecision(2)}
          tick={{ fill: muted, fontSize: 11 }}
        />
        <Tooltip contentStyle={tooltip} />
        <ReferenceLine
          y={data.threshold}
          stroke="#efb257"
          strokeDasharray="3 3"
        />
        {first && (
          <ReferenceArea
            x1={first.start_sample / rate}
            x2={first.end_sample / rate}
            fill={accent}
            fillOpacity={0.16}
            label={{
              value: `PW ${detection.pulse_width_samples} samples`,
              fill: accent,
              fontSize: 11,
              position: "insideTopLeft",
            }}
          />
        )}
        {second && (
          <ReferenceLine
            x={second.start_sample / rate}
            stroke={accent}
            strokeDasharray="4 4"
            label={{
              value: `PRI ${detection.pri_samples} samples`,
              fill: accent,
              fontSize: 11,
              position: "insideTopRight",
            }}
          />
        )}
        <Line
          dataKey="value"
          stroke={accent}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
