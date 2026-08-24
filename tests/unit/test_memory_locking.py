"""Unit tests for the optimistic-locking primitives and retry orchestration.

Covers ``fingerprint_of``'s absence-sentinel/digest behavior,
``next_backoff_delay``'s bound, the error hierarchy's shape, and
``write_with_retry``'s composition of ``read_with_fingerprint`` +
``write_if_match`` into a bounded, jittered retry loop. Uses a real
``LocalFilesystemBackend`` against a temp directory, per the project's
existing no-mocking pattern for this module (see ``test_memory_backend.py``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mixpanel_headless._internal.memory.backend import LocalFilesystemBackend
from mixpanel_headless._internal.memory.limits import (
    MAX_MEMORY_WRITE_BYTES,
    MemorySizeLimitError,
)
from mixpanel_headless._internal.memory.locking import (
    MAX_MEMORY_WRITE_ATTEMPTS,
    RETRY_BACKOFF_BASE_SECONDS,
    Fingerprint,
    MemoryConflictError,
    MemoryConflictRetriesExhaustedError,
    MemoryLockingError,
    fingerprint_of,
    next_backoff_delay,
    write_with_retry,
)


@pytest.fixture
def scope_dir(tmp_path: Path) -> Path:
    """Return a (not-yet-created) scope directory under a tmp path.

    Args:
        tmp_path: pytest per-test temporary directory.

    Returns:
        Path to a ``memory`` scope directory that does not exist yet.
    """
    return tmp_path / "projects" / "1" / "memory"


class TestRetryPolicyConstants:
    """The retry-policy constants are locked to the spec'd values."""

    def test_max_attempts_is_5(self) -> None:
        """``MAX_MEMORY_WRITE_ATTEMPTS`` is exactly 5 total attempts."""
        assert MAX_MEMORY_WRITE_ATTEMPTS == 5

    def test_backoff_base_is_positive_and_small(self) -> None:
        """``RETRY_BACKOFF_BASE_SECONDS`` is within the locked 10-20ms range."""
        assert 0.010 <= RETRY_BACKOFF_BASE_SECONDS <= 0.020


class TestFingerprintOf:
    """``fingerprint_of`` maps bytes/None to a digest/absence sentinel."""

    def test_none_returns_none(self) -> None:
        """Absence is fingerprinted as ``None``."""
        assert fingerprint_of(None) is None

    def test_empty_bytes_returns_digest_distinct_from_absence(self) -> None:
        """An existing, empty file's fingerprint is a 32-byte digest, not ``None``."""
        fp = fingerprint_of(b"")
        assert fp is not None
        assert isinstance(fp, bytes)
        assert len(fp) == 32
        assert fp != fingerprint_of(None)

    def test_deterministic_for_identical_bytes(self) -> None:
        """The same content always fingerprints identically."""
        data = b"hello world"
        assert fingerprint_of(data) == fingerprint_of(data)

    def test_matches_hashlib_sha256_digest(self) -> None:
        """The fingerprint is exactly ``hashlib.sha256(data).digest()``."""
        data = b"some memory note content"
        assert fingerprint_of(data) == hashlib.sha256(data).digest()

    def test_different_payloads_produce_different_fingerprints(self) -> None:
        """Two different byte payloads produce different fingerprints."""
        assert fingerprint_of(b"a") != fingerprint_of(b"b")
        assert fingerprint_of(b"note v1") != fingerprint_of(b"note v2")


class TestNextBackoffDelay:
    """``next_backoff_delay`` returns a jittered value within the base window."""

    def test_returns_value_in_bounds(self) -> None:
        """A single call returns a value in ``[0, RETRY_BACKOFF_BASE_SECONDS)``."""
        delay = next_backoff_delay()
        assert 0.0 <= delay < RETRY_BACKOFF_BASE_SECONDS


