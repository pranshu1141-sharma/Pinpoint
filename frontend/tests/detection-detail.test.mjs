import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

// Compile the real TSX component in memory with Vite's existing compiler.
const { outputFiles } = await build({
  entryPoints: [fileURLToPath(new URL('../src/bolt/DetectionDetailPanel.tsx', import.meta.url))],
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', packages: 'external',
});
const compiled = { exports: {} };
const cjsRequire = createRequire(import.meta.url);
new Function('require', 'module', 'exports', outputFiles[0].text)(cjsRequire, compiled, compiled.exports);
const { DetectionDetailPanel } = compiled.exports;
// Same require() the compiled bundle used, so the QueryClientContext instance
// matches instead of diverging across an ESM/CJS dual-package boundary.
const { QueryClient, QueryClientProvider } = cjsRequire('@tanstack/react-query');
const base = {
  id: '0', start_sample: 0, end_sample: 48000, freq_lower_hz: -1000, freq_upper_hz: 1000,
  confidence: .8, detection_method: 'adaptive_threshold', needs_review: false,
  is_pulsed: false, pulse_width_samples: null, pri_samples: null, pulse_windows: [], threshold_excess_db: 8,
};
// The symbol-rate reveal panel fetches on demand via useQuery, so a real
// QueryClient must be present even though the reveal starts collapsed.
const render = (fields = {}) => {
  const client = new QueryClient();
  return renderToStaticMarkup(createElement(QueryClientProvider, { client },
    createElement(DetectionDetailPanel, { detection: { ...base, ...fields }, sampleRate: 48000 })));
};

test('measured values retain zero, signs and refined RF precision; caveats are inline', () => {
  const html = render({ estimate_status: 'estimated', center_frequency_hz: -1234.56,
    center_frequency_refined_hz: 100008000.12, bandwidth_3db_hz: 0, bandwidth_99pct_hz: 1000,
    bandwidth_99pct_caveat: 'unshaped-pulse-sidelobes', snr_db: 0,
    modulation_family: 'constant-envelope', modulation_confidence: 0,
    fine_modulation_label: null, symbol_rate_hz: null,
    symbol_rate_status: 'not reliably estimated (not attempted: fallback rung 2)',
  });
  for (const text of ['Midpoint (Detect)', 'Width (Detect)', '-1,234.56 Hz', '100,008,000.12 Hz',
    '0.00 Hz', '0.00 dB', '0% (heuristic)', '1,000.00 Hz — unshaped-pulse-sidelobes',
    'Not reliably estimated', 'Not attempted']) assert.ok(html.includes(text), text);
  assert.ok(!html.includes('>null<'));
});

test('Detect-only results have explicit absent-stage states without invented measurements', () => {
  const html = render();
  assert.ok(html.includes('Not attempted (this analysis)'));
  assert.ok(html.includes('Not reliably estimated'));
  assert.ok(!html.includes('0.00 dB'));
  assert.ok(!html.includes('undefined'));
});

test('unavailable IQ estimates show the backend reason instead of zero', () => {
  const html = render({ estimate_status: 'not reliably estimated (requires complex IQ)',
    center_frequency_hz: null, snr_db: null, modulation_family: null, modulation_confidence: null });
  assert.ok(html.includes('requires complex IQ'));
  assert.ok(html.includes('Not reliably estimated'));
  assert.ok(!html.includes('0.00 dB'));
});
