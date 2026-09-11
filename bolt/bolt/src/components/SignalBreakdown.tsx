import { useRef, useEffect, useState, useCallback } from 'react';
import type WaveSurfer from 'wavesurfer.js';
import type { DetectionLayersResponse, DetectionLayer, Detection } from '@/lib/types';
import { cn } from '@/lib/utils';
import { AlertTriangle, Play, Pause } from 'lucide-react';
import { formatFreq, formatTime, formatSamples } from '@/lib/format';

interface SignalBreakdownProps {
  layers: DetectionLayersResponse | null;
  isLoading: boolean;
  detection: Detection | null;
  sampleRate: number;
}

export function SignalBreakdown({
  layers,
  isLoading,
  detection,
  sampleRate,
}: SignalBreakdownProps) {
  const [activeLayer, setActiveLayer] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const waveformCanvasRef = useRef<HTMLCanvasElement>(null);
  const wsContainerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const [fadeKey, setFadeKey] = useState(0);

  const currentLayer: DetectionLayer | null =
    layers?.layers[activeLayer] ?? null;

  // Reset to first tab when detection changes
  useEffect(() => {
    setActiveLayer(0);
    setIsPlaying(false);
  }, [detection?.id]);

  // Draw waveform on canvas
  useEffect(() => {
    const canvas = waveformCanvasRef.current;
    if (!canvas || !currentLayer || !currentLayer.available) return;

    const container = canvas.parentElement;
    if (!container) return;
    const w = container.clientWidth;
    const h = 120;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#1e1e1e';
    ctx.fillRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = '#2a2a2a';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = (h / 4) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
    for (let i = 0; i <= 10; i++) {
      const x = (w / 10) * i;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }

    // Zero line
    ctx.strokeStyle = '#3c3c3c';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, h / 2);
    ctx.lineTo(w, h / 2);
    ctx.stroke();

    // Waveform with fill
    const data = currentLayer.waveform;
    if (data.length > 0) {
      // Fill
      ctx.beginPath();
      const step = data.length / w;
      for (let x = 0; x < w; x++) {
        const idx = Math.floor(x * step);
        const val = data[idx] ?? 0;
        const y = h / 2 - val * (h / 2) * 0.85;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.lineTo(w, h / 2);
      ctx.lineTo(0, h / 2);
      ctx.closePath();
      ctx.fillStyle = 'rgba(42, 130, 218, 0.08)';
      ctx.fill();

      // Line
      ctx.strokeStyle = '#2a82da';
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = 0; x < w; x++) {
        const idx = Math.floor(x * step);
        const val = data[idx] ?? 0;
        const y = h / 2 - val * (h / 2) * 0.85;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    // Axis labels
    ctx.fillStyle = '#7f7f7f';
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('0', 2, 2);
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText('+1.0', w - 2, h / 2 - 2);
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillText('-1.0', w - 2, h / 2 + 2);
  }, [currentLayer, fadeKey]);

  // Setup wavesurfer player
  useEffect(() => {
    if (!wsContainerRef.current || !currentLayer || !currentLayer.available) {
      if (wsRef.current) {
        wsRef.current.destroy();
        wsRef.current = null;
      }
      return;
    }

    let cancelled = false;

    const setupWaveSurfer = async () => {
      const WaveSurferMod = (await import('wavesurfer.js')).default;
      if (cancelled || !wsContainerRef.current) return;

      if (wsRef.current) {
        wsRef.current.destroy();
        wsRef.current = null;
      }

      const data = currentLayer.waveform;
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      const buffer = audioCtx.createBuffer(1, data.length, sampleRate);
      const channelData = buffer.getChannelData(0);
      for (let i = 0; i < data.length; i++) {
        channelData[i] = Math.max(-1, Math.min(1, data[i]));
      }

      const wavBlob = audioBufferToWav(buffer);
      const url = URL.createObjectURL(wavBlob);
      audioCtx.close();

      const ws = WaveSurferMod.create({
        container: wsContainerRef.current,
        waveColor: '#2a82da',
        progressColor: '#1c5a9c',
        cursorColor: '#d4d4d4',
        cursorWidth: 1,
        height: 64,
        barWidth: 1,
        barGap: 1,
        normalize: true,
        interact: true,
      });

      ws.load(url);
      ws.on('play', () => setIsPlaying(true));
      ws.on('pause', () => setIsPlaying(false));
      ws.on('finish', () => setIsPlaying(false));
      wsRef.current = ws;
    };

    setupWaveSurfer();
    setFadeKey(k => k + 1);

    return () => {
      cancelled = true;
    };
  }, [currentLayer, sampleRate]);

  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.destroy();
        wsRef.current = null;
      }
    };
  }, []);

  const handlePlayPause = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.playPause();
    }
  }, []);

  if (!detection) {
    return (
      <div className="flex items-center justify-center h-full text-rf-text-secondary text-[12px] p-4">
        Select a detection to view its signal breakdown.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-rf-text-secondary text-[12px] p-4">
        Loading layers...
      </div>
    );
  }

  if (!layers || layers.layers.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-rf-text-secondary text-[12px] p-4">
        No layer data available for this detection.
      </div>
    );
  }

  const startTime = detection.start_sample / sampleRate;
  const endTime = detection.end_sample / sampleRate;
  const centerFreq = (detection.freq_lower_hz + detection.freq_upper_hz) / 2;
  const bandwidth = detection.freq_upper_hz - detection.freq_lower_hz;
  const sampleCount = detection.end_sample - detection.start_sample;

  return (
    <div className="flex flex-col h-full bg-rf-recessed">
      {/* Detect-stage notice */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-rf-panel border-b border-rf-border">
        <AlertTriangle className="w-3 h-3 text-rf-text-secondary shrink-0" />
        <span className="text-[10px] text-rf-text-secondary">
          Detect-stage isolation only — full demodulation is a planned future stage (Classify), not built here.
        </span>
      </div>

      {/* Detection metadata bar */}
      <div className="flex items-center gap-4 px-3 py-1 bg-rf-recessed border-b border-rf-border text-[10px] font-mono">
        <span className="text-rf-text-secondary">ID: <span className="text-rf-text-primary">{detection.id}</span></span>
        <span className="text-rf-text-secondary">CF: <span className="text-rf-text-primary tabular-nums">{formatFreq(centerFreq)}</span></span>
        <span className="text-rf-text-secondary">BW: <span className="text-rf-text-primary tabular-nums">{formatFreq(bandwidth)}</span></span>
        <span className="text-rf-text-secondary">Time: <span className="text-rf-text-primary tabular-nums">{formatTime(startTime)}–{formatTime(endTime)}</span></span>
        <span className="text-rf-text-secondary">N: <span className="text-rf-text-primary tabular-nums">{formatSamples(sampleCount)}</span></span>
        {detection.is_pulsed && detection.pulse_width_samples !== null && (
          <span className="text-rf-text-secondary">PW: <span className="text-rf-text-primary tabular-nums">{formatSamples(detection.pulse_width_samples)}</span></span>
        )}
        {detection.is_pulsed && detection.pri_samples !== null && (
          <span className="text-rf-text-secondary">PRI: <span className="text-rf-text-primary tabular-nums">{formatSamples(detection.pri_samples)}</span></span>
        )}
      </div>

      {/* Layer tabs */}
      <div className="flex items-center gap-0 px-2 py-1 bg-rf-panel border-b border-rf-border">
        {layers.layers.map((layer, idx) => (
          <button
            key={idx}
            disabled={!layer.available}
            onClick={() => setActiveLayer(idx)}
            className={cn(
              'px-3 py-1.5 text-[11px] border-b-2 transition-colors',
              idx === activeLayer
                ? 'border-rf-accent text-rf-text-primary bg-rf-recessed'
                : layer.available
                  ? 'border-transparent text-rf-text-secondary hover:text-rf-text-primary'
                  : 'border-transparent text-rf-text-secondary/50 cursor-not-allowed',
            )}
            style={{ borderRadius: 0 }}
          >
            {layer.name}
            {!layer.available && (
              <span className="ml-1.5 text-[9px] text-rf-text-secondary/50">(n/a)</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      {currentLayer && currentLayer.available ? (
        <div
          key={fadeKey}
          className="flex-1 flex flex-col gap-2 p-3 overflow-auto"
          style={{ animation: 'fadeIn 120ms ease-out' }}
        >
          <div className="text-[11px] text-rf-text-secondary">{currentLayer.description}</div>

          {/* Waveform canvas */}
          <div className="border border-rf-border bg-rf-plot">
            <div className="flex items-center px-2 py-1 text-[10px] text-rf-text-secondary uppercase tracking-wide border-b border-rf-border">
              <span>Waveform</span>
              <span className="ml-auto font-mono normal-case tracking-normal">{currentLayer.waveform.length.toLocaleString()} samples</span>
            </div>
            <canvas ref={waveformCanvasRef} />
          </div>

          {/* Wavesurfer player */}
          <div className="border border-rf-border bg-rf-plot">
            <div className="flex items-center gap-2 px-2 py-1 border-b border-rf-border">
              <span className="text-[10px] text-rf-text-secondary uppercase tracking-wide">Audio Playback</span>
              <button
                onClick={handlePlayPause}
                className="ml-auto flex items-center gap-1 px-2 py-0.5 text-[10px] text-rf-text-primary bg-rf-panel border border-rf-border-light hover:border-rf-accent transition-colors"
                style={{ borderRadius: '2px' }}
              >
                {isPlaying ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
                {isPlaying ? 'Pause' : 'Play'}
              </button>
            </div>
            <div ref={wsContainerRef} className="px-2 py-2" />
          </div>
        </div>
      ) : currentLayer && !currentLayer.available ? (
        <div className="flex-1 flex items-center justify-center text-rf-text-secondary text-[12px] p-4">
          <div className="text-center">
            <div className="mb-1 text-rf-text-primary text-[13px]">{currentLayer.name}</div>
            <div className="text-[11px]">{currentLayer.description}</div>
            <div className="mt-2 text-[10px] text-rf-alert">This layer does not apply to this detection.</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function audioBufferToWav(buffer: AudioBuffer): Blob {
  const numChannels = buffer.numberOfChannels;
  const sampleRate = buffer.sampleRate;
  const format = 1;
  const bitDepth = 16;
  const bytesPerSample = bitDepth / 8;
  const blockAlign = numChannels * bytesPerSample;
  const dataSize = buffer.length * blockAlign;
  const bufferSize = 44 + dataSize;
  const arrayBuffer = new ArrayBuffer(bufferSize);
  const view = new DataView(arrayBuffer);

  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, format, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitDepth, true);
  writeString(view, 36, 'data');
  view.setUint32(40, dataSize, true);

  const channelData = buffer.getChannelData(0);
  let offset = 44;
  for (let i = 0; i < buffer.length; i++) {
    const sample = Math.max(-1, Math.min(1, channelData[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }

  return new Blob([arrayBuffer], { type: 'audio/wav' });
}

function writeString(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}
