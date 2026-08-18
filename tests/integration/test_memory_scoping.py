"""Integration tests for two-tree scoping and hermetic storage-root behavior.

Exercises the full stack (``storage_root`` -> ``paths`` -> ``backend``):
- US1: the user and project trees are physically separate for the same key.
- US3: every artifact honors ``$MP_OAUTH_STORAGE_DIR`` and nothing leaks to
  the real home directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mixpanel_headless._internal.memory.backend import LocalFilesystemBackend
from mixpanel_headless._internal.memory.paths import (
    project_memory_dir,
    user_memory_dir,
)
from mixpanel_headless._internal.storage_root import storage_root


class TestTwoTreeIsolation:
    """US1 — the same key in each scope stores independent values."""

    def test_same_key_independent_across_scopes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Writing ``notes.md`` in each tree yields two independent notes."""
        monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", str(tmp_path))
        root = storage_root()

        user = LocalFilesystemBackend(user_memory_dir("personal", root=root))
        proj = LocalFilesystemBackend(project_memory_dir("3713224", root=root))

        user.write("notes.md", b"user note")
        proj.write("notes.md", b"project note")

        assert user.read("notes.md") == b"user note"
        assert proj.read("notes.md") == b"project note"
        assert (
            tmp_path / "accounts" / "personal" / "memory" / "notes.md"
        ).read_bytes() == b"user note"
        assert (
            tmp_path / "projects" / "3713224" / "memory" / "notes.md"
        ).read_bytes() == b"project note"


class TestHermeticRoot:
    """US3 — all artifacts land under the override; nothing under real home."""

    def test_writes_contained_under_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A full write/read/list cycle is contained under the override root."""
        storage = tmp_path / "storage"
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", str(storage))
        monkeypatch.setenv("HOME", str(fake_home))

        root = storage_root()
        backend = LocalFilesystemBackend(project_memory_dir("42", root=root))
        backend.write("a.md", b"hello")
        assert backend.read("a.md") == b"hello"
        assert backend.list() == ["a.md"]

        # Everything is under the override; the fake home stays empty.
        assert (storage / "projects" / "42" / "memory" / "a.md").is_file()
        assert not any(fake_home.rglob("*"))

    def test_root_resolved_at_call_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Changing the override between calls redirects new writes."""
        first = tmp_path / "first"
        second = tmp_path / "second"

        monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", str(first))
        LocalFilesystemBackend(project_memory_dir("1", root=storage_root())).write(
            "a.md", b"1"
        )

        monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", str(second))
        LocalFilesystemBackend(project_memory_dir("1", root=storage_root())).write(
            "a.md", b"2"
        )

        assert (first / "projects" / "1" / "memory" / "a.md").read_bytes() == b"1"
        assert (second / "projects" / "1" / "memory" / "a.md").read_bytes() == b"2"
