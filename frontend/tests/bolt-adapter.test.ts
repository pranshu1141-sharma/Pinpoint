import { test } from 'node:test';
import assert from 'node:assert/strict';
import { adaptDetections, adaptSpectrogram, describeFile } from '../src/bolt/adapter.ts';

test('candidate identifiers become display strings without changing signed bounds or pulse windows', () => {
  const candidate = { id: 0, start_sample: 0, end_sample: 100, freq_lower_hz: -400, freq_upper_hz: -200, confidence: .6, needs_review: true, is_pulsed: true, pulse_windows: [{start_sample: 20, end_sample: 30}], pulse_width_samples: 10, pri_samples: null, detection_method: 'adaptive_threshold', threshold_excess_db: 2 };
  const [view] = adaptDetections([candidate]);
  assert.equal(view.id, '0');
  assert.equal(view.freq_lower_hz, -400);
  assert.deepEqual(view.pulse_windows, candidate.pulse_windows);
  assert.equal(view.pri_samples, null);
});

test('spectrogram retains exact unequal viewport edges and measured color limits', () => {
  const source = { magnitude_db: [[-60, -20], [-55, -30]], frequency_edges_hz: [-500, -100, 500], time_edges_seconds: [0, .4, 1], min_db: -58, max_db: -20, aggregation: 'maximum power per viewport cell', unit: 'dB re 1 sample-unit²/Hz' };
  const view = adaptSpectrogram(source);
  assert.deepEqual(view.frequency_edges_hz, source.frequency_edges_hz);
  assert.deepEqual(view.time_edges_seconds, source.time_edges_seconds);
  assert.deepEqual(view.freq_bins, [-300, 200]);
  assert.deepEqual(view.time_bins, [.2, .7]);
  assert.equal(view.min_db, -58);
  assert.equal(view.max_db, -20);
});

test('file description never guesses size or sample metadata for an unanalyzed file', () => {
  assert.equal(describeFile(null), null);
  const info = describeFile({ filename: 'audio.wav', sample_rate: 16000, sample_count: 32000, duration_seconds: 2, datatype: 'rf32_le', source_kind: 'audio', center_frequency_hz: null, power_unit: 'dB re 1 sample-unit²/Hz', frequency_reference: 'baseband offset', wav_disambiguation: { result: 'real_audio', reason: 'Mono' } });
  assert.equal(info?.sampleRate, 16000);
  assert.equal(info?.fileSize, 'Not reported');
  assert.equal(info?.interpretation, 'Real audio');
});
