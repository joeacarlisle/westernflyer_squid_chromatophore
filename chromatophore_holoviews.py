"""Panel / HoloViews dashboard for the chromatophore video analysis (read-only).

Run with the scripts in scripts/ (they pass --static-dirs so the browser can play videos/*.mp4):
    python -m panel serve chromatophore_holoviews.py --port 5009 --static-dirs videos=videos --show

Reads processed/wf_chromatophore.duckdb written by main.py.  The video is always visible at the top; its
play position drives a cursor on the signal plots, and the slider next to it moves the video.
"""
import functools
import json
from pathlib import Path

import cv2
import duckdb
import holoviews as hv
import numpy as np
import pandas as pd
import panel as pn
from scipy.signal import spectrogram

hv.extension('bokeh')
pn.extension('tabulator')

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'processed' / 'wf_chromatophore.duckdb'
VIDEO_DIR = BASE_DIR / 'videos'
STATE_COLORS = {'quiet': '#9aa5b1', 'flickering': '#f0a500', 'flashing': '#d62728', 'untracked': '#e6e6e6'}
ROI_COLORS = ['#1f77b4', '#2ca02c', '#9467bd', '#8c564b', '#e377c2', '#17becf']

if not DB_PATH.exists():
    raise SystemExit(f'{DB_PATH} not found. Run first:  python main.py --demo')
con = duckdb.connect(str(DB_PATH), read_only=True)


def q(sql, params=()):
    return con.execute(sql, params).df()


videos = q('SELECT * FROM videos ORDER BY video_id')
if videos.empty:
    raise SystemExit('No videos in the database. Run:  python main.py --demo')

# ── Widgets ──────────────────────────────────────────────────────────────────────
video_select = pn.widgets.Select(name='Video', options=list(videos['video_id']), value=videos['video_id'].iloc[0])
roi_select = pn.widgets.CheckBoxGroup(name='Regions of interest (ROI)', options=[], value=[])
truth_toggle = pn.widgets.Checkbox(name='Show known truth (synthetic demo only)', value=False)


def _video_row():
    return videos[videos['video_id'] == video_select.value].iloc[0]


def _rois(video_id):
    return list(q('SELECT roi FROM rois WHERE video_id = ? ORDER BY roi', (video_id,))['roi'])


def _truth(video_id):
    p = VIDEO_DIR / f'{video_id}_truth.json'
    return json.loads(p.read_text()) if p.exists() else None


video_pane = pn.pane.Video(object=str(videos['path'].iloc[0]), width=640, height=360, loop=False, throttle=100, time=0.0)
time_slider = pn.widgets.FloatSlider(name='Video position (s)', start=0, end=1, step=0.1, value=0, width=640)
time_slider.link(video_pane, value='time', bidirectional=True)


def _on_video(*_):
    v = _video_row()
    rois = _rois(v['video_id'])
    roi_select.options = rois
    roi_select.value = rois
    video_pane.object = str(v['path'])                      # e.g. videos/demo_two_squid.mp4, served by --static-dirs
    video_pane.time = 0.0
    time_slider.end = float(v['duration_s'])
    time_slider.value = 0.0
    truth_toggle.visible = _truth(v['video_id']) is not None       # only the synthetic demo has a known truth
    if not truth_toggle.visible:
        truth_toggle.value = False


video_select.param.watch(_on_video, 'value')
_on_video()


def _color(roi, rois):
    return ROI_COLORS[rois.index(roi) % len(ROI_COLORS)]


# ── Summary tiles under the video ────────────────────────────────────────────────
def _summary(video_id, rois):
    if not rois:
        return pn.pane.Alert('Select at least one ROI.', alert_type='warning')
    ph = ', '.join(f"'{r}'" for r in rois)
    df = q(f"SELECT roi, state, count(*) AS n, avg(dom_freq_hz) AS f FROM roi_windows "
           f"WHERE video_id = ? AND roi IN ({ph}) GROUP BY roi, state", (video_id,))
    lines = []
    for r in rois:
        d = df[df['roi'] == r]
        tot = d['n'].sum()
        if tot == 0:
            continue
        share = {s: 100.0 * d.loc[d['state'] == s, 'n'].sum() / tot for s in STATE_COLORS}
        fl = d[d['state'] == 'flashing']
        ftxt = f", mean flash frequency {fl['f'].iat[0]:.2f} Hz" if len(fl) else ''
        lines.append(f"**{r}** - flashing {share['flashing']:.0f}%, flickering {share['flickering']:.0f}%, "
                     f"quiet {share['quiet']:.0f}% of the time{ftxt}"
                     + (f", **untracked {share['untracked']:.0f}%** (tracking lost the animal)" if share['untracked'] else ''))
    return pn.pane.Markdown('\n\n'.join(lines), sizing_mode='stretch_width')


