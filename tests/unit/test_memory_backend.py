"""Unit tests for ``LocalFilesystemBackend`` and the ``MemoryBackend`` seam.

Covers byte storage, addressing safety (symlink refusal, lighter-than-
credential read), write-time size limiting, and protocol conformance
(a caller typed against ``MemoryBackend`` works for any implementation).
"""

from __future__ import annotations

import os
import platform
import stat
from pathlib import Path

import pytest

from mixpanel_headless._internal.io_utils import CredentialPathError
from mixpanel_headless._internal.memory.backend import (
    LocalFilesystemBackend,
    MemoryBackend,
)
from mixpanel_headless._internal.memory.limits import (
    MAX_MEMORY_WRITE_BYTES,
    MemorySizeLimitError,
)
from mixpanel_headless._internal.memory.locking import (
    Fingerprint,
    MemoryConflictError,
    fingerprint_of,
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


class TestByteStorage:
    """Write/read/list/delete round-trips over a scope directory."""

    def test_write_then_read_roundtrip(self, scope_dir: Path) -> None:
        """Bytes written to a key are read back exactly."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("notes.md", b"# hello\n")
        assert backend.read("notes.md") == b"# hello\n"

    def test_read_absent_returns_none(self, scope_dir: Path) -> None:
        """Reading a key that was never written returns ``None``."""
        backend = LocalFilesystemBackend(scope_dir)
        assert backend.read("missing.md") is None

    def test_write_creates_scope_dir_on_demand(self, scope_dir: Path) -> None:
        """The scope directory is created lazily on first write."""
        assert not scope_dir.exists()
        LocalFilesystemBackend(scope_dir).write("a.md", b"x")
        assert scope_dir.is_dir()

    def test_nested_key_roundtrip(self, scope_dir: Path) -> None:
        """A nested key creates intermediate dirs and round-trips."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("context/goals.md", b"g")
        assert backend.read("context/goals.md") == b"g"
        assert (scope_dir / "context" / "goals.md").is_file()

    def test_list_empty_for_absent_scope(self, scope_dir: Path) -> None:
        """Listing a scope that does not exist returns an empty list."""
        assert LocalFilesystemBackend(scope_dir).list() == []

    def test_list_returns_sorted_keys(self, scope_dir: Path) -> None:
        """``list`` returns POSIX-style relative keys, sorted."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("b.md", b"1")
        backend.write("a.md", b"2")
        backend.write("sub/c.md", b"3")
        assert backend.list() == ["a.md", "b.md", "sub/c.md"]

    def test_list_prefix_filter(self, scope_dir: Path) -> None:
        """``list(prefix)`` returns only keys under the prefix."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("sub/c.md", b"3")
        backend.write("a.md", b"2")
        assert backend.list("sub/") == ["sub/c.md"]

    def test_delete_present_key(self, scope_dir: Path) -> None:
        """Deleting a present key removes it."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("a.md", b"1")
        backend.delete("a.md")
        assert backend.read("a.md") is None

    def test_delete_absent_is_noop(self, scope_dir: Path) -> None:
        """Deleting an absent key is a successful no-op."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.delete("nope.md")  # must not raise

    @pytest.mark.skipif(
        platform.system() == "Windows",
        reason="POSIX file permissions not available on Windows",
    )
    def test_written_file_is_owner_only(self, scope_dir: Path) -> None:
        """Notes are written with ``0o600`` permissions."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("a.md", b"1")
        mode = stat.S_IMODE((scope_dir / "a.md").stat().st_mode)
        assert mode == 0o600


class TestWriteSizeLimit:
    """Writes are rejected once content exceeds ``MAX_MEMORY_WRITE_BYTES``."""

    def test_write_one_under_ceiling_roundtrips(self, scope_dir: Path) -> None:
        """A payload one byte under the ceiling writes and reads back exactly."""
        backend = LocalFilesystemBackend(scope_dir)
        data = b"x" * (MAX_MEMORY_WRITE_BYTES - 1)
        backend.write("under.md", data)
        assert backend.read("under.md") == data

    def test_write_exactly_at_ceiling_roundtrips(self, scope_dir: Path) -> None:
        """A payload exactly at the ceiling writes and reads back exactly."""
        backend = LocalFilesystemBackend(scope_dir)
        data = b"x" * MAX_MEMORY_WRITE_BYTES
        backend.write("at.md", data)
        assert backend.read("at.md") == data

    def test_write_zero_byte_roundtrips(self, scope_dir: Path) -> None:
        """A zero-byte payload writes and reads back exactly."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("zero.md", b"")
        assert backend.read("zero.md") == b""

    def test_oversized_write_to_fresh_key_raises_and_creates_nothing(
        self, scope_dir: Path
    ) -> None:
        """An oversized write against a nonexistent key raises and touches no disk.

        No scope directory is created (``_ensure_dir`` is never reached), and
        no file exists at the key afterward.
        """
        backend = LocalFilesystemBackend(scope_dir)
        data = b"x" * (MAX_MEMORY_WRITE_BYTES + 1)
        with pytest.raises(MemorySizeLimitError) as exc_info:
            backend.write("fresh.md", data)
        err = exc_info.value
        assert err.size == len(data)
        assert err.limit == MAX_MEMORY_WRITE_BYTES
        assert not scope_dir.exists()
        assert backend.read("fresh.md") is None

    def test_oversized_overwrite_leaves_existing_file_unchanged(
        self, scope_dir: Path
    ) -> None:
        """An oversized write against an existing key raises and leaves it untouched.

        The original bytes remain byte-for-byte unchanged, and no
        ``.tmp.*`` temp file is left behind in the scope directory.
        """
        backend = LocalFilesystemBackend(scope_dir)
        original = b"original content"
        backend.write("existing.md", original)

        oversized = b"x" * (MAX_MEMORY_WRITE_BYTES + 1)
        with pytest.raises(MemorySizeLimitError):
            backend.write("existing.md", oversized)

        assert backend.read("existing.md") == original
        tmp_leftovers = list(scope_dir.rglob("*.tmp.*"))
        assert tmp_leftovers == []

    def test_oversized_write_to_nested_fresh_key_creates_no_directories(
        self, scope_dir: Path
    ) -> None:
        """An oversized write against a nested, never-written key creates no directories.

        The size guard runs before any filesystem access, so a nested key
        like ``"a/b/c/note.md"`` must not cause any of its intermediate
        directories — nor the scope directory itself — to spring into
        existence.
        """
        assert not scope_dir.exists()
        backend = LocalFilesystemBackend(scope_dir)
        data = b"x" * (MAX_MEMORY_WRITE_BYTES + 1)
        with pytest.raises(MemorySizeLimitError):
            backend.write("a/b/c/note.md", data)
        assert not scope_dir.exists()
        assert not (scope_dir / "a").exists()

    def test_oversized_write_into_populated_scope_leaves_siblings_untouched(
        self, scope_dir: Path
    ) -> None:
        """An oversized write to a new key in a populated scope disturbs nothing else.

        Seeded sibling notes must remain byte-identical, no file must exist
        at the rejected key, and no ``.tmp.*`` file must be left anywhere
        under the scope directory (checked recursively, since the rejected
        key could nest under a subdirectory).
        """
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("sibling_one.md", b"first note")
        backend.write("sub/sibling_two.md", b"second note")

        oversized = b"x" * (MAX_MEMORY_WRITE_BYTES + 1)
        with pytest.raises(MemorySizeLimitError):
            backend.write("new/key.md", oversized)

        assert backend.read("sibling_one.md") == b"first note"
        assert backend.read("sub/sibling_two.md") == b"second note"
        assert backend.read("new/key.md") is None
        assert not (scope_dir / "new").exists()
        assert list(scope_dir.rglob("*.tmp.*")) == []


class TestAddressingSafety:
    """Hostile keys are rejected before any disk write."""

    @pytest.mark.parametrize("key", ["", "   "])
    def test_empty_key_rejected(self, scope_dir: Path, key: str) -> None:
        """Empty/whitespace keys raise ``ValueError`` and write nothing."""
        backend = LocalFilesystemBackend(scope_dir)
        with pytest.raises(ValueError):
            backend.write(key, b"x")
        assert not scope_dir.exists()

    @pytest.mark.parametrize("key", ["/etc/passwd", "/abs"])
    def test_absolute_key_rejected(self, scope_dir: Path, key: str) -> None:
        """Absolute keys raise ``ValueError`` and write nothing."""
        backend = LocalFilesystemBackend(scope_dir)
        with pytest.raises(ValueError):
            backend.write(key, b"x")
        assert not scope_dir.exists()

    @pytest.mark.parametrize("key", ["../escape.md", "../../etc/passwd"])
    def test_traversal_key_rejected(self, scope_dir: Path, key: str) -> None:
        """Traversal keys raise ``ValueError`` and write nothing."""
        backend = LocalFilesystemBackend(scope_dir)
        with pytest.raises(ValueError):
            backend.write(key, b"x")
        assert not scope_dir.exists()

    def test_read_and_delete_also_validate(self, scope_dir: Path) -> None:
        """``read`` and ``delete`` reject hostile keys too."""
        backend = LocalFilesystemBackend(scope_dir)
        with pytest.raises(ValueError):
            backend.read("../x")
        with pytest.raises(ValueError):
            backend.delete("../x")


class TestSymlinkAndPermissions:
    """Symlink refusal, but no credential-grade mode/size enforcement."""

    @pytest.mark.skipif(
        platform.system() == "Windows",
        reason="POSIX symlinks not reliably available on Windows",
    )
    def test_read_refuses_symlinked_note(self, scope_dir: Path, tmp_path: Path) -> None:
        """A symlinked note path is refused, not followed."""
        scope_dir.mkdir(parents=True)
        target = tmp_path / "target.md"
        target.write_bytes(b"secret")
        (scope_dir / "note.md").symlink_to(target)

        backend = LocalFilesystemBackend(scope_dir)
        with pytest.raises(CredentialPathError):
            backend.read("note.md")

    @pytest.mark.skipif(
        platform.system() == "Windows",
        reason="POSIX file permissions not available on Windows",
    )
    def test_read_allows_loose_permission_bits(self, scope_dir: Path) -> None:
        """A note with 0o644 (looser than the credential rule) still reads.

        This is the intentional divergence from ``read_credential_text``:
        memory reads do NOT enforce owner-only mode.
        """
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("a.md", b"data")
        os.chmod(scope_dir / "a.md", 0o644)
        assert backend.read("a.md") == b"data"


class _InMemoryBackend:
    """A trivial in-memory ``MemoryBackend`` used for conformance testing."""

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._store: dict[str, bytes] = {}

    def read(self, key: str) -> bytes | None:
        """Return the stored bytes for ``key`` or ``None``."""
        return self._store.get(key)

    def write(self, key: str, data: bytes) -> None:
        """Store ``data`` at ``key``."""
        self._store[key] = data

    def list(self, prefix: str = "") -> list[str]:
        """Return sorted keys under ``prefix``."""
        return sorted(k for k in self._store if k.startswith(prefix))

    def delete(self, key: str) -> None:
        """Remove ``key`` if present."""
        self._store.pop(key, None)

    def read_with_fingerprint(self, key: str) -> tuple[bytes | None, Fingerprint]:
        """Return the stored bytes for ``key`` and their fingerprint."""
        data = self.read(key)
        return data, fingerprint_of(data)

    def write_if_match(self, key: str, data: bytes, *, expected: Fingerprint) -> None:
        """Store ``data`` at ``key`` iff its current fingerprint matches ``expected``."""
        actual = fingerprint_of(self.read(key))
        if actual != expected:
            raise MemoryConflictError(key, expected, actual)
        self.write(key, data)


def _exercise(backend: MemoryBackend) -> list[str]:
    """Run a write/read/list/delete sequence through the abstract seam.

    Args:
        backend: Any ``MemoryBackend`` implementation.

    Returns:
        The key listing observed after the write, before deletion.
    """
    backend.write("a.md", b"1")
    assert backend.read("a.md") == b"1"
    listing = backend.list()
    backend.delete("a.md")
    assert backend.read("a.md") is None
    return listing


class TestReadWithFingerprint:
    """``read_with_fingerprint`` pairs current bytes with their fingerprint."""

    def test_absent_key_returns_none_none(self, scope_dir: Path) -> None:
        """An absent key returns ``(None, None)``."""
        backend = LocalFilesystemBackend(scope_dir)
        assert backend.read_with_fingerprint("missing.md") == (None, None)

    def test_existing_key_returns_data_and_its_fingerprint(
        self, scope_dir: Path
    ) -> None:
        """An existing key returns its bytes and ``fingerprint_of(data)``."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("notes.md", b"content")
        data, fp = backend.read_with_fingerprint("notes.md")
        assert data == b"content"
        assert fp == fingerprint_of(b"content")


class TestWriteIfMatchUncontested:
    """An uncontested ``write_if_match`` behaves like ``write`` plus one check."""

    def test_fresh_key_with_none_expected_succeeds(self, scope_dir: Path) -> None:
        """A fresh key with ``expected=None`` commits and reads back exactly."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write_if_match("fresh.md", b"new content", expected=None)
        assert backend.read("fresh.md") == b"new content"

    def test_existing_key_overwrite_succeeds(self, scope_dir: Path) -> None:
        """An existing key whose fingerprint matches ``expected`` is overwritten."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("existing.md", b"old")
        _, fp = backend.read_with_fingerprint("existing.md")
        backend.write_if_match("existing.md", b"new", expected=fp)
        assert backend.read("existing.md") == b"new"

    def test_oversized_data_raises_size_error_not_conflict(
        self, scope_dir: Path
    ) -> None:
        """A matching fingerprint with oversized data raises ``MemorySizeLimitError``."""
        backend = LocalFilesystemBackend(scope_dir)
        oversized = b"x" * (MAX_MEMORY_WRITE_BYTES + 1)
        with pytest.raises(MemorySizeLimitError):
            backend.write_if_match("fresh.md", oversized, expected=None)
        assert backend.read("fresh.md") is None


class TestWriteIfMatchConflictDetection:
    """A stale fingerprint at commit time raises ``MemoryConflictError``."""

    def test_create_vs_create_race_detected(self, scope_dir: Path) -> None:
        """Believing a key absent when another writer already created it conflicts."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("shared.md", b"winner's content")

        with pytest.raises(MemoryConflictError) as exc_info:
            backend.write_if_match("shared.md", b"loser's content", expected=None)

        err = exc_info.value
        assert err.actual == fingerprint_of(b"winner's content")
        assert err.expected is None
        assert backend.read("shared.md") == b"winner's content"

    def test_modify_vs_modify_race_detected(self, scope_dir: Path) -> None:
        """A stale fingerprint against an intervening overwrite conflicts."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("shared.md", b"original")
        _, stale_fp = backend.read_with_fingerprint("shared.md")
        backend.write("shared.md", b"intervening writer's update")

        with pytest.raises(MemoryConflictError):
            backend.write_if_match(
                "shared.md", b"stale writer's update", expected=stale_fp
            )

        assert backend.read("shared.md") == b"intervening writer's update"

    def test_modify_vs_delete_race_detected(self, scope_dir: Path) -> None:
        """A stale fingerprint against an intervening delete conflicts with actual=None."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("shared.md", b"original")
        _, stale_fp = backend.read_with_fingerprint("shared.md")
        backend.delete("shared.md")

        with pytest.raises(MemoryConflictError) as exc_info:
            backend.write_if_match(
                "shared.md", b"stale writer's update", expected=stale_fp
            )

        assert exc_info.value.actual is None
        assert backend.read("shared.md") is None

    def test_conflict_leaves_no_tmp_file(self, scope_dir: Path) -> None:
        """A detected conflict never invokes the atomic-write path at all."""
        backend = LocalFilesystemBackend(scope_dir)
        backend.write("shared.md", b"winner's content")
        with pytest.raises(MemoryConflictError):
            backend.write_if_match("shared.md", b"loser's content", expected=None)
        assert list(scope_dir.rglob("*.tmp.*")) == []


class TestProtocolConformance:
    """A caller typed against ``MemoryBackend`` works for any implementation."""

    def test_local_backend_conforms(self, scope_dir: Path) -> None:
        """The filesystem backend satisfies the protocol-typed caller."""
        assert _exercise(LocalFilesystemBackend(scope_dir)) == ["a.md"]

    def test_in_memory_fake_conforms(self) -> None:
        """A different implementation works with the same caller, unchanged."""
        assert _exercise(_InMemoryBackend()) == ["a.md"]
