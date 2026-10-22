import { useQuery } from '@tanstack/react-query';
import { request, type ReadinessEvidence } from '../api';

export type EvidenceKind = 'label' | 'rate' | 'decode';

const pct = (v: number) => `${(100 * v).toFixed(1)}%`;

const GENERATORS: { key: keyof ReadinessEvidence['label']; name: string }[] = [
  { key: 'G1', name: 'Synthetic test (G1)' },
  { key: 'G2', name: 'Synthetic test (G2)' },
  { key: 'G4', name: 'Impaired synthetic (G4)' },
  { key: 'G5', name: 'Real benchmark (G5)' },
];

// Decode has no scoreboard criteria; this restates DECODING.md's measured acceptance evidence.
const DECODE_ROWS = [
  { name: 'Synthetic PSK (RRC)', text: 'symbol error ≤ 2% at the gated SNR over 10 seeds; symbol-rate error up to 3e-4 tracked' },
  { name: 'Synthetic FSK2/ASK2', text: 'bit error 0.12% (FSK2, 10 dB gate) / 0.01% (ASK2, 8 dB gate); 0 false decodes in 1,500 noise/wrong-family trials' },
  { name: 'Real captures', text: 'none with known symbols tested' },
];

export function evidenceRows(kind: 'label' | 'rate', evidence: ReadinessEvidence) {
  return GENERATORS.map(({ key, name }) => {
    const g = evidence[kind][key];
    return { name, text: `${pct(g.correct)} correct (n=${g.n_correct}) · ${pct(g.wrong)} wrong (n=${g.n})` };
  });
}

export function EvidenceTable({ kind, evidence }: { kind: EvidenceKind; evidence: ReadinessEvidence | null }) {
  const rows = kind === 'decode' ? DECODE_ROWS : evidence ? evidenceRows(kind, evidence) : [];
  const title = { label: 'Measured evidence for published labels', rate: 'Measured evidence for published symbol rates',
    decode: 'Measured evidence for decoding' }[kind];
  return (
    <div className="evidence-table" role="note" aria-label={title}>
      <div className="evidence-title">{title} — not a probability for this capture</div>
      {rows.map((r) => <div key={r.name} className="evidence-row"><span>{r.name}</span><span>{r.text}</span></div>)}
      {kind !== 'decode' && evidence && (
        <div className="evidence-source">{evidence.estimator} estimator · {evidence.source} @ {evidence.measured.commit} ({evidence.measured.date}) · see docs/CLAIMS.md</div>
      )}
    </div>
  );
}

export function EvidenceLine({ kind }: { kind: EvidenceKind }) {
  const readiness = useQuery({
    queryKey: ['readiness'],
    queryFn: () => request<ReadinessEvidence>('/api/readiness'),
    staleTime: Infinity,
    retry: false,
    enabled: kind !== 'decode',
  });
  if (kind !== 'decode' && readiness.isError) {
    return <div className="evidence-table evidence-missing">Measured evidence unavailable: {readiness.error.message}</div>;
  }
  if (kind !== 'decode' && !readiness.data) return null;
  return <EvidenceTable kind={kind} evidence={readiness.data ?? null} />;
}
