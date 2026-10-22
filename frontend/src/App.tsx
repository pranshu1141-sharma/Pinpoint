import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, ExternalLink, Loader2 } from 'lucide-react';
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
import { AnalysisPage } from './bolt/AnalysisPage';
import { buildUploadForm, hasWav, needsRawSettings, type CaptureSettings } from './app/upload';
import { useSessionHistory } from './app/history';
import { useKeyboardShortcuts } from './app/useKeyboardShortcuts';
import { Toolbar } from './app/Toolbar';
import { CaptureSettingsBar } from './app/CaptureSettingsBar';
import { WelcomeScreen } from './app/WelcomeScreen';
import { ExportPanel } from './app/ExportPanel';
import { Roadmap, SessionHistoryList } from './app/SidebarPanels';
import { ShortcutsOverlay } from './app/ShortcutsOverlay';

type Run = { demo?: 'iq' | 'audio'; resume?: string };
type Cursor = { frequency: number | null; power: number | null; time: number | null };
const NO_CURSOR: Cursor = { frequency: null, power: null, time: null };

export default function App() {
  const input = useRef<HTMLInputElement>(null), resumed = useRef(false);
  const queryClient = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [result, setResult] = useState<Analysis | null>(null);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [settings, setSettingsState] = useState<CaptureSettings>({ margin: '8', rate: '', datatype: '', wavMode: 'auto', mode: 'adaptive', fixed: '' });
  const updateSettings = (patch: Partial<CaptureSettings>) => setSettingsState(s => ({ ...s, ...patch }));
  const [settingsOpen, setSettingsOpen] = useState(false), [breakdownOpen, setBreakdownOpen] = useState(true);
  const [progress, setProgress] = useState<AnalysisProgress | null>(null);
  const [error, setError] = useState('');
  const { history, record: recordHistory } = useSessionHistory();
  const [cursor, setCursor] = useState<Cursor>(NO_CURSOR);
  const [playheadTime, setPlayheadTime] = useState<number | null>(null);
  const [lastSource, setLastSource] = useState<Run>({});
  const [confidenceFilter, setConfidenceFilter] = useState(0);
  const [jumpTo, setJumpTo] = useState<{ id: string; token: number } | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [analysisView, setAnalysisView] = useState(false);

  const health = useQuery({ queryKey: ['health'], queryFn: () => request<{status: string; max_upload_bytes: number}>('/api/health'), refetchInterval: 15000, retry: false });
  const connected = health.isSuccess && !health.isError;
  const accuracy = useQuery({ queryKey: ['fine-classification-accuracy'], queryFn: () => request<AccuracyCurveData>('/api/validation/fine-classification-accuracy'), enabled: connected, staleTime: Infinity, retry: false });
  const mutation = useMutation({
    mutationFn: async (run: Run) => {
      if (run.resume) return waitForAnalysis(run.resume, setProgress);
      if (run.demo) return request<Analysis>(`/api/demo?kind=${run.demo}&margin_db=${Number(settings.margin)}`, { method: 'POST' });
      return uploadCapture(buildUploadForm(files, settings, health.data?.max_upload_bytes), setProgress);
    },
    onMutate: () => { setError(''); setProgress(null); setResult(null); setSelected(null); setCursor(NO_CURSOR); setConfidenceFilter(0); },
    onSuccess: (data, run) => {
      setResult(data);
      updateSettings({ margin: String(data.settings.margin_db), mode: data.settings.mode, fixed: data.settings.mode === 'fixed_debug' ? String(data.threshold_db) : '' });
      setSelected(data.detections.length ? String(data.detections[0].id) : null);
      setLastSource(run.demo ? { demo: run.demo } : {}); setProgress(null); setBreakdownOpen(true); recordHistory(data);
    },
    onError: (e) => { setError(e.message); setProgress(null); setSettingsOpen(true); },
  });
  const rerun = useMutation({
    mutationFn: (jobId: string) => rerunJob(jobId, { marginDb: Number(settings.margin), mode: settings.mode, fixedThresholdDb: settings.fixed }),
    onMutate: () => setError(''),
    onSuccess: (data) => {
      setResult(data); setRevision(r => r + 1);
      setSelected(data.detections.length ? String(data.detections[0].id) : null);
      queryClient.invalidateQueries({ queryKey: ['spectrogram', data.job_id] }); recordHistory(data);
    },
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
  useEffect(() => { if (!viewDetection) setAnalysisView(false); }, [viewDetection]);

  const psd = useMemo(() => shown ? { freqs: shown.psd.map(p => p.frequency_hz), magnitudes: shown.psd.map(p => p.power_db) } : null, [shown]);
  const sampleRate = shown?.metadata.sample_rate ?? 1;
  const freqMin = shown?.metadata.source_kind === 'audio' ? 0 : -sampleRate / 2, freqMax = sampleRate / 2;
  const captureFile = files.find(f => !/\.sigmf-meta$/i.test(f.name));
  const fileInfo = describeFile(shown?.metadata ?? null, !lastSource.demo && captureFile?.name === shown?.metadata.filename ? captureFile?.size : undefined);
  const bounds = shown ? [shown.noise_floor_db, shown.threshold_db, ...shown.psd.map(p => p.power_db)] : [0];
  const dbMin = Math.floor((Math.min(...bounds) - 5) / 10) * 10, dbMax = Math.ceil((Math.max(...bounds) + 5) / 10) * 10;
  const { margin, mode, fixed } = settings;
  const draftThreshold = shown ? mode === 'adaptive' ? shown.noise_floor_db + Number(margin) : Number(fixed || shown.threshold_db) : 0;
  const changed = !!shown && (shown.settings.mode !== mode || (mode === 'adaptive' ? Number(margin) !== shown.settings.margin_db : Number(fixed) !== shown.threshold_db));

  const select = (id: string) => { setSelected(id); setBreakdownOpen(true); };
  const selectAndJump = (id: string) => { select(id); setJumpTo({ id, token: Date.now() }); };
  useKeyboardShortcuts({
    hasResult: !!shown, candidateIds: visibleDetections.map(d => d.id), selected, shortcutsOpen, setShortcutsOpen,
    deselect: () => setSelected(null), toggleBreakdown: () => setBreakdownOpen(v => !v), selectAndJump,
  });
  function assign(incoming: File[]) {
    if (pending) return;
    setFiles(incoming); setResult(null); setSelected(null); setError(''); updateSettings({ rate: '', datatype: '', wavMode: 'auto' }); setLastSource({});
    setSettingsOpen(incoming.some(f => /\.(iq|wav)$/i.test(f.name)));
  }
  const startDemo = (demo: 'iq' | 'audio') => { setFiles([]); updateSettings({ mode: 'adaptive', fixed: '' }); mutation.mutate({ demo }); };
  const openAnalysis = () => viewDetection && setAnalysisView(true);

  return <div className="bolt-app">
    <input ref={input} type="file" multiple accept=".iq,.wav,.sigmf-data,.sigmf-meta" hidden onChange={e => { assign(Array.from(e.target.files ?? [])); e.target.value = ''; }} />
    <Toolbar
      fileLabel={files.length ? files.map(f => f.name).join(' + ') : shown?.metadata.filename ?? 'No capture loaded'}
      rate={shown ? sampleRate : null} duration={shown ? shown.metadata.duration_seconds : null}
      health={health.isPending ? 'connecting' : connected ? 'connected' : 'disconnected'}
      pending={pending} settingsOpen={settingsOpen} shortcutsOpen={shortcutsOpen}
      canAnalyze={!pending && connected && (files.length > 0 || !!lastSource.demo)} hasResult={!!shown}
      onOpenFile={() => input.current?.click()} onToggleShortcuts={() => setShortcutsOpen(v => !v)}
      onToggleSettings={() => setSettingsOpen(v => !v)} onAnalyze={() => mutation.mutate(lastSource.demo ? lastSource : {})} />
    {settingsOpen && <CaptureSettingsBar settings={settings} onChange={updateSettings} raw={needsRawSettings(files)} wav={hasWav(files)} pending={pending} detectorLocked={!!lastSource.demo} />}
    {!connected && !health.isPending && <div className="bolt-error" role="alert">Not connected. Start the FastAPI backend to analyze captures.<button onClick={() => health.refetch()}>Reconnect</button></div>}
    {(error || spec.isError) && <div className="bolt-error" role="alert">{error || spec.error?.message}<button onClick={() => { setError(''); if (spec.isError) spec.refetch(); }}>Dismiss / retry</button></div>}
    {pending && <div className="bolt-progress" role="status">
      <Loader2 size={13} className="animate-spin" /><span>{progress?.message ?? 'Analyzing the capture…'}</span>
      <progress max="1" value={progress?.fraction ?? undefined} />{progress?.fraction != null && <span>{Math.round(progress.fraction * 100)}%</span>}
    </div>}
    {shown && analysisView && viewDetection ? <AnalysisPage analysis={shown} detection={viewDetection} spectrum={spectrum} psd={psd} freqMin={freqMin} freqMax={freqMax} dbMin={dbMin} dbMax={dbMax} sampleRate={sampleRate} onBack={() => setAnalysisView(false)} /> :
    !shown ? <WelcomeScreen files={files} pending={pending} connected={connected} onBrowse={() => input.current?.click()} onDropFiles={assign} onAnalyze={() => mutation.mutate({})} onDemo={startDemo} /> :
    <main className="bolt-workspace"><div className="bolt-center">
      <section className="fft-section">
        <div className="plot-title">FFT / PSD<span>Welch · {shown.metadata.power_unit}</span></div>
        <FftPlot psdData={psd} noiseFloorDb={shown.noise_floor_db} thresholdDb={draftThreshold} thresholdLabel={changed ? 'Pending threshold — reanalyze' : 'Applied threshold'}
          onThresholdChange={v => mode === 'adaptive' ? updateSettings({ margin: Math.max(3, Math.min(30, v - shown.noise_floor_db)).toFixed(1) }) : updateSettings({ fixed: v.toFixed(1) })}
          detections={visibleDetections} selectedDetectionId={selected} onSelectDetection={select} freqMin={freqMin} freqMax={freqMax} dbMin={dbMin} dbMax={dbMax}
          onCursorMove={(frequency, power) => setCursor({ frequency, power, time: null })} height={170} />
        <div className="plot-caption">Baseband offset · drag threshold to set the next scan {changed
          ? <button disabled={rerun.isPending} onClick={() => rerun.mutate(shown.job_id)}>{rerun.isPending ? <Loader2 size={12} className="animate-spin" /> : null}Apply &amp; re-run</button>
          : <span>{shown.settings.mode === 'fixed_debug' ? 'FIXED DEBUG' : `Adaptive margin ${shown.settings.margin_db} dB`} · {shown.elapsed_ms.toFixed(0)} ms</span>}</div>
        {shown.settings.processing && <p className="block-note">Noise and threshold lines summarize block estimates; each block uses its own threshold.</p>}
      </section>
      <section className="waterfall-section">
        <div className="waterfall-main">
          <div className="plot-title">Waterfall<span>{spec.isFetching ? 'Loading measured spectrogram…' : `${shown.settings.nfft} FFT · ${(sampleRate / shown.settings.nfft).toFixed(3)} Hz/bin`}</span></div>
          <div className="waterfall-canvas"><Waterfall spectrogram={spectrum} detections={visibleDetections} selectedDetectionId={selected} onSelectDetection={select} freqMin={freqMin} freqMax={freqMax}
            onCursorMove={(frequency, time, power) => setCursor({ frequency, time, power })} sampleRate={sampleRate} totalSamples={shown.metadata.sample_count} jumpTo={jumpTo} playheadTime={playheadTime} /></div>
        </div>
        {spectrum && <div className="waterfall-legend"><ColormapLegend minDb={spectrum.min_db} maxDb={spectrum.max_db} height={110} /></div>}
      </section>
      <section className={`bolt-breakdown ${breakdownOpen ? 'open' : ''}`}>
        <button className="dock-toggle" aria-expanded={breakdownOpen} onClick={() => setBreakdownOpen(v => !v)}>
          {breakdownOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}Signal Breakdown — Detect Stage
          <span>{selected !== null ? `C${Number(selected) + 1}` : 'Select a candidate'}</span><small>Space to toggle</small>
        </button>
        {breakdownOpen && <SignalBreakdown key={`${shown.job_id}:${selected}`} analysis={shown} detection={detection} onPlayheadChange={setPlayheadTime} />}
      </section>
    </div><aside className="bolt-sidebar">
      <DockPanel title="Detections" className="detections-dock" actions={<label className="confidence-filter" title="Hide candidates below this confidence from the list and spectrogram">
        <span>Min conf</span><input type="range" min="0" max="1" step="0.01" value={confidenceFilter} onChange={e => setConfidenceFilter(Number(e.target.value))} />
        <span className="confidence-filter-value">{Math.round(confidenceFilter * 100)}%</span>
      </label>}>
        <DetectionsPanel detections={visibleDetections} selectedDetectionId={selected} onSelectDetection={selectAndJump} sampleRate={sampleRate} />
        <p className="evidence-note">Confidence is a heuristic evidence score, not a probability.{detections.length !== visibleDetections.length && ` ${detections.length - visibleDetections.length} candidate(s) hidden below ${Math.round(confidenceFilter * 100)}% confidence.`}</p>
      </DockPanel>
      <DockPanel title="Detection Detail" className="detail-dock" actions={<span className={`analyze-action${viewDetection ? '' : ' disabled'}`} role="button" tabIndex={viewDetection ? 0 : -1}
        title="Open the focused Analysis page for this candidate" onClick={openAnalysis}
        onKeyDown={e => { if (viewDetection && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openAnalysis(); } }}><ExternalLink size={11} />Analyze</span>}>
        <DetectionDetailPanel detection={viewDetection} sampleRate={sampleRate} jobId={shown?.job_id} />
      </DockPanel>
      <DockPanel title="File Info" className="file-dock"><FileInfoPanel fileInfo={fileInfo} /><p className="evidence-note">{shown.metadata.wav_disambiguation.reason}</p></DockPanel>
      <DockPanel title="Pipeline Log" className="log-dock" defaultOpen={false}><PipelineLogPanel logLines={shown.pipeline_log} /></DockPanel>
      <DockPanel title="Export" defaultOpen={false}><ExportPanel key={`${shown.job_id}:${revision}`} jobId={shown.job_id} detections={shown.detections} onError={setError} /></DockPanel>
      <DockPanel title="Fine Classification Accuracy" defaultOpen={false}><AccuracyCurve data={accuracy.data ?? null} loading={accuracy.isPending} /></DockPanel>
      <DockPanel title="Session History" defaultOpen={false}><SessionHistoryList history={history} pending={pending} onResume={jobId => mutation.mutate({ resume: jobId })} /></DockPanel>
      <DockPanel title="Pipeline / Roadmap" defaultOpen={false}><Roadmap /></DockPanel>
      <div className="sidebar-demos">
        <button disabled={pending} onClick={() => startDemo('iq')}>IQ demo</button><button disabled={pending} onClick={() => startDemo('audio')}>Audio demo</button>
        <a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">API contract ↗</a>
      </div>
    </aside></main>}
    {shown
      ? <StatusBar sampleRate={sampleRate} durationSeconds={shown.metadata.duration_seconds} cursorFreq={cursor.frequency} cursorPower={cursor.power} cursorTime={cursor.time} detectionCount={shown.detections.length} thresholdDb={shown.threshold_db} noiseFloorDb={shown.noise_floor_db} selectedDetectionId={selected} />
      : <footer className="welcome-status"><span>SIH26147 · Detect Stage</span><span>{pending ? 'Processing capture' : 'Ready to open a capture'} · Offline analysis · Relative symbol recovery only</span></footer>}
    {shortcutsOpen && <ShortcutsOverlay onClose={() => setShortcutsOpen(false)} />}
  </div>;
}
