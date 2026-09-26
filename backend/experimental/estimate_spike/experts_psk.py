"""PSK/QAM experts: rebuild the capture as snapped symbols with a flat (NRZ) or RRC pulse."""
from typing import Optional

import numpy as np

from .alphabets import LABEL, alphabet_size, extra_params, snap_to_alphabet, usage_ratio
from .config import SpikeConfig
from .dsp import TINY, rrc_pulse
from .hypothesis import Hypothesis
from .timing import fine_search, spectral_line_timing


def transition_timing(xc: np.ndarray, rate: float, fs: float) -> float:
    return spectral_line_timing(np.abs(np.diff(xc)) ** 2, rate, fs)


def _nrz_at(xc: np.ndarray, sps: float, tau: float, alphabets, block: int) -> tuple:
    """(score, order, residual, usage) for flat symbols at timing tau; partial end symbols dropped."""
    k = np.floor(np.arange(len(xc)) / sps + tau).astype(int)
    k -= k.min()
    msk = (k > 0) & (k < k.max())
    kk = k[msk] - 1
    cnt = np.bincount(kk).astype(float)
    cnt[cnt == 0] = 1
    xm = xc[msk]
    m = (np.bincount(kk, xm.real) + 1j * np.bincount(kk, xm.imag)) / cnt
    n_eff, n_sym = int(msk.sum()), len(m)
    best = (np.inf, None, np.nan, 0.0)
    for order in alphabets:
        rec, idx = snap_to_alphabet(m, order, block, return_index=True)
        res = np.mean(np.abs(xm - rec[kk]) ** 2) + TINY
        score = np.log(res) + (n_sym * np.log(alphabet_size(order)) + np.ceil(n_sym / block) * np.log(n_eff)
                               + 0.5 * extra_params(order) * np.log(n_eff)) / n_eff
        if score < best[0]:
            best = (float(score), order, float(res), usage_ratio(idx, alphabet_size(order)))
    return best


def flat_score(xc: np.ndarray, fs: float, rate: float) -> float:
    """Alphabet-free local rate score: mean power around flat per-symbol means at the
    spectral-line timing. Only for comparing nearby rates (a finer grid always lowers it)."""
    sps = fs / rate
    tau = transition_timing(xc, rate, fs)
    k = np.floor(np.arange(len(xc)) / sps + tau).astype(int)
    k -= k.min()
    msk = (k > 0) & (k < k.max())
    cnt = np.maximum(np.bincount(k), 1)
    m = (np.bincount(k, xc.real) + 1j * np.bincount(k, xc.imag)) / cnt
    return float(np.mean(np.abs(xc[msk] - m[k[msk]]) ** 2))


def nrz_quick_score(xc: np.ndarray, fs: float, rate: float, cfg: SpikeConfig) -> float:
    """Cheap ranking score: cfg.quick_alphabets (QPSK, unipolar ASK), spectral-line timing only."""
    sps = fs / rate
    return _nrz_at(xc, sps, transition_timing(xc, rate, fs), cfg.quick_alphabets, cfg.snap_block)[0]


class NrzPskExpert:
    name = "nrz"

    def __init__(self, cfg: SpikeConfig):
        self.cfg = cfg

    def fit(self, x: np.ndarray, xc: np.ndarray, fs: float, rate: float) -> Optional[Hypothesis]:
        sps = fs / rate
        _, (score, order, res, usage) = fine_search(
            lambda tau: _nrz_at(xc, sps, tau, self.cfg.alphabets, self.cfg.snap_block),
            transition_timing(xc, rate, fs), sps)
        if order is None:
            return None
        return Hypothesis(self.name, LABEL[order], float(rate), score, res, usage)


