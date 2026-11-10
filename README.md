# Western Flyer Humboldt Squid Chromatophores (prototype)

This repository is a prototype for measuring chromatophore displays (flashing and flickering) in video of Humboldt squid (*Dosidicus gigas*), with an interactive dashboard to review the results. It follows the layout of the other Western Flyer projects (CTD, flow-through, echogram).

**Status: prototype.** The only video stored in the repository is a synthetic demo: two drawn shapes whose color follows known flashing and flickering signals, so the analysis can be checked against the truth. Four short real clips (Movies 1 to 4 of Rosen et al. 2015) are included for testing (see *Real clips used for testing* and the *Acknowledgment*). Real footage needs ROI boxes and thresholds tuned against clips that have been labeled by hand.

## Feature Summary

* **Brightness signal per region of interest (ROI):** For each ROI box (a patch of skin), the mean grayscale value is taken for every video frame. This is the same quantity Rosen et al. (2015, J Exp Biol 218:265) measured by hand to describe flashing and flickering in free-swimming Humboldt squid.
* **Automatic state detection:** A sliding window (2 s by default) is analysed with an FFT. Each window is labeled **quiet**, **flickering** (broadband activity with no single rhythm) or **flashing** (one sharp rhythm, 1.5 to 5 Hz by default; Rosen et al. report 2 to 4 Hz).
* **Rhythm measurements:** Dominant frequency and swing (peak to peak) for every window, and episodes (start, end, duration, mean flash frequency) for every state.
* **Cycle-by-cycle flash frequency and amplitude:** Inside each flashing episode, one frequency and one amplitude per flash cycle, so drift within an episode can be seen (the paper's instantaneous frequency).
* **Pauses:** Spans where the signal stops changing, with whether they followed activity and whether a flash followed (the paper's pauses before flashing).
* **Spatial synchrony (optional):** A grid of small boxes over one skin area gives a synchrony score per window (the paper's spatial standard deviation across boxes).
* **ROI tracking (optional):** A box can follow the animal through the video (optical flow, translation only). Windows in which tracking was lost are labeled **untracked** and left out of the states and the phase. Tracking is switched on per ROI in the video's `.toml`.
* **Phase between two squid:** In windows where two ROIs both flash, the phase of one against the other (0 degrees = together, 180 degrees = opposite). The log also gives the share of those windows in phase, using the paper's criterion (lag or lead under 20% of a cycle).
* **DuckDB storage:** Results go to `processed/wf_chromatophore.duckdb`, with a record of the settings and the video's SHA-256. Per-video records are replaced atomically. Tables: `videos`, `rois`, `roi_track`, `roi_signal`, `roi_windows`, `pair_windows`, `episodes`, `flash_cycles`, `pauses`, `grid_windows`, `build_metadata`. DuckDB is pinned to 2.0 in `pyproject.toml`, because the file format changes between major versions: a file written by 2.0 cannot be opened by 1.x.
* **Interactive dashboard (Panel, HoloViews, Bokeh):** The video plays at the top, with a cursor on the signal plots that follows the playback position. A second picture next to the video shows the ROI boxes (tracked ones move) at the current position. Tabs: signal and detected states, spectrogram, episodes, phase between squid, tracking, and setup (ROI preview and settings).
* **Spectrum comparison:** `compare_spectra.py` compares the brightness spectra of ROIs across clips, for example flicker against the sunlight reference of Movie 4.
* **Known truth for the demo:** The synthetic video comes with a truth file, shown in the dashboard as colored bars, so the detected states can be compared with what was drawn.

The dashboard shows the states, spectrogram, episodes, phase and tracking. The `flash_cycles`, `pauses` and `grid_windows` tables, and the cycle columns of `episodes`, are in the database but not yet drawn in the dashboard; query them with DuckDB.

## Root Directory Notes

The project root can be named anything (e.g., `westernflyer_squid_chromatophore`).

To avoid Windows permission issues, place the root folder inside your Windows user directory:
`C:\Users\<your_username>\westernflyer_squid_chromatophore`

## Python Installation Requirements

This project requires **Python 3.13** (the same version as the other Western Flyer projects).

### Windows

Install Python 3.13 from python.org (not from the Microsoft Store, which puts it in a different folder than the instructions below assume).

1. If you installed Python 3.13 from the Microsoft Store, remove it first: Windows Settings, Apps, "Python 3.13", Uninstall.
2. Download the "Windows installer (64-bit)" for Python 3.13 from https://www.python.org/downloads/windows/.
3. Run it and choose **Install Now**. Leave **"Install for all users"** unticked, so it installs for your user only. Leave the **py launcher** ticked.
4. When the installer asks to **"Add python.exe to PATH"**, select **No** (leave it unticked).
5. Python installs to `C:\Users\<your_username>\AppData\Local\Programs\Python\Python313\`.
6. Check it in Command Prompt: `py -0p` should list `Python313` under `AppData\Local\Programs\Python`.

### macOS (Homebrew)

    brew install python@3.13

### Linux (Ubuntu / Debian) using apt install

    sudo add-apt-repository ppa:deadsnakes/ppa
    sudo apt update
    sudo apt install python3.13 python3.13-venv

### Linux (Ubuntu / Debian) using pyenv

This has the advantage of not requiring root privileges, and it does not install Python 3.13 system wide.

    # Install pyenv:
    curl -fsSL https://pyenv.run | bash
    # Install Python 3.13:
    pyenv install 3.13

> The pipeline and dashboard were developed and tested on Linux with Python 3.13 (headless Chrome for the dashboard). They have not yet been run on Windows.

## Project Structure

*`processed/` and `logs/` are created automatically on first run.*

    .
    |   main.py                     orchestrator: video + ROIs -> DuckDB
    |   chroma_analysis.py          windowed FFT, states, phase, episodes, flash cycles, pauses, grid synchrony (numpy, pandas, scipy)
    |   roi_tracker.py              ROI box that follows the animal (OpenCV optical flow)
    |   chromatophore_holoviews.py  dashboard
    |   make_demo_video.py          synthetic two-squid demo video with known truth
    |   compare_spectra.py          compares ROI spectra across clips (read-only)
    |   config.defaults.toml        analysis settings and thresholds
    |   pyproject.toml
    +---videos
    |       demo_two_squid.mp4          synthetic demo video (small, kept in git)
    |       demo_two_squid.toml         its ROI boxes
    |       demo_two_squid_truth.json   what the generator drew (shown in the dashboard)
    |       jeb114157_video1..4.mp4/.toml  real test clips (Rosen et al. 2015) and their ROIs
    +---processed
    |       wf_chromatophore.duckdb
    |       <video_id>_roi_preview.png  first frame with the ROI boxes drawn on it
    |       spectra_compare.csv         written by compare_spectra.py
    +---logs
    \---scripts
        +---linux_mac   chromatophore_build.sh, chromatophore_demo.sh, chromatophore_dashboard.sh
        \---windows     chromatophore_build.bat, chromatophore_demo.bat, chromatophore_dashboard.bat

## File Descriptions

* **main.py** - Orchestrator. Reads each video with OpenCV, extracts the mean grayscale per ROI and frame, runs the analysis, and writes the DuckDB atomically with build provenance.
* **chroma_analysis.py** - The analysis itself (no video or database code): window features, state classification, phase between ROIs and the in-phase share, episodes, flash cycles (frequency and amplitude), pauses, and grid synchrony.
* **roi_tracker.py** - `BoxTracker`: follows a box with the median motion of feature points inside it (Lucas-Kanade optical flow, each point checked by tracking it backwards).
* **chromatophore_holoviews.py** - Read-only Panel dashboard.
* **make_demo_video.py** - Draws the synthetic demo video and writes the truth file. Uses the ffmpeg bundled with `imageio-ffmpeg` to write H.264, which plays in every browser.
* **compare_spectra.py** - Compares the brightness spectra of ROIs from the database across clips and writes `processed/spectra_compare.csv`.
* **config.defaults.toml** - Analysis settings. See *Settings* below.
* **videos/&lt;video_id&gt;.toml** - Per-video ROI boxes (required), optional `[tracking]` and `[grids]` tables, and optional overrides of any setting.

## Prerequisites

**Git** must be installed to download the software from GitHub (`git clone`). Download it from [git-scm.com](https://git-scm.com/downloads) and confirm with `git --version`.

Python 3.13 is required (see above). All dependencies, including OpenCV and a bundled ffmpeg, are declared in `pyproject.toml` and installed from PyPI when you run `pip install -e .` - no manual download required.

## Getting Started

    git clone https://github.com/joeacarlisle/westernflyer_squid_chromatophore.git
    cd westernflyer_squid_chromatophore

Then follow the **Prerequisites** and **Setup** sections to install Python 3.13 and the project dependencies.

## Setup: Virtual Environment and Installation

*Run from the project root directory.*

### Windows (Command Prompt)

    cd C:\Users\<your_username>\westernflyer_squid_chromatophore
    C:\Users\<your_username>\AppData\Local\Programs\Python\Python313\python.exe -m venv .venv
    .venv\Scripts\activate
    pip install -e .

### macOS / Linux

    cd westernflyer_squid_chromatophore
    python3.13 -m venv .venv
    source .venv/bin/activate
    pip install -e .

## Try the Demo

The repository includes the synthetic demo video, so the dashboard works right after installation, once the analysis has run:

* **Windows:** `scripts\windows\chromatophore_demo.bat`
* **Linux / macOS:** `./scripts/linux_mac/chromatophore_demo.sh` (run `chmod +x scripts/linux_mac/*.sh` once to make the scripts executable)

This regenerates the demo video (about 30 seconds), and analyses it. Then start the dashboard (see *Running the Dashboard*). In the sidebar, tick **Show known truth** to see the truth as colored bars under each signal and compare it with the detected bands.

The demo video has two shapes, each drawn red or white. The timeline (both squid unless noted):

| Time (s) | What the generator draws |
|---|---|
| 0 - 8 | quiet |
| 8 - 18 | flickering: many small skin patches, each with its own random activity |
| 18 - 30 | flashing at 3 Hz; squid B in step with A until 24 s, then opposite (180 degrees) |
| 30 - 34 | quiet (a pause) |
| 34 - 40 | flashing at 2 Hz, with squid B 90 degrees ahead of A |

## Analysing a Real Video

1. Put the video in `videos/` as an `.mp4` (H.264, so that browsers can play it). To convert another format: `ffmpeg -i input.mov -c:v libx264 -pix_fmt yuv420p videos/<video_id>.mp4`; an `.m4v` that is already H.264 can be remuxed without re-encoding: `ffmpeg -i input.m4v -c copy videos/<video_id>.mp4`. The video id is the file name without `.mp4`.
2. Create `videos/<video_id>.toml` with one ROI box per squid, each as `name = [x, y, width, height]` in pixels (the origin is the top-left corner of the frame):

        [rois]
        squid_1 = [320, 210, 120, 60]
        squid_2 = [610, 180, 100, 50]

   Pick a patch of skin that stays on the animal for the whole clip. Any image viewer that shows the cursor position can give you the coordinates.
3. Run the analysis: `scripts\windows\chromatophore_build.bat <video_id>` (Linux / macOS: `./scripts/linux_mac/chromatophore_build.sh <video_id>`). Without a video id every `videos/*.mp4` is analysed.
4. Open the dashboard and check the **Setup** tab: it shows the first frame with the ROI boxes drawn on it. If a box is in the wrong place, edit the `.toml` and run the analysis again.

   An open-water ROI (for example `background = [x, y, w, h]`) is a useful reference: if it oscillates like the skin ROI, the rhythm comes from the camera or the lighting, not from the animal.

   To measure spatial synchrony over an area, add a `[grids]` table, `name = [x, y, width, height, rows, columns]`. The area is split into rows x columns boxes (grids are not tracked):

        [grids]
        mantle_grid = [320, 210, 120, 60, 2, 6]

By default a box stays where you put it, so the animal must stay inside it. To make a box follow the animal, name it in a `[tracking]` table in the same `.toml`:

        [tracking]
        rois = ["squid_2"]

   Place the box on the animal in the *first* frame; the tracker moves it from there. Check the **Tracking** tab and the second picture next to the video: tracking follows only translation (the box keeps its size), it drifts when the animal turns, leaves the frame or has no texture, and it can slide onto the background. Frames where too few points could be followed are flagged as lost, and windows with more than 20% lost frames (`tracking.max_lost_frac`) are labeled *untracked*.

   Track only boxes that need it. In the Movie 2 clip the box on the camera-carrying squid's own mantle was better left fixed: tracking it moved the box over parts of the body with different brightness and reduced the detected flashing from 43% to 14% of windows.

## Running the Pipeline

    python main.py                   # every videos/*.mp4
    python main.py <video_id>        # one video (id or path)
    python main.py --demo            # regenerate the synthetic demo video first
    python compare_spectra.py [video_id:roi[:skip_s] ...]   # compare ROI spectra across clips

Or use the scripts in `scripts/` (Windows `.bat`, Linux / macOS `.sh`).

## Running the Dashboard

* **Windows:** `scripts\windows\chromatophore_dashboard.bat`
* **Linux / macOS:** `./scripts/linux_mac/chromatophore_dashboard.sh`

Or run `python -m panel serve chromatophore_holoviews.py --port 5009 --static-dirs videos=videos --show` from the project root with the virtual environment activated. The `--static-dirs` option lets the browser play the videos. The dashboard runs on port 5009 (http://localhost:5009/chromatophore_holoviews), so it can run alongside the CTD (5006), flow-through (5007) and echogram (5008) dashboards.

The video is at the top. Its position and the slider below it are linked: the dashed cursor on the signal plots follows the video while it plays, and moving the slider moves the video. Choose the video and the ROIs in the sidebar.

* **Signal and states:** Brightness of each ROI over time. Background colors are the detected states (gray quiet, amber flickering, red flashing).
* **Spectrogram:** Frequency content over time. A bright horizontal band is a steady rhythm; white dots mark windows detected as flashing.
* **Episodes:** Every run of one state, with start, end, duration and mean flash frequency, plus the time spent in each state.
* **Phase between squid:** For the first two selected ROIs, the phase of the second against the first in windows where both flash.
* **Setup:** The ROI boxes on the first frame, and all settings used for the analysis.

## Settings

`config.defaults.toml`; a video's own `.toml` can override any value by adding a table of the same name (`[analysis]`, `[classify]`, `[cycles]`, `[pauses]`, `[synchrony]`, `[tracking]`).

| Setting | Meaning |
|---|---|
| `analysis.window_s` | Length of each analysis window (2 s). The frequency resolution is about 1 / window_s. |
| `analysis.hop_s` | Step between windows (0.5 s). |
| `analysis.band_hz` | Frequencies considered (0.5 to 8 Hz). Slower drift from lighting or swimming is ignored. |
| `analysis.nfft` | Zero-padded FFT length (512), which interpolates the peak frequency. |
| `classify.quiet_p2p_max` | Below this swing (0 to 1 gray units) a window is quiet (0.04). |
| `classify.flash_freq_hz` | Frequency range counted as flashing (1.5 to 5 Hz). |
| `classify.flash_p2p_min` | Minimum swing for flashing (0.15). |
| `classify.flash_peak_conc_min` | Share of the band power that must lie within 0.5 Hz of the peak (0.55). A sharp peak means a rhythm; a flat spectrum means flickering. |
| `classify.smooth_windows` | Median filter over this many windows (3). |
| `cycles.smooth_frames`, `cycles.min_prominence_frac` | Cycle-by-cycle flash frequency: smoothing before peak finding (3 frames) and how far a peak must stand out (0.3 of the episode's swing). |
| `pauses.window_s`, `below_frac`, `min_s`, `context_s`, `follow_s` | Pause detection: rolling window (0.4 s), level below which the signal counts as paused (0.25 of the flickering level), shortest pause (0.3 s), look-back for earlier activity (1 s), look-ahead for a flash (1.5 s). Placeholders. |
| `synchrony.min_std` | A grid box must vary at least this much (std, 0 to 1 gray units, 0.01) in a window to count towards the synchrony score. |

**These thresholds are placeholders.** They were tuned on the synthetic demo, where the answer is known. They must be checked against clips that Dr. Gilly's group has labeled by hand before the numbers are used for anything scientific.

## Cycle frequency, amplitude, pauses and synchrony

These follow what Rosen et al. (2015) measured from video. All of them are written to the database; none is drawn in the dashboard yet.

* **Flash cycles** (`flash_cycles` table; `n_cycles`, `cycle_freq_hz`, `cycle_freq_sd_hz`, `cycle_amp_mean` in `episodes`): one frequency and one amplitude per flash cycle inside each flashing episode. Cycles are the peaks of the smoothed signal, refined to a fraction of a frame; the amplitude is the swing of the cycle on the unsmoothed signal (0 to 1 gray units). The window FFT gives one frequency per 2 s window; this shows drift within an episode, and a phase jump between two squid appears as a larger SD.
* **Pauses** (`pauses` table): spans where the frame-to-frame change falls well below its flickering level. `preceded_by_activity` separates a pause inside a display from a quiet stretch that was never active; `followed_by_flash` marks pauses that lead into a flash. The thresholds are placeholders.
* **Spatial synchrony** (`grid_windows` table): `sync` is the mean correlation between the boxes of a grid (about 1 when they move together) and `spatial_sd` is the spread of their brightness. On the demo it is 1.00 while flashing and about 0.25 while flickering. **On the real clips it is 0.8 to 1.0 even for the flickering clip (Movie 3)**, so on these small, low-resolution mantle areas it does not separate flashing from flickering: camera movement and exposure change all the boxes together.
* **Phase** (`pair_windows`, and a line in the log): the share of windows where both ROIs flash and are within 20% of a cycle of each other.
* **Spectra** (`compare_spectra.py`): ROI spectra with a 0.5 Hz high-pass, as in the paper. Movie 4 is the paper's sunlight reference, so its `dorsal_light` ROI can be compared with the flicker of Movie 3. That ROI is a guess and needs checking against the video. The clips are 4 to 15 s long, so the frequency resolution is only 0.06 to 0.2 Hz and the comparison is coarse.

Re-run `python main.py` to add these tables to an existing database.

## Real clips used for testing

Movies 1 to 4 of Rosen et al. (2015), grayscale Crittercam footage at 15 fps (176 x 144 pixels for Movies 1 to 3, 320 x 240 for Movie 4). Results are from this prototype with placeholder thresholds and fixed ROIs; they show that the method gives plausible output, not that it matches the paper quantitatively.

| Clip | What the paper says it shows | What the analysis gives |
|---|---|---|
| `jeb114157_video1` (15.4 s) | A pair of secondary squid interact; the camera squid approaches and they jet away. | The mantle ROI reads as flashing from about 3.4 s (about 2.8 Hz), but the `background` ROI has a spectral peak at about 2.7 Hz too. That points to camera shake or lighting, not skin color. **Do not treat this clip as flashing** until it has been checked by eye. |
| `jeb114157_video2` (5.6 s) | Flashing. | Mantle: flickering to about 2.9 s, then flashing (2.5 Hz by window FFT, 2.3 Hz by cycle, only 3 cycles). `squid2` is tracked but lost on 27% of frames. |
| `jeb114157_video3` (4.5 s) | Flickering. | Mantle: flickering in every window. |
| `jeb114157_video4` (10.6 s) | Sunlight reflections on the dorsal surface, before release (a light reference, not a display). | No rhythm. The first frames are black. The `dorsal_light` ROI is a guess. |

The `.mp4` files of Movies 1 and 4 were remuxed from `.m4v` without re-encoding. The clips and their `.toml` files are tracked in git; they are small. If you add large footage, use Git LFS.

## Validation

The synthetic demo has a known truth (`videos/demo_two_squid_truth.json`), which the dashboard draws under each signal when you tick **Show known truth**. During development the analysis was compared with it and gave: every clearly-inside window labeled correctly, flash frequency within 0.02 Hz of the true 3.0 and 2.0 Hz, phase between the squid within a few degrees of the true 0, 180 and 90 degrees, cycle frequency within 0.1 Hz, the ratio of cycle amplitudes within 10%, grid synchrony above 0.9 while flashing and about 0.25 while flickering, and a synthetic pause found. There is no automated test, so after changing the analysis or the settings, re-run `python main.py --demo` and compare with the truth in the dashboard.

This shows that the method works on clean synthetic signals with a good ROI. It does not show how it will perform on real footage, which has moving animals, changing light, particles in the water, and displays that are messier than a sine wave. The thresholds were also tuned on this same video, so the score is not an independent test.

## Known limitations

* ROI boxes are fixed unless tracking is switched on for them. Tracking follows translation only (no rotation or scale), is a prototype, and drifts when an animal turns or leaves the frame; it can slide onto the background, so the *untracked* label is a warning, not a guarantee. If a fixed box loses the animal, the signal is wrong.
* State changes are only resolved to about one window (2 s). Short transitions can appear as brief "flickering" episodes between a flash and a quiet period.
* Only grayscale brightness is used. Color (red against white) is not separated from overall brightness, and lighting changes (for example from the ship or a rising animal) are not corrected.
* Flashing is detected as one dominant rhythm in the brightness of the box. Spatial patterns, such as traveling waves of flickering across the body, are not analysed.
* One frequency per window, so a flash that changes rate faster than a window is averaged. The cycle-by-cycle frequency is not limited this way, but at 15 fps a 3 Hz cycle is only 5 frames long, so single cycles are coarse.
* The real clips are 4 to 15 s long. That is too short for the paper's 30 s spectra, for statistics, or for judging pause detection.
* Spatial synchrony does not separate flashing from flickering on the real clips (see above), and grids are not tracked.
* Camera movement and the animal's own swimming change the brightness of every box. A background ROI shows whether a rhythm is from the skin (Movie 1 is the open case).
* The first frames of Movie 4 are black, which inflates the first windows; there is no setting yet to skip the start of a clip.
* The dashboard does not yet show the cycle, pause or grid results.

## Next steps (suggested)

1. Ask Dr. Gilly which measurements matter (flash frequency and amplitude, phase between squid, time spent flashing, triggers) and obtain a few clips with hand-labeled flashing and flickering periods.
2. Tune and test the thresholds on those clips, and report how often the automatic labels agree with the hand labels.
3. Replace the optical-flow tracker with detection and tracking of the animal itself (a detector such as YOLO with a tracker, or SAM2 segmentation; this needs labeled frames of Humboldt squid) so that the ROI follows the animal through turns and occlusions.
4. Extend the spatial analysis across the body (a per-pixel map, or grids on a stable part of the animal) to describe flicker waves, and remove camera motion before computing synchrony.
5. Link each clip to depth, temperature and oxygen from the CTD project, if the footage is time-stamped.
6. Show the cycle, pause and grid results in the dashboard, and add a setting to skip the start of a clip.
7. Add per-clip annotations (other squid visible, physical contact) so that the paper's contact and social-context comparisons can be tested when there are enough episodes.

## Reference

Rosen H, Gilly W, Bell L, Abernathy K, Marshall G (2015). Chromogenic behaviors of the Humboldt squid (*Dosidicus gigas*) studied in situ with an animal-borne video package. Journal of Experimental Biology 218: 265-275. https://doi.org/10.1242/jeb.114157

## Acknowledgment

This project is built on the work of Rosen, Gilly, Bell, Abernathy and Marshall (2015), cited above. The idea of measuring skin brightness in a box on the animal, the definitions of flashing and flickering, the 2 to 4 Hz flash range, the cycle-by-cycle frequency, the pauses, and the grid of small boxes for spatial synchrony all come from their paper. The four real clips used for testing (`jeb114157_video1` to `jeb114157_video4`) are the paper's supplementary Movies 1 to 4, recorded with National Geographic's Crittercam on Humboldt squid in the Gulf of California. The footage belongs to the authors and the publisher and is included here only to test the method; the rights stay with them. This is an independent reimplementation; any errors in it are not theirs.

## Dashboard stops responding

The dashboard stops responding after a period of inactivity and needs to be refreshed (press F5 or reload the page). This is the browser's tab-sleeping setting, on Windows and on Mac: Edge puts an inactive tab to sleep (15 minutes on the Windows machine this was tested on; the time is configurable), and Chrome's Memory Saver can do the same. Either one cuts the tab's link to the dashboard server. In Edge, add the dashboard address to Settings > System and performance > Performance > "Always keep these sites active" (for example `localhost`), or turn off "Automatically put tabs to sleep". In Chrome, use Settings > Performance > "Always keep these sites active", or turn off Memory Saver.

## Contact

Joe Carlisle - joeacarlisle@gmail.com
