import { Activity, FolderOpen, HelpCircle, Loader2, Settings2 } from 'lucide-react';

export function Toolbar({ fileLabel, rate, duration, health, pending, settingsOpen, shortcutsOpen, canAnalyze, hasResult, onOpenFile, onToggleShortcuts, onToggleSettings, onAnalyze }: {
  fileLabel: string;
  rate: number | null;
  duration: number | null;
  health: 'connecting' | 'connected' | 'disconnected';
  pending: boolean;
  settingsOpen: boolean;
  shortcutsOpen: boolean;
  canAnalyze: boolean;
  hasResult: boolean;
  onOpenFile: () => void;
  onToggleShortcuts: () => void;
  onToggleSettings: () => void;
  onAnalyze: () => void;
}) {
  return (
    <header className="bolt-toolbar">
      <button disabled={pending} onClick={onOpenFile}><FolderOpen size={14} />Open File</button><span className="toolbar-divider" />
      <div className="toolbar-file">
        <span>File:</span> <strong>{fileLabel}</strong>
        {rate !== null && duration !== null && <><span>Rate:</span><strong>{rate.toLocaleString()} samples/s</strong><span>Duration:</span><strong>{duration.toFixed(3)} s</strong></>}
      </div>
      <div className="toolbar-actions">
        <span className={`api-status ${health === 'connected' ? 'connected' : ''}`}><i />{{ connecting: 'Connecting', connected: 'API connected', disconnected: 'Not connected' }[health]}</span>
        <button aria-expanded={shortcutsOpen} onClick={onToggleShortcuts} title="Keyboard shortcuts (?)"><HelpCircle size={14} /></button>
        <button disabled={pending} aria-expanded={settingsOpen} onClick={onToggleSettings} title="Capture and detector settings"><Settings2 size={14} /><span>Settings</span></button>
        <button className="primary" disabled={!canAnalyze} onClick={onAnalyze}>
          {pending ? <Loader2 size={14} className="animate-spin" /> : <Activity size={14} />}{pending ? 'Analyzing…' : hasResult ? 'Reanalyze' : 'Analyze'}
        </button>
      </div>
    </header>
  );
}
