import type { CaptureSettings } from './upload';

const DATATYPES = ['cf32_le', 'cf32_be', 'ci16_le', 'ci16_be'];

export function CaptureSettingsBar({ settings, onChange, raw, wav, pending, detectorLocked }: {
  settings: CaptureSettings;
  onChange: (patch: Partial<CaptureSettings>) => void;
  raw: boolean;
  wav: boolean;
  pending: boolean;
  detectorLocked: boolean;
}) {
  return (
    <section className="capture-settings" aria-label="Capture settings">
      <label>Adaptive margin <input type="number" min="3" max="30" step="0.1" value={settings.margin} onChange={e => onChange({ margin: e.target.value })} disabled={pending} /> dB</label>
      {raw && <>
        <label>Sample rate (Hz)<input type="number" min="1" value={settings.rate} onChange={e => onChange({ rate: e.target.value })} disabled={pending} placeholder="Required" /></label>
        <label>Raw datatype<select value={settings.datatype} onChange={e => onChange({ datatype: e.target.value })} disabled={pending}>
          <option value="">Choose encoding</option>{DATATYPES.map(v => <option key={v}>{v}</option>)}
        </select></label>
      </>}
      {wav && <label>WAV interpretation<select value={settings.wavMode} onChange={e => onChange({ wavMode: e.target.value })} disabled={pending}>
        <option value="auto">Automatic quadrature check</option>
        <option value="iq">Confirm I=left / Q=right</option>
        <option value="audio_left">Left real audio</option>
        <option value="audio_right">Right real audio</option>
      </select></label>}
      <label>Detector<select value={settings.mode} disabled={pending || detectorLocked} onChange={e => onChange({ mode: e.target.value })}>
        <option value="adaptive">Adaptive threshold</option>
        <option value="fixed_debug">Fixed threshold — debug</option>
      </select></label>
      {settings.mode === 'fixed_debug' && <label>Absolute threshold (dB/Hz)<input type="number" step="0.1" value={settings.fixed} onChange={e => onChange({ fixed: e.target.value })} disabled={pending} /></label>}
      <span>Up to 2 GiB · select SigMF data + metadata together</span>
    </section>
  );
}
