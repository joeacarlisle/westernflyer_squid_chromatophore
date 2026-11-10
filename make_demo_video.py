"""Synthetic demo video: two Humboldt-squid-like shapes whose body color changes between red and white.

There is no squid footage in this prototype.  This script draws two ellipses on a dark-blue
background and drives their color with KNOWN signals, so the analysis can be checked against the truth:

    quiet       steady dark red, only sensor noise
    flickering  low-amplitude, broadband, independent activity in many small skin patches
    flashing    the whole body oscillates white <-> red together (2-4 Hz in real squid, Rosen et al. 2015)

Squid B follows squid A with a chosen phase lag during flashing, so the phase analysis has an answer.
Everything the generator decides is written to ``<video_id>_truth.json`` next to the video.

Usage:  python make_demo_video.py     (writes videos/demo_two_squid.mp4, .toml and _truth.json)
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
VIDEO_DIR = BASE_DIR / 'videos'
VIDEO_ID = 'demo_two_squid'

W, H, FPS, DURATION_S = 640, 360, 30, 40
GRID = (4, 8)                                # skin patches (rows, columns) per squid
RED = np.array([200, 30, 30], float)         # RGB with chromatophores open
WHITE = np.array([235, 225, 220], float)     # RGB with chromatophores closed (white skin shows)

# name -> ellipse centre, half-axes, angle, ROI box (x, y, w, h) that stays inside the ellipse
SQUID = {
    'squid_A': dict(c=(200, 190), ax=(110, 45), ang=-10, roi=(140, 172, 120, 36)),
    'squid_B': dict(c=(440, 170), ax=(90, 40), ang=8, roi=(385, 152, 100, 36)),
}

# Truth timeline per squid: (t_start, t_end, state, freq_hz, amplitude, phase_deg)
# amplitude = swing of whiteness (0-1); phase_deg = lag of squid B against squid A (B rows only)
TRUTH = {
    'squid_A': [(0, 8, 'quiet', 0, 0, 0), (8, 18, 'flickering', 0, 0, 0), (18, 30, 'flashing', 3.0, 0.8, 0),
                (30, 34, 'quiet', 0, 0, 0), (34, 40, 'flashing', 2.0, 0.5, 0)],
    'squid_B': [(0, 8, 'quiet', 0, 0, 0), (8, 18, 'flickering', 0, 0, 0), (18, 24, 'flashing', 3.0, 0.8, 0),
                (24, 30, 'flashing', 3.0, 0.8, 180), (30, 34, 'quiet', 0, 0, 0), (34, 40, 'flashing', 2.0, 0.5, 90)],
}


def _segment(name, t):
    for seg in TRUTH[name]:
        if seg[0] <= t < seg[1]:
            return seg
    return TRUTH[name][-1]


def _whiteness_grid(name, t, comps):
    """Whiteness (0 red .. 1 white) of every skin patch of one squid at time t."""
    t0, _, state, freq, amp, phase = _segment(name, t)
    if state == 'flashing':
        lag = np.radians(phase) if name == 'squid_B' else 0.0
        return np.full(GRID, 0.5 + 0.5 * amp * np.sin(2 * np.pi * freq * (t - t0) + lag))
    if state == 'flickering':
        f, ph = comps[name]       # each patch: several sinusoids of random frequency 0.7-7 Hz, random phase
        return 0.32 + 0.45 * np.sin(2 * np.pi * f * t + ph).mean(axis=0)
    return np.full(GRID, 0.12)


def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return 'ffmpeg'


def render(out_path):
    rng = np.random.default_rng(7)
    comps = {n: (rng.uniform(0.7, 7.0, (6,) + GRID), rng.uniform(0, 2 * np.pi, (6,) + GRID)) for n in SQUID}
    cmd = [_ffmpeg(), '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}',
           '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '27',
           '-preset', 'veryfast', '-movflags', '+faststart', str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    yy = np.mgrid[0:H, 0:W][0].astype(float)
    bg = np.stack([40 + 0.12 * yy] * 3, axis=-1) * np.array([1.0, 0.55, 0.25])      # deep-blue gradient (BGR)
    for k in range(FPS * DURATION_S):
        t = k / FPS
        frame = bg.copy()
        for name, sq in SQUID.items():
            grid = np.clip(_whiteness_grid(name, t, comps), 0, 1).astype(np.float32)
            shift = 0.0 if name == 'squid_A' else 1.3
            cx = sq['c'][0] + 6 * np.sin(2 * np.pi * t / 17 + shift)          # slow drift of the animal
            cy = sq['c'][1] + 3 * np.sin(2 * np.pi * t / 11)
            mask = np.zeros((H, W), np.uint8)
            cv2.ellipse(mask, (int(cx), int(cy)), sq['ax'], sq['ang'], 0, 360, 255, -1, cv2.LINE_AA)
            # stretch the patch grid over the whole frame area of the ellipse's bounding box
            pad = 30                         # the rotated ellipse extends beyond its half-axes
            x0, x1 = int(cx - sq['ax'][0]) - pad, int(cx + sq['ax'][0]) + pad
            y0, y1 = int(cy - sq['ax'][1]) - pad, int(cy + sq['ax'][1]) + pad
            field = cv2.resize(grid, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
            full = np.zeros((H, W), np.float32)
            ys, xs = max(y0, 0), max(x0, 0)
            ye, xe = min(y1, H), min(x1, W)
            full[ys:ye, xs:xe] = field[ys - y0:ye - y0, xs - x0:xe - x0]
            rgb = RED[None, None, :] * (1 - full[..., None]) + WHITE[None, None, :] * full[..., None]
            m = (mask.astype(np.float32) / 255.0)[..., None]
            frame = frame * (1 - m) + rgb[..., ::-1] * m
        frame += rng.normal(0, 2.5, frame.shape)                                  # sensor noise
        proc.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()


def main():
    VIDEO_DIR.mkdir(exist_ok=True)
    out = VIDEO_DIR / f'{VIDEO_ID}.mp4'
    print(f'Rendering {out} ({DURATION_S} s, {W}x{H}, {FPS} fps) ...')
    render(out)
    lines = [f'# ROI boxes (x, y, width, height in pixels) for {VIDEO_ID}.mp4', '[rois]']
    lines += [f'{n} = {list(sq["roi"])}' for n, sq in SQUID.items()]
    lines += ['', '# Grids: [x, y, width, height, rows, columns] (spatial synchrony across small boxes)', '[grids]']
    lines += [f'grid_{n} = {list(sq["roi"]) + [2, 6]}' for n, sq in SQUID.items()]
    (VIDEO_DIR / f'{VIDEO_ID}.toml').write_text('\n'.join(lines) + '\n')
    truth = dict(video_id=VIDEO_ID, fps=FPS, synthetic=True,
                 segments={n: [dict(t_start=a, t_end=b, state=s, freq_hz=f, amplitude=amp, phase_B_deg=ph)
                               for a, b, s, f, amp, ph in segs] for n, segs in TRUTH.items()})
    (VIDEO_DIR / f'{VIDEO_ID}_truth.json').write_text(json.dumps(truth, indent=2))
    print('Done.')


if __name__ == '__main__':
    sys.exit(main())
