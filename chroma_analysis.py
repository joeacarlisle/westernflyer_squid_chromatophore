"""Chromatophore signal analysis: pure numpy / pandas, no video or database code.

Input is one brightness-versus-time signal per region of interest (ROI), sampled at the video frame rate.
Output is a table with one row per sliding window: swing, dominant frequency, how sharp that frequency
peak is, and a state (quiet / flickering / flashing, or untracked when the tracker lost the animal).  The method follows what Rosen et al. (2015, J Exp
Biol 218:265) did by hand: quantify skin color (grayscale) in a box on the animal and look at its time
course.  Here the box can follow the animal (see roi_tracker.py) and the frequency analysis is automatic.
"""
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

STATES = ('quiet', 'flickering', 'flashing')
_CODE = {s: i for i, s in enumerate(STATES)}


def _windows(n, fps, window_s, hop_s):
    w, h = int(round(window_s * fps)), max(1, int(round(hop_s * fps)))
    return [(s, s + w) for s in range(0, n - w + 1, h)]


def _spectrum(x, nfft):
    x = np.asarray(x, float)
    k = np.arange(len(x))
    A = np.vstack([k, np.ones_like(k)]).T
    x = x - A @ np.linalg.lstsq(A, x, rcond=None)[0]            # remove mean and linear drift
    return np.fft.rfft(x * np.hanning(len(x)), n=nfft)


def window_features(signal, fps, cfg, lost=None):
    """One row per window: t_start_s, t_end_s, t_center_s, p2p, rms, dom_freq_hz, peak_conc, lost_frac.

    lost: optional per-frame flags from the ROI tracker; lost_frac is the share of the window's frames flagged."""
    a, c = cfg['analysis'], cfg['classify']
    lo, hi = a['band_hz']
    nfft = int(a['nfft'])
    freqs = np.fft.rfftfreq(nfft, 1.0 / fps)
    band = (freqs >= lo) & (freqs <= hi)
    rows = []
    for s, e in _windows(len(signal), fps, a['window_s'], a['hop_s']):
        x = np.asarray(signal[s:e], float)
        k = np.arange(len(x))
        resid = x - np.polyval(np.polyfit(k, x, 1), k)
        spec = np.abs(_spectrum(x, nfft)) ** 2
        band_power = spec[band].sum()
        if band_power <= 0:
            f0, conc = np.nan, 0.0
        else:
            i = np.argmax(np.where(band, spec, 0))
            f0 = freqs[i]
            near = band & (np.abs(freqs - f0) <= 0.5)
            conc = spec[near].sum() / band_power
        rows.append(dict(t_start_s=s / fps, t_end_s=e / fps, t_center_s=(s + e) / 2 / fps,
                         p2p=float(np.percentile(resid, 98) - np.percentile(resid, 2)),
                         rms=float(resid.std()), dom_freq_hz=float(f0), peak_conc=float(conc),
                         lost_frac=float(np.mean(lost[s:e])) if lost is not None else 0.0))
    return pd.DataFrame(rows)


def classify(feat, cfg):
    """Add a ``state`` column (quiet / flickering / flashing) using the thresholds in cfg['classify']."""
    c = cfg['classify']
    f_lo, f_hi = c['flash_freq_hz']
    state = np.where(feat['p2p'] < c['quiet_p2p_max'], 'quiet', 'flickering')
    flash = ((feat['p2p'] >= c['flash_p2p_min']) & (feat['peak_conc'] >= c['flash_peak_conc_min'])
             & feat['dom_freq_hz'].between(f_lo, f_hi))
    state = np.where(flash, 'flashing', state)
    k = int(c.get('smooth_windows', 1))
    if k > 1 and len(state) >= k:
        codes = pd.Series([_CODE[s] for s in state], dtype=float)
        smooth = codes.rolling(k, center=True, min_periods=1).median().round().astype(int)
        state = np.array([STATES[i] for i in smooth])
    max_lost = cfg.get('tracking', {}).get('max_lost_frac', 1.0)
    state = np.where(feat['lost_frac'].to_numpy() > max_lost, 'untracked', state) if 'lost_frac' in feat else state
    out = feat.copy()
    out['state'] = state
    return out


