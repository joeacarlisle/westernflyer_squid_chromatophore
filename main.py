"""Chromatophore video pipeline: video + ROI boxes -> signals, windowed features, states and episodes in DuckDB.

Usage:
    python main.py                      analyse every videos/*.mp4
    python main.py demo_two_squid       analyse one video (id or path)
    python main.py --demo               (re)generate the synthetic demo video first, then analyse it

Each video needs videos/<video_id>.toml with a [rois] table: name = [x, y, width, height] in pixels.
Settings (window length, thresholds) come from config.defaults.toml; a video's own toml may override them.
Results go to processed/wf_chromatophore.duckdb; per-video records are replaced atomically.
"""
import argparse
import copy
import hashlib
import json
import logging
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import cv2
import duckdb
import numpy as np
import pandas as pd

import chroma_analysis as ca
from roi_tracker import BoxTracker

BASE_DIR = Path(__file__).resolve().parent
VIDEO_DIR = BASE_DIR / 'videos'
PROCESSED_DIR = BASE_DIR / 'processed'
LOG_DIR = BASE_DIR / 'logs'
DB_PATH = PROCESSED_DIR / 'wf_chromatophore.duckdb'
ANALYSIS_VERSION = '0.4-prototype'


def _deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(video_id):
    cfg = tomllib.loads((BASE_DIR / 'config.defaults.toml').read_text())
    own = VIDEO_DIR / f'{video_id}.toml'
    if not own.exists():
        raise FileNotFoundError(f'{own} not found. Create it with a [rois] table: name = [x, y, width, height]')
    own_cfg = tomllib.loads(own.read_text())
    rois = own_cfg.pop('rois', None)
    grids = own_cfg.pop('grids', {})
    if not rois:
        raise ValueError(f'{own}: needs a [rois] table, e.g.  squid_1 = [x, y, width, height]')
    cfg = _deep_merge(cfg, own_cfg)
    cfg['rois'] = {k: [int(v) for v in box] for k, box in rois.items()}
    cfg['grids'] = {k: [int(v) for v in g] for k, g in grids.items()}
    for k, g in cfg['grids'].items():
        if len(g) != 6 or g[4] < 1 or g[5] < 1:
            raise ValueError(f'[grids] {k}: needs [x, y, width, height, rows, columns]')
    return cfg