class TestMemoryLockingErrorHierarchy:
    """The error hierarchy satisfies the sibling-separation guarantee."""

    def test_locking_error_is_exception_subclass(self) -> None:
        """``MemoryLockingError`` subclasses plain ``Exception``."""
        assert issubclass(MemoryLockingError, Exception)
        assert not issubclass(MemoryLockingError, ValueError)

    def test_conflict_error_is_locking_error(self) -> None:
        """``MemoryConflictError`` is a ``MemoryLockingError`` with fields set."""
        err = MemoryConflictError("notes.md", b"expected" * 4, b"actual__" * 4)
        assert isinstance(err, MemoryLockingError)
        assert err.key == "notes.md"
        assert err.expected == b"expected" * 4
        assert err.actual == b"actual__" * 4

    def test_conflict_error_message_names_the_key(self) -> None:
        """The message names the conflicting key."""
        err = MemoryConflictError("notes.md", None, b"x" * 32)
        assert "notes.md" in str(err)

    def test_exhausted_error_is_locking_error_not_conflict_error(self) -> None:
        """``MemoryConflictRetriesExhaustedError`` is a sibling, not a subclass."""
        conflict = MemoryConflictError("notes.md", None, b"x" * 32)
        err = MemoryConflictRetriesExhaustedError("notes.md", 5, conflict)
        assert isinstance(err, MemoryLockingError)
        assert not isinstance(err, MemoryConflictError)
        assert err.key == "notes.md"
        assert err.attempts == 5
        assert err.last_conflict is conflict

    def test_exhausted_error_message_names_key_and_attempts(self) -> None:
        """The message names both the key and the attempt count."""
        conflict = MemoryConflictError("notes.md", None, b"x" * 32)
        err = MemoryConflictRetriesExhaustedError("notes.md", 5, conflict)
        message = str(err)
        assert "notes.md" in message
        assert "5" in message

    def test_conflict_error_not_instance_of_exhausted_error(self) -> None:
        """A per-attempt conflict is never mistaken for retries-exhausted."""
        err = MemoryConflictError("notes.md", None, b"x" * 32)
        assert not isinstance(err, MemoryConflictRetriesExhaustedError)


class TestWriteWithRetryUncontested:
    """An uncontested write succeeds on the first attempt, no retry."""

    def test_succeeds_on_first_attempt_fresh_key(self, scope_dir: Path) -> None:
        """A fresh key succeeds immediately; ``mutate`` invoked exactly once."""
        backend = LocalFilesystemBackend(scope_dir)
        calls: list[bytes | None] = []

        def mutate(current: bytes | None) -> bytes:
            calls.append(current)
            return b"first content"

        write_with_retry(backend, "fresh.md", mutate)
        assert len(calls) == 1
        assert calls[0] is None
        assert backend.read("fresh.md") == b"first content"

    def test_succeeds_on_first_attempt_existing_key(self, scope_dir: Path) -> None:
        """An existing key succeeds immediately with the fresh content passed in."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("existing.md", b"base")
        calls: list[bytes | None] = []

        def mutate(current: bytes | None) -> bytes:
            calls.append(current)
            return (current or b"") + b" + appended"

        write_with_retry(backend, "existing.md", mutate)
        assert calls == [b"base"]
        assert backend.read("existing.md") == b"base + appended"

    def test_no_sleep_when_uncontested(
        self, scope_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No backoff delay is computed when there is no conflict."""
        backend = LocalFilesystemBackend(scope_dir)
        calls = {"count": 0}

        def fake_next_backoff_delay() -> float:
            calls["count"] += 1
            return 0.0

        monkeypatch.setattr(
            "mixpanel_headless._internal.memory.locking.next_backoff_delay",
            fake_next_backoff_delay,
        )
        write_with_retry(backend, "quiet.md", lambda _current: b"x")
        assert calls["count"] == 0


class TestWriteWithRetrySingleConflict:
    """Exactly one intervening write is retried automatically within budget."""

    def test_second_attempt_succeeds_against_fresh_content(
        self, scope_dir: Path
    ) -> None:
        """The retry re-reads and re-mutates against the intervening writer's content."""
        backend = LocalFilesystemBackend(scope_dir)
        calls: list[bytes | None] = []

        def mutate(current: bytes | None) -> bytes:
            calls.append(current)
            if len(calls) == 1:
                # A second writer lands behind our back before we commit.
                backend.write("shared.md", b"someone else's update")
            return (current or b"") + b"\nmy update"

        write_with_retry(backend, "shared.md", mutate)
        assert len(calls) == 2
        assert calls[0] is None
        assert calls[1] == b"someone else's update"
        assert backend.read("shared.md") == b"someone else's update\nmy update"


