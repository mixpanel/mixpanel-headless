"""Optimistic-locking concurrency primitives for Headless Memory writes.

Holds the pure fingerprint/error/retry-policy building blocks a guarded
read-modify-write cycle needs to detect and recover from a concurrent
writer, plus the one orchestration function (:func:`write_with_retry`)
that composes them with the I/O-bearing ``backend.py`` methods into an
automatic, bounded retry loop. Everything in this module is free of
filesystem and network I/O except the single ``time.sleep`` call inside
:func:`write_with_retry`'s loop body, matching the pure/IO split also
used by the write-time size-limit module (``limits.py``).
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from mixpanel_headless._internal.memory.backend import MemoryBackend

__all__ = [
    "MAX_MEMORY_WRITE_ATTEMPTS",
    "RETRY_BACKOFF_BASE_SECONDS",
    "Fingerprint",
    "MemoryConflictError",
    "MemoryConflictRetriesExhaustedError",
    "MemoryLockingError",
    "fingerprint_of",
    "next_backoff_delay",
    "write_with_retry",
]

Fingerprint = bytes | None
"""A whole-file content fingerprint, or the absence sentinel.

``bytes`` (a 32-byte ``sha256`` digest) when content exists at a key, or
the ``None`` singleton when no file exists at that key. ``None`` can
never be confused with a digest at the type level, so a create-vs-create
race is detected the same way as a modify-vs-modify race.
"""

MAX_MEMORY_WRITE_ATTEMPTS: Final[int] = 5
"""Total attempts :func:`write_with_retry` makes, including the first.

Locked at 5 (the first attempt plus up to 4 retries) — not configurable
per call. Every caller of the retrying helper shares this single constant
so retry behavior cannot drift between call sites.
"""

RETRY_BACKOFF_BASE_SECONDS: Final[float] = 0.015
"""Upper bound of the full-jitter backoff window, in seconds.

