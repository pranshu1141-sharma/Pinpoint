import { useState } from 'react';
import type { Analysis } from '../api';

export type HistoryEntry = { job_id: string; filename: string; timestamp: number; detectionCount: number; sourceKind: string };

const HISTORY_KEY = 'detect-session-history';

function loadHistory(): HistoryEntry[] {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]'); } catch { return []; }
}

function saveHistory(list: HistoryEntry[]) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, 10))); } catch { /* storage unavailable */ }
}

/** Analyzed files remembered in this browser, newest first, at most 10 stored. */
export function useSessionHistory() {
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());
  const record = (data: Analysis) => setHistory((prev) => {
    const entry: HistoryEntry = { job_id: data.job_id, filename: data.metadata.filename, timestamp: Date.now(), detectionCount: data.detections.length, sourceKind: data.metadata.source_kind };
    const next = [entry, ...prev.filter((h) => h.job_id !== data.job_id)];
    saveHistory(next);
    return next;
  });
  return { history, record };
}