class TestWriteWithRetryExhaustion:
    """Persistent conflict on every attempt raises the exhaustion error."""

    def test_raises_exhausted_after_max_attempts(self, scope_dir: Path) -> None:
        """Every attempt colliding raises ``MemoryConflictRetriesExhaustedError``."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("contended.md", b"seed")
        call_count = {"n": 0}

        def mutate(current: bytes | None) -> bytes:
            call_count["n"] += 1
            # Always commit a fresh intervening write, guaranteeing the
            # caller's own commit is always stale by the time it lands.
            backend.write("contended.md", f"racer-{call_count['n']}".encode())
            return b"my update"

        with pytest.raises(MemoryConflictRetriesExhaustedError) as exc_info:
            write_with_retry(backend, "contended.md", mutate)

        err = exc_info.value
        assert err.key == "contended.md"
        assert err.attempts == MAX_MEMORY_WRITE_ATTEMPTS
        assert isinstance(err.last_conflict, MemoryConflictError)
        assert call_count["n"] == MAX_MEMORY_WRITE_ATTEMPTS
        # The content committed is whichever racer wrote last -- never the
        # caller's own stale "my update".
        assert (
            backend.read("contended.md")
            == f"racer-{MAX_MEMORY_WRITE_ATTEMPTS}".encode()
        )


class _RaisingWriteBackend:
    """Fake backend whose ``write_if_match`` always raises a given exception.

    Used to verify that :func:`write_with_retry` does not treat a
    non-``MemoryConflictError`` failure as retryable.
    """

    def __init__(self, exc: Exception) -> None:
        """Store the exception to raise from ``write_if_match``.

        Args:
            exc: The exception instance to raise on every ``write_if_match``
                call.
        """
        self._exc = exc
        self.write_if_match_calls = 0

    def read(self, key: str) -> bytes | None:
        """Unused by :func:`write_with_retry`; not exercised by this fake.

        Args:
            key: Ignored.

        Raises:
            NotImplementedError: Always -- this fake only supports the
                ``read_with_fingerprint`` / ``write_if_match`` pairing.
        """
        raise NotImplementedError

    def write(self, key: str, data: bytes) -> None:
        """Unused by :func:`write_with_retry`; not exercised by this fake.

        Args:
            key: Ignored.
            data: Ignored.

        Raises:
            NotImplementedError: Always -- this fake only supports the
                ``read_with_fingerprint`` / ``write_if_match`` pairing.
        """
        raise NotImplementedError

    def list(self, prefix: str = "") -> list[str]:
        """Unused by :func:`write_with_retry`; not exercised by this fake.

        Args:
            prefix: Ignored.

        Raises:
            NotImplementedError: Always -- this fake only supports the
                ``read_with_fingerprint`` / ``write_if_match`` pairing.
        """
        raise NotImplementedError

    def delete(self, key: str) -> None:
        """Unused by :func:`write_with_retry`; not exercised by this fake.

        Args:
            key: Ignored.

        Raises:
            NotImplementedError: Always -- this fake only supports the
                ``read_with_fingerprint`` / ``write_if_match`` pairing.
        """
        raise NotImplementedError

    def read_with_fingerprint(self, key: str) -> tuple[bytes | None, Fingerprint]:
        """Return a fixed ``(None, None)`` pair regardless of ``key``.

        Args:
            key: Ignored.

        Returns:
            ``(None, None)`` — this fake has no persisted content.
        """
        return None, None

    def write_if_match(self, key: str, data: bytes, *, expected: Fingerprint) -> None:
        """Record the call and raise the stored exception.

        Args:
            key: Ignored.
            data: Ignored.
            expected: Ignored.

        Raises:
            Exception: Always raises the exception passed to ``__init__``.
        """
        self.write_if_match_calls += 1
        raise self._exc


class TestWriteWithRetryNonConflictError:
    """A non-conflict error from ``write_if_match`` is never retried."""

    def test_os_error_propagates_immediately_no_retry(self) -> None:
        """``OSError`` from ``write_if_match`` propagates on the first attempt."""
        backend = _RaisingWriteBackend(OSError("disk full"))

        with pytest.raises(OSError, match="disk full"):
            write_with_retry(backend, "notes.md", lambda _current: b"x")

        assert backend.write_if_match_calls == 1


class TestWriteWithRetryBackoffSleep:
    """The backoff delay is slept exactly once per genuine conflict."""

    def test_sleeps_once_with_backoff_value_on_single_conflict(
        self, scope_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One conflict then success sleeps exactly once with the jittered value."""
        backend = LocalFilesystemBackend(scope_dir)
        sleep_calls: list[float] = []
        fixed_delay = 0.007

        monkeypatch.setattr(
            "mixpanel_headless._internal.memory.locking.time.sleep",
            lambda seconds: sleep_calls.append(seconds),
        )
        monkeypatch.setattr(
            "mixpanel_headless._internal.memory.locking.next_backoff_delay",
            lambda: fixed_delay,
        )

        calls: list[bytes | None] = []

        def mutate(current: bytes | None) -> bytes:
            calls.append(current)
            if len(calls) == 1:
                backend.write("shared.md", b"someone else's update")
            return (current or b"") + b"\nmy update"

        write_with_retry(backend, "shared.md", mutate)

        assert sleep_calls == [fixed_delay]