summary = pn.bind(lambda v, r: _summary(v, r), video_select, roi_select)


# ── Tabs ─────────────────────────────────────────────────────────────────────────
def _signal_impl(video_id, rois, show_truth):
    if not rois:
        return pn.pane.Alert('Select at least one ROI.', alert_type='warning')
    cursor = hv.streams.Params(video_pane, ['time'], rename={'time': 't'})
    plots = []
    truth = _truth(video_id) if show_truth else None
    for r in rois:
        sig = q('SELECT t_s, gray FROM roi_signal WHERE video_id = ? AND roi = ? ORDER BY frame', (video_id, r))
        eps = q('SELECT state, t_start_s, t_end_s FROM episodes WHERE video_id = ? AND roi = ? ORDER BY t_start_s',
                (video_id, r))
        ymin, ymax = float(sig['gray'].min()), float(sig['gray'].max())
        span = max(ymax - ymin, 0.05)
        pad = 0.05 * span
        bar = 0.07 * span if truth and r in truth['segments'] else 0.0       # room for the truth bars at the bottom
        bands = hv.Overlay([hv.VSpan(a, b).opts(color=STATE_COLORS[s], alpha=0.25, line_alpha=0)
                            for s, a, b in zip(eps['state'], eps['t_start_s'], eps['t_end_s'])])
        curve = hv.Curve(sig, 't_s', 'gray', label=r).opts(color=_color(r, rois), line_width=1.5)
        line = hv.DynamicMap(lambda t: hv.VLine(t or 0).opts(color='black', line_width=1.5, line_dash='dashed'),
                             streams=[cursor])
        p = bands * curve * line
        if bar:
            y0 = ymin - pad - bar
            rect = hv.Rectangles([(sg['t_start'], y0, sg['t_end'], y0 + bar, sg['state']) for sg in truth['segments'][r]],
                                 vdims=['state']).opts(color='state', cmap=STATE_COLORS, line_color=None,
                                                       show_legend=False)
            p = p * rect
        plots.append(p.opts(height=190, responsive=True, ylim=(ymin - pad - bar, ymax + pad),
                            ylabel='brightness', xlabel='', tools=['hover'], show_grid=True, show_legend=False,
                            title=r))
    plots[-1] = plots[-1].opts(xlabel='time (s)')
    legend = pn.pane.HTML(' '.join(
        f'<span style="background:{c};opacity:.55;padding:2px 10px;margin-right:8px;border-radius:3px">{s}</span>'
        for s, c in STATE_COLORS.items()) + ' &nbsp; shaded bands = detected state' + (' &nbsp; bars at the bottom = known truth' if show_truth else ''))
    return pn.Column(legend, pn.pane.HoloViews(hv.Layout(plots).cols(1), sizing_mode='stretch_width'),
                     sizing_mode='stretch_width')


view_signal = pn.bind(_signal_impl, video_select, roi_select, truth_toggle)

_spec_cache = {}


def _spectrogram(video_id, roi, fps, cfg):
    key = (video_id, roi)
    if key not in _spec_cache:
        sig = q('SELECT gray FROM roi_signal WHERE video_id = ? AND roi = ? ORDER BY frame', (video_id, roi))['gray'].to_numpy()
        nper = int(round(cfg['analysis']['window_s'] * fps))
        hop = max(1, int(round(cfg['analysis']['hop_s'] * fps)))
        f, t, S = spectrogram(sig - sig.mean(), fs=fps, window='hann', nperseg=nper, noverlap=nper - hop,
                              nfft=int(cfg['analysis']['nfft']), detrend='linear', mode='psd')
        lo, hi = cfg['analysis']['band_hz']
        m = (f >= 0) & (f <= hi)
        _spec_cache[key] = (f[m], t, S[m])
    return _spec_cache[key]