class RrcPskExpert:
    """Matched-filter symbol estimates, snap inner symbols, rebuild with the RRC pulse.

    Removing this expert roughly doubles confident mistakes: flat-block models
    fit RRC signals better at 2x the rate.
    """
    name = "rrc"

    def __init__(self, cfg: SpikeConfig):
        self.cfg = cfg

    def fit(self, x: np.ndarray, xc: np.ndarray, fs: float, rate: float) -> Optional[Hypothesis]:
        cfg, span = self.cfg, self.cfg.rrc_span
        sps = fs / rate
        nn = np.arange(len(xc))
        edge = int(np.ceil((span + 1) * sps))
        msk = np.zeros(len(xc), bool)
        msk[edge:len(xc) - edge] = True
        n_eff = int(msk.sum())
        if n_eff < 256:
            return None
        best = (np.inf, None, np.nan, 0.0)
        for phi in np.arange(cfg.rrc_phases) / cfg.rrc_phases:
            u = nn / sps - phi
            k0 = np.floor(u).astype(int)
            ks = [k0 + d for d in range(-span, span + 1)]
            ps = [rrc_pulse(u - k, cfg.rrc_alpha) for k in ks]
            kmin = min(k.min() for k in ks)
            ks = [k - kmin for k in ks]
            nk = max(k.max() for k in ks) + 1
            num = sum(np.bincount(k, xc.real * p, nk) + 1j * np.bincount(k, xc.imag * p, nk)
                      for k, p in zip(ks, ps))
            den = sum(np.bincount(k, p * p, nk) for k, p in zip(ks, ps)) + 1e-12
            a = num / den
            inner = slice(span + 1, nk - span - 1)
            n_sym = inner.stop - inner.start
            for order in cfg.alphabets:
                aq = a.copy()
                aq[inner], idx = snap_to_alphabet(a[inner], order, cfg.snap_block, return_index=True)
                rec = sum(aq[k] * p for k, p in zip(ks, ps))
                res = np.mean(np.abs(xc[msk] - rec[msk]) ** 2) + TINY
                cost = n_sym * np.log(alphabet_size(order)) + np.ceil(n_sym / cfg.snap_block) * np.log(n_eff) \
                    + np.log(n_eff) + 0.5 * extra_params(order) * np.log(n_eff)
                score = np.log(res) + cost / n_eff
                if score < best[0]:
                    best = (float(score), order, float(res), usage_ratio(idx, alphabet_size(order)))
        if best[1] is None:
            return None
        return Hypothesis(self.name, LABEL[best[1]], float(rate), best[0], best[2], best[3])


def _block_means(xc: np.ndarray, sps: float, tau: float, centre: float = 0.5):
    """Per-symbol means at timing tau over the central `centre` fraction of each symbol
    (smoothed transitions blur full-block means enough to flip 8PSK decisions).
    Returns (symbol coordinate u, k, msk, means)."""
    u = np.arange(len(xc)) / sps + tau
    k = np.floor(u).astype(int)
    k0 = k.min()
    k -= k0
    msk = (k > 0) & (k < k.max())
    frac = u - np.floor(u)
    w = (np.abs(frac - 0.5) <= centre / 2).astype(float)
    if sps * centre < 1:                      # fewer than one central sample: use the whole block
        w[:] = 1.0
    cnt = np.bincount(k, w)
    empty = cnt == 0
    cnt[empty] = 1.0
    m = (np.bincount(k, xc.real * w) + 1j * np.bincount(k, xc.imag * w)) / cnt
    if empty.any():
        full = np.maximum(np.bincount(k), 1)
        m[empty] = ((np.bincount(k, xc.real) + 1j * np.bincount(k, xc.imag)) / full)[empty]
    return u - k0, k, msk, m


def _pulse_taps(u: np.ndarray, n_sym: int, span: int, grid: int) -> tuple:
    """Sparse structure of the pulse model x[n] ~= sum_j a[sym[n,j]] * w[n,j] * p[col[n,j]]:
    a real pulse p sampled every 1/grid symbol on [-span, span] (symbol k centred at
    k + 0.5), linearly interpolated. Returns (sym, col, w), each (N, 2*(2*span+2))."""
    m_par = 2 * span * grid + 1
    kb = np.floor(u).astype(int)
    syms, cols, ws = [], [], []
    for d in range(-span - 1, span + 1):
        k = kb + d
        g = (u - (k + 0.5) + span) * grid
        j0 = np.floor(g).astype(int)
        fr = g - j0
        for j, w in ((j0, 1 - fr), (j0 + 1, fr)):
            ok = (k >= 0) & (k < n_sym) & (j >= 0) & (j < m_par)
            syms.append(np.where(ok, k, 0))
            cols.append(np.where(ok, j, 0))
            ws.append(np.where(ok, w, 0.0))
    return np.stack(syms, 1), np.stack(cols, 1), np.stack(ws, 1)


def _pulse_lstsq(y: np.ndarray, a: np.ndarray, taps: tuple, m_par: int) -> tuple:
    """Least-squares real pulse via sparse normal equations; returns (pulse, rebuild)."""
    sym, col, w = taps
    v = a[sym] * w                                         # (N, P) complex coefficients
    P = col.shape[1]
    ii = (col[:, :, None] * m_par + col[:, None, :]).ravel()
    gram = np.real(np.conj(v)[:, :, None] * v[:, None, :]).ravel()
    G = np.bincount(ii, gram, m_par * m_par).reshape(m_par, m_par)
    rhs = np.bincount(col.ravel(), np.real(np.conj(v) * y[:, None]).ravel(), m_par)
    G[np.diag_indices(m_par)] += 1e-9 * (np.trace(G) / m_par + TINY)
    p = np.linalg.solve(G, rhs)
    return p, np.sum(v * p[col], axis=1)


