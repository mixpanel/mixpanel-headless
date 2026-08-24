"""Concurrency-flavored property test locking write_with_retry's core invariant.

Locks the SC-002/SC-003/SC-005 invariant: a guarded write, under any
number of intervening writes up to and including the retry budget,
either (a) succeeds within budget or (b) raises
``MemoryConflictRetriesExhaustedError`` -- and it always terminates, never
hangs, and never raises anything else undeclared.

Randomized interleavings are modeled by having the caller-supplied
``mutate`` callback itself commit an intervening write on a
Hypothesis-drawn subset of its own invocations, landing the race between
``write_with_retry``'s read and its ``write_if_match`` call for that
attempt -- a real single-process race on the same real temp-directory
backend, exercising the retry *logic* rather than OS thread scheduling
(per tasks.md's Phase 5 notes).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mixpanel_headless._internal.memory.backend import LocalFilesystemBackend
from mixpanel_headless._internal.memory.locking import (
    MAX_MEMORY_WRITE_ATTEMPTS,
    MemoryConflictRetriesExhaustedError,
    MemoryLockingError,
    write_with_retry,
)


@given(
    intervention_attempts=st.sets(
        st.integers(min_value=1, max_value=MAX_MEMORY_WRITE_ATTEMPTS),
        max_size=MAX_MEMORY_WRITE_ATTEMPTS,
    )
)
@settings(deadline=None)
def test_write_with_retry_terminates_and_resolves_deterministically(
    intervention_attempts: set[int],
) -> None:
    """``write_with_retry`` always terminates via success or the exhaustion error.

    ``intervention_attempts`` is a randomized subset of attempt indices
    (1-based, up to ``MAX_MEMORY_WRITE_ATTEMPTS``) at which an intervening
    writer commits behind ``write_with_retry``'s back just before its own
    commit for that attempt. If every attempt in the budget is
    intervened-upon, the call must exhaust; otherwise it must succeed
    once an attempt lands with no intervention, and the committed content
    must be a deterministic function of the sequence of intervening
    writes and the final ``mutate`` invocation -- never a hang, never any
    other exception type.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        scope_dir = Path(tmp_dir) / "projects" / "1" / "memory"
        backend = LocalFilesystemBackend(scope_dir)
        key = "raced.md"
        call_log: list[int] = []

        def mutate(current: bytes | None) -> bytes:
            attempt = len(call_log) + 1
            call_log.append(attempt)
            if attempt in intervention_attempts:
                backend.write(key, f"intervening-{attempt}".encode())
            return f"mine-after-attempt-{attempt}".encode()

        all_attempts_intervened = intervention_attempts.issuperset(
            range(1, MAX_MEMORY_WRITE_ATTEMPTS + 1)
        )

        if all_attempts_intervened:
            with pytest.raises(MemoryConflictRetriesExhaustedError) as exc_info:
                write_with_retry(backend, key, mutate)
            assert exc_info.value.attempts == MAX_MEMORY_WRITE_ATTEMPTS
            assert len(call_log) == MAX_MEMORY_WRITE_ATTEMPTS
            # The winning content is whatever the final intervening writer left.
            assert (
                backend.read(key) == f"intervening-{MAX_MEMORY_WRITE_ATTEMPTS}".encode()
            )
        else:
            write_with_retry(backend, key, mutate)
            # Succeeded: the last attempt made had no intervention landing
            # on it, so its own write committed cleanly.
            last_attempt = call_log[-1]
            assert last_attempt not in intervention_attempts
            assert backend.read(key) == f"mine-after-attempt-{last_attempt}".encode()
            assert len(call_log) <= MAX_MEMORY_WRITE_ATTEMPTS


@given(
    intervention_attempts=st.sets(
        st.integers(min_value=1, max_value=MAX_MEMORY_WRITE_ATTEMPTS),
        max_size=MAX_MEMORY_WRITE_ATTEMPTS,
    )
)
@settings(deadline=None)
def test_write_with_retry_never_raises_undeclared_exception(
    intervention_attempts: set[int],
) -> None:
    """The only exceptions ``write_with_retry`` can raise here are declared ones."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        scope_dir = Path(tmp_dir) / "projects" / "1" / "memory"
        backend = LocalFilesystemBackend(scope_dir)
        key = "raced2.md"
        calls = {"n": 0}

        def mutate(current: bytes | None) -> bytes:
            calls["n"] += 1
            if calls["n"] in intervention_attempts:
                backend.write(key, f"racer-{calls['n']}".encode())
            return b"payload"

        try:
            write_with_retry(backend, key, mutate)
        except MemoryLockingError as exc:
            assert isinstance(exc, MemoryConflictRetriesExhaustedError)
