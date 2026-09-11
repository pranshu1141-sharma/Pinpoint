import { useState } from 'react';
import { FolderOpen, Radio, Upload } from 'lucide-react';
import { cn } from '@/lib/utils';

interface WelcomeScreenProps {
  onFileOpen: (file: File) => void;
  onAnalyze: () => void;
}

export function WelcomeScreen({ onFileOpen, onAnalyze }: WelcomeScreenProps) {
  const [dragging, setDragging] = useState(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      onFileOpen(file);
      setTimeout(onAnalyze, 100);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };

  const handleDragLeave = () => setDragging(false);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onFileOpen(file);
      setTimeout(onAnalyze, 100);
    }
    e.target.value = '';
  };

  return (
    <div className="flex-1 flex items-center justify-center bg-rf-recessed p-8">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={cn(
          'flex flex-col items-center gap-4 max-w-md w-full p-8 border-2 border-dashed transition-colors',
          dragging ? 'border-rf-accent bg-rf-accent/5' : 'border-rf-border-light bg-rf-plot',
        )}
        style={{ borderRadius: '2px' }}
      >
        <Radio className="w-10 h-10 text-rf-text-secondary" />
        <div className="text-center">
          <h2 className="text-[14px] font-medium text-rf-text-primary mb-1">
            SIH26147 Signal Analysis
          </h2>
          <p className="text-[11px] text-rf-text-secondary">
            Detect-stage pipeline — candidate signal region identification
          </p>
        </div>

        <label
          className={cn(
            'flex items-center gap-2 px-4 py-2 text-[12px] border cursor-pointer transition-colors',
            dragging
              ? 'border-rf-accent text-rf-accent'
              : 'border-rf-border-light text-rf-text-primary hover:border-rf-accent',
          )}
          style={{ borderRadius: '2px' }}
        >
          <Upload className="w-3.5 h-3.5" />
          Drop IQ file here or click to browse
          <input
            type="file"
            className="hidden"
            accept=".wav,.cf32,.iq,.raw,.cfile,.bin"
            onChange={handleFileInput}
          />
        </label>

        <div className="flex items-center gap-4 text-[10px] text-rf-text-secondary">
          <div className="flex items-center gap-1.5">
            <FolderOpen className="w-3 h-3" />
            Supports: .wav, .cf32, .iq, .raw
          </div>
        </div>

        <div className="text-[10px] text-rf-text-secondary/70 text-center max-w-xs">
          After loading a file, click Analyze to run the detection pipeline.
          The threshold line on the FFT plot is draggable to adjust sensitivity.
        </div>
      </div>
    </div>
  );
}