def pair_phase(sig_a, sig_b, feat_a, feat_b, fps, cfg):
    """Phase of ROI B relative to ROI A in windows where both are flashing.

    phase_deg > 0 means B leads A; 0 = in step, +-180 = opposite (one white while the other is red).
    """
    a = cfg['analysis']
    nfft = int(a['nfft'])
    freqs = np.fft.rfftfreq(nfft, 1.0 / fps)
    rows = []
    for i, (s, e) in enumerate(_windows(len(sig_a), fps, a['window_s'], a['hop_s'])):
        if i >= len(feat_a) or i >= len(feat_b):
            break
        both = feat_a['state'].iat[i] == 'flashing' and feat_b['state'].iat[i] == 'flashing'
        phase, f0 = np.nan, np.nan
        if both:
            f0 = float(feat_a['dom_freq_hz'].iat[i])
            j = int(np.argmin(np.abs(freqs - f0)))
            fa, fb = _spectrum(sig_a[s:e], nfft)[j], _spectrum(sig_b[s:e], nfft)[j]
            phase = float(np.degrees(np.angle(fb * np.conj(fa))))
        rows.append(dict(t_center_s=float(feat_a['t_center_s'].iat[i]), both_flashing=bool(both),
                         freq_hz=f0, phase_deg=phase))
    return pd.DataFrame(rows)


def episodes(feat, duration_s, hop_s):
    """Merge consecutive windows with the same state into episodes (start, end, duration, mean frequency)."""
    rows = []
    if feat.empty:
        return pd.DataFrame(rows, columns=['state', 't_start_s', 't_end_s', 'duration_s', 'mean_freq_hz', 'mean_p2p'])
    grp = (feat['state'] != feat['state'].shift()).cumsum()
    first_t = feat['t_center_s'].iat[0]
    for _, g in feat.groupby(grp, sort=True):
        t0 = 0.0 if g['t_center_s'].iat[0] == first_t else g['t_center_s'].iat[0] - hop_s / 2
        t1 = g['t_center_s'].iat[-1] + hop_s / 2
        if g.index[-1] == feat.index[-1]:
            t1 = duration_s
        st = g['state'].iat[0]
        rows.append(dict(state=st, t_start_s=float(t0), t_end_s=float(t1), duration_s=float(t1 - t0),
                         mean_freq_hz=float(g['dom_freq_hz'].mean()) if st == 'flashing' else np.nan,
                         mean_p2p=float(g['p2p'].mean())))
    return pd.DataFrame(rows)


def _moving_mean(x, n):
    """Centered moving average with the same length as x (edges padded with the end values)."""
    n = max(1, int(n))
    if n == 1:
        return np.asarray(x, float)
    pad = n // 2
    return np.convolve(np.pad(np.asarray(x, float), (pad, n - 1 - pad), mode='edge'), np.ones(n) / n, mode='valid')


def _empty_cycles():
    return pd.DataFrame({'episode': pd.Series(dtype='int64'), 't_s': pd.Series(dtype='float64'),
                         'period_s': pd.Series(dtype='float64'), 'freq_hz': pd.Series(dtype='float64'),
                         'amplitude': pd.Series(dtype='float64')})


