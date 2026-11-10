"""Compare the brightness spectra of ROIs across clips (e.g. flicker against a sunlight reference).

Rosen et al. (2015) compared the spectrum of flickering with that of sunlight fluctuations recorded just below the
surface and found them qualitatively similar.  Movie 4 of that paper shows sunlight reflected on the dorsal surface,
so it can serve as the reference.  Each series is the whole signal of one ROI (linear drift removed, 0.5 Hz high-pass
as in the paper, Hann window).

Usage:
    python compare_spectra.py                                  default set (see DEFAULT below)
    python compare_spectra.py video_id:roi[:skip_s] ...        e.g.  jeb114157_video4:dorsal_light:1.0
(skip_s drops the first seconds, e.g. the black frames at the start of Movie 4.)

Prints a table (peak frequency, share of power at 1-4 Hz, spectral flatness) and the correlation between the
normalized spectra at 1-4 Hz, and writes processed/spectra_compare.csv (long form: series, freq_hz, power).
These are short clips: the frequency resolution is about 1 / clip length, so the comparison is coarse.
"""
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'processed' / 'wf_chromatophore.duckdb'
DEFAULT = ['jeb114157_video4:dorsal_light:1.0', 'jeb114157_video3:mantle', 'jeb114157_video2:mantle']
BAND = (0.5, 8.0)
COMPARE = (1.0, 4.0)
NFFT = 1024


def spectrum(x, fps):
    x = np.asarray(x, float)
    k = np.arange(len(x))
    x = x - np.polyval(np.polyfit(k, x, 1), k)
    f = np.fft.rfftfreq(NFFT, 1.0 / fps)
    p = np.abs(np.fft.rfft(x * np.hanning(len(x)), n=NFFT)) ** 2
    m = (f >= BAND[0]) & (f <= BAND[1])
    return f[m], p[m]


def main(argv):
    specs = argv or DEFAULT
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows, long, curves = [], [], {}
    grid = np.linspace(*COMPARE, 61)
    for spec in specs:
        vid, roi, *rest = spec.split(':')
        skip = float(rest[0]) if rest else 0.0
        d = con.execute('SELECT t_s, gray FROM roi_signal WHERE video_id=? AND roi=? AND t_s>=? ORDER BY frame',
                        (vid, roi, skip)).df()
        if len(d) < 16:
            print(f'{spec}: not enough frames ({len(d)}), skipped (is the video analysed and the ROI in its toml?)')
            continue
        fps = 1.0 / float(np.median(np.diff(d.t_s)))
        f, p = spectrum(d.gray.to_numpy(), fps)
        pn = p / p.sum()
        name = f'{vid}:{roi}'
        curves[name] = np.interp(grid, f, pn)
        long.append(pd.DataFrame({'series': name, 'freq_hz': f, 'power': pn}))
        sel = (f >= COMPARE[0]) & (f <= COMPARE[1])
        rows.append(dict(series=name, seconds=round(len(d) / fps, 1), resolution_hz=round(fps / len(d), 2),
                         peak_hz=round(float(f[np.argmax(p)]), 2), share_1_4hz=round(float(pn[sel].sum()), 2),
                         flatness=round(float(np.exp(np.log(p + 1e-18).mean()) / p.mean()), 2)))
    if not rows:
        return 1
    print(pd.DataFrame(rows).to_string(index=False))
    if len(curves) > 1:
        corr = pd.DataFrame(curves).corr().round(2)
        print('\nCorrelation of the normalized spectra at 1-4 Hz (1 = same shape):')
        print(corr.to_string())
    out = BASE_DIR / 'processed' / 'spectra_compare.csv'
    pd.concat(long, ignore_index=True).to_csv(out, index=False)
    print(f'\nWrote {out.relative_to(BASE_DIR)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
