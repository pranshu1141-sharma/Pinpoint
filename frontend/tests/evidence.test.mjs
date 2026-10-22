import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const { outputFiles } = await build({
  entryPoints: [fileURLToPath(new URL('../src/bolt/Evidence.tsx', import.meta.url))],
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', packages: 'external',
});
const compiled = { exports: {} };
new Function('require', 'module', 'exports', outputFiles[0].text)(createRequire(import.meta.url), compiled, compiled.exports);
const { EvidenceTable, evidenceRows } = compiled.exports;

const stat = (correct, wrong, n, n_correct) => ({ correct, wrong, n, n_correct });
const evidence = {
  estimator: 'verify', source: 'docs/readiness.json', measured: { commit: '3c2ec6c', date: '2026-09-29' },
  label: { G1: stat(.976, .003, 300, 83), G2: stat(.939, .013, 1032, 864), G4: stat(.071, .045, 336, 168), G5: stat(0, .149, 87, 84) },
  rate: { G1: stat(.952, .01, 300, 83), G2: stat(.846, .005, 1032, 960), G4: stat(.056, .036, 336, 216), G5: stat(0, 0, 45, 45) },
};
const render = (kind, ev = evidence) => renderToStaticMarkup(createElement(EvidenceTable, { kind, evidence: ev }));

test('label evidence lists every generator, including the failing real benchmark', () => {
  const html = render('label');
  for (const text of ['Measured evidence for published labels', 'not a probability for this capture',
    'Synthetic test (G1)', '97.6% correct (n=83) · 0.3% wrong (n=300)', 'Impaired synthetic (G4)',
    'Real benchmark (G5)', '0.0% correct (n=84) · 14.9% wrong (n=87)', '3c2ec6c', 'docs/CLAIMS.md'])
    assert.ok(html.includes(text), text);
});

test('rate evidence reads the rate statistics, not the label ones', () => {
  const rows = evidenceRows('rate', evidence);
  assert.equal(rows[1].text, '84.6% correct (n=960) · 0.5% wrong (n=1032)');
  assert.equal(rows[3].text, '0.0% correct (n=45) · 0.0% wrong (n=45)');
});

test('decode evidence restates DECODING.md and says no real capture was tested', () => {
  const html = render('decode', null);
  assert.ok(html.includes('Measured evidence for decoding'));
  assert.ok(html.includes('none with known symbols tested'));
  assert.ok(html.includes('0.12% (FSK2, 10 dB gate)'));
  const decoding = readFileSync(fileURLToPath(new URL('../../DECODING.md', import.meta.url)), 'utf8');
  for (const fact of ['**0.12%**', '**0.01%**', '0/1,500']) assert.ok(decoding.includes(fact), fact);
});

test('the projection served by the API matches the shape the UI reads', () => {
  const raw = JSON.parse(readFileSync(fileURLToPath(new URL('../../docs/readiness.json', import.meta.url)), 'utf8'));
  const s = raw.stats[raw.product];
  assert.ok(typeof s.G2.label.published_correct_in_library === 'number');
  assert.ok(typeof raw.meta.g5.n_with_label === 'number');
});
