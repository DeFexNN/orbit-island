"""Audio-clock-driven word holds and continuous lyric spotlight glides.

The focus stays at a sung word's optical center, then glides to the next
word after its cue begins. Every coordinate is a pure function of media
position, so pause and seeking need no reset or wall-clock animation state.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from functools import lru_cache

from lyrics_timing import LyricsFrame


_MAX_GLIDE_MS = 320.0
_CUE_GLIDE_FRACTION = 0.8
_LAUNCH_MS = 20.0


def focus_x_at(frame: LyricsFrame, word_bounds: Sequence[tuple[float, float]]) -> float | None:
    """Return the held/gliding word center at ``frame.position_ms``.

    The center and adaptive footprint share one curve. Moving the focus
    through glyph edges would make a word-sized capsule crawl off its word;
    moving between word centers keeps the luminous background aligned.
    """
    span = focus_span_at(frame, word_bounds, padding_px=0.0)
    return None if span is None else (span[0] + span[1]) * 0.5


def focus_span_at(
    frame: LyricsFrame,
    word_bounds: Sequence[tuple[float, float]],
    padding_px: float = 4.0,
) -> tuple[float, float] | None:
    """Return the word-sized ``(left, right)`` spotlight footprint.

    Incoming cues launch a short glide; the remainder of each cue holds
    that word's measured glyph bounds. Both edges use the same smooth blend,
    making center and width continuous across spaces and word boundaries.
    Real timing gaps hold the previous word until the next cue starts.
    """
    words = frame.words
    position = frame.position_ms
    if frame.line_index < 0 or position is None or not words or len(word_bounds) != len(words):
        return None
    bounds = tuple((float(left), float(right)) for left, right in word_bounds)
    curve = _word_curve(tuple(words), bounds, frame.line_start_ms, frame.line_end_ms)
    if not curve:
        return None
    starts, ends, lefts, rights = curve
    index = max(0, bisect_right(starts, float(position)) - 1)
    left, right = lefts[index], rights[index]
    if index > 0 and position < ends[index]:
        blend = _glide_progress(float(position) - starts[index], ends[index] - starts[index])
        left = lefts[index - 1] + (left - lefts[index - 1]) * blend
        right = rights[index - 1] + (right - rights[index - 1]) * blend
    padding = max(0.0, float(padding_px))
    return left - padding, right + padding


@lru_cache(maxsize=128)
def _word_curve(words, bounds, line_start, line_end):
    """Cache cue windows, not individual audio-frame samples."""
    cues = []
    prior_time = float("-inf")
    prior_right = float("-inf")
    single_zero_duration = (
        len(words) == 1
        and words[0].end_ms <= words[0].start_ms
        and line_start is not None and line_end is not None and line_end > line_start
    )
    for word, (left, right) in zip(words, bounds):
        left, right = min(left, right), max(left, right)
        left = max(left, prior_right)
        right = max(left, right)
        start = float(line_start) if single_zero_duration else float(word.start_ms)
        end = float(line_end) if single_zero_duration else float(word.end_ms)
        start = max(prior_time, start)
        end = max(start, end)
        prior_time, prior_right = end, right
        # Instantaneous enhanced-LRC words cannot have a visible hold. Keep
        # the next timed cue rather than injecting a zero-time teleport.
        if end > start:
            cues.append((start, end, left, right))
    if not cues:
        # A malformed all-zero line still has a stable, meaningful focus.
        left, right = bounds[0]
        start = float(words[0].start_ms)
        return (start,), (start,), (min(left, right),), (max(left, right),)

    starts, glide_ends, lefts, rights = [], [], [], []
    for index, (start, end, left, right) in enumerate(cues):
        # Finishing before the next cue leaves an explicit word-center hold,
        # including short rap cues, and prevents overlapping transitions.
        available = end - start
        if index + 1 < len(cues):
            available = min(available, cues[index + 1][0] - start)
        glide_ms = min(_MAX_GLIDE_MS, max(0.0, available) * _CUE_GLIDE_FRACTION)
        starts.append(start)
        glide_ends.append(start + glide_ms if index else start)
        lefts.append(left)
        rights.append(right)
    return tuple(starts), tuple(glide_ends), tuple(lefts), tuple(rights)


def _glide_progress(elapsed_ms: float, duration_ms: float) -> float:
    """Fast deceleration with a short, continuous zero-velocity launch.

    The reference moves decisively toward the incoming word then settles
    into its hold. A brief quadratic time ramp avoids the velocity jump of
    plain ease-out cubic while retaining that front-loaded movement.
    """
    if duration_ms <= 0.0 or elapsed_ms >= duration_ms:
        return 1.0
    if elapsed_ms <= 0.0:
        return 0.0
    launch = min(_LAUNCH_MS, duration_ms * 0.2)
    if elapsed_ms < launch:
        travel_time = elapsed_ms * elapsed_ms / (2.0 * launch)
    else:
        travel_time = elapsed_ms - launch * 0.5
    u = travel_time / (duration_ms - launch * 0.5)
    return 1.0 - (1.0 - u) ** 3
