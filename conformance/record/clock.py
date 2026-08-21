"""Deterministic clock, UUID, and sleep control for record mode (design D1.4).

Record mode freezes the process clock at :data:`RECORD_EPOCH` via freezegun,
replaces ``uuid.uuid4`` with a counter-seeded deterministic stream (reset per
test), and patches ``time.sleep`` to a VIRTUAL sleep that advances the frozen
clock instead of waiting. The virtual sleep is what makes wall-clock-deadline
loops (e.g. the lookup-table poll loop at ``workspace.py`` ``_poll_lookup_upload``)
terminate after a machine-independent, deterministic number of iterations:
freezegun freezes ``time.monotonic``/``time.perf_counter`` too, and
``tick(d)`` advances them (verified empirically against freezegun 1.5.5).

Both replay runners (design D7/D12) install the same shims so recorded and
replayed behavior match bit-for-bit.
"""

from __future__ import annotations

import operator
import time
import uuid
from collections.abc import Callable
from typing import SupportsIndex

from freezegun import freeze_time
from freezegun.api import FrozenDateTimeFactory

RECORD_EPOCH = "2026-01-15T12:00:00Z"
"""The frozen instant for every record run (design D1.4); stored in the manifest."""

_UUID_TEMPLATE = "00000000-0000-4000-8000-{seq:012d}"
"""Template for the deterministic UUID stream (design D1.4)."""


class DeterministicUuidStream:
    """Counter-seeded replacement for ``uuid.uuid4`` (design D1.4).

    Produces ``00000000-0000-4000-8000-{seq:012d}`` UUIDs in call order.
    The counter is reset per test so vector content never depends on how
    many earlier tests consumed UUIDs.

    Example:
        ```python
        stream = DeterministicUuidStream()
        str(stream())
        # "00000000-0000-4000-8000-000000000000"
        ```
    """

    def __init__(self) -> None:
        """Initialize the stream with the counter at zero."""
        self._counter = 0

    def __call__(self) -> uuid.UUID:
        """Return the next deterministic UUID and advance the counter.

        Returns:
            The next UUID in the ``00000000-0000-4000-8000-{seq:012d}`` stream.
        """
        value = uuid.UUID(_UUID_TEMPLATE.format(seq=self._counter))
        self._counter += 1
        return value

    def reset(self) -> None:
        """Reset the counter to zero (called at the start of every test)."""
        self._counter = 0


class RecordClock:
    """Session-scoped frozen clock + deterministic UUID + virtual sleep.

    ``start()`` installs three patches; ``stop()`` restores all of them:

    1. ``freezegun.freeze_time(epoch)`` — freezes ``time.time``,
       ``time.monotonic``, ``time.perf_counter``, ``datetime.now``,
       ``date.today``.
    2. ``time.sleep`` → virtual sleep: advances the frozen clock by the
       requested duration via ``factory.tick`` and returns immediately.
    3. ``uuid.uuid4`` → :class:`DeterministicUuidStream`.

    Example:
        ```python
        clock = RecordClock()
        clock.start()
        try:
            before = time.monotonic()
            time.sleep(1.5)
            time.monotonic() - before
            # 1.5 (no real waiting happened)
        finally:
            clock.stop()
        ```
    """

    def __init__(self, epoch: str = RECORD_EPOCH) -> None:
        """Initialize an inactive clock.

        Args:
            epoch: ISO-8601 instant to freeze at; defaults to
                :data:`RECORD_EPOCH`.
        """
        self.epoch = epoch
        self.uuid_stream = DeterministicUuidStream()
        self._freezer: object | None = None
        self._factory: FrozenDateTimeFactory | None = None
        self._original_sleep: Callable[[float | SupportsIndex], None] | None = None
        self._original_uuid4: Callable[[], uuid.UUID] | None = None

    @property
    def active(self) -> bool:
        """Return whether the clock patches are currently installed.

        Returns:
            True between ``start()`` and ``stop()``.
        """
        return self._factory is not None

    def start(self) -> None:
        """Install the freeze, virtual sleep, and deterministic UUID patches.

        Raises:
            RuntimeError: If the clock is already started, or freezegun did
                not hand back a :class:`FrozenDateTimeFactory` (the only
                factory type whose ``tick`` semantics design D1.4 relies on).
        """
        if self.active:
            raise RuntimeError("RecordClock is already started")
        freezer = freeze_time(self.epoch)
        factory = freezer.start()
        if not isinstance(factory, FrozenDateTimeFactory):
            freezer.stop()
            raise RuntimeError(
                f"freeze_time returned {type(factory).__name__}; record mode "
                "requires a FrozenDateTimeFactory (design D1.4)"
            )
        self._freezer = freezer
        self._factory = factory
        self._original_sleep = time.sleep
        time.sleep = self._virtual_sleep
        self._original_uuid4 = uuid.uuid4
        uuid.uuid4 = self.uuid_stream.__call__

    def stop(self) -> None:
        """Restore ``time.sleep``, ``uuid.uuid4``, and the real clock.

        Safe to call when not started (no-op).
        """
        if self._original_sleep is not None:
            time.sleep = self._original_sleep
            self._original_sleep = None
        if self._original_uuid4 is not None:
            uuid.uuid4 = self._original_uuid4
            self._original_uuid4 = None
        if self._freezer is not None:
            # freezegun's private API surface is stable enough here: the
            # object returned by freeze_time always has stop().
            self._freezer.stop()  # type: ignore[attr-defined]
            self._freezer = None
        self._factory = None

    def reset_test_state(self) -> None:
        """Reset per-test determinism state (design D1.4).

        Resets the UUID counter AND moves the frozen clock back to the
        epoch. Without the clock reset, virtual-sleep ticks accumulate
        ACROSS tests — and because retry backoff includes ``random``
        jitter, the accumulated offset is nondeterministic, leaking
        run-varying sub-second fractions into every later
        ``datetime.now()``-derived payload (caught by the PR-5 double-run
        byte-diff on ``OAuthTokens.expires_at``). Per-test epoch reset
        also makes each vector independent of how much earlier tests
        slept.
        """
        self.uuid_stream.reset()
        if self._factory is not None:
            self._factory.move_to(self.epoch)

    def _virtual_sleep(self, seconds: float | SupportsIndex) -> None:
        """Advance the frozen clock by ``seconds`` instead of waiting.

        Mirrors real ``time.sleep`` input validation so hostile inputs fail
        identically (a negative Retry-After must still raise, see
        test_api_client.py negative Retry-After suite).

        Args:
            seconds: Requested sleep duration in seconds.

        Raises:
            ValueError: If ``seconds`` is negative (as real ``time.sleep``).
            RuntimeError: If called while the clock is not started.
        """
        duration = (
            float(seconds)
            if isinstance(seconds, int | float)
            else float(operator.index(seconds))
        )
        if duration < 0:
            raise ValueError("sleep length must be non-negative")
        if self._factory is None:
            raise RuntimeError("virtual sleep called on a stopped RecordClock")
        if duration > 0:
            self._factory.tick(duration)
