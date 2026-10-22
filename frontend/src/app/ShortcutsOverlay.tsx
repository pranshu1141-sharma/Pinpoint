import { X } from 'lucide-react';

const SHORTCUTS: [string, string][] = [
  ['?', 'Toggle this shortcuts overlay'],
  ['↑ ↓ ← →', 'Step through detections, jumping the waterfall to frame each one'],
  ['Space', 'Toggle Signal Breakdown open/closed'],
  ['Esc', 'Close this overlay, or deselect the current detection'],
  ['Scroll on waterfall', 'Zoom, centered on the cursor'],
  ['Drag on waterfall', 'Pan the spectrogram viewport'],
  ['Click on waterfall', 'Pin a freq/time/power readout at that point'],
  ['Double-click waterfall', 'Reset zoom to the full capture'],
];

export function ShortcutsOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div className="shortcuts-overlay" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" onClick={onClose}>
      <div className="shortcuts-panel" onClick={e => e.stopPropagation()}>
        <div className="shortcuts-header"><h2>Keyboard shortcuts</h2><button aria-label="Close" onClick={onClose}><X size={16} /></button></div>
        <dl>{SHORTCUTS.map(([key, text]) => <div key={key}><dt>{key}</dt><dd>{text}</dd></div>)}</dl>
        <p className="shortcuts-footnote">Shortcuts are inactive while typing in a text field.</p>
      </div>
    </div>
  );
}
