"""The set-up as it was after each change, to step back and forth through: undo and redo."""

from __future__ import annotations


class History:
    """Snapshots of the project (as text), the current one and those before and after it.

    A snapshot is taken when the project is saved, which happens shortly after each change, so a burst of
    changes (dragging a handle, typing in several fields at once) is one step.
    """

    def __init__(self, limit: int = 200) -> None:
        self.limit = limit
        self._before: list[str] = []
        self._after: list[str] = []
        self.current: str | None = None

    def reset(self, snapshot: str | None) -> None:
        """Start again from this state, with nothing to undo or redo (a project was opened or closed)."""
        self._before.clear()
        self._after.clear()
        self.current = snapshot

    def record(self, snapshot: str) -> bool:
        """Note the state after a change; True if it differs from the last one noted."""
        if self.current is None:
            self.current = snapshot
            return False
        if snapshot == self.current:
            return False
        self._before.append(self.current)
        del self._before[: max(0, len(self._before) - self.limit)]
        self._after.clear()
        self.current = snapshot
        return True

    def step_back(self) -> str | None:
        """The state before the current one (undo), or None if there is none."""
        if not self._before:
            return None
        self._after.append(self.current)
        self.current = self._before.pop()
        return self.current

    def step_forward(self) -> str | None:
        """The state that was undone last (redo), or None if there is none."""
        if not self._after:
            return None
        self._before.append(self.current)
        self.current = self._after.pop()
        return self.current

    @property
    def can_undo(self) -> bool:
        return bool(self._before)

    @property
    def can_redo(self) -> bool:
        return bool(self._after)
