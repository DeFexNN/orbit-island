<div align="center">

<img src="docs/media/hero.png" alt="Orbit — Dynamic Island for Windows, with the actual music capsule and its orbital light" width="100%">

# ORBIT

**Your music. A little closer.**

A native Windows music island with fluid motion, player controls, and lyrics that stay within reach.

[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-8e7cbb?style=flat-square)](#quick-start)
[![Python](https://img.shields.io/badge/Python-3.11%20%2F%203.12-c0abe7?style=flat-square)](#quick-start)
[![Tests](https://github.com/DeFexNN/orbit-island/actions/workflows/tests.yml/badge.svg)](https://github.com/DeFexNN/orbit-island/actions/workflows/tests.yml)
[![MIT](https://img.shields.io/badge/License-MIT-c0abe7?style=flat-square)](LICENSE)

[**Watch the film ↗**](https://github.com/DeFexNN/orbit-island/releases/latest/download/ORBIT-Cinematic-Intro.mp4)
&nbsp; · &nbsp; [Get started](#quick-start)
&nbsp; · &nbsp; [Releases](https://github.com/DeFexNN/orbit-island/releases)
&nbsp; · &nbsp; [Українською](docs/README.uk.md)

</div>

---

Orbit brings your current track to a small, always-on-top capsule. Open it for
transport, seeking, and player volume. Follow lyrics inside the island or in a
separate floating companion. Tuck the island into a thin strip when you want
more room.

Built with **Python, PyQt6, Windows media sessions, and Core Audio**. Custom
painted surfaces, interruptible springs, and shared lyric timing keep the
interface cohesive.

## See it in motion

[![Orbit in motion — real compact and expanded controls, lyrics, and floating companion](docs/media/teaser.gif)](https://github.com/DeFexNN/orbit-island/releases/latest/download/ORBIT-Cinematic-Intro.mp4)

**[Play the complete 32-second film with sound →](https://github.com/DeFexNN/orbit-island/releases/latest/download/ORBIT-Cinematic-Intro.mp4)**

The film uses real app widgets with authored offline demo metadata and LRC.
Its original score includes soft tonal transitions, UI accents, and a cinematic
resolution. The rendering and sound-design sources live in [`cinematic/`](cinematic/).

## Small surface. Useful depth.

| | What is implemented |
| --- | --- |
| **Now playing** | Track title, artist, cover artwork, and an animated waveform in a compact capsule. |
| **Playback** | Play/pause, previous/next, progress, and seeking through Windows SMTC. Spotify sessions get priority. |
| **Player volume** | Volume and mute for the matched player's Core Audio sessions, including active output devices. |
| **Lyrics** | LRCLIB lookup, local `.lrc` / `.txt` import, compact highlights, and a draggable floating companion. |
| **Motion** | Interruptible spring geometry, layered fades, cover transitions, and responsive control details. |
| **Make space** | Drag upward to minimize into a strip; click the strip to restore. |

![Actual native Orbit states: compact music capsule, expanded transport with volume, and floating lyrics](docs/media/interface.png)

## Quick start

Use **Windows 10 or 11**, **64-bit Python 3.11 or 3.12**, and PowerShell. Python
3.12 is the recommended setup. The published `winsdk` wheels determine this
installation range; newer Python versions require a separate compatible build.

```powershell
git clone https://github.com/DeFexNN/orbit-island.git
cd orbit-island

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

For Python 3.11, replace `py -3.12` with `py -3.11`. After setup, `run.bat`
automatically uses `.venv` when present and works from another working directory.

Start playback in Spotify Desktop or a player that exposes a Windows media
session. Orbit reads the session without Spotify API keys or a Spotify developer
application.

Try the interface with authored demo content:

```powershell
.\.venv\Scripts\python.exe main.py --demo
```

Demo transport, position, lyrics, and volume are simulated. Clicking the demo
cover still opens Spotify.

## A few small gestures

| Action | Result |
| --- | --- |
| Click the capsule background | Expand or collapse the player. |
| Click the cover | Focus or launch Spotify Desktop. |
| Use transport and progress controls | Control the selected media session. |
| Use volume or mute | Change the matched player's volume. |
| Click **Лірика ↗** | Show the floating lyric companion. |
| Right-click the island | Open lyric actions, including local file import. |
| Drag the island upward | Tuck it into the strip. |
| Click the strip | Restore the island. |

The current UI labels are Ukrainian. This source release has no tray icon or
in-app Quit command; stop its Python process from the launch terminal or Task
Manager when finished.

## Honest details

- Playback commands depend on the active player's SMTC support. Volume can be
  unavailable when a packaged player cannot be matched to its audio process.
- Enhanced LRC preserves supplied word timestamps. Ordinary line-timed LRC uses
  approximate word highlights. Lyric availability depends on the source.
- The waveform is decorative; it does not analyze audio. The dark glass is
  custom painting rather than live desktop blur.
- This is a source release. No installer or prebuilt `.exe` is included.

## Data and privacy

Playback metadata comes from Windows media sessions. Automatic lyric lookup sends
the current track's title, artist, album, and duration to
[LRCLIB](https://lrclib.net). Lyric results are cached locally in
`%LOCALAPPDATA%\DynamicIslandWin\lyrics_cache.json`.

There is no account system or analytics pipeline in this application. Imported
lyric files are read locally. See [third-party notices](THIRD_PARTY_NOTICES.md)
for dependencies and service references.

## Built to inspect

```text
main.py                  Application wiring and offline demo
island.py                Native capsule, controls, spring geometry, gestures
spotify.py               Windows media-session worker and commands
volume_control.py        Per-player Core Audio worker
lyrics_provider.py       Asynchronous LRCLIB lookup and cache
lyrics_timing.py         LRC parsing and timeline evaluation
lyrics_widgets.py        Native lyric ink and highlight rendering
floating_lyrics.py       Floating lyric companion
playback_clock.py        Shared monotonic playback clock
tests/                   Motion, lyrics, controls, and integration contracts
cinematic/               Original film compositor and sound-design sources
```

Run the regression suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For the film, install [`cinematic/requirements-cinematic.txt`](cinematic/requirements-cinematic.txt)
and FFmpeg/FFprobe, then follow the [production notes](cinematic/README.md).

Read [Contributing](CONTRIBUTING.md), report a [bug](https://github.com/DeFexNN/orbit-island/issues/new?template=bug_report.yml),
or suggest an [improvement](https://github.com/DeFexNN/orbit-island/issues/new?template=feature_request.yml).

---

<div align="center">

**Small by design.**

Created by [DeFexNN](https://github.com/DeFexNN). Independent project; not affiliated with Apple or Spotify.

Original source is [MIT licensed](LICENSE); see [COPYRIGHT.md](COPYRIGHT.md) for scope.
The original cinematic sound-design source and score are [CC0](cinematic/audio/LICENSE.txt).

</div>
