import { useEffect, useRef } from 'react';

interface PipelineLogPanelProps {
  logLines: string[];
}

export function PipelineLogPanel({ logLines }: PipelineLogPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logLines]);

  if (logLines.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-rf-text-secondary text-[11px] p-4">
        No pipeline output. Run analysis to see processing logs.
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      className="overflow-auto h-full p-2 space-y-0.5"
    >
      {logLines.map((line, i) => (
        <div key={i} className="flex items-start gap-2 text-[11px] font-mono leading-relaxed">
          <span className="text-rf-text-secondary tabular-nums shrink-0 select-none">
            {String(i + 1).padStart(3, '0')}
          </span>
          <span className="text-rf-text-primary">{line}</span>
        </div>
      ))}
    </div>
  );
}