def flash_cycles(signal, fps, ep, cfg):
    """Cycle-by-cycle flash frequency inside each flashing episode.

    Rosen et al. (2015) measured the instantaneous flash frequency as the inverse of the time between successive
    cycles (they used the paling minima).  Here the brightness maxima of the smoothed, detrended signal are used,
    refined to a fraction of a frame.  The window FFT gives one frequency per 2 s window; this gives one per cycle,
    so frequency drift within an episode can be seen.

    ep: the episodes table of one ROI.  Returns (ep with episode, n_cycles, cycle_freq_hz, cycle_freq_sd_hz added,
    cycles table with episode, t_s, period_s, freq_hz, amplitude).
    amplitude is the swing of one cycle (brightest point minus the darkest point between two peaks, 0-1 gray units,
    measured on the unsmoothed signal); Rosen et al. described amplitude changes only qualitatively.  Intervals outside half the lower to 1.5 x the upper flash
    frequency are dropped (a missed or an extra peak).
    """
    cc = cfg.get('cycles', {})
    smooth, prom = int(cc.get('smooth_frames', 3)), float(cc.get('min_prominence_frac', 0.3))
    f_lo, f_hi = cfg['classify']['flash_freq_hz']
    ep = ep.reset_index(drop=True).copy()
    ep['episode'] = np.arange(len(ep), dtype='int64')
    for col in ('n_cycles', 'cycle_freq_hz', 'cycle_freq_sd_hz', 'cycle_amp_mean'):
        ep[col] = np.nan
    sig = np.asarray(signal, float)
    rows = []
    for i, r in ep.iterrows():
        if r['state'] != 'flashing':
            continue
        s, e = int(round(r['t_start_s'] * fps)), min(len(sig), int(round(r['t_end_s'] * fps)))
        if e - s < 4:
            continue
        x = _moving_mean(sig[s:e], smooth)
        k = np.arange(len(x))
        x = x - np.polyval(np.polyfit(k, x, 1), k)
        xr = sig[s:e] - np.polyval(np.polyfit(k, sig[s:e], 1), k)         # unsmoothed, for the amplitude
        swing = np.percentile(x, 98) - np.percentile(x, 2)
        if swing <= 0:
            continue
        peaks, _ = find_peaks(x, prominence=prom * swing, distance=max(1, int(fps / (1.5 * f_hi))))
        pos = []
        for p in peaks:
            off = 0.0
            if 0 < p < len(x) - 1:
                d = x[p - 1] - 2 * x[p] + x[p + 1]
                off = 0.5 * (x[p - 1] - x[p + 1]) / d if d != 0 else 0.0
            pos.append(p + off)
        if len(pos) < 2:
            continue
        t = (s + np.asarray(pos)) / fps
        period = np.diff(t)
        freq = 1.0 / period
        keep = (freq >= 0.5 * f_lo) & (freq <= 1.5 * f_hi)
        if not keep.any():
            continue
        tm = ((t[:-1] + t[1:]) / 2)[keep]
        top = np.array([xr[max(0, q - 1):q + 2].max() for q in peaks])
        amp = np.array([0.5 * (top[j] + top[j + 1]) - xr[peaks[j]:peaks[j + 1] + 1].min() for j in range(len(peaks) - 1)])
        rows.append(pd.DataFrame({'episode': np.int64(i), 't_s': tm, 'period_s': period[keep], 'freq_hz': freq[keep],
                                  'amplitude': amp[keep]}))
        ep.loc[i, 'cycle_amp_mean'] = float(amp[keep].mean())
        ep.loc[i, 'n_cycles'] = int(keep.sum())
        ep.loc[i, 'cycle_freq_hz'] = float(freq[keep].mean())
        ep.loc[i, 'cycle_freq_sd_hz'] = float(freq[keep].std(ddof=1)) if keep.sum() >= 2 else np.nan
    return ep, (pd.concat(rows, ignore_index=True) if rows else _empty_cycles())


def _empty_pauses():
    f = pd.Series(dtype='float64')
    return pd.DataFrame({'t_start_s': f, 't_end_s': f, 'duration_s': f,
                         'preceded_by_activity': pd.Series(dtype='bool'), 'followed_by_flash': pd.Series(dtype='bool')})


