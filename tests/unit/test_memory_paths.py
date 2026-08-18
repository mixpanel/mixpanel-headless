"""Unit tests for the pure memory path/validation logic.

Covers the I/O-free ``paths`` module: account-name and project-id
validators, the user/project memory-dir builders, and ``resolve_key``
containment/rejection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mixpanel_headless._internal.memory.paths import (
    project_memory_dir,
    resolve_key,
    user_memory_dir,
    validate_account_name,
    validate_project_id,
)


class TestValidateAccountName:
    """``validate_account_name`` accepts the account-name rule, rejects the rest."""

    @pytest.mark.parametrize("name", ["personal", "team-1", "a_b", "A" * 64, "x"])
    def test_accepts_valid(self, name: str) -> None:
        """Valid names are returned unchanged."""
        assert validate_account_name(name) == name

    @pytest.mark.parametrize(
        "name", ["", "a" * 65, "has space", "../etc", "dot.name", "slash/name"]
    )
    def test_rejects_invalid(self, name: str) -> None:
        """Invalid names raise ``ValueError``."""
        with pytest.raises(ValueError):
            validate_account_name(name)


class TestValidateProjectId:
    """``validate_project_id`` accepts ``^\\d{1,20}$`` opaque, rejects the rest."""

    @pytest.mark.parametrize("pid", ["1", "3713224", "0", "007", "1" * 20])
    def test_accepts_valid(self, pid: str) -> None:
        """Valid ids are returned unchanged (no int normalization)."""
        assert validate_project_id(pid) == pid

    @pytest.mark.parametrize(
        "pid", ["", "12ab", "-1", "1.0", "../etc", "1" * 21, " 12", "12 "]
    )
    def test_rejects_invalid(self, pid: str) -> None:
        """Non-numeric, empty, over-long, or padded ids raise ``ValueError``."""
        with pytest.raises(ValueError):
            validate_project_id(pid)

    def test_leading_zeros_preserved(self) -> None:
        """The opaque string form (leading zeros) survives validation."""
        assert validate_project_id("007") == "007"


class TestMemoryDirBuilders:
    """The user/project memory-dir builders produce the expected layout."""

    def test_user_memory_dir(self) -> None:
        """User memory lives under ``<root>/accounts/{name}/memory``."""
        root = Path("/tmp/root")
        assert user_memory_dir("personal", root=root) == (
            root / "accounts" / "personal" / "memory"
        )

    def test_project_memory_dir(self) -> None:
        """Project memory lives under ``<root>/projects/{id}/memory``."""
        root = Path("/tmp/root")
        assert project_memory_dir("3713224", root=root) == (
            root / "projects" / "3713224" / "memory"
        )

    def test_user_dir_validates_name(self) -> None:
        """An invalid account name is rejected before a path is built."""
        with pytest.raises(ValueError):
            user_memory_dir("../escape", root=Path("/tmp/root"))

    def test_project_dir_validates_id(self) -> None:
        """An invalid project id is rejected before a path is built."""
        with pytest.raises(ValueError):
            project_memory_dir("../escape", root=Path("/tmp/root"))


class TestResolveKey:
    """``resolve_key`` joins in-tree and rejects escapes."""

    def test_simple_key(self) -> None:
        """A plain key resolves directly under the scope dir."""
        scope = Path("/tmp/root/projects/1/memory")
        assert resolve_key(scope, "notes.md") == scope / "notes.md"

    def test_nested_key(self) -> None:
        """A nested key resolves to the corresponding subpath."""
        scope = Path("/tmp/root/projects/1/memory")
        assert resolve_key(scope, "context/goals.md") == (
            scope / "context" / "goals.md"
        )

    @pytest.mark.parametrize("key", ["", "   ", "\t"])
    def test_empty_key_rejected(self, key: str) -> None:
        """Empty or whitespace-only keys raise ``ValueError``."""
        with pytest.raises(ValueError):
            resolve_key(Path("/tmp/root/memory"), key)

    @pytest.mark.parametrize("key", ["/etc/passwd", "/abs/path"])
    def test_absolute_key_rejected(self, key: str) -> None:
        """Absolute keys raise ``ValueError``."""
        with pytest.raises(ValueError):
            resolve_key(Path("/tmp/root/memory"), key)

    @pytest.mark.parametrize(
        "key", ["../secrets", "../../etc/passwd", "a/../../b", "sub/../../out"]
    )
    def test_traversal_rejected(self, key: str) -> None:
        """Keys that escape the scope via ``..`` raise ``ValueError``."""
        with pytest.raises(ValueError):
            resolve_key(Path("/tmp/root/memory"), key)

    def test_dot_key_rejected(self) -> None:
        """A key resolving to the scope dir itself is not a valid note key."""
        with pytest.raises(ValueError):
            resolve_key(Path("/tmp/root/memory"), ".")

    def test_interior_dotdot_that_stays_in_scope_is_allowed(self) -> None:
        """``a/../b`` normalizes to ``b`` and stays in-tree."""
        scope = Path("/tmp/root/memory")
        assert resolve_key(scope, "a/../b.md") == scope / "b.md"
