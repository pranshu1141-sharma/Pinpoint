export type CaptureSettings = {
  margin: string; rate: string; datatype: string; wavMode: string; mode: string; fixed: string;
};

const isMeta = (f: { name: string }) => f.name.toLowerCase().endsWith('.sigmf-meta');

/** Validate the selected files and build the /api/analyze form. Throws the message shown to the user. */
export function buildUploadForm(files: File[], settings: CaptureSettings, maxBytes = 2147483648): FormData {
  const captures = files.filter(f => !isMeta(f));
  const metas = files.filter(isMeta);
  if (captures.length !== 1 || metas.length > 1) throw new Error('Select one capture and, for SigMF, its paired metadata file.');
  if (metas.length && captures[0].name.replace(/\.(iq|sigmf-data)$/i, '') !== metas[0].name.replace(/\.sigmf-meta$/i, '')) throw new Error('The capture and SigMF metadata filenames must have matching stems.');
  if (captures[0].size > maxBytes) throw new Error('Maximum capture size is 2 GiB.');
  const body = new FormData(); body.append('file', captures[0]);
  if (metas[0]) body.append('metadata', metas[0]);
  if (settings.rate) body.append('sample_rate', settings.rate);
  if (settings.datatype) body.append('datatype', settings.datatype);
  body.append('wav_mode', settings.wavMode); body.append('margin_db', settings.margin); body.append('mode', settings.mode);
  if (settings.fixed) body.append('fixed_threshold_db', settings.fixed);
  return body;
}

/** Raw .iq without SigMF metadata needs an explicit sample rate and datatype. */
export const needsRawSettings = (files: File[]) => files.some(f => /\.iq$/i.test(f.name)) && !files.some(isMeta);
export const hasWav = (files: File[]) => files.some(f => /\.wav$/i.test(f.name));
