import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, FolderOpen, Loader2, Radio, Upload, Settings2, ChevronDown, ChevronRight, Download, Copy, Check } from 'lucide-react';
import { request, rerunJob, uploadCapture, waitForAnalysis, type Analysis, type AnalysisProgress, type Spectrogram, type AccuracyCurve as AccuracyCurveData } from './api';
import { AccuracyCurve } from './bolt/AccuracyCurve';
import { adaptDetections, adaptSpectrogram, describeFile } from './bolt/adapter';
import { FftPlot } from './bolt/FftPlot';
import { Waterfall } from './bolt/Waterfall';
import { DockPanel } from './bolt/DockPanel';
import { DetectionsPanel } from './bolt/DetectionsPanel';
import { DetectionDetailPanel } from './bolt/DetectionDetailPanel';
import { FileInfoPanel } from './bolt/FileInfoPanel';
import { PipelineLogPanel } from './bolt/PipelineLogPanel';
import { StatusBar } from './bolt/StatusBar';
import { ColormapLegend } from './bolt/ColormapLegend';
import { SignalBreakdown } from './bolt/SignalBreakdown';

type Run = { demo?: 'iq' | 'audio'; resume?: string };
export default function App() {
  const input = useRef<HTMLInputElement>(null), resumed = useRef(false);
  const queryClient = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [result, setResult] = useState<Analysis | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [margin, setMargin] = useState('8'), [rate, setRate] = useState(''), [datatype, setDatatype] = useState('');
  const [wavMode, setWavMode] = useState('auto'), [mode, setMode] = useState('adaptive'), [fixed, setFixed] = useState('');
  const [settings, setSettings] = useState(false), [breakdownOpen, setBreakdownOpen] = useState(true), [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<AnalysisProgress | null>(null);
  const [error, setError] = useState(''), [copied, setCopied] = useState(false);
  const [cursor, setCursor] = useState<{ frequency: number | null; power: number | null; time: number | null }>({ frequency: null, power: null, time: null });
  const [playheadTime, setPlayheadTime] = useState<number | null>(null);
  const [lastSource, setLastSource] = useState<Run>({});
  const [confidenceFilter, setConfidenceFilter] = useState(0);
  const health = useQuery({ queryKey: ['health'], queryFn: () => request<{status: string; max_upload_bytes: number}>('/api/health'), refetchInterval: 15000, retry: false });
  const connected = health.isSuccess && !health.isError;
  const accuracy = useQuery({ queryKey: ['fine-classification-accuracy'], queryFn: () => request<AccuracyCurveData>('/api/validation/fine-classification-accuracy'), enabled: connected, staleTime: Infinity, retry: false });
  const mutation = useMutation({
    mutationFn: async (run: Run) => {
      if (run.resume) return waitForAnalysis(run.resume, setProgress);
      if (run.demo) return request<Analysis>(`/api/demo?kind=${run.demo}&margin_db=${Number(margin)}`, { method: 'POST' });
      const captures = files.filter(f => !f.name.toLowerCase().endsWith('.sigmf-meta'));
      const metas = files.filter(f => f.name.toLowerCase().endsWith('.sigmf-meta'));
      if (captures.length !== 1 || metas.length > 1) throw new Error('Select one capture and, for SigMF, its paired metadata file.');
      if (metas.length && captures[0].name.replace(/\.(iq|sigmf-data)$/i, '') !== metas[0].name.replace(/\.sigmf-meta$/i, '')) throw new Error('The capture and SigMF metadata filenames must have matching stems.');
      if (captures[0].size > (health.data?.max_upload_bytes ?? 2147483648)) throw new Error('Maximum capture size is 2 GiB.');
      const body = new FormData(); body.append('file', captures[0]);
      if (metas[0]) body.append('metadata', metas[0]);
      if (rate) body.append('sample_rate', rate);
      if (datatype) body.append('datatype', datatype);
      body.append('wav_mode', wavMode); body.append('margin_db', margin); body.append('mode', mode);
      if (fixed) body.append('fixed_threshold_db', fixed);
      return uploadCapture(body, setProgress);
    },
    onMutate: () => { setError(''); setProgress(null); setResult(null); setSelected(null); setCursor({frequency:null,power:null,time:null}); setConfidenceFilter(0); },
    onSuccess: (data, run) => { setResult(data); setMargin(String(data.settings.margin_db)); setMode(data.settings.mode); setFixed(data.settings.mode === 'fixed_debug' ? String(data.threshold_db) : ''); setSelected(data.detections.length ? String(data.detections[0].id) : null); setLastSource(run.demo ? { demo: run.demo } : {}); setProgress(null); setBreakdownOpen(true); },
    onError: (e) => { setError(e.message); setProgress(null); setSettings(true); },
  });
  const rerun = useMutation({
    mutationFn: (jobId: string) => rerunJob(jobId, { marginDb: Number(margin), mode, fixedThresholdDb: fixed }),
    onMutate: () => setError(''),
    onSuccess: (data) => { setResult(data); setSelected(data.detections.length ? String(data.detections[0].id) : null); queryClient.invalidateQueries({ queryKey: ['spectrogram', data.job_id] }); },
    onError: (e) => setError(e.message),
  });
  useEffect(() => {
    if (connected && !resumed.current) { resumed.current = true; const id = sessionStorage.getItem('detect-active-job'); if (id) mutation.mutate({ resume: id }); }
  }, [connected]);
  const shown = connected ? result : null, pending = mutation.isPending;
  const spec = useQuery({ queryKey: ['spectrogram', shown?.job_id], queryFn: () => request<Spectrogram>(`/api/spectrogram/${shown!.job_id}?width=640&height=380`), enabled: !!shown });
  const spectrum = useMemo(() => spec.data ? adaptSpectrogram(spec.data) : null, [spec.data]);
  const detections = useMemo(() => adaptDetections(shown?.detections ?? []), [shown]);
  const visibleDetections = useMemo(() => detections.filter(d => d.confidence >= confidenceFilter), [detections, confidenceFilter]);
  const detection = shown?.detections.find(d => String(d.id) === selected) ?? null;
  const viewDetection = detections.find(d => d.id === selected) ?? null;
  useEffect(() => {
    if (selected !== null && !visibleDetections.some(d => d.id === selected)) setSelected(null);
  }, [visibleDetections, selected]);
  const psd = useMemo(() => shown ? { freqs: shown.psd.map(p => p.frequency_hz), magnitudes: shown.psd.map(p => p.power_db) } : null, [shown]);
  const sampleRate = shown?.metadata.sample_rate ?? 1;
  const freqMin = shown?.metadata.source_kind === 'audio' ? 0 : -sampleRate / 2, freqMax = sampleRate / 2;
  const captureFile = files.find(f => !/\.sigmf-meta$/i.test(f.name));
  const fileInfo = describeFile(shown?.metadata ?? null, !lastSource.demo && captureFile?.name === shown?.metadata.filename ? captureFile?.size : undefined);
  const bounds = shown ? [shown.noise_floor_db, shown.threshold_db, ...shown.psd.map(p => p.power_db)] : [0];
  const dbMin = Math.floor((Math.min(...bounds) - 5) / 10) * 10, dbMax = Math.ceil((Math.max(...bounds) + 5) / 10) * 10;
  const raw = files.some(f => /\.iq$/i.test(f.name)) && !files.some(f => /\.sigmf-meta$/i.test(f.name)), wav = files.some(f => /\.wav$/i.test(f.name));
  const draftThreshold = shown ? mode === 'adaptive' ? shown.noise_floor_db + Number(margin) : Number(fixed || shown.threshold_db) : 0;
  const changed = !!shown && (shown.settings.mode !== mode || (mode === 'adaptive' ? Number(margin) !== shown.settings.margin_db : Number(fixed) !== shown.threshold_db));
  const select = (id: string) => { setSelected(id); setBreakdownOpen(true); };
  const [jumpTo, setJumpTo] = useState<{ id: string; token: number } | null>(null);
  const selectAndJump = (id: string) => { select(id); setJumpTo({ id, token: Date.now() }); };
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest('input, select, textarea, button, [contenteditable="true"]') || !shown) return;
      if (e.key === 'Escape') setSelected(null);
      if (e.key === ' ') { e.preventDefault(); setBreakdownOpen(v => !v); }
      if (['ArrowDown','ArrowRight','ArrowUp','ArrowLeft'].includes(e.key) && visibleDetections.length) {
        e.preventDefault(); const index = visibleDetections.findIndex(d => d.id === selected), step = ['ArrowDown','ArrowRight'].includes(e.key) ? 1 : -1;
        selectAndJump(visibleDetections[Math.max(0, Math.min(visibleDetections.length - 1, index + step))].id);
      }
    };
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler);
  }, [shown, selected, visibleDetections]);
  function assign(incoming: File[]) {
    if (pending) return;
    setFiles(incoming); setResult(null); setSelected(null); setError(''); setRate(''); setDatatype(''); setWavMode('auto'); setLastSource({});
    setSettings(incoming.some(f => /\.(iq|wav)$/i.test(f.name)));
  }
  function save(value: unknown, filename: string) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type:'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url);
  }
  async function exportSigmf() { if (!shown) return; try { save(await request(`/api/export/${shown.job_id}?format=sigmf`), 'detections.sigmf-meta'); } catch (e) { setError((e as Error).message); } }
  const startDemo = (demo: 'iq' | 'audio') => { setFiles([]); setMode('adaptive'); setFixed(''); mutation.mutate({demo}); };
  return <div className="bolt-app">
    <input ref={input} type="file" multiple accept=".iq,.wav,.sigmf-data,.sigmf-meta" hidden onChange={e => { assign(Array.from(e.target.files ?? [])); e.target.value = ''; }} />
    <header className="bolt-toolbar">
      <button disabled={pending} onClick={() => input.current?.click()}><FolderOpen size={14} />Open File</button><span className="toolbar-divider" />
      <div className="toolbar-file"><span>File:</span> <strong>{files.length ? files.map(f => f.name).join(' + ') : shown?.metadata.filename ?? 'No capture loaded'}</strong>{shown && <><span>Rate:</span><strong>{sampleRate.toLocaleString()} samples/s</strong><span>Duration:</span><strong>{shown.metadata.duration_seconds.toFixed(3)} s</strong></>}</div>
      <div className="toolbar-actions"><span className={`api-status ${connected ? 'connected' : ''}`}><i />{health.isPending ? 'Connecting' : connected ? 'API connected' : 'Not connected'}</span><button disabled={pending} aria-expanded={settings} onClick={() => setSettings(v => !v)} title="Capture and detector settings"><Settings2 size={14} /><span>Settings</span></button><button className="primary" disabled={pending || !connected || (!files.length && !lastSource.demo)} onClick={() => mutation.mutate(lastSource.demo ? lastSource : {})}>{pending ? <Loader2 size={14} className="animate-spin" /> : <Activity size={14} />}{pending ? 'Analyzing…' : shown ? 'Reanalyze' : 'Analyze'}</button></div>
    </header>
    {settings && <section className="capture-settings" aria-label="Capture settings">
      <label>Adaptive margin <input type="number" min="3" max="30" step="0.1" value={margin} onChange={e => setMargin(e.target.value)} disabled={pending} /> dB</label>
      {raw && <><label>Sample rate (Hz)<input type="number" min="1" value={rate} onChange={e => setRate(e.target.value)} disabled={pending} placeholder="Required" /></label><label>Raw datatype<select value={datatype} onChange={e => setDatatype(e.target.value)} disabled={pending}><option value="">Choose encoding</option>{['cf32_le','cf32_be','ci16_le','ci16_be'].map(v => <option key={v}>{v}</option>)}</select></label></>}
      {wav && <label>WAV interpretation<select value={wavMode} onChange={e => setWavMode(e.target.value)} disabled={pending}><option value="auto">Automatic quadrature check</option><option value="iq">Confirm I=left / Q=right</option><option value="audio_left">Left real audio</option><option value="audio_right">Right real audio</option></select></label>}
      <label>Detector<select value={mode} disabled={pending || !!lastSource.demo} onChange={e => setMode(e.target.value)}><option value="adaptive">Adaptive threshold</option><option value="fixed_debug">Fixed threshold — debug</option></select></label>
      {mode === 'fixed_debug' && <label>Absolute threshold (dB/Hz)<input type="number" step="0.1" value={fixed} onChange={e => setFixed(e.target.value)} disabled={pending} /></label>}<span>Up to 2 GiB · select SigMF data + metadata together</span>
    </section>}
    {!connected && !health.isPending && <div className="bolt-error" role="alert">Not connected. Start the FastAPI backend to analyze captures.<button onClick={() => health.refetch()}>Reconnect</button></div>}
    {(error || spec.isError) && <div className="bolt-error" role="alert">{error || spec.error?.message}<button onClick={() => { setError(''); if(spec.isError) spec.refetch(); }}>Dismiss / retry</button></div>}
    {pending && <div className="bolt-progress" role="status"><Loader2 size={13} className="animate-spin" /><span>{progress?.message ?? 'Analyzing the capture…'}</span><progress max="1" value={progress?.fraction ?? undefined} />{progress?.fraction != null && <span>{Math.round(progress.fraction * 100)}%</span>}</div>}
    {!shown ? <main className="bolt-welcome"><div className={`welcome-drop ${dragging ? 'dragging' : ''}`} onDragOver={e => {e.preventDefault(); setDragging(true);}} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); assign(Array.from(e.dataTransfer.files)); }}>
      <Radio size={40} /><h1>SIH26147 Signal Analysis</h1><p>Detect-stage pipeline — candidate signal region identification</p><button disabled={pending} onClick={() => input.current?.click()}><Upload size={14} />Drop IQ file here or click to browse</button>
      {files.length > 0 && <div className="selected-files">{files.map(f => <div key={f.name}>{f.name} · {(f.size / 1024 ** 2).toFixed(2)} MiB</div>)}<button className="primary" disabled={pending || !connected} onClick={() => mutation.mutate({})}>Analyze selected capture</button></div>}
      <small><FolderOpen size={12} />Supports: .wav, .iq, .sigmf-data + .sigmf-meta</small><p className="welcome-help">After loading a file, click Analyze to run the detection pipeline.<br />Use Settings to specify raw IQ or stereo WAV interpretation.</p><div className="demo-buttons"><button disabled={pending || !connected} onClick={() => startDemo('iq')}>IQ demo</button><button disabled={pending || !connected} onClick={() => startDemo('audio')}>Audio demo</button></div><small>Bundled captures processed by the real pipeline.</small>
    </div></main> : <main className="bolt-workspace"><div className="bolt-center">
      <section className="fft-section"><div className="plot-title">FFT / PSD<span>Welch · {shown.metadata.power_unit}</span></div><FftPlot psdData={psd} noiseFloorDb={shown.noise_floor_db} thresholdDb={draftThreshold} thresholdLabel={changed ? 'Pending threshold — reanalyze' : 'Applied threshold'} onThresholdChange={v => { if (mode === 'adaptive') setMargin(Math.max(3, Math.min(30, v - shown.noise_floor_db)).toFixed(1)); else setFixed(v.toFixed(1)); }} detections={visibleDetections} selectedDetectionId={selected} onSelectDetection={select} freqMin={freqMin} freqMax={freqMax} dbMin={dbMin} dbMax={dbMax} onCursorMove={(frequency, power) => setCursor({frequency, power, time:null})} height={170} />
        <div className="plot-caption">Baseband offset · drag threshold to set the next scan {changed ? <button disabled={rerun.isPending} onClick={() => rerun.mutate(shown.job_id)}>{rerun.isPending ? <Loader2 size={12} className="animate-spin" /> : null}Apply &amp; re-run</button> : <span>{shown.settings.mode === 'fixed_debug' ? 'FIXED DEBUG' : `Adaptive margin ${shown.settings.margin_db} dB`} · {shown.elapsed_ms.toFixed(0)} ms</span>}</div>{shown.settings.processing && <p className="block-note">Noise and threshold lines summarize block estimates; each block uses its own threshold.</p>}
      </section>
      <section className="waterfall-section"><div className="waterfall-main"><div className="plot-title">Waterfall<span>{spec.isFetching ? 'Loading measured spectrogram…' : `${shown.settings.nfft} FFT · ${(sampleRate / shown.settings.nfft).toFixed(3)} Hz/bin`}</span></div><div className="waterfall-canvas"><Waterfall spectrogram={spectrum} detections={visibleDetections} selectedDetectionId={selected} onSelectDetection={select} freqMin={freqMin} freqMax={freqMax} onCursorMove={(frequency, time, power) => setCursor({frequency,time,power})} sampleRate={sampleRate} totalSamples={shown.metadata.sample_count} jumpTo={jumpTo} playheadTime={playheadTime} /></div></div>{spectrum && <div className="waterfall-legend"><ColormapLegend minDb={spectrum.min_db} maxDb={spectrum.max_db} height={110} /></div>}</section>
      <section className={`bolt-breakdown ${breakdownOpen ? 'open' : ''}`}><button className="dock-toggle" aria-expanded={breakdownOpen} onClick={() => setBreakdownOpen(v => !v)}>{breakdownOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}Signal Breakdown — Detect Stage<span>{selected !== null ? `C${Number(selected)+1}` : 'Select a candidate'}</span><small>Space to toggle</small></button>{breakdownOpen && <SignalBreakdown key={`${shown.job_id}:${selected}`} analysis={shown} detection={detection} onPlayheadChange={setPlayheadTime} />}</section>
    </div><aside className="bolt-sidebar">
      <DockPanel title="Detections" className="detections-dock" actions={<label className="confidence-filter" title="Hide candidates below this confidence from the list and spectrogram"><span>Min conf</span><input type="range" min="0" max="1" step="0.01" value={confidenceFilter} onChange={e => setConfidenceFilter(Number(e.target.value))} /><span className="confidence-filter-value">{Math.round(confidenceFilter * 100)}%</span></label>}><DetectionsPanel detections={visibleDetections} selectedDetectionId={selected} onSelectDetection={selectAndJump} sampleRate={sampleRate} /><p className="evidence-note">Confidence is a heuristic evidence score, not a probability.{detections.length !== visibleDetections.length && ` ${detections.length - visibleDetections.length} candidate(s) hidden below ${Math.round(confidenceFilter * 100)}% confidence.`}</p></DockPanel>
      <DockPanel title="Detection Detail" className="detail-dock"><DetectionDetailPanel detection={viewDetection} sampleRate={sampleRate} jobId={shown?.job_id} /></DockPanel>
      <DockPanel title="File Info" className="file-dock"><FileInfoPanel fileInfo={fileInfo} /><p className="evidence-note">{shown.metadata.wav_disambiguation.reason}</p></DockPanel>
      <DockPanel title="Pipeline Log" className="log-dock" defaultOpen={false}><PipelineLogPanel logLines={shown.pipeline_log} /></DockPanel>
      <DockPanel title="Export / JSON" defaultOpen={false}><div className="export-actions"><button onClick={async () => {try {await navigator.clipboard.writeText(JSON.stringify(shown.detections,null,2));setCopied(true);setTimeout(()=>setCopied(false),1500);}catch {setError('Clipboard unavailable. Use JSON download.');}}}>{copied ? <Check size={12}/> : <Copy size={12}/>}Copy</button><button onClick={() => save(shown.detections,'detections.json')}><Download size={12}/>JSON</button><button onClick={exportSigmf}>SigMF</button></div><pre>{JSON.stringify(shown.detections,null,2)}</pre></DockPanel>
      <DockPanel title="Fine Classification Accuracy" defaultOpen={false}><AccuracyCurve data={accuracy.data ?? null} loading={accuracy.isPending} /></DockPanel>
      <DockPanel title="Pipeline / Roadmap" defaultOpen={false}><div className="roadmap"><p><b>Detect · Estimate · Classify · built</b> → Report</p><p>Classify now includes coarse envelope family, Mth-power carrier refinement, fine PSK classification (BPSK/QPSK only) and symbol-rate estimation, each gated to its validated SNR range with an explicit unknown status otherwise. FM and pulsed candidates never receive a fine label or symbol rate.</p><p>Planned, not built: cyclostationary analysis, deep-learning detection, co-channel separation, frequency-hopping tracking, matched filtering, real-time streaming, and the Report stage.</p><p>Demodulation into decoded audio/data remains planned, not built in this version.</p></div></DockPanel>
      <div className="sidebar-demos"><button disabled={pending} onClick={() => startDemo('iq')}>IQ demo</button><button disabled={pending} onClick={() => startDemo('audio')}>Audio demo</button><a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">API contract ↗</a></div>
    </aside></main>}
    {shown ? <StatusBar sampleRate={sampleRate} durationSeconds={shown.metadata.duration_seconds} cursorFreq={cursor.frequency} cursorPower={cursor.power} cursorTime={cursor.time} detectionCount={shown.detections.length} thresholdDb={shown.threshold_db} noiseFloorDb={shown.noise_floor_db} selectedDetectionId={selected} /> : <footer className="welcome-status"><span>SIH26147 · Detect Stage</span><span>{pending ? 'Processing capture' : 'Ready to open a capture'} · Offline analysis · No decoding</span></footer>}
  </div>;
}
