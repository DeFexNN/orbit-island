# ORBIT — Dynamic Island for Windows

A 32-second original product film, rendered at **1920 × 1080, 60 fps**, with a
fully synchronized original stereo score. The application is the subject: every
island, control, lyric highlight, and floating panel is painted by the actual
unmodified PyQt6 application. The surrounding light, camera and typography are
original procedural motion graphics.

## Deliverables

- `output/Dynamic_Island_ORBIT.mp4` — H.264, YUV 4:2:0, AAC stereo, web fast-start.
- `output/Dynamic_Island_ORBIT_v2.mp4` — revised tonal-transition delivery copy.
- `output/storyboard.jpg` — twelve full-film composition checkpoints.
- `output/frames/` — full-resolution review frames.
- `audio/soundtrack.wav` — original 48 kHz stereo 24-bit master.
- `audio/sound_design.py` — seeded, reproducible musical and sound synthesis.
- `render.py` — film compositor, typography, camera, orbital lighting and export.
- `native.py` — deterministic capture harness for the real application widgets.
- `output/render_manifest.json` — dimensions, duration, frame count and file hash.
- `output/verification.json` — checks of the actual encoded deliverable.

No application source files were changed. The film is a standalone introduction;
it is not injected into startup and adds no runtime dependencies to the app.

## Rebuild on Windows

Use Python 3.10 or later, FFmpeg and FFprobe on PATH, and installed Segoe UI fonts.
The capture code uses this repository's original Python modules one directory
above `cinematic/`. The source archive preserves that layout and includes the
application snapshot needed by the capture harness.

```powershell
python -m pip install PyQt6 numpy Pillow
python cinematic/audio/sound_design.py
python cinematic/render.py --preview
python cinematic/render.py --render
python cinematic/verify.py
```

The current soundtrack revision replaces broadband rustling with low-mid tonal
glides and resonant glass accents. The original musical stem and all cue times
are preserved. `python cinematic/replace_audio.py` updates the existing film
without re-encoding the video; compressed video-packet hashes must match before
the file is replaced. In the production workspace, the first film and score
remain in `output/previous/` and `audio/previous_sound/`; historical backups are
excluded from the delivery archive. `python cinematic/package_project.py` creates the
self-contained working-project archive.

The render reads the existing application modules and uses Qt's offscreen
platform at 2× pixel density. It never instantiates the Spotify monitor or Core
Audio controller. Source capture runs at a fixed 60 Hz independently of export
speed. The renderer streams frames directly into FFmpeg, avoiding a large image
sequence. Output defaults to `cinematic/output/`; `--out path/to/film.mp4` changes
the MP4 destination.

`native.py --proof` exports representative original widget states. Application
regression checks: `python -m unittest discover -s tests -v` (73 passed during
production).

## Audiovisual storyboard

| Time | Picture | Sound |
| --- | --- | --- |
| 0–5.2 s | A real empty island emerges inside a slowly turning orbit. “A different orbit.” | Near-silence, ignition at 0.8, suspended harmony, bowed-glass anticipation at 3.2. |
| 5.2–8.4 s | Travelling type reveal; real metadata capsule springs open with the existing demo artwork. | Warm reveal impact, harmonic swell and suspended glass bloom. |
| 8.4–14.4 s | Camera carries the actual island into its expanded state. Pause/resume, seek and volume are demonstrated on native controls. | Expansion accent; frame-aligned UI details at 10.2, 11.2 and 12.4. |
| 14.4–18.2 s | The existing enhanced LRC demo enters the real compact lyric widget. | Opening harmony, soft F harmonic glide and lyric accent at 16.2. |
| 18.2–21.8 s | The actual floating lyrics companion joins the island. | Resonant glass shimmer with room for the words. |
| 21.8–26.4 s | Native strip minimization, then real restoration at 23.8. | Descending warm tone, kinetic pulse, rising harmonic restore gesture. |
| 26.4–32 s | Final brand composition; the real compact player remains the hero. A gentle complete fade. | Controlled low impact, harmonic resolution, release at 30.5, silence by 31.8. |

All cue times are exact film-frame boundaries at 60 fps. The audio master has
32.000 seconds / 1,536,000 samples per channel. See `audio/CUE_SHEET.md` and
`audio/soundtrack_metrics.json` for synthesis provenance and measured levels.

## Fidelity notes

- Metadata and artwork come from `main.demo_art` and the app's existing
  “Neon Afterglow / Island Sessions” offline demonstration.
- Lyrics use the app's existing `DEMO_LRC` and actual `LyricsTimeline`.
  The on-film footer explicitly labels the offline UI and authored LRC timing.
  The musical bed is an original film score; the demo metadata does not imply
  that Spotify is streaming a commercially released recording.
- Actual playback, seek and volume **widgets** are demonstrated offline. The
  underlying Windows integrations exist in `spotify.py` and `volume_control.py`;
  the film makes no claim to be a live Spotify session.
- Compact/expanded/strip geometry, glass, cover art, control glyphs, lyric
  highlighting and crossfades all come from the application, not mock screens.
- The waveform remains the app's decorative animated waveform. There is no
  claim of audio analysis, live desktop blur or universal exact word timing.
- Camera moves, orbit lines, title type and small interaction rings are film
  treatments. Interaction rings follow the **painted native slider thumb**.
- No call, battery, notification, AI, speed or other unimplemented capabilities
  are shown or claimed.

## Sound and rights

All pads, bass, tonal glides, reverberation, glass notes, UI details and impacts are
original procedural synthesis with no external samples or recordings. The
original sound-design source and generated score are CC0-1.0; see
`audio/LICENSE.txt`. Original film code and procedural graphics created for this
project may be used, modified and exported with your application without
attribution. Existing application source and system fonts retain their existing
rights. Font binaries are not redistributed.

The revised PCM master measured −18.85 LUFS integrated and −3.06 dBTP, with zero
clipped samples. No broadband transition noise or background air bed remains.
`verify.py` measures the final MP4 independently; its encoded audio results take
precedence for the delivered video. `audio/transition_comparison.json` records
the old/new transition-window measurements.
