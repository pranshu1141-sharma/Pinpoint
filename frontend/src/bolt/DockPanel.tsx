import { useState, type ReactNode } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';

interface DockPanelProps {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  actions?: ReactNode;
}

export function DockPanel({
  title,
  children,
  defaultOpen = true,
  className,
  actions,
}: DockPanelProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={cn('flex flex-col bg-rf-panel border border-rf-border', className)}>
      <button type="button" aria-expanded={open}
        className="flex items-center justify-between h-7 px-2 bg-rf-panel border-b border-rf-border cursor-pointer select-none"
        onClick={() => setOpen(!open)}
      >
        <div className="flex items-center gap-1.5">
          {open ? (
            <ChevronDown className="w-3 h-3 text-rf-text-secondary" />
          ) : (
            <ChevronRight className="w-3 h-3 text-rf-text-secondary" />
          )}
          <span className="text-[11px] font-medium text-rf-text-primary tracking-wide uppercase">
            {title}
          </span>
        </div>
        {actions && <div onClick={(e) => e.stopPropagation()}>{actions}</div>}
      </button>
      {open && <div className="flex-1 min-h-0 overflow-auto">{children}</div>}
    </div>
  );
}