def extract_signals(video_path, rois, track_cfg=None, grids=None):
    """Mean grayscale (0-1) inside every ROI for every frame.

    ROIs named in track_cfg['rois'] follow the animal (roi_tracker.BoxTracker); the others stay where they are.
    Also returns the box used on every frame: {roi: array of (x, y, w, h, lost)}, and for every grid
    (name = [x, y, w, h, rows, columns]) an array (frames, boxes) of the mean grayscale of each cell.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise IOError(f'Cannot open video: {video_path}')
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    tracked = set((track_cfg or {}).get('rois', []))
    unknown = tracked - set(rois)
    if unknown:
        raise ValueError(f'[tracking] rois names {sorted(unknown)} that are not in [rois]')
    grids = grids or {}
    sig = {k: [] for k in rois}
    gsig = {k: [] for k in grids}
    boxes = {k: [] for k in rois}
    trackers = {}
    first = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray_u8 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if first is None:
            first = frame.copy()
            h, w = frame.shape[:2]
            for k, (x, y, bw, bh) in rois.items():
                if x < 0 or y < 0 or x + bw > w or y + bh > h or bw < 2 or bh < 2:
                    raise ValueError(f'ROI {k} {rois[k]} does not fit inside the {w}x{h} frame')
            for k, (x, y, bw, bh, r, c) in grids.items():
                if x < 0 or y < 0 or x + bw > w or y + bh > h or bw < c or bh < r:
                    raise ValueError(f'grid {k} {grids[k]} does not fit inside the {w}x{h} frame')
            trackers = {k: BoxTracker(rois[k], track_cfg) for k in tracked}
        gray = gray_u8.astype(np.float32) / 255.0
        for k, (x, y, bw, bh) in rois.items():
            if k in trackers:
                tx, ty, _, _, lost = trackers[k].update(gray_u8)
                x, y = int(round(tx)), int(round(ty))
            else:
                lost = False
            boxes[k].append((x, y, bw, bh, lost))
            sig[k].append(float(gray[y:y + bh, x:x + bw].mean()))
        for k, (x, y, bw, bh, r, c) in grids.items():
            ys, xs = np.linspace(0, bh, r + 1).round().astype(int), np.linspace(0, bw, c + 1).round().astype(int)
            cell = gray[y:y + bh, x:x + bw]
            gsig[k].append([cell[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].mean() for i in range(r) for j in range(c)])
    cap.release()
    if first is None:
        raise IOError(f'No frames read from {video_path}')
    return (fps, first, {k: np.asarray(v) for k, v in sig.items()}, {k: np.asarray(v) for k, v in boxes.items()},
            {k: np.asarray(v) for k, v in gsig.items()})


def write_roi_preview(first_frame, rois, out_path):
    img = first_frame.copy()
    for k, (x, y, w, h) in rois.items():
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 255, 255), 2)
        cv2.putText(img, k, (x, max(14, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), img)


def analyse_video(video_path, con):
    video_path = Path(video_path)
    video_id = video_path.stem
    cfg = load_config(video_id)
    logging.info(f'{video_id}: reading {video_path.name} ...')
    fps, first, sig, boxes, gsig = extract_signals(video_path, cfg['rois'], cfg.get('tracking'), cfg['grids'])
    n = len(next(iter(sig.values())))
    duration = n / fps
    logging.info(f'{video_id}: {n} frames, {fps:g} fps, {duration:.1f} s, ROIs: {", ".join(sig)}')

    feats, sigs_rows, ep_rows, cyc_rows, pause_rows = {}, [], [], [], []
    for name, x in sig.items():
        f = ca.classify(ca.window_features(x, fps, cfg, lost=boxes[name][:, 4]), cfg)
        f.insert(0, 'roi', name)
        feats[name] = f
        ep = ca.episodes(f, duration, cfg['analysis']['hop_s'])
        ep, cyc = ca.flash_cycles(x, fps, ep, cfg)
        pz = ca.find_pauses(x, fps, ep, cfg)
        ep.insert(0, 'roi', name)
        cyc.insert(0, 'roi', name)
        pz.insert(0, 'roi', name)
        ep_rows.append(ep)
        cyc_rows.append(cyc)
        pause_rows.append(pz)
        sigs_rows.append(pd.DataFrame({'roi': name, 'frame': np.arange(n), 't_s': np.arange(n) / fps, 'gray': x}))
        fl = ep[ep['n_cycles'].notna()]
        if len(fl):
            logging.info(f'{video_id}/{name}: flash cycles ' + '; '.join(
                f'{r.t_start_s:.1f}-{r.t_end_s:.1f}s {r.cycle_freq_hz:.2f} Hz (SD {r.cycle_freq_sd_hz:.2f}, {int(r.n_cycles)} cycles)'
                for r in fl.itertuples()))
        act = pz[pz['preceded_by_activity']]
        logging.info(f'{video_id}/{name}: {len(pz)} pauses, {len(act)} after activity, '
                     f'{int(act["followed_by_flash"].sum())} of those followed by a flash')
        shares = f['state'].value_counts(normalize=True).round(2).to_dict()
        logging.info(f'{video_id}/{name}: window states {shares}')
        if name in cfg['tracking']['rois']:
            lost = boxes[name][:, 4].mean()
            move = np.hypot(*(boxes[name][:, :2].max(axis=0) - boxes[name][:, :2].min(axis=0)))
            logging.info(f'{video_id}/{name}: tracked, box moved up to {move:.0f} px, tracking lost on {100 * lost:.0f}% of frames')

    grid_rows = []
    for name, g in gsig.items():
        gw = ca.grid_features(g, fps, cfg)
        gw.insert(0, 'grid', name)
        grid_rows.append(gw)
        logging.info(f'{video_id}/{name}: grid of {g.shape[1]} boxes, mean synchrony {gw["sync"].mean():.2f} '
                     f'(1 = all boxes move together), spatial SD {gw["spatial_sd"].mean():.3f}')

    pair_rows = []
    names = list(sig)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            p = ca.pair_phase(sig[a], sig[b], feats[a], feats[b], fps, cfg)
            if p['both_flashing'].any():
                logging.info(f'{video_id}: {a} and {b} in phase (within 20% of a cycle) in '
                             f'{100 * ca.in_phase_fraction(p):.0f}% of the windows where both flash')
            p.insert(0, 'roi_b', b)
            p.insert(0, 'roi_a', a)
            pair_rows.append(p)

    tables = {
        'videos': pd.DataFrame([dict(video_id=video_id, path=f'videos/{video_path.name}', fps=float(fps),
                                     n_frames=int(n), duration_s=float(duration), width=int(first.shape[1]),
                                     height=int(first.shape[0]),
                                     synthetic=bool((VIDEO_DIR / f'{video_id}_truth.json').exists()))]),
        'rois': pd.DataFrame([dict(video_id=video_id, roi=k, x=v[0], y=v[1], w=v[2], h=v[3])
                              for k, v in cfg['rois'].items()]),
        'roi_track': pd.concat([pd.DataFrame({'roi': k, 'frame': np.arange(n), 't_s': np.arange(n) / fps,
                                              'x': b[:, 0].astype(int), 'y': b[:, 1].astype(int), 'w': b[:, 2].astype(int),
                                              'h': b[:, 3].astype(int), 'tracked': k in cfg['tracking']['rois'],
                                              'lost': b[:, 4].astype(bool)}) for k, b in boxes.items()], ignore_index=True),
        'roi_signal': pd.concat(sigs_rows, ignore_index=True),
        'roi_windows': pd.concat(feats.values(), ignore_index=True),
        'pair_windows': pd.concat(pair_rows, ignore_index=True) if pair_rows else pd.DataFrame(
            columns=['roi_a', 'roi_b', 't_center_s', 'both_flashing', 'freq_hz', 'phase_deg']),
        'episodes': pd.concat(ep_rows, ignore_index=True),
        'flash_cycles': pd.concat(cyc_rows, ignore_index=True),
        'pauses': pd.concat(pause_rows, ignore_index=True),
        'grid_windows': pd.concat(grid_rows, ignore_index=True) if grid_rows else ca._empty_grid().assign(grid=pd.Series(dtype='string')),
        'build_metadata': pd.DataFrame([dict(
            video_id=video_id, analysed_utc=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            analysis_version=ANALYSIS_VERSION,
            video_sha256=hashlib.sha256(video_path.read_bytes()).hexdigest(),
            settings_json=json.dumps({k: cfg[k] for k in ('analysis', 'classify', 'tracking', 'cycles', 'pauses', 'synchrony')}, sort_keys=True))]),
    }
    for t in ('roi_windows', 'pair_windows', 'episodes', 'roi_signal', 'roi_track', 'flash_cycles', 'pauses', 'grid_windows'):
        tables[t].insert(0, 'video_id', video_id)

    con.execute('BEGIN')
    try:
        for name, df in tables.items():
            con.register('_df', df)
            con.execute(f'CREATE TABLE IF NOT EXISTS {name} AS SELECT * FROM _df WHERE 1=0')
            have = {r[0] for r in con.execute(f'DESCRIBE {name}').fetchall()}
            for col, typ, *_ in con.execute('DESCRIBE _df').fetchall():       # a database from an older version gets the new columns
                if col not in have:
                    con.execute(f'ALTER TABLE {name} ADD COLUMN {col} {typ}')
            con.execute(f'DELETE FROM {name} WHERE video_id = ?', (video_id,))
            con.execute(f'INSERT INTO {name} BY NAME SELECT * FROM _df')
            con.unregister('_df')
        con.execute('COMMIT')
    except Exception:
        con.execute('ROLLBACK')
        raise
    PROCESSED_DIR.mkdir(exist_ok=True)
    write_roi_preview(first, cfg['rois'], PROCESSED_DIR / f'{video_id}_roi_preview.png')
    logging.info(f'{video_id}: done')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video', nargs='?', help='video id (videos/<id>.mp4) or path; default: all videos/*.mp4')
    ap.add_argument('--demo', action='store_true', help='regenerate the synthetic demo video first')
    args = ap.parse_args(argv)

    LOG_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                        handlers=[logging.FileHandler(LOG_DIR / f'wf_chromatophore_{stamp}.log'),
                                  logging.StreamHandler(sys.stdout)])
    if args.demo:
        import make_demo_video
        make_demo_video.main()

    if args.video:
        p = Path(args.video)
        videos = [p if p.suffix else VIDEO_DIR / f'{args.video}.mp4']
    else:
        videos = sorted(VIDEO_DIR.glob('*.mp4'))
    if not videos:
        logging.error('No videos found. Put .mp4 files in videos/ (and a matching .toml), or run: python main.py --demo')
        return 1

    con = duckdb.connect(str(DB_PATH))
    failed = 0
    for v in videos:
        try:
            analyse_video(v, con)
        except Exception as e:
            failed += 1
            logging.error(f'{v.stem}: FAILED - {e}')
    con.close()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
