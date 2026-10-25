# Dynamic Island — original cinematic score, tonal transition revision

32.000 seconds · 48 kHz · stereo · 24-bit PCM · 100 BPM · CC0-1.0

Regenerate with `python sound_design.py`. NumPy is the only nonstandard Python
dependency. Optional ffmpeg measures integrated loudness and true peak. The
seeded synthesis is deterministic and uses no external audio material. All scene
transitions now use clean, soft harmonic glides in the low midrange. No noise
risers, rustling layers, background air, or noisy impact transients remain.
The prior score is retained in `previous_sound/`. Music and UI cue timing are
preserved; mastering uses the previous gain reference to avoid raising the beds.

| Time | Musical / sound-design cue |
| --- | --- |
| 0.8 | Tiny ignition and glass spark |
| 3.2 | Warm bowed-glass anticipation swell |
| 5.2 | Hero reveal: warm impact, harmonic swell, suspended glass bloom |
| 8.4 | Expansion impact and sparse control rhythm |
| 10.2 | Pause/play UI ticks |
| 11.2 | Soft tonal seek gesture |
| 12.4 | Ascending tonal volume gesture |
| 14.4 | Lyric morph: opening harmony and soft F harmonic glide |
| 16.2 | Lyric accent |
| 18.2 | Floating lyric shimmer and warm swell |
| 21.8 | Descending warm collapse tone and kinetic pulse |
| 23.8 | Soft rising restore gesture |
| 26.4 | Largest controlled low impact and D minor/add9 resolution |
| 30.5 | Soft glass release |
| 31.8–32.0 | Exact digital silence |

Master statistics and cue descriptions are in `soundtrack_metrics.json`.
The revised master measures -18.85 LUFS integrated / -3.06 dBTP; its AAC 256k
preview measures -18.86 LUFS / -3.07 dBTP. It is 0.52 LU quieter than the prior
score. All eleven transition windows are slightly quieter (0.06–0.56 dB RMS).
The original pad/sub/glass/pulse music stem is bit-identical before mastering.
Full old/new window measurements are in `transition_comparison.json`.
