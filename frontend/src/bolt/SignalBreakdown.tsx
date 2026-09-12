import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Download } from 'lucide-react';
import { request, type Analysis, type Detection, type Layer, type Envelope } from '../api';
import { AudioPlayer } from '../components/Breakdown';
import { Waveform, PulsePlot } from '../components/Plots';
import { formatFreq, formatTime, formatSamples } from './format';

const SPEED_OPTIONS = [800, 1600, 3200, 6400];

function downloadWaveformSvg(container: HTMLDivElement | null, filename: string) {
  const svg = container?.querySelector('svg');
  if (!svg) return;
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('style', 'background:#1e1e1e');
  const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

export function SignalBreakdown({analysis, detection, onPlayheadChange}: {analysis: Analysis; detection: Detection | null; onPlayheadChange?: (t: number | null) => void}) {
  const [active, setActive] = useState(0), [auto, setAuto] = useState(false), [speed, setSpeed] = useState(3200);
  const waveRef = useRef<HTMLDivElement>(null);
  const layers = useQuery({queryKey:['layers',analysis.job_id,detection?.id], queryFn: () => request<Layer[]>(`/api/detections/${analysis.job_id}/${detection!.id}/layers`), enabled: !!detection});
  const envelope = useQuery({queryKey:['envelope',analysis.job_id,detection?.id], queryFn: () => request<Envelope>(`/api/detections/${analysis.job_id}/${detection!.id}/envelope`), enabled: !!detection?.is_pulsed});
  const layer = layers.data?.find(l => l.id === active);
  useEffect(() => { if (!auto) return; const timer = setTimeout(() => { const next = layers.data?.find(l => l.enabled && l.id > active); if(next) setActive(next.id); else setAuto(false); },speed); return () => clearTimeout(timer); },[auto, active, layers.data, speed]);
  if (!detection) return <p className="breakdown-empty">Select a detection to view its signal breakdown.</p>;
  const rate = analysis.metadata.sample_rate;
  return <div className="signal-breakdown-content">
    <div className="scope-note"><AlertTriangle size={12}/><span>Full demodulation into decoded audio/data is Phase 3 (Classify) — planned, not built in this version.</span></div>
    <div className="breakdown-metadata"><span>ID: <b>C{detection.id+1}</b></span><span>CF: <b>{formatFreq((detection.freq_lower_hz+detection.freq_upper_hz)/2)}</b></span><span>BW: <b>{formatFreq(detection.freq_upper_hz-detection.freq_lower_hz)}</b></span><span>Time: <b>{formatTime(detection.start_sample/rate)}–{formatTime(detection.end_sample/rate)}</b></span><span>N: <b>{formatSamples(detection.end_sample-detection.start_sample)}</b></span></div>
    {layers.isPending && <p className="breakdown-empty">Loading layers…</p>}{layers.isError && <p className="bolt-error" role="alert">{layers.error.message}<button onClick={() => layers.refetch()}>Retry</button></p>}
    <div className="layer-tabs" role="tablist" aria-label="Detection isolation layers">{layers.data?.map(l => <button key={l.id} role="tab" aria-selected={l.id === active} disabled={!l.enabled} title={l.enabled ? l.description : l.disabled_reason ?? 'Not applicable'} onClick={() => {setActive(l.id);setAuto(false);}}>{l.name}{!l.enabled && <small> (n/a)</small>}</button>)}
      {layers.data && <button className="auto-step" onClick={() => setAuto(v => !v)}>{auto ? 'Stop auto-step' : 'Auto-step'}</button>}
      {layers.data && <label className="auto-step-speed" title="Auto-step interval per layer">
        <span>Speed</span>
        <input type="range" min={0} max={SPEED_OPTIONS.length - 1} step={1}
          value={SPEED_OPTIONS.indexOf(speed)}
          onChange={e => setSpeed(SPEED_OPTIONS[Number(e.target.value)])} />
        <span className="auto-step-speed-value">{(speed / 1000).toFixed(1)}s</span>
      </label>}
    </div>
    {layer && <div className="layer-content" role="tabpanel" aria-label={layer.name}><p>{layer.description}</p>
      <div className="wave-panel" ref={waveRef}>
        <div className="plot-title">{layer.name === 'Envelope View' ? 'Power envelope' : 'Peak magnitude'}<span>{layer.sample_rate.toLocaleString()} samples/s · {layer.sample_count.toLocaleString()} samples</span>
          <button className="layer-download" title="Download this layer's waveform as an image" onClick={() => downloadWaveformSvg(waveRef.current, `${layer.name.toLowerCase().replace(/\s+/g,'-')}.svg`)}><Download size={11}/></button>
        </div>
        <Waveform points={layer.waveform}/>
      </div>
      {layer.audio_url ? <AudioPlayer layer={layer} detection={detection} rate={rate} onPlayheadChange={onPlayheadChange}/> : <p className="no-audio">{layer.audio_description}</p>}
      {detection.is_pulsed && <div className="wave-panel"><div className="plot-title">Pulse timing<span>PW: {detection.pulse_width_samples ?? '—'} samples · PRI: {detection.pri_samples ?? '—'} samples</span></div>{envelope.data && <><PulsePlot data={envelope.data} detection={detection} rate={rate}/><p>{envelope.data.threshold_description ?? 'Envelope threshold'} · measured isolated-band power</p></>}{envelope.isError && <p role="alert">{envelope.error.message}</p>}</div>}
    </div>}
  </div>;
}