def find_pauses(signal, fps, ep, cfg):
    """Spans where the signal stops changing, as in the 'pauses' of Rosen et al. (2015).

    They found pauses with a rolling standard deviation of intensity.  Here the rolling RMS of the frame-to-frame
    change (insensitive to slow drift) is compared with its typical value during flickering in the same clip (during
    flashing if the clip never flickers).  A pause is a run of at least pauses.min_s where it falls below
    pauses.below_frac of that baseline.  preceded_by_activity: the signal was active in the pauses.context_s before.
    followed_by_flash: a flashing episode covers some of the pauses.follow_s after.  Quiet stretches that were never
    active also come out as pauses; preceded_by_activity separates them from a pause inside a display.
    """
    pc = cfg.get('pauses', {})
    win, below = int(round(float(pc.get('window_s', 0.4)) * fps)), float(pc.get('below_frac', 0.25))
    min_n, ctx_n = int(round(float(pc.get('min_s', 0.3)) * fps)), int(round(float(pc.get('context_s', 1.0)) * fps))
    fol_n = int(round(float(pc.get('follow_s', 1.5)) * fps))
    sig = np.asarray(signal, float)
    n = len(sig)
    rms = np.sqrt(_moving_mean(np.diff(sig, prepend=sig[0]) ** 2, max(2, win)))
    masks = {st: np.zeros(n, bool) for st in STATES}
    for _, r in ep.iterrows():
        if r['state'] in masks:
            masks[r['state']][int(round(r['t_start_s'] * fps)):int(round(r['t_end_s'] * fps))] = True
    base_mask = masks['flickering'] if masks['flickering'].sum() >= max(2, win) else masks['flickering'] | masks['flashing']
    if base_mask.sum() < max(2, win):
        return _empty_pauses()
    baseline = float(np.median(rms[base_mask]))
    if baseline <= 0:
        return _empty_pauses()
    low = rms < below * baseline
    rows, i = [], 0
    while i < n:
        if not low[i]:
            i += 1
            continue
        j = i
        while j < n and low[j]:
            j += 1
        if j - i >= min_n:
            ctx = rms[max(0, i - ctx_n):i]
            rows.append(dict(t_start_s=i / fps, t_end_s=j / fps, duration_s=(j - i) / fps,
                             preceded_by_activity=bool(len(ctx) > 0 and ctx.mean() >= 0.5 * baseline),
                             followed_by_flash=bool(masks['flashing'][j:j + fol_n].any())))
        i = j
    return pd.DataFrame(rows) if rows else _empty_pauses()


def in_phase_fraction(pair, tol=0.2):
    """Share of both-flashing windows in which two ROIs are in phase: lag or lead under tol of a cycle (Rosen et al. used 20%)."""
    sel = pair[pair['both_flashing']]
    return float((sel['phase_deg'].abs() < tol * 360.0).mean()) if len(sel) else float('nan')


def _empty_grid():
    f = pd.Series(dtype='float64')
    return pd.DataFrame({'t_start_s': f, 't_end_s': f, 't_center_s': f, 'sync': f, 'spatial_sd': f,
                         'n_boxes': pd.Series(dtype='int64')})


def grid_features(boxes, fps, cfg):
    """Spatial synchrony of a grid of small boxes over one skin area, per sliding window.

    Rosen et al. (2015) averaged skin color in an array of 10 x 10 px boxes (3 x 6) and used the spatial standard
    deviation: global flashing is synchronous across the boxes, flickering is patchy.  boxes: array (frames, boxes).
    sync: mean correlation between the boxes' detrended signals (about 1 when they move together, about 0 when
    independent; NaN when fewer than two boxes vary by at least synchrony.min_std).
    spatial_sd: standard deviation of the boxes' brightness at each frame, averaged over the window.
    """
    a = cfg['analysis']
    min_std = float(cfg.get('synchrony', {}).get('min_std', 0.01))
    X = np.asarray(boxes, float)
    rows = []
    for s, e in _windows(len(X), fps, a['window_s'], a['hop_s']):
        W = X[s:e]
        k = np.arange(len(W))
        A = np.vstack([k, np.ones_like(k)]).T
        R = W - A @ np.linalg.lstsq(A, W, rcond=None)[0]
        use = R.std(axis=0) >= min_std
        sync = np.nan
        if use.sum() >= 2:
            C = np.corrcoef(R[:, use].T)
            sync = float((C.sum() - np.trace(C)) / (C.size - len(C)))
        rows.append(dict(t_start_s=s / fps, t_end_s=e / fps, t_center_s=(s + e) / 2 / fps, sync=sync,
                         spatial_sd=float(W.std(axis=1).mean()), n_boxes=int(X.shape[1])))
    return pd.DataFrame(rows) if rows else _empty_grid()
