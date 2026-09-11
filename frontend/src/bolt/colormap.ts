/**
 * Classic cold-to-hot colormap used by GQRX / SDR# / Inspectrum.
 * Maps normalized intensity [0..1] to [r, g, b] (0..255).
 *
 * Stops: dark blue -> blue -> cyan -> green -> yellow -> orange -> red -> white
 */
const stops: Array<{ t: number; r: number; g: number; b: number }> = [
  { t: 0.0, r: 0, g: 0, b: 20 },
  { t: 0.1, r: 0, g: 0, b: 80 },
  { t: 0.2, r: 0, g: 40, b: 160 },
  { t: 0.3, r: 0, g: 120, b: 200 },
  { t: 0.4, r: 0, g: 200, b: 200 },
  { t: 0.5, r: 60, g: 220, b: 80 },
  { t: 0.6, r: 180, g: 240, b: 40 },
  { t: 0.7, r: 240, g: 220, b: 20 },
  { t: 0.8, r: 250, g: 140, b: 20 },
  { t: 0.9, r: 240, g: 40, b: 20 },
  { t: 1.0, r: 255, g: 240, b: 220 },
];

export function colormap(value: number): [number, number, number] {
  const clamped = Math.max(0, Math.min(1, value));

  for (let i = 0; i < stops.length - 1; i++) {
    const a = stops[i];
    const b = stops[i + 1];
    if (clamped >= a.t && clamped <= b.t) {
      const f = (clamped - a.t) / (b.t - a.t);
      return [
        Math.round(a.r + (b.r - a.r) * f),
        Math.round(a.g + (b.g - a.g) * f),
        Math.round(a.b + (b.b - a.b) * f),
      ];
    }
  }

  const last = stops[stops.length - 1];
  return [last.r, last.g, last.b];
}

/**
 * Precompute a 256-entry lookup table for speed.
 */
export function buildColormapLUT(): Uint8ClampedArray {
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const [r, g, b] = colormap(i / 255);
    lut[i * 3] = r;
    lut[i * 3 + 1] = g;
    lut[i * 3 + 2] = b;
  }
  return lut;
}