The delay between a detected conflict and the next attempt is drawn
uniformly from ``[0, RETRY_BACKOFF_BASE_SECONDS)`` (see
:func:`next_backoff_delay`). 15 ms sits within the locked 10-20 ms
range; full jitter (rather than a fixed or exponential delay) keeps
independently-colliding writers from resynchronizing onto the same
retry cadence.
"""


def fingerprint_of(data: bytes | None) -> Fingerprint:
    """Return the content fingerprint for ``data``, or the absence sentinel.

    A pure, I/O-free function of its single argument. Never persisted to
    disk — a fingerprint exists only for the duration of one guarded-write
    attempt.

    Args:
        data: The raw bytes currently at a key, or ``None`` if no file
            exists there.

    Returns:
        ``None`` when ``data is None`` (the absence sentinel — distinct
        from the digest of any actual content, including empty bytes).
        Otherwise ``hashlib.sha256(data).digest()``.

    Example:
        ```python
        fingerprint_of(None)  # None -- no file exists
        fingerprint_of(b"")  # a 32-byte digest -- an existing, empty file
        fingerprint_of(b"hello") == fingerprint_of(b"hello")  # True
        ```
    """
    if data is None:
        return None
    return hashlib.sha256(data).digest()


def next_backoff_delay() -> float:
    """Return a jittered delay to sleep before the next retry attempt.

    Pure with respect to program state other than the process-global
    ``random`` source. Isolated as its own function (rather than inlined
    at the ``time.sleep`` call site) so the distribution of delays it
    returns is unit- and property-testable without monkeypatching
    ``time.sleep`` itself.

    Returns:
        A value drawn uniformly from ``[0, RETRY_BACKOFF_BASE_SECONDS)``.

    Example:
        ```python
        delay = next_backoff_delay()
        assert 0.0 <= delay < RETRY_BACKOFF_BASE_SECONDS
        ```
    """
    return random.random() * RETRY_BACKOFF_BASE_SECONDS


class MemoryLockingError(Exception):
    """Common base for every typed error this module raises.

    Never raised directly. Lets a caller catch any locking failure with
    one type — ``except MemoryLockingError`` — while
    :class:`MemoryConflictError` and
    :class:`MemoryConflictRetriesExhaustedError` remain siblings: catching
    one never incidentally catches the other. Subclasses plain
    ``Exception`` (not ``ValueError``) so this hierarchy stays independent
    of ``MemorySizeLimitError``, which has no memory-specific base of its
    own to align with.
    """


class MemoryConflictError(MemoryLockingError):
    """Raised when a single guarded-write attempt detects a stale fingerprint.

    The fingerprint captured at read time no longer matches the current
    on-disk state at commit time. Always constructed with
    ``expected != actual`` — the check that raises it never fires when
    they match.

    Attributes:
        key: The memory key the conflict occurred on.
        expected: The fingerprint the caller read at the start of the
            attempt.
        actual: The fingerprint observed at commit time.

    Example:
        ```python
        try:
            backend.write_if_match("notes.md", data, expected=stale_fp)
        except MemoryConflictError as err:
            err.key, err.expected, err.actual
        ```
    """

    def __init__(self, key: str, expected: Fingerprint, actual: Fingerprint) -> None:
        """Initialize the error with the key and both fingerprints.

        Args:
            key: The memory key the conflict occurred on.
            expected: The fingerprint the caller read at the start of the
                attempt.
            actual: The fingerprint observed at commit time.
        """
        self.key = key
        self.expected = expected
        self.actual = actual
        super().__init__(f"Concurrent write conflict detected for memory key {key!r}.")


class MemoryConflictRetriesExhaustedError(MemoryLockingError):
    """Raised when every attempt within the retry budget conflicted.

    Distinct from, and not a subclass of, :class:`MemoryConflictError` —
    exhausting a bounded retry budget is a different failure mode from a
    single collision, so a caller can catch either specifically without
    the other leaking through a shared parent.

    Attributes:
        key: The memory key that could not be committed.
        attempts: The total number of attempts made, equal to
            :data:`MAX_MEMORY_WRITE_ATTEMPTS`.
        last_conflict: The final attempt's :class:`MemoryConflictError`.

    Example:
        ```python
        try:
            write_with_retry(backend, "contended.md", always_races)
        except MemoryConflictRetriesExhaustedError as err:
            err.key, err.attempts, err.last_conflict
        ```
    """

    def __init__(
        self, key: str, attempts: int, last_conflict: MemoryConflictError
    ) -> None:
        """Initialize the error with the key, attempt count, and final conflict.

        Args:
            key: The memory key that could not be committed.
            attempts: The total number of attempts made.
            last_conflict: The final attempt's ``MemoryConflictError``.
        """
        self.key = key
        self.attempts = attempts
        self.last_conflict = last_conflict
        super().__init__(
            f"Memory key {key!r} still conflicted after {attempts} attempts."
        )


def write_with_retry(
    backend: MemoryBackend,
    key: str,
    mutate: Callable[[bytes | None], bytes],
) -> None:
    """Read, mutate, and write ``key`` with automatic conflict retry.

    Loops up to :data:`MAX_MEMORY_WRITE_ATTEMPTS` times. Each iteration
    reads the key's current content and fingerprint, invokes ``mutate``
    against that fresh content, and attempts to commit via
    ``backend.write_if_match``. On a detected conflict, sleeps a jittered
    backoff (:func:`next_backoff_delay`) and retries with freshly re-read
    content; on success, returns immediately.

    ``mutate`` may be invoked once per attempt, so it must be safe to
    re-run against different "current content" inputs, producing only its
    return value as an effect (no side effects that would be wrong to
    repeat). This is a documented contract on the caller, not something
    enforced at runtime.

    ``MemorySizeLimitError`` from any attempt is never caught, retried, or
    wrapped — it propagates immediately, since an oversized payload is an
    unrelated failure mode from a stale-fingerprint conflict.

    Args:
        backend: The ``MemoryBackend`` to read from and write to.
        key: Relative key naming the note within the backend's scope.
        mutate: Transform from the key's current content (``None`` if
            absent) to the new bytes to attempt to commit.

    Raises:
        MemoryConflictRetriesExhaustedError: Every attempt within
            ``MAX_MEMORY_WRITE_ATTEMPTS`` raised ``MemoryConflictError``.
        MemorySizeLimitError: Any attempt's mutated content exceeds the
            per-file byte ceiling. Never retried.
        ValueError: ``key`` is empty, absolute, or escapes the scope.
        OSError: I/O failure.

    Example:
        ```python
        def append_line(current: bytes | None) -> bytes:
            return (current or b"") + b"another fact\\n"

        write_with_retry(backend, "notes.md", append_line)
        ```
    """
    attempt = 0
    while True:
        attempt += 1
        current, fingerprint = backend.read_with_fingerprint(key)
        new_data = mutate(current)
        try:
            backend.write_if_match(key, new_data, expected=fingerprint)
            return
        except MemoryConflictError as exc:
            if attempt >= MAX_MEMORY_WRITE_ATTEMPTS:
                raise MemoryConflictRetriesExhaustedError(
                    key, MAX_MEMORY_WRITE_ATTEMPTS, exc
                ) from exc
            time.sleep(next_backoff_delay())