def _spectro_impl(video_id, rois):
    if not rois:
        return pn.pane.Alert('Select at least one ROI.', alert_type='warning')
    meta = q('SELECT settings_json FROM build_metadata WHERE video_id = ?', (video_id,))
    cfg = json.loads(meta['settings_json'].iat[0])
    fps = float(_video_row()['fps'])
    plots = []
    for r in rois:
        f, t, S = _spectrogram(video_id, r, fps, cfg)
        img = hv.Image((t, f, np.log10(S + 1e-12)), kdims=['time (s)', 'frequency (Hz)'], vdims=['log10 power'])
        w = q('SELECT t_center_s, dom_freq_hz, state FROM roi_windows WHERE video_id = ? AND roi = ? '
              'ORDER BY t_center_s', (video_id, r))
        fl = w[w['state'] == 'flashing']
        pts = hv.Scatter(fl, 't_center_s', 'dom_freq_hz').opts(color='white', size=5, line_color='black')
        plots.append((img.opts(cmap='magma', colorbar=True, height=240, responsive=True, title=f'{r}: spectrogram',
                               tools=['hover']) * pts))
    note = pn.pane.Markdown('Bright horizontal band = a steady rhythm. White dots = windows detected as flashing, '
                            'at their dominant frequency. Flickering is broadband, so it has no single band.')
    return pn.Column(note, pn.pane.HoloViews(hv.Layout(plots).cols(1), sizing_mode='stretch_width'),
                     sizing_mode='stretch_width')


view_spectro = pn.bind(_spectro_impl, video_select, roi_select)


def _episodes_impl(video_id, rois):
    if not rois:
        return pn.pane.Alert('Select at least one ROI.', alert_type='warning')
    ph = ', '.join(f"'{r}'" for r in rois)
    ep = q(f"SELECT roi AS ROI, state AS State, round(t_start_s, 1) AS \"Start (s)\", round(t_end_s, 1) AS \"End (s)\", "
           f"round(duration_s, 1) AS \"Duration (s)\", round(mean_freq_hz, 2) AS \"Mean flash freq (Hz)\", "
           f"round(mean_p2p, 3) AS \"Mean swing\" FROM episodes WHERE video_id = ? AND roi IN ({ph}) "
           f"ORDER BY ROI, \"Start (s)\"", (video_id,))
    bars = q(f"SELECT roi, state, sum(duration_s) AS seconds FROM episodes WHERE video_id = ? AND roi IN ({ph}) "
             f"GROUP BY roi, state", (video_id,))
    chart = hv.Bars(bars, ['roi', 'state'], 'seconds').opts(
        stacked=True, height=260, width=420, cmap=STATE_COLORS, color='state', legend_position='right',
        title='Time spent in each state (s)', tools=['hover'])
    table = pn.widgets.Tabulator(ep, theme='midnight', show_index=False, sizing_mode='stretch_width', height=340,
                                 disabled=True)
    return pn.Column(pn.pane.HoloViews(chart), table, sizing_mode='stretch_width')


view_episodes = pn.bind(_episodes_impl, video_select, roi_select)


def _phase_impl(video_id, rois):
    if len(rois) < 2:
        return pn.pane.Alert('Select two or more ROIs to compare their rhythms.', alert_type='info')
    a, b = rois[0], rois[1]
    ph = q('SELECT t_center_s, phase_deg, freq_hz FROM pair_windows WHERE video_id = ? AND roi_a = ? AND roi_b = ? '
           'AND both_flashing ORDER BY t_center_s', (video_id, a, b))
    if ph.empty:
        return pn.pane.Alert(f'{a} and {b} never flash at the same time in this video.', alert_type='info')
    sc = hv.Scatter(ph, 't_center_s', ['phase_deg', 'freq_hz']).opts(
        color='freq_hz', cmap='viridis', colorbar=True, size=8, ylim=(-200, 200), height=320, responsive=True,
        xlabel='time (s)', ylabel=f'phase of {b} vs {a} (deg)', tools=['hover'],
        title=f'Phase between {a} and {b} while both flash')
    lines = hv.Overlay([hv.HLine(y).opts(color='gray', line_dash='dashed', line_width=1) for y in (-180, 0, 180)])
    txt = pn.pane.Markdown(
        f'**0 deg** = {a} and {b} flash together; **+-180 deg** = opposite (one white while the other is red); '
        f'positive = {b} leads {a}. Only windows where both are detected as flashing are shown.')
    return pn.Column(txt, pn.pane.HoloViews(sc * lines, sizing_mode='stretch_width'), sizing_mode='stretch_width')


