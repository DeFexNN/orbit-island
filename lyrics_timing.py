"""Small, dependency-free LRC parsing and lyric timeline helpers.

Enhanced LRC word timestamps are preserved as supplied. Plain LRC word spans
are estimates, weighted by token length, and are explicitly marked as such.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import re
from typing import Iterable


_LINE_STAMP = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_WORD_STAMP = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")
_META = re.compile(r"\[[A-Za-z][A-Za-z0-9_-]*\s*:[^\]]*\]")
_OFFSET = re.compile(r"\[offset\s*:\s*([+-]?\d+)\s*\]", re.IGNORECASE)
_TOKEN = re.compile(r"\S+")
_MAX_LINE_MS = 8000


def _stamp_ms(minutes: str, seconds: str, fraction: str | None) -> int:
    # LRC fractions conventionally use centiseconds; tolerate milliseconds too.
    frac = fraction or "0"
    scale = 100 if len(frac) == 1 else (10 if len(frac) == 2 else 1)
    return (int(minutes) * 60 + int(seconds)) * 1000 + int(frac) * scale


@dataclass(frozen=True)
class LyricWord:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class LyricLine:
    start_ms: int
    end_ms: int
    text: str
    words: tuple[LyricWord, ...] = ()
    word_timed: bool = False


@dataclass(frozen=True)
class LyricsFrame:
    line_index: int = -1
    text: str = ""
    next_text: str = ""
    line_progress: float = 0.0
    word_index: int = -1
    word_progress: float = 0.0
    words: tuple[LyricWord, ...] = ()
    word_timed: bool = False
    position_ms: float | None = None
    line_start_ms: int | None = None
    line_end_ms: int | None = None


class LyricsTimeline:
    """Immutable, precomputed lyric rows that can be queried at any position."""

    __slots__ = ("_lines", "_starts")

    def __init__(self, lines: Iterable[LyricLine] = ()) -> None:
        self._lines = tuple(lines)
        self._starts = tuple(line.start_ms for line in self._lines)

    @property
    def lines(self) -> tuple[LyricLine, ...]:
        return self._lines

    @classmethod
    def from_lrc(cls, text: str, duration_ms: int = 0) -> "LyricsTimeline":
        offset_ms = 0
        for match in _OFFSET.finditer(text):
            offset_ms = int(match.group(1))

        entries: list[tuple[int, str, tuple[tuple[int, str], ...] | None]] = []
        for raw_line in text.splitlines():
            stamps = list(_LINE_STAMP.finditer(raw_line))
            if not stamps:
                continue
            body = raw_line[stamps[-1].end():]
            # Strip metadata headers that are not timestamps; preserve ordinary text.
            body = _META.sub("", body).strip()
            word_matches = list(_WORD_STAMP.finditer(body))
            enhanced: tuple[tuple[int, str], ...] | None = None
            if word_matches:
                parts: list[tuple[int, str]] = []
                prefix = body[:word_matches[0].start()]
                if prefix.strip():
                    first_ms = _stamp_ms(*word_matches[0].groups())
                    parts.append((first_ms + offset_ms, prefix))
                for idx, mark in enumerate(word_matches):
                    stop = word_matches[idx + 1].start() if idx + 1 < len(word_matches) else len(body)
                    value = body[mark.end():stop]
                    parts.append((_stamp_ms(*mark.groups()) + offset_ms, value))
                enhanced = tuple(parts)
                body = "".join(part for _, part in parts).strip()
            first_line_stamp = _stamp_ms(*stamps[0].groups()) + offset_ms
            for stamp in stamps:
                start = _stamp_ms(*stamp.groups()) + offset_ms
                if start < 0:
                    start = 0
                if duration_ms > 0 and start >= duration_ms:
                    continue
                shifted = enhanced
                if enhanced is not None:
                    shift = start - first_line_stamp
                    shifted = tuple((word_start + shift, segment) for word_start, segment in enhanced)
                entries.append((start, body, shifted))

        # Duplicate timestamps are common in malformed files; keep the last
        # nonempty version, while retaining blank rows as explicit clears.
        entries.sort(key=lambda item: item[0])
        deduped: list[tuple[int, str, tuple[tuple[int, str], ...] | None]] = []
        for entry in entries:
            if deduped and deduped[-1][0] == entry[0]:
                if entry[1] or not deduped[-1][1]:
                    deduped[-1] = entry
            else:
                deduped.append(entry)

        lines: list[LyricLine] = []
        for idx, (start, line_text, enhanced) in enumerate(deduped):
            next_start = deduped[idx + 1][0] if idx + 1 < len(deduped) else 0
            if idx + 1 < len(deduped):
                end = next_start
            elif duration_ms > 0:
                end = duration_ms
            else:
                end = start + _MAX_LINE_MS
            if duration_ms > 0:
                end = min(end, duration_ms)
            if end <= start:
                continue
            if not line_text:
                lines.append(LyricLine(start, end, ""))
                continue

            if enhanced:
                words = _enhanced_words(enhanced, start, end)
                lines.append(LyricLine(start, end, line_text, words, True))
            else:
                words = _estimated_words(line_text, start, end)
                lines.append(LyricLine(start, end, line_text, words, False))
        return cls(lines)

    @classmethod
    def from_plain(cls, text: str) -> "LyricsTimeline":
        """Return no timed rows for unsynchronized text."""
        return cls()

    def frame_at(self, position_ms: float) -> LyricsFrame:
        if not self._lines:
            return LyricsFrame(position_ms=position_ms)
        if position_ms < self._lines[0].start_ms:
            return LyricsFrame(next_text=self._upcoming_text(0), position_ms=position_ms)
        idx = bisect_right(self._starts, position_ms) - 1
        if idx < 0:
            return LyricsFrame(position_ms=position_ms)
        line = self._lines[idx]
        if not line.text or position_ms >= line.end_ms:
            return LyricsFrame(next_text=self._upcoming_text(idx + 1), position_ms=position_ms,
                               line_start_ms=line.start_ms, line_end_ms=line.end_ms)
        duration = max(1, line.end_ms - line.start_ms)
        progress = min(1.0, max(0.0, (position_ms - line.start_ms) / duration))
        next_text = ""
        if idx + 1 < len(self._lines):
            candidate = self._lines[idx + 1]
            if candidate.start_ms <= line.end_ms and candidate.text:
                next_text = candidate.text

        word_index = -1
        word_progress = 0.0
        for word_idx, word in enumerate(line.words):
            if word.start_ms <= position_ms < word.end_ms:
                word_index = word_idx
                word_progress = min(1.0, max(0.0, (position_ms - word.start_ms) / max(1, word.end_ms - word.start_ms)))
                break
        return LyricsFrame(idx, line.text, next_text, progress, word_index,
                           word_progress, line.words, line.word_timed, position_ms,
                           line.start_ms, line.end_ms)

    def _upcoming_text(self, start_index: int) -> str:
        for line in self._lines[start_index:]:
            if line.text:
                return line.text
        return ""


def _estimated_words(text: str, start: int, end: int) -> tuple[LyricWord, ...]:
    matches = list(_TOKEN.finditer(text))
    if not matches:
        return ()
    weights = [max(1, len(match.group())) for match in matches]
    total = sum(weights)
    span = max(0, end - start)
    words: list[LyricWord] = []
    cursor = start
    consumed = 0
    for i, (match, weight) in enumerate(zip(matches, weights)):
        consumed += weight
        stop = end if i == len(matches) - 1 else start + round(span * consumed / total)
        words.append(LyricWord(match.group(), cursor, max(cursor, stop)))
        cursor = stop
    return tuple(words)


def _enhanced_words(parts: tuple[tuple[int, str], ...], start: int, end: int) -> tuple[LyricWord, ...]:
    words: list[LyricWord] = []
    for idx, (word_start, segment) in enumerate(parts):
        segment_start = max(start, word_start)
        segment_end = min(end, parts[idx + 1][0] if idx + 1 < len(parts) else end)
        tokens = list(_TOKEN.finditer(segment))
        if not tokens:
            continue
        weights = [max(1, len(token.group())) for token in tokens]
        total = sum(weights)
        cursor = segment_start
        consumed = 0
        for token_idx, (token, weight) in enumerate(zip(tokens, weights)):
            consumed += weight
            stop = segment_end if token_idx == len(tokens) - 1 else segment_start + round((segment_end - segment_start) * consumed / total)
            words.append(LyricWord(token.group(), cursor, max(cursor, stop)))
            cursor = stop
    return tuple(words)
