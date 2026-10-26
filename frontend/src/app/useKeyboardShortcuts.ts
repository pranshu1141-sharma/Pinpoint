import { useEffect } from 'react';

type Options = {
  hasResult: boolean;
  candidateIds: string[];
  selected: string | null;
  shortcutsOpen: boolean;
  setShortcutsOpen: (update: (open: boolean) => boolean) => void;
  deselect: () => void;
  toggleBreakdown: () => void;
  selectAndJump: (id: string) => void;
};

/** ? overlay, Esc close/deselect, Space breakdown, arrows step candidates; inactive while typing or on a button. */
export function useKeyboardShortcuts({ hasResult, candidateIds, selected, shortcutsOpen, setShortcutsOpen, deselect, toggleBreakdown, selectAndJump }: Options) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target instanceof Element ? e.target : null;
      const inField = target?.closest('input, select, textarea, [contenteditable="true"]');
      if (e.key === 'Escape') { if (shortcutsOpen) { setShortcutsOpen(() => false); return; } if (!inField) deselect(); return; }
      if (inField || target?.closest('button')) return;
      if (e.key === '?') { e.preventDefault(); setShortcutsOpen(v => !v); return; }
      if (!hasResult) return;
      if (e.key === ' ') { e.preventDefault(); toggleBreakdown(); }
      if (['ArrowDown', 'ArrowRight', 'ArrowUp', 'ArrowLeft'].includes(e.key) && candidateIds.length) {
        e.preventDefault();
        const index = candidateIds.indexOf(selected ?? ''), step = ['ArrowDown', 'ArrowRight'].includes(e.key) ? 1 : -1;
        selectAndJump(candidateIds[Math.max(0, Math.min(candidateIds.length - 1, index + step))]);
      }
    };
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler);
  });
}
