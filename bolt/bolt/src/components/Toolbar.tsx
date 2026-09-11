import { useRef } from 'react';
import { FolderOpen, Activity, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ToolbarProps {
  onFileOpen: (file: File) => void;
  onAnalyze: () => void;
  isAnalyzing: boolean;
  fileName: string | null;
  sampleRate: number | null;
  durationSeconds: number | null;
  hasFile: boolean;
  hasAnalysis: boolean;
}

export function Toolbar({
  onFileOpen,
  onAnalyze,
  isAnalyzing,
  fileName,
  sampleRate,
  durationSeconds,
  hasFile,
  hasAnalysis,
}: ToolbarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="flex items-center gap-3 h-9 px-3 bg-rf-panel border-b border-rf-border shrink-0">
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        accept=".wav,.cf32,.iq,.raw,.cfile,.bin"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFileOpen(file);
          e.target.value = '';
        }}
      />
      <button
        onClick={() => fileInputRef.current?.click()}
        className="flex items-center gap-1.5 h-7 px-2.5 text-[12px] text-rf-text-primary bg-rf-recessed border border-rf-border-light hover:border-rf-accent transition-colors"
        style={{ borderRadius: '2px' }}
      >
        <FolderOpen className="w-3.5 h-3.5" />
        Open File
      </button>

      <div className="h-5 w-px bg-rf-border" />

      {fileName && (
        <div className="flex items-center gap-3 text-[12px]">
          <span className="text-rf-text-secondary">File:</span>
          <span className="font-mono text-rf-text-primary">{fileName}</span>
          {sampleRate && (
            <>
              <span className="text-rf-text-secondary">|</span>
              <span className="text-rf-text-secondary">Rate:</span>
              <span className="font-mono text-rf-text-primary tabular-nums">
                {(sampleRate / 1e6).toFixed(2)} Msps
              </span>
            </>
          )}
          {durationSeconds && (
            <>
              <span className="text-rf-text-secondary">|</span>
              <span className="text-rf-text-secondary">Duration:</span>
              <span className="font-mono text-rf-text-primary tabular-nums">
                {durationSeconds.toFixed(3)} s
              </span>
            </>
          )}
        </div>
      )}

      <div className="flex-1" />

      <button
        onClick={onAnalyze}
        disabled={!hasFile || isAnalyzing}
        className={cn(
          'flex items-center gap-1.5 h-7 px-3 text-[12px] border transition-colors',
          hasFile && !isAnalyzing
            ? 'bg-rf-accent text-white border-rf-accent hover:bg-rf-accent-dim'
            : 'bg-rf-recessed text-rf-text-secondary border-rf-border-light cursor-not-allowed',
        )}
        style={{ borderRadius: '2px' }}
      >
        {isAnalyzing ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <Activity className="w-3.5 h-3.5" />
        )}
        {isAnalyzing ? 'Analyzing...' : 'Analyze'}
      </button>
    </div>
  );
}
