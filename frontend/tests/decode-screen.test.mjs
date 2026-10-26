import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const { outputFiles } = await build({
  entryPoints: [fileURLToPath(new URL('../src/bolt/DecodeScreen.tsx', import.meta.url))],
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', packages: 'external',
});
const compiled = { exports: {} };
new Function('require', 'module', 'exports', outputFiles[0].text)(createRequire(import.meta.url), compiled, compiled.exports);
const { DecodeResultView, formatSymbolRows, decodeSummary } = compiled.exports;

const detection = {
  id: '2', start_sample: 0, end_sample: 96000, freq_lower_hz: -1000, freq_upper_hz: 1000,
  modulation_label: 'BPSK', verify_status: 'estimated (label margin passed)', symbol_rate_hz: 500,
};
const declined = {
  decode_label: null, decoded_symbol_indices: null, decoded_symbol_count: null, decoded_symbols_truncated: false,
  decode_confidence: null, decode_phase_offset_rad: null, decode_rotation_ambiguity_modulus: null, decode_span: null,
  decode_status: 'not attempted (no published modulation label: unknown family (structure outside the library))',
};
const render = (result, det = detection) => renderToStaticMarkup(createElement(DecodeResultView, { detection: det, result }));

test('a declined decode shows the backend reason and no stream', () => {
  const html = render(declined, { ...detection, modulation_label: null, verify_status: 'unknown family' });
  assert.ok(html.includes('Not decoded'));
  assert.ok(html.includes('no published modulation label: unknown family'));
  assert.ok(html.includes('unknown family'));
  assert.ok(!html.includes('Recovered'));
  assert.ok(!html.includes('>null<'));
});

test('a decoded stream shows count, decoder, ambiguity and the symbols', () => {
  const indices = Array.from({ length: 130 }, (_, i) => i % 2);
  const html = render({ ...declined, decode_label: 'bpsk', decoded_symbol_indices: indices, decoded_symbol_count: 130,
    decode_confidence: 0.99, decode_rotation_ambiguity_modulus: 2, decode_status: 'decoded (…) up to an unknown constant rotation mod 2' });
  for (const text of ['Decoded 130 symbols', 'BPSK', 'rotation mod 2 + start offset', '0.990', '500.00 Hz',
    'Recovered symbols', '130 of 130 shown', '[130 values — use Download]']) assert.ok(html.includes(text), text);
});

test('fsk2/ask2 streams are labelled as bits and truncation is disclosed', () => {
  const html = render({ ...declined, decode_label: 'ask2', decoded_symbol_indices: [1, 0, 1], decoded_symbol_count: 50000,
    decoded_symbols_truncated: true, decode_rotation_ambiguity_modulus: 2, decode_status: 'decoded' });
  assert.ok(html.includes('Decoded 50,000 bits'));
  assert.ok(html.includes('3 of 50,000 shown · download holds the first 3'));
});

test('symbol rows are offset-labelled, 64 per row, grouped by 8, capped by limit', () => {
  const rows = formatSymbolRows(Array.from({ length: 200 }, (_, i) => i % 4), 150);
  assert.equal(rows.length, 3);
  assert.equal(rows[0], '     0  01230123 01230123 01230123 01230123 01230123 01230123 01230123 01230123');
  assert.ok(rows[2].startsWith('   128  '));
  assert.equal(rows[2].replace(/^\s*128\s+/, '').replace(/ /g, '').length, 22);
});

test('the exported summary carries every returned symbol', () => {
  const s = decodeSummary(detection, { ...declined, decoded_symbol_indices: [0, 1, 1] });
  assert.deepEqual(s.decoded_symbol_indices, [0, 1, 1]);
  assert.equal(s.candidate, 'C3');
  assert.equal(s.modulation_label, 'BPSK');
});

test('a decode window narrower than the candidate is shown; the same window is not repeated', () => {
  const base = { ...declined, decode_label: 'bpsk', decoded_symbol_indices: [0], decoded_symbol_count: 1, decode_status: 'decoded' };
  assert.ok(render({ ...base, decode_span: { start_sample: 1000, end_sample: 51000 } }).includes('Decoded window'));
  assert.ok(!render({ ...base, decode_span: { start_sample: 0, end_sample: 96000 } }).includes('Decoded window'));
});