view_phase = pn.bind(_phase_impl, video_select, roi_select)


def _setup_impl(video_id):
    prev = BASE_DIR / 'processed' / f'{video_id}_roi_preview.png'
    meta = q('SELECT analysed_utc, analysis_version, video_sha256, settings_json FROM build_metadata '
             'WHERE video_id = ?', (video_id,))
    cfg = json.loads(meta['settings_json'].iat[0])
    rows = [('Analysed (UTC)', meta['analysed_utc'].iat[0]), ('Analysis version', meta['analysis_version'].iat[0]),
            ('Video SHA-256', meta['video_sha256'].iat[0][:16] + '...')]
    rows += [(f'analysis.{k}', str(v)) for k, v in cfg['analysis'].items()]
    rows += [(f'classify.{k}', str(v)) for k, v in cfg['classify'].items()]
    rows += [(f'tracking.{k}', str(v)) for k, v in cfg.get('tracking', {}).items()]
    tbl = pn.widgets.Tabulator(pd.DataFrame(rows, columns=['Setting', 'Value']), theme='midnight', show_index=False,
                               disabled=True, width=620, height=420)
    items = [pn.pane.Markdown('### Regions of interest (yellow boxes on the first frame)')]
    items.append(pn.pane.PNG(str(prev), width=520) if prev.exists() else pn.pane.Markdown('*(preview not found)*'))
    items += [pn.pane.Markdown('### Settings used for this analysis'), tbl,
              pn.pane.Markdown('*Thresholds are placeholders tuned on the synthetic demo. They need checking against '
                               'clips labeled by hand before any scientific use.*')]
    return pn.Column(*items)


view_setup = pn.bind(_setup_impl, video_select)


# ── Tracked boxes ────────────────────────────────────────────────────────────────
@functools.lru_cache(maxsize=8)
def _track(video_id):
    """Box of every ROI on every frame (older databases without roi_track fall back to the fixed boxes)."""
    try:
        return q('SELECT roi, frame, x, y, w, h, tracked, lost FROM roi_track WHERE video_id = ? ORDER BY roi, frame', (video_id,))
    except duckdb.CatalogException:
        r = q('SELECT roi, x, y, w, h FROM rois WHERE video_id = ?', (video_id,))
        r['frame'], r['tracked'], r['lost'] = 0, False, False
        return r