class LsPulsePskExpert:
    """Generic smooth pulse: decide symbols from flat blocks, then solve a real pulse
    over +-lsp_span symbols by least squares and rebuild. Charged 0.5 ln N per pulse
    sample in the MDL cost. Covers filtered NRZ, RC/RRC of any roll-off, Gaussian.

    Without it, smoothed-NRZ captures are fitted better by RRC at 2x or 3x the rate.
    """
    name = "lsp"

    def __init__(self, cfg: SpikeConfig):
        self.cfg = cfg

    def _fit(self, xc: np.ndarray, fs: float, rate: float, orders) -> tuple:
        """(score, order, residual, rebuild, inner slice, usage) at `rate`, best of `orders`."""
        cfg = self.cfg
        sps = fs / rate
        span, grid = cfg.lsp_span, cfg.lsp_grid
        edge = int(np.ceil((span + 1) * sps))
        if len(xc) - 2 * edge < 256:
            return (np.inf, None, np.nan, None, None, 0.0)
        tau, _ = fine_search(lambda t: _nrz_at(xc, sps, t, cfg.alphabets, cfg.snap_block),
                             transition_timing(xc, rate, fs), sps)
        u, k, _, m = _block_means(xc, sps, tau)
        inner = slice(edge, len(xc) - edge)
        n_eff = inner.stop - inner.start
        n_sym = int(np.ptp(k[inner])) + 1
        m_par = 2 * span * grid + 1
        y = xc[inner]
        taps = _pulse_taps(u[inner], len(m), span, grid)
        best = (np.inf, None, np.nan, None, inner, 0.0)
        for order in orders:
            a, idx = snap_to_alphabet(m, order, cfg.snap_block, return_index=True)
            _, rec = _pulse_lstsq(y, a, taps, m_par)
            res = np.mean(np.abs(y - rec) ** 2) + TINY
            cost = n_sym * np.log(alphabet_size(order)) + np.ceil(n_sym / cfg.snap_block) * np.log(n_eff) \
                + 0.5 * (m_par + extra_params(order)) * np.log(n_eff)
            score = np.log(res) + cost / n_eff
            if score < best[0]:
                sel = (k[inner].min() <= np.arange(len(idx))) & (np.arange(len(idx)) <= k[inner].max())
                best = (float(score), order, float(res), rec, inner, usage_ratio(idx[sel], alphabet_size(order)))
        return best

    def fit(self, x: np.ndarray, xc: np.ndarray, fs: float, rate: float) -> Optional[Hypothesis]:
        """Fit at `rate` (all alphabets), then refine the rate decision-directed and
        refit with the chosen alphabet (a 1e-4 rate nudge does not change it).

        Spectral-line rate estimates leave ~1e-4 relative error; over hundreds of
        symbols that misaligns the edges enough, at high SNR, for a 2x-rate model
        to win. Local timing shifts s_j of the rebuild in chunks (x ~ y + s_j y')
        grow linearly, s_j = eps * n_j, when the true rate is rate * (1 + eps).
        """
        cfg = self.cfg
        best = self._fit(xc, fs, rate, cfg.alphabets)
        if best[1] is None:
            return None
        for _ in range(cfg.lsp_rate_iters):
            eps = _drift(xc[best[4]], best[3], cfg.lsp_drift_chunks)
            if eps is None or abs(eps) > cfg.lsp_max_drift:
                break
            trial = self._fit(xc, fs, rate * (1 + eps), (best[1],))
            if not trial[0] < best[0]:
                break
            rate, best = rate * (1 + eps), trial
        return Hypothesis(self.name, LABEL[best[1]], float(rate), best[0], best[2], best[5])


def _drift(y: np.ndarray, rec: np.ndarray, chunks: int) -> Optional[float]:
    """Relative clock error eps from chunk-wise timing shifts of a rebuild `rec` against `y`."""
    d = np.gradient(rec)
    edges = np.linspace(0, len(y), chunks + 1).astype(int)
    shifts, weights, centres = [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        e = np.sum(np.abs(d[a:b]) ** 2)
        if e <= 0:
            return None
        shifts.append(np.real(np.sum((y[a:b] - rec[a:b]) * np.conj(d[a:b]))) / e)
        weights.append(np.sqrt(e))
        centres.append((a + b) / 2)
    return float(np.polyfit(centres, shifts, 1, w=weights)[0])
