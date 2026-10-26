import { useState } from 'react';
import { Check, Copy, Download } from 'lucide-react';
import { request } from '../api';

function save(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); URL.revokeObjectURL(url);
}

/** JSON/SigMF export preview, copy and download. Remount (key) per result to reset to JSON. */
export function ExportPanel({ jobId, detections, onError }: {
  jobId: string;
  detections: unknown[];
  onError: (message: string) => void;
}) {
  const [view, setView] = useState<'json' | 'sigmf'>('json');
  const [sigmf, setSigmf] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const shown = view === 'sigmf' ? sigmf : detections;

  async function loadSigmf() {
    setView('sigmf'); setSigmf(null); setLoading(true);
    try { setSigmf(await request(`/api/export/${jobId}?format=sigmf`)); }
    catch (e) { onError((e as Error).message); setView('json'); }
    finally { setLoading(false); }
  }

  async function copy() {
    try { await navigator.clipboard.writeText(JSON.stringify(shown, null, 2)); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch { onError('Clipboard unavailable. Use download instead.'); }
  }

  return <>
    <div className="export-tabs" role="tablist" aria-label="Export format preview">
      <button role="tab" aria-selected={view === 'json'} onClick={() => setView('json')}>JSON</button>
      <button role="tab" aria-selected={view === 'sigmf'} onClick={loadSigmf}>SigMF</button>
    </div>
    <div className="export-actions">
      <button onClick={copy} disabled={view === 'sigmf' && !sigmf}>{copied ? <Check size={12} /> : <Copy size={12} />}Copy</button>
      <button onClick={() => view === 'sigmf' ? save(sigmf, 'detections.sigmf-meta') : save(detections, 'detections.json')} disabled={view === 'sigmf' && !sigmf}>
        <Download size={12} />Download {view === 'sigmf' ? '.sigmf-meta' : '.json'}
      </button>
    </div>
    {view === 'sigmf' && loading ? <p className="export-loading">Fetching SigMF metadata…</p> : <pre>{JSON.stringify(shown, null, 2)}</pre>}
  </>;
}
