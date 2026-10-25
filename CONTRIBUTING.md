# Contributing to Orbit

Orbit is a native Windows music surface. Changes should make an existing music
workflow clearer, calmer, or more reliable.

## Development setup

Use Windows and Python 3.11 or 3.12 x64. Follow the README setup, then run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --demo
```

For visual changes, inspect compact, lyric, expanded, and strip states. Check
pause/resume and seek behavior, rapid expand/collapse reversals, long titles,
short and long lyric lines, and the floating companion. Describe what you
actually verified in the pull request.

## Working principles

- Keep Qt widget access on the GUI thread; use queued signals for worker work.
- Keep network and Core Audio work out of paint and animation callbacks.
- Preserve timing supplied by the lyric source. Clearly distinguish exact word
  timestamps from estimates.
- Preserve unavailable/empty states rather than fabricating successful results.
- Treat the waveform as decoration unless real audio analysis is implemented.
- Add focused tests for behavioral changes. Avoid screenshot churn for unrelated
  updates.

## Pull requests

Explain the problem, resulting behavior, and relevant validation. Include a
before/after image or short recording when layout or motion changes. Keep one
coherent improvement per pull request.

Do not commit credentials, lyrics caches, personal track data, logs, reference
videos, virtual environments, or generated film exports. Original large media
belongs in Releases. Dependency notices belong in `THIRD_PARTY_NOTICES.md`.

The author has not assigned an open-source license to the application source
yet; see `COPYRIGHT.md` before planning redistribution or submitting work that
depends on a particular project license.
