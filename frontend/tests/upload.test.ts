import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildUploadForm, hasWav, needsRawSettings } from '../src/app/upload.ts';

const settings = { margin: '8', rate: '48000', datatype: 'cf32_le', wavMode: 'auto', mode: 'adaptive', fixed: '' };
const file = (name: string, size = 4) => new File([new Uint8Array(size)], name);

test('a raw capture becomes the analyze form with every setting', () => {
  const form = buildUploadForm([file('c.iq')], settings);
  assert.equal((form.get('file') as File).name, 'c.iq');
  assert.equal(form.get('sample_rate'), '48000');
  assert.equal(form.get('datatype'), 'cf32_le');
  assert.equal(form.get('wav_mode'), 'auto');
  assert.equal(form.get('margin_db'), '8');
  assert.equal(form.get('mode'), 'adaptive');
  assert.equal(form.get('metadata'), null);
  assert.equal(form.get('fixed_threshold_db'), null);
});

test('empty optional settings are omitted, a fixed threshold is sent', () => {
  const form = buildUploadForm([file('a.wav')], { ...settings, rate: '', datatype: '', mode: 'fixed_debug', fixed: '-40' });
  assert.equal(form.get('sample_rate'), null);
  assert.equal(form.get('datatype'), null);
  assert.equal(form.get('fixed_threshold_db'), '-40');
});

test('a SigMF pair is sent together only when the stems match', () => {
  const form = buildUploadForm([file('x.sigmf-data'), file('x.sigmf-meta')], settings);
  assert.equal((form.get('metadata') as File).name, 'x.sigmf-meta');
  assert.throws(() => buildUploadForm([file('x.sigmf-data'), file('y.sigmf-meta')], settings), /matching stems/);
});

test('zero, two, or oversized captures are rejected with the user-facing message', () => {
  assert.throws(() => buildUploadForm([], settings), /Select one capture/);
  assert.throws(() => buildUploadForm([file('a.iq'), file('b.iq')], settings), /Select one capture/);
  assert.throws(() => buildUploadForm([file('a.iq', 10)], settings, 5), /2 GiB/);
});

test('raw settings are needed for bare .iq only; wav is detected', () => {
  assert.equal(needsRawSettings([file('a.iq')]), true);
  assert.equal(needsRawSettings([file('a.iq'), file('a.sigmf-meta')]), false);
  assert.equal(needsRawSettings([file('a.wav')]), false);
  assert.equal(hasWav([file('A.WAV')]), true);
});
