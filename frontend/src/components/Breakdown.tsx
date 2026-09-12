import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import WaveSurfer from "wavesurfer.js";
import Regions from "wavesurfer.js/dist/plugins/regions.esm.js";
import Timeline from "wavesurfer.js/dist/plugins/timeline.esm.js";
import SpectrogramPlugin from "wavesurfer.js/dist/plugins/spectrogram.esm.js";
import {
  Play,
  Pause,
  SkipForward,
  X,
  AudioLines,
  LockKeyhole,
  Download,
} from "lucide-react";
import { request, contactName } from "../api";
import type { Analysis, Detection, Envelope, Layer } from "../api";
import { Waveform, PulsePlot } from "./Plots";

export function AudioPlayer({
  layer,
  detection,
  rate,
  onPlayheadChange,
}: {
  layer: Layer;
  detection: Detection;
  rate: number;
  onPlayheadChange?: (absoluteSeconds: number | null) => void;
}) {
  const ref = useRef<HTMLDivElement>(null),
    spectrum = useRef<HTMLDivElement>(null),
    player = useRef<WaveSurfer | null>(null);
  const [playing, setPlaying] = useState(false),
    [ready, setReady] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    if (!ref.current || !spectrum.current || !layer.audio_url) return;
    setReady(false);
    setPlaying(false);
    setError("");
    const regions = Regions.create();
    const ws = WaveSurfer.create({
      container: ref.current,
      waveColor: "#2a82da",
      progressColor: "#1c5a9c",
      height: 72,
      barWidth: 1,
      normalize: false,
      plugins: [
        regions,
        Timeline.create(),
        SpectrogramPlugin.create({
          container: spectrum.current,
          height: 80,
          labels: false,
          fftSamples: 512,
        }),
      ],
    });
    player.current = ws;
    const offset =
      layer.audio_start_seconds ??
      (layer.name === "Detected Region Only"
        ? detection.start_sample / rate
        : 0);
    ws.on("ready", () => {
      setReady(true);
      const start = Math.max(0, detection.start_sample / rate - offset),
        end = Math.min(ws.getDuration(), detection.end_sample / rate - offset);
      if (end > start)
        regions.addRegion({
          start,
          end,
          color: "rgba(110,215,241,.10)",
          drag: false,
          resize: false,
        });
    });
    ws.on("play", () => setPlaying(true));
    ws.on("pause", () => setPlaying(false));
    ws.on("finish", () => setPlaying(false));
    ws.on("timeupdate", (t) => onPlayheadChange?.(t + offset));
    ws.on("interaction", () => onPlayheadChange?.(ws.getCurrentTime() + offset));
    ws.on("error", (e) => {
      if (e.name !== "AbortError") setError(e.message);
    });
    ws.load(layer.audio_url).catch((e) => {
      if (e.name !== "AbortError")
        setError(
          "Could not load this audio clip. Analyze the capture again if the job expired.",
        );
    });
    return () => {
      ws.destroy();
      player.current = null;
      onPlayheadChange?.(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layer, detection, rate]);
  return (
    <div className="audio-player">
      <div className="audio-label">
        <AudioLines size={15} />
        <span>REAL AUDIO PREVIEW</span>
        <button
          disabled={!ready}
          onClick={() =>
            player.current
              ?.playPause()
              .catch(() => setError("Playback could not start. Try again."))
          }
        >
          {playing ? <Pause size={13} /> : <Play size={13} />}{" "}
          {playing ? "Pause" : "Play clip"}
        </button>
        <a
          className="audio-download"
          href={layer.audio_url ?? undefined}
          download={`${layer.name.toLowerCase().replace(/\s+/g, "-")}.wav`}
          aria-label="Download this layer's audio clip"
          title="Download audio clip"
        >
          <Download size={13} /> Audio
        </a>
      </div>
      <div ref={ref} />
      <div ref={spectrum} />
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      <p className="fineprint">
        {layer.audio_description} Clip:{" "}
        {layer.clip_duration_seconds?.toFixed(2)} s.
      </p>
    </div>
  );
}

