/**
 * Format a frequency in Hz into a human-readable string with appropriate units.
 */
export function formatFreq(hz: number): string {
  const abs = Math.abs(hz);
  if (abs >= 1e9) return `${(hz / 1e9).toFixed(3)} GHz`;
  if (abs >= 1e6) return `${(hz / 1e6).toFixed(3)} MHz`;
  if (abs >= 1e3) return `${(hz / 1e3).toFixed(2)} kHz`;
  return `${hz.toFixed(0)} Hz`;
}

/**
 * Format a frequency in Hz into a short string (no unit suffix, for axis labels).
 */
export function formatFreqShort(hz: number): string {
  const abs = Math.abs(hz);
  if (abs >= 1e6) return `${(hz / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(hz / 1e3).toFixed(0)}k`;
  return `${hz.toFixed(0)}`;
}

/**
 * Format a dB value.
 */
export function formatDb(db: number): string {
  return `${db.toFixed(1)} dB`;
}

/**
 * Format a time value in seconds.
 */
export function formatTime(seconds: number): string {
  if (seconds >= 1) return `${seconds.toFixed(3)} s`;
  if (seconds >= 1e-3) return `${(seconds * 1e3).toFixed(2)} ms`;
  if (seconds >= 1e-6) return `${(seconds * 1e6).toFixed(1)} µs`;
  return `${(seconds * 1e9).toFixed(0)} ns`;
}

/**
 * Format a sample count.
 */
export function formatSamples(samples: number): string {
  if (samples >= 1e6) return `${(samples / 1e6).toFixed(2)}M`;
  if (samples >= 1e3) return `${(samples / 1e3).toFixed(1)}k`;
  return `${samples}`;
}

/**
 * Format a confidence value as a percentage.
 */
export function formatConfidence(conf: number): string {
  return `${(conf * 100).toFixed(0)}%`;
}

/**
 * Format a file size in bytes.
 */
export function formatFileSize(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} kB`;
  return `${bytes} B`;
}