def _bgr(hex_color):
    h = hex_color.lstrip('#')
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def _frame_impl(video_id, rois, t):
    v = videos[videos['video_id'] == video_id].iloc[0]
    cap = cv2.VideoCapture(str(BASE_DIR / v['path']))
    idx = int(min(max(round(t * v['fps']), 0), v['n_frames'] - 1))
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, img = cap.read()
    cap.release()
    if not ok:
        return pn.pane.Markdown('*(frame not available)*')
    scale = 440 / img.shape[1]
    img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    tr, all_rois = _track(video_id), _rois(video_id)
    for r in rois:
        d = tr[tr['roi'] == r]
        d = d[d['frame'] == min(idx, d['frame'].max())]
        if d.empty:
            continue
        d = d.iloc[0]
        col = (80, 80, 255) if d['lost'] else _bgr(_color(r, all_rois))
        p0 = (int(d['x'] * scale), int(d['y'] * scale))
        p1 = (int((d['x'] + d['w']) * scale), int((d['y'] + d['h']) * scale))
        cv2.rectangle(img, p0, p1, col, 2)
        cv2.putText(img, r + (' (lost)' if d['lost'] else ''), (p0[0], max(12, p0[1] - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
    return pn.pane.PNG(cv2.imencode('.png', img)[1].tobytes(), width=440)


view_frame = pn.bind(_frame_impl, video_select, roi_select, time_slider.param.value_throttled)


def _tracking_impl(video_id, rois):
    tr = _track(video_id)
    fps = float(videos.loc[videos['video_id'] == video_id, 'fps'].iat[0])
    all_rois = _rois(video_id)
    tr = tr[tr['roi'].isin(rois)]
    if tr.empty or not tr['tracked'].any():
        return pn.pane.Markdown('*No ROI of this video is tracked: its boxes are fixed. Tracking is switched on in '
                                'videos/<video_id>.toml with  [tracking]  rois = ["name"].*')
    tr = tr[tr['tracked']].assign(t_s=lambda d: d['frame'] / fps)
    curves = []
    for r, d in tr.groupby('roi'):
        c = _color(r, all_rois)
        for col, dash in (('x', 'solid'), ('y', 'dashed')):
            curves.append(hv.Curve(d, 't_s', col, label=f'{r} {col}').opts(color=c, line_dash=dash, line_width=2))
    lost = tr[tr['lost']]
    pts = hv.Scatter(lost, 't_s', 'x').opts(color='red', size=6) if len(lost) else hv.Scatter([])
    plot = (hv.Overlay(curves) * pts).opts(height=300, responsive=True, ylabel='box corner (px)', xlabel='time (s)',
                                           legend_position='right', tools=['hover'], title='Where the tracked boxes are')
    share = tr.groupby('roi')['lost'].mean().mul(100).round(0).astype(int)
    txt = '  \n'.join(f'**{r}** - tracking lost on {s}% of frames' for r, s in share.items())
    return pn.Column(pn.pane.Markdown(
        'Solid = x (left edge), dashed = y (top edge) of each tracked box. Red dots mark frames where too few feature points '
        'could be followed, so the box stayed where it was. Windows with many such frames are labeled *untracked* and '
        'excluded from the states and the phase.\n\n' + txt), pn.pane.HoloViews(plot, sizing_mode='stretch_width'),
        sizing_mode='stretch_width')


view_tracking = pn.bind(_tracking_impl, video_select, roi_select)

tabs = pn.Tabs(('Signal and states', view_signal), ('Spectrogram', view_spectro), ('Episodes', view_episodes),
               ('Phase between squid', view_phase), ('Tracking', view_tracking), ('Setup', view_setup), dynamic=True)

BANNER_SYNTHETIC = ('**Prototype.** This video is synthetic (two drawn shapes with known flashing and flickering), so the '
                    'results can be checked against the truth. Real footage will need ROI boxes and tuned thresholds.')
BANNER_REAL = ('**Prototype - real footage.** The ROI boxes were placed by hand on the first frame and follow the animals by '
               'optical-flow tracking, which can drift (see the Tracking tab). Thresholds were tuned on the synthetic demo and are placeholders until checked '
               'against expert annotation.')


def _banner_impl(video_id):
    synthetic = bool(videos.loc[videos['video_id'] == video_id, 'synthetic'].iloc[0])
    return pn.pane.Alert(BANNER_SYNTHETIC if synthetic else BANNER_REAL, alert_type='warning', sizing_mode='stretch_width')


banner = pn.bind(_banner_impl, video_select)

top = pn.Column(pn.Row(pn.Column(video_pane, time_slider, width=660),
                       pn.Column(pn.pane.Markdown('**ROI boxes at the video position**', margin=(0, 10, 0, 10)), view_frame, width=460)),
                pn.pane.Markdown('### Summary'), summary, sizing_mode='stretch_width')

dashboard = pn.template.FastListTemplate(
    title='Gilly Lab - Humboldt squid chromatophores (prototype)',
    sidebar=[video_select, pn.pane.Markdown('**Regions of interest**', margin=(10, 10, 0, 10)), roi_select,
             truth_toggle],
    main=[banner, top, tabs],
    accent_base_color='#d62728', header_background='#1a1a1a')
dashboard.servable()
