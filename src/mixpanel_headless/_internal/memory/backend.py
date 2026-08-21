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
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from mixpanel_headless._internal.io_utils import atomic_write_bytes, reject_if_symlink
from mixpanel_headless._internal.memory.limits import check_write_size
from mixpanel_headless._internal.memory.paths import resolve_key

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
