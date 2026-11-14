"""How long a run still needs, from how fast its simulated time has been advancing lately."""

from __future__ import annotations

import time
from collections import deque


class Pace:
    """The pace of a run: simulated time (or iterations) against the clock over the last ``window`` seconds.

    The recent pace counts, not the average since the start: runs often begin slowly and settle.
    """

    def __init__(self, window: float = 120.0, warm_up: float = 5.0) -> None:
        self.window = window  # seconds of clock the pace is taken over
        self.warm_up = warm_up  # no estimate before this much clock has passed
        self._samples: deque[tuple[float, float]] = deque()

    def reset(self) -> None:
        self._samples.clear()

    def add(self, done: float, now: float | None = None) -> None:
        """Note how far the run is (in its own time) at this moment."""
        now = time.monotonic() if now is None else now
        if self._samples and done < self._samples[-1][1]:  # started again from the beginning
            self._samples.clear()
        if self._samples and done == self._samples[-1][1]:
            return  # nothing new; keep the time it was first reached
        self._samples.append((now, done))
        while len(self._samples) > 2 and now - self._samples[1][0] > self.window:
            self._samples.popleft()

    def seconds_left(self, total: float) -> float | None:
        """Clock seconds until ``total`` is reached at the recent pace, or None while there is no pace yet."""
        if len(self._samples) < 2:
            return None
        (t0, d0), (t1, d1) = self._samples[0], self._samples[-1]
        if t1 - t0 < self.warm_up or d1 <= d0:
            return None
        return max(0.0, (total - d1) * (t1 - t0) / (d1 - d0))


def in_words(seconds: float) -> str:
    """A duration still to come, rounded the way people say it: "about 12 min"."""
    if seconds < 45:
        return "less than a minute"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"about {max(1, minutes)} min"
    hours, rest = divmod(minutes, 60)
    return f"about {hours} h {rest} min" if rest else f"about {hours} h"


def took(seconds: float) -> str:
    """A duration that has passed: "40 s", "3 min 20 s", "1 h 05 min"."""
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds} s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {rest:02d} s" if rest else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"