class TestWriteWithRetryBoundaryAttempts:
    """The attempt count boundary at ``MAX_MEMORY_WRITE_ATTEMPTS`` is exact."""

    def test_succeeds_on_final_attempt_after_max_minus_one_conflicts(
        self, scope_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exactly ``MAX_MEMORY_WRITE_ATTEMPTS - 1`` conflicts then success returns normally.

        Guards against an off-by-one in the ``attempt >= MAX_MEMORY_WRITE_ATTEMPTS``
        check: the caller's own final attempt must be allowed to succeed
        without ever being mistaken for an exhausted retry budget.
        """
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("contended.md", b"seed")
        monkeypatch.setattr(
            "mixpanel_headless._internal.memory.locking.time.sleep",
            lambda _seconds: None,
        )
        call_count = {"n": 0}
        conflicts_to_inject = MAX_MEMORY_WRITE_ATTEMPTS - 1

        def mutate(current: bytes | None) -> bytes:
            call_count["n"] += 1
            if call_count["n"] <= conflicts_to_inject:
                backend.write("contended.md", f"racer-{call_count['n']}".encode())
            return b"final content"

        write_with_retry(backend, "contended.md", mutate)

        assert call_count["n"] == MAX_MEMORY_WRITE_ATTEMPTS
        assert backend.read("contended.md") == b"final content"


class TestWriteWithRetryMutateRaises:
    """A mutate callback's own exception is never swallowed or retried."""

    def test_mutate_exception_propagates_immediately(self, scope_dir: Path) -> None:
        """An exception raised by ``mutate`` propagates with no retry."""
        backend = LocalFilesystemBackend(scope_dir)
        call_count = {"n": 0}

        def mutate(current: bytes | None) -> bytes:
            call_count["n"] += 1
            raise ValueError("mutate blew up")

        with pytest.raises(ValueError, match="mutate blew up"):
            write_with_retry(backend, "notes.md", mutate)

        assert call_count["n"] == 1


class TestWriteWithRetrySizeLimit:
    """An oversized mutation output is never treated as a conflict."""

    def test_oversized_output_raises_immediately_no_retry(
        self, scope_dir: Path
    ) -> None:
        """``MemorySizeLimitError`` propagates on the first attempt, uncaught."""
        backend = LocalFilesystemBackend(scope_dir)
        call_count = {"n": 0}
        oversized = b"x" * (MAX_MEMORY_WRITE_BYTES + 1)

        def mutate(current: bytes | None) -> bytes:
            call_count["n"] += 1
            return oversized

        with pytest.raises(MemorySizeLimitError):
            write_with_retry(backend, "toobig.md", mutate)

        assert call_count["n"] == 1
        assert backend.read("toobig.md") is None
