"""The Headless Memory backend seam and its local filesystem implementation.

``MemoryBackend`` is a thin, content-agnostic protocol — read / write / list /
delete over relative keys returning and accepting raw bytes. It deliberately
knows nothing about the note format, concurrency, or PII (each owned by a
sibling layer built on top); the concrete backend below enforces a size limit
at the write boundary, but the protocol itself stays silent on that policy.
Keeping the seam dumb is what lets a future team-shared backend swap in
behind the same interface without rewriting callers.

``LocalFilesystemBackend`` is the only implementation in this slice. It binds
to a single resolved scope directory (a user- or project-scoped ``memory``
dir) and stores each note as a plain file.

Security posture: writes are atomic (:func:`~mixpanel_headless._internal.io_utils.atomic_write_bytes`)
and reads refuse a symlinked note path
(:func:`~mixpanel_headless._internal.io_utils.reject_if_symlink`). Reads
intentionally do NOT enforce the credential owner-only-mode rule or the 1 MiB
credential size cap — memory notes are not secrets in that sense, and the
future team backend may carry files with looser permission bits.

Concurrency posture: ``write_if_match`` guards its compare-and-commit
sequence with an exclusive ``flock`` on the scope directory
(``LocalFilesystemBackend._locked_scope``) so two processes racing on the
same key can never both pass the fingerprint check and both commit — one
of them always observes the other's write and raises
``MemoryConflictError``. POSIX-only (guarded ``fcntl`` import); degrades
to no cross-process guarantee on Windows.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from mixpanel_headless._internal.io_utils import atomic_write_bytes, reject_if_symlink
from mixpanel_headless._internal.memory.limits import check_write_size
from mixpanel_headless._internal.memory.locking import (
    Fingerprint,
    MemoryConflictError,
    fingerprint_of,
)
from mixpanel_headless._internal.memory.paths import resolve_key

try:
    # POSIX only. Guarded so the module still imports on Windows; the
    # cross-process mutual exclusion in ``write_if_match`` degrades to a
    # no-op there (see ``LocalFilesystemBackend._locked_scope``).
    import fcntl
except ImportError:  # pragma: no cover — exercised only on Windows CI
    fcntl = None  # type: ignore[assignment]

__all__ = ["LocalFilesystemBackend", "MemoryBackend"]


class MemoryBackend(Protocol):
    """Content-agnostic byte store addressed by relative key within one scope."""

    def read(self, key: str) -> bytes | None:
        """Return the bytes stored at ``key``, or ``None`` if absent.

        Args:
            key: Relative key naming a note within the scope.

        Returns:
            The stored bytes, or ``None`` when no note exists at ``key``.

        Raises:
            ValueError: ``key`` is empty, absolute, or escapes the scope.
        """
        ...

    def write(self, key: str, data: bytes) -> None:
        """Store ``data`` at ``key``, creating the scope directory on demand.

        Args:
            key: Relative key naming a note within the scope.
            data: Raw bytes to store.

        Raises:
            MemorySizeLimitError: ``len(data)`` exceeds
                :data:`~mixpanel_headless._internal.memory.limits.MAX_MEMORY_WRITE_BYTES`.
            ValueError: ``key`` is empty, absolute, or escapes the scope.
        """
        ...

    def list(self, prefix: str = "") -> list[str]:
        """Return the relative keys under ``prefix``, sorted.

        Args:
            prefix: Key prefix to filter by. Empty string lists all keys.

        Returns:
            Sorted relative keys; ``[]`` for an empty or absent scope.
        """
        ...

    def delete(self, key: str) -> None:
        """Remove the note at ``key``; a no-op if it is absent.

        Args:
            key: Relative key naming a note within the scope.

        Raises:
            ValueError: ``key`` is empty, absolute, or escapes the scope.
        """
        ...

    def read_with_fingerprint(self, key: str) -> tuple[bytes | None, Fingerprint]:
        """Return ``(current bytes or None, its fingerprint)``.

        Args:
            key: Relative key naming a note within the scope.

        Returns:
            A tuple of the stored bytes (or ``None`` if absent) and the
            corresponding :class:`~mixpanel_headless._internal.memory.locking.Fingerprint`.

        Raises:
            ValueError: ``key`` is empty, absolute, or escapes the scope.
        """
        ...

    def write_if_match(self, key: str, data: bytes, *, expected: Fingerprint) -> None:
        """Atomically store ``data`` at ``key`` iff its current fingerprint matches.

        The re-read of the current fingerprint, the comparison against
        ``expected``, and the commit are one mutually-exclusive critical
        section with respect to every other process calling
        ``write_if_match`` against the same scope directory, so two
        processes racing on the same key can never both observe a
        matching fingerprint and both commit (see
        ``LocalFilesystemBackend.write_if_match`` for the locking
        mechanism).

        Args:
            key: Relative key naming a note within the scope.
            data: Raw bytes to store if the fingerprint check passes.
            expected: The fingerprint the caller believes is currently at
                ``key`` (from a prior ``read_with_fingerprint`` call).

        Raises:
            MemoryConflictError: The current fingerprint at ``key`` no
                longer equals ``expected``.
            MemorySizeLimitError: ``len(data)`` exceeds
                :data:`~mixpanel_headless._internal.memory.limits.MAX_MEMORY_WRITE_BYTES`.
            ValueError: ``key`` is empty, absolute, or escapes the scope.
            OSError: I/O failure.
        """
        ...


class LocalFilesystemBackend:
    """:class:`MemoryBackend` over a single on-disk scope directory.

    Args:
        scope_dir: The scope's ``memory`` directory (from
            :func:`~mixpanel_headless._internal.memory.paths.user_memory_dir`
            or ``project_memory_dir``). Not required to exist — it is created
            on the first write.

    Example:
        ```python
        from mixpanel_headless._internal.storage_root import storage_root
        from mixpanel_headless._internal.memory.paths import project_memory_dir

        backend = LocalFilesystemBackend(
            project_memory_dir("3713224", root=storage_root())
        )
        backend.write("notes.md", b"# context\n")
        backend.read("notes.md")  # b"# context\n"
        ```
    """

    def __init__(self, scope_dir: Path) -> None:
        """Initialize the backend bound to ``scope_dir``.

        Args:
            scope_dir: The scope's ``memory`` directory.
        """
        self._scope_dir = scope_dir

    def _resolve(self, key: str) -> Path:
        """Validate ``key`` and return its in-scope path.

        Args:
            key: Relative key naming a note within the scope.

        Returns:
            The path for ``key`` under the scope directory.

        Raises:
            ValueError: ``key`` is empty, absolute, or escapes the scope.
        """
        return resolve_key(self._scope_dir, key)

    @contextlib.contextmanager
    def _locked_scope(self) -> Iterator[None]:
        """Hold an exclusive, cross-process lock scoped to this backend's directory.

        Backs the mutual exclusion :meth:`write_if_match` needs: the
        directory is opened and ``flock``-ed for the duration of the
        ``with`` block, so any other process (or thread) doing the same
        for the same scope directory blocks until this one exits the
        block. The lock is held on the directory itself (not a
        dedicated lock file), so no extra entry ever appears in
        :meth:`list`'s output and no lock-file cleanup is needed.

        The scope directory is created first (idempotently) if absent,
        since a directory must exist to be opened and locked — this is
        why a fresh, never-written-to scope can now have its directory
        created as a side effect of a call that ultimately conflicts or
        fails the size guard (see the updated ``write_if_match``
        contract).

        On platforms without ``fcntl`` (Windows), this degrades to a
        plain no-op context manager — cross-process mutual exclusion is
        POSIX-only here and is not silently faked.

        Yields:
            Nothing; the block runs with the lock held (or, on Windows,
            with no lock at all).

        Raises:
            OSError: The directory cannot be created or opened.
        """
        self._ensure_dir(self._scope_dir)
        if fcntl is None:  # pragma: no cover — exercised only on Windows CI
            yield
            return
        dir_flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            dir_flags |= os.O_DIRECTORY
        fd = os.open(str(self._scope_dir), dir_flags)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    @staticmethod
    def _ensure_dir(directory: Path) -> None:
        """Create ``directory`` (and parents) with owner-only permissions.

        Uses the ``umask(0o077)`` + ``mkdir`` pattern so newly-created
        directories land at ``0o700``, matching the account-directory model.

        Args:
            directory: Directory to create; idempotent if it already exists.
        """
        old_umask = os.umask(0o077)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        finally:
            os.umask(old_umask)

    def read(self, key: str) -> bytes | None:
        """Return the bytes stored at ``key``, or ``None`` if absent.

        Refuses a symlinked note path. Does NOT enforce owner-only mode or a
        size cap — memory notes are read even with looser permission bits.

        Args:
            key: Relative key naming a note within the scope.

        Returns:
            The stored bytes, or ``None`` when no note exists at ``key``.

        Raises:
            ValueError: ``key`` is empty, absolute, or escapes the scope.
            CredentialPathError: The note path is a symlink.
            OSError: Other I/O failure.
        """
        path = self._resolve(key)
        reject_if_symlink(path)
        if not path.exists():
            return None
        return path.read_bytes()

    def write(self, key: str, data: bytes) -> None:
        """Atomically store ``data`` at ``key``, creating dirs on demand.

        The size guard runs first, before any filesystem access, so a
        rejected write is a strict no-op with respect to disk state: no
        directory is created, no file is created or modified, and no tmp
        file is left behind.

        Args:
            key: Relative key naming a note within the scope.
            data: Raw bytes to store.

        Raises:
            MemorySizeLimitError: ``len(data)`` exceeds
                :data:`~mixpanel_headless._internal.memory.limits.MAX_MEMORY_WRITE_BYTES`.
            ValueError: ``key`` is empty, absolute, or escapes the scope.
            OSError: I/O failure.
        """
        check_write_size(data)
        path = self._resolve(key)
        self._ensure_dir(path.parent)
        atomic_write_bytes(path, data, mode=0o600)

    def list(self, prefix: str = "") -> list[str]:
        """Return the relative keys under ``prefix``, sorted.

        Args:
            prefix: Key prefix to filter by. Empty string lists all keys.

        Returns:
            Sorted relative keys (POSIX-style, ``/``-separated); ``[]`` when
            the scope directory does not exist.
        """
        if not self._scope_dir.exists():
            return []
        keys: list[str] = []
        for path in self._scope_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(self._scope_dir).as_posix()
            if rel.startswith(prefix):
                keys.append(rel)
        keys.sort()
        return keys

    def delete(self, key: str) -> None:
        """Remove the note at ``key``; a no-op if it is absent.

        Args:
            key: Relative key naming a note within the scope.

        Raises:
            ValueError: ``key`` is empty, absolute, or escapes the scope.
        """
        path = self._resolve(key)
        path.unlink(missing_ok=True)

    def read_with_fingerprint(self, key: str) -> tuple[bytes | None, Fingerprint]:
        """Return ``(current bytes or None, its fingerprint)``.

        A convenience pairing of :meth:`read` with
        :func:`~mixpanel_headless._internal.memory.locking.fingerprint_of`
        so a caller never computes a fingerprint from a value it did not
        just read (avoiding a caller-side TOCTOU between its own read and
        its own hashing).

        Args:
            key: Relative key naming a note within the scope.

        Returns:
            ``(None, None)`` when no file exists at ``key``, otherwise
            ``(data, fingerprint_of(data))``.

        Raises:
            ValueError: ``key`` is empty, absolute, or escapes the scope.
            CredentialPathError: The note path is a symlink.
            OSError: Other I/O failure.
        """
        data = self.read(key)
        return data, fingerprint_of(data)

    def write_if_match(self, key: str, data: bytes, *, expected: Fingerprint) -> None:
        """Atomically store ``data`` at ``key`` iff its current fingerprint matches.

        Makes exactly one attempt; never retries and never sleeps. The
        re-read of the current fingerprint, its comparison against
        ``expected``, and the eventual commit all happen while holding an
        exclusive ``flock`` on the scope directory (:meth:`_locked_scope`),
        so two processes racing on the same key can never both observe a
        matching fingerprint and both commit — one always loses the lock
        acquisition, re-observes the other's already-committed fingerprint,
        and raises ``MemoryConflictError`` instead of silently clobbering
        it. This is what makes "atomically" in this docstring literally
        true across processes, not just within one.

        The fingerprint re-check runs first, strictly before the size
        guard and strictly before any code path that could write to disk,
        so a raised error at either checkpoint is a strict no-op with
        respect to note/tmp file state (the scope directory itself may
        now be created as a side effect of acquiring the lock — see
        :meth:`_locked_scope`).

        On platforms without ``fcntl`` (Windows), the lock degrades to a
        no-op and this method's cross-process guarantee does not hold —
        only the single-process, single-attempt fingerprint check remains.

        Args:
            key: Relative key naming a note within the scope.
            data: Raw bytes to store if the fingerprint check passes.
            expected: The fingerprint the caller believes is currently at
                ``key`` (from a prior :meth:`read_with_fingerprint` call,
                or ``None`` for a caller that believes the key does not
                yet exist).

        Raises:
            MemoryConflictError: The current fingerprint at ``key`` no
                longer equals ``expected``.
            MemorySizeLimitError: ``len(data)`` exceeds
                :data:`~mixpanel_headless._internal.memory.limits.MAX_MEMORY_WRITE_BYTES`.
            ValueError: ``key`` is empty, absolute, or escapes the scope.
            OSError: I/O failure.
        """
        self._resolve(key)  # validate before locking/creating the scope dir
        with self._locked_scope():
            _, actual = self.read_with_fingerprint(key)
            if actual != expected:
                raise MemoryConflictError(key, expected, actual)
            self.write(key, data)