export default function Breakdown({
  analysis,
  detection,
  onClose,
}: {
  analysis: Analysis;
  detection: Detection;
  onClose: () => void;
}) {
  const [step, setStep] = useState(0),
    [auto, setAuto] = useState(false);
  const layers = useQuery({
    queryKey: ["layers", analysis.job_id, detection.id],
    queryFn: () =>
      request<Layer[]>(
        `/api/detections/${analysis.job_id}/${detection.id}/layers`,
      ),
  });
  const envelope = useQuery({
    queryKey: ["envelope", analysis.job_id, detection.id],
    queryFn: () =>
      request<Envelope>(
        `/api/detections/${analysis.job_id}/${detection.id}/envelope`,
      ),
    enabled: detection.is_pulsed,
  });
  const available = layers.data?.filter((l) => l.enabled) || [];
  useEffect(() => {
    setStep(0);
    setAuto(false);
  }, [analysis.job_id, detection.id]);
  useEffect(() => {
    if (!auto || !available.length) return;
    const timer = setTimeout(() => {
      const next = available.find((l) => l.id > step);
      if (next) setStep(next.id);
      else setAuto(false);
    }, 3200);
    return () => clearTimeout(timer);
  }, [auto, step, available]);
  const layer = layers.data?.find((l) => l.id === step);
  return (
    <motion.section
      id="breakdown"
      className="breakdown panel"
      layout
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 18 }}
    >
      <div className="section-heading">
        <div>
          <span className="eyebrow">{contactName(detection)} / INSPECTION</span>
          <h2>Signal Breakdown — Detect Stage</h2>
        </div>
        <button
          className="icon-button"
          aria-label="Close signal breakdown"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <p className="scope-note">
        Full demodulation into decoded audio/data is Phase 3 (Classify) —
        planned, not built in this version.
      </p>
      {layers.isPending && (
        <p className="empty">
          Computing isolation layers from the selected capture…
        </p>
      )}
      {layers.error && (
        <p role="alert" className="error-text">
          {layers.error.message}{" "}
          <button onClick={() => layers.refetch()}>Retry</button>
        </p>
      )}
      {layers.data && (
        <div className="breakdown-grid">
          <nav className="layer-steps" aria-label="Detection isolation layers">
            {layers.data.map((l) => (
              <button
                key={l.id}
                className={l.id === step ? "current" : ""}
                disabled={!l.enabled}
                title={l.disabled_reason || l.description}
                onClick={() => {
                  setStep(l.id);
                  setAuto(false);
                }}
              >
                <span className="step-number">
                  {String(l.id).padStart(2, "0")}
                </span>
                <span>
                  {l.name}
                  <small>
                    {l.enabled
                      ? l.id === step
                        ? "VIEWING LAYER"
                        : "DETECT TRANSFORM"
                      : "NOT APPLICABLE"}
                  </small>
                </span>
                {!l.enabled && <LockKeyhole size={13} />}
              </button>
            ))}
            <div className="step-actions">
              <button onClick={() => setAuto(!auto)}>
                {auto ? <Pause size={13} /> : <Play size={13} />}{" "}
                {auto ? "Pause sequence" : "Auto-step"}
              </button>
              <button
                disabled={!available.some((l) => l.id > step)}
                onClick={() => {
                  setAuto(false);
                  setStep(available.find((l) => l.id > step)!.id);
                }}
                aria-label="Next applicable layer"
              >
                <SkipForward size={14} />
              </button>
            </div>
            <p className="fineprint">
              Auto-step changes the view. Audio playback is manual.
            </p>
          </nav>
          <div className="layer-content">
            <AnimatePresence mode="wait">
              {layer && (
                <motion.div
                  key={`${detection.id}-${layer.id}`}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="layer-title">
                    <h3>{layer.name}</h3>
                    <span className="mono">
                      {layer.sample_rate.toLocaleString()} Hz
                    </span>
                  </div>
                  <p>{layer.description}</p>
                  <span className="plot-unit">
                    {layer.name === "Envelope View"
                      ? "POWER ENVELOPE / sample-unit²"
                      : "PEAK MAGNITUDE / sample units"}{" "}
                    · TIME / s
                  </span>
                  <Waveform points={layer.waveform} />
                  {layer.audio_url ? (
                    <AudioPlayer
                      layer={layer}
                      detection={detection}
                      rate={analysis.metadata.sample_rate}
                    />
                  ) : (
                    <p className="fineprint">
                      <AudioLines size={14} /> {layer.audio_description}
                    </p>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      )}
      {detection.is_pulsed && (
        <div className="pulse-section">
          <div className="section-heading">
            <h3>Pulse timing</h3>
            <span className="mono">
              PW {detection.pulse_width_samples} samples · PRI{" "}
              {detection.pri_samples ?? "unavailable"} samples
            </span>
          </div>
          <p className="fineprint">
            Measured on the isolated-band power envelope. Amber line:{" "}
            {envelope.data?.threshold_description || "envelope threshold"}.
          </p>
          {envelope.data && (
            <PulsePlot
              data={envelope.data}
              detection={detection}
              rate={analysis.metadata.sample_rate}
            />
          )}{" "}
          {envelope.error && (
            <p role="alert" className="error-text">
              {envelope.error.message}
            </p>
          )}
        </div>
      )}
    </motion.section>
  );
}
