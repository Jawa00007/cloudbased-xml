"""
Global ingestion concurrency guard.

asyncio is single-threaded cooperative multitasking, so a plain boolean
flag (no OS lock needed) is safe: there are no await points between the
check and the set in claim(), so no other coroutine can interleave.

The flag covers both "about to start" (claimed in endpoint before the
background task is queued) and "actively running" states, closing the
race window that would exist if the lock were acquired inside the task.
"""

from __future__ import annotations

from datetime import datetime, timezone


class IngestionGuard:
    """Tracks whether an ingestion run is pending or in progress."""

    def __init__(self) -> None:
        self._running: bool = False
        self.triggered_by: str | None = None
        self.started_at: datetime | None = None
        self.current_account: str | None = None
        self.accounts_done: int = 0
        self.accounts_total: int = 0
        self.files_done: int = 0
        self.files_total: int = 0
        self.phase: str = ""  # "scanning" | "processing" | ""

    # ── Public API ────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._running

    def claim(self, triggered_by: str) -> bool:
        """
        Atomically mark ingestion as pending/running.

        Returns True if the claim succeeded, False if already held.
        Must NOT contain any await — the caller relies on atomicity.
        """
        if self._running:
            return False
        self._running = True
        self.triggered_by = triggered_by
        self.started_at = datetime.now(timezone.utc)
        self.current_account = None
        self.accounts_done = 0
        self.accounts_total = 0
        self.files_done = 0
        self.files_total = 0
        self.phase = ""
        return True

    def release(self) -> None:
        """Clear the guard once ingestion completes or fails."""
        self._running = False
        self.triggered_by = None
        self.started_at = None
        self.current_account = None
        self.accounts_done = 0
        self.accounts_total = 0
        self.files_done = 0
        self.files_total = 0
        self.phase = ""


# Module-level singleton — shared by the scheduler and the API routes
guard = IngestionGuard()
