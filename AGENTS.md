# AGENTS.md - Western Flyer Humboldt squid chromatophores (prototype)

Guidance for AI coding agents working in this repository.

## What this is

A prototype that measures chromatophore displays (flashing and flickering) in squid video and shows them in a Panel/HoloViews dashboard. The only video in the repository is a synthetic demo with known truth. Treat every threshold as a placeholder until it has been checked against hand-labeled real footage.

## Components

1. **chroma_analysis.py** - pure numpy/pandas analysis: `window_features`, `classify`, `pair_phase`, `episodes`, `flash_cycles` (cycle-by-cycle frequency and amplitude), `find_pauses`, `grid_features` (spatial synchrony), `in_phase_fraction`. No video or database code here.
2. **main.py** - orchestrator: reads a video with OpenCV, extracts mean grayscale per ROI and frame, calls the analysis, and writes `processed/wf_chromatophore.duckdb` atomically (per-video DELETE + INSERT in one transaction).
3. **chromatophore_holoviews.py** - read-only dashboard. Reads the database; plays `videos/*.mp4` through `--static-dirs videos=videos`.
4. **roi_tracker.py** - `BoxTracker` (optical-flow ROI tracking) used by `main.extract_signals` for the ROIs named in a video's `[tracking] rois`. Frames it flags as lost make `lost_frac` windows labeled `untracked` in `chroma_analysis.classify`.
5. **compare_spectra.py** - read-only: compares the brightness spectra of ROIs across clips (flicker against the Movie 4 sunlight reference).
6. **make_demo_video.py** - synthetic video with a truth file (`videos/demo_two_squid_truth.json`), shown in the dashboard as "Show known truth".

## Rules

- Settings live in `config.defaults.toml`; a video's `videos/<id>.toml` may override them. Do not hard-code thresholds in the analysis code.
- Each video needs `videos/<id>.toml` with a `[rois]` table (`name = [x, y, width, height]` in pixels). An optional `[grids]` table (`name = [x, y, width, height, rows, columns]`) gives a spatial synchrony index. A `background` ROI in open water is a useful reference for camera or lighting changes.
- Tables: `videos`, `rois`, `roi_signal`, `roi_windows`, `pair_windows`, `episodes` (also n_cycles, cycle_freq_hz, cycle_freq_sd_hz), `flash_cycles` (with amplitude), `pauses`, `grid_windows`, `build_metadata`, all keyed by `video_id`.
- After changing the analysis, run `python main.py --demo` and compare the detected states, flash frequencies and phases with the known truth in the dashboard (tick **Show known truth**). There is no automated test.
- The video must be H.264 `.mp4` for browsers. `make_demo_video.py` writes H.264 through the ffmpeg bundled with `imageio-ffmpeg`.
- Videos in `videos/` are tracked in git: the synthetic demo and the small real clips (Movies 1 to 4 of Rosen et al. 2015, 35 KB to 950 KB each). Keep clips small, or use Git LFS. Rights to the real clips stay with the authors and publisher; keep the attribution in the README.
- Python 3.13 (`requires-python = ">=3.13,<3.14"`). Dashboard port 5009 (CTD 5006, flow-through 5007, echogram 5008).
- Dependencies are pinned in `pyproject.toml` with `~=` (compatible patch releases). DuckDB is pinned to 2.0: a database file written by 2.0 cannot be opened by 1.x.
- Be honest in the docs about what the synthetic demo does and does not show.
