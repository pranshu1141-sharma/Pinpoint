import { useState } from 'react';
import { FolderOpen, Radio, Upload } from 'lucide-react';

export function WelcomeScreen({ files, pending, connected, onBrowse, onDropFiles, onAnalyze, onDemo }: {
  files: File[];
  pending: boolean;
  connected: boolean;
  onBrowse: () => void;
  onDropFiles: (files: File[]) => void;
  onAnalyze: () => void;
  onDemo: (demo: 'iq' | 'audio') => void;
}) {
  const [dragging, setDragging] = useState(false);
  return (
    <main className="bolt-welcome">
      <div className={`welcome-drop ${dragging ? 'dragging' : ''}`}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); onDropFiles(Array.from(e.dataTransfer.files)); }}>
        <Radio size={40} /><h1>SIH26147 Signal Analysis</h1><p>Detect-stage pipeline — candidate signal region identification</p>
        <button disabled={pending} onClick={onBrowse}><Upload size={14} />Drop IQ file here or click to browse</button>
        {files.length > 0 && <div className="selected-files">
          {files.map(f => <div key={f.name}>{f.name} · {(f.size / 1024 ** 2).toFixed(2)} MiB</div>)}
          <button className="primary" disabled={pending || !connected} onClick={onAnalyze}>Analyze selected capture</button>
        </div>}
        <small><FolderOpen size={12} />Supports: .wav, .iq, .sigmf-data + .sigmf-meta</small>
        <p className="welcome-help">After loading a file, click Analyze to run the detection pipeline.<br />Use Settings to specify raw IQ or stereo WAV interpretation.</p>
        <div className="demo-buttons">
          <button disabled={pending || !connected} onClick={() => onDemo('iq')}>IQ demo</button>
          <button disabled={pending || !connected} onClick={() => onDemo('audio')}>Audio demo</button>
        </div>
        <small>Bundled captures processed by the real pipeline.</small>
      </div>
    </main>
  );
}
