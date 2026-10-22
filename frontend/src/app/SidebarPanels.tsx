import type { HistoryEntry } from './history';

export function SessionHistoryList({ history, pending, onResume }: {
  history: HistoryEntry[];
  pending: boolean;
  onResume: (jobId: string) => void;
}) {
  return <>
    {history.length === 0 ? <p className="history-empty">Analyzed files appear here, remembered in this browser.</p> : (
      <ul className="history-list">
        {history.map((h) => (
          <li key={h.job_id}>
            <button disabled={pending} onClick={() => onResume(h.job_id)}>
              <span className="history-filename">{h.filename}</span>
              <span className="history-meta">{h.sourceKind} · {h.detectionCount} candidate{h.detectionCount === 1 ? '' : 's'} · {new Date(h.timestamp).toLocaleTimeString()}</span>
            </button>
          </li>
        ))}
      </ul>
    )}
    <p className="history-note">Reload requires the backend job to still exist (~30-minute expiry); an expired job reports so instead of guessing.</p>
  </>;
}

export function Roadmap() {
  return (
    <div className="roadmap">
      <p><b>Detect · Estimate · Classify · built</b> → Report</p>
      <p>Classify now includes coarse envelope family, Mth-power carrier refinement, fine PSK classification (BPSK/QPSK only) and symbol-rate estimation, each gated to its validated SNR range with an explicit unknown status otherwise. FM and pulsed candidates never receive a fine label or symbol rate.</p>
      <p>Planned, not built: cyclostationary analysis, deep-learning detection, co-channel separation, frequency-hopping tracking, matched filtering, real-time streaming, and the Report stage.</p>
      <p>Demodulation into decoded audio/data remains planned, not built in this version.</p>
    </div>
  );
}
