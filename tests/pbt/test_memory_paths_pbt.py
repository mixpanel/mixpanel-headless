"""Property-based tests for the pure memory path/validation logic.

Invariants verified across randomized inputs (the I/O-free ``paths`` module
is the mutmut target, so these properties carry the mutation-kill weight):

- Valid id/name + any non-escaping key -> resolved path is always inside scope.
- Any escaping ``..`` key -> always raises.
- Any invalid id/name -> always raises, regardless of key.
- ``resolve_key`` is deterministic/idempotent for fixed inputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.memory.paths import (
    project_memory_dir,
    resolve_key,
    user_memory_dir,
    validate_account_name,
    validate_project_id,
)

_NAME_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
_SEGMENT_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."

account_names = st.text(alphabet=_NAME_ALPHABET, min_size=1, max_size=64)
project_ids = st.from_regex(r"\A\d{1,20}\Z", fullmatch=True)
# Segments that never equal ".." and are never empty -> a key that cannot
# escape its scope.
_safe_segments = st.text(alphabet=_SEGMENT_ALPHABET, min_size=1, max_size=12).filter(
    lambda s: s not in ("..", ".")
)
safe_keys = st.lists(_safe_segments, min_size=1, max_size=5).map("/".join)

_ROOT = Path("/srv/mp")


class TestScopeDirInvariants:
    """The memory-dir builders always produce the documented layout."""

    @given(name=account_names)
    def test_user_dir_shape(self, name: str) -> None:
        """User memory dir ends with ``accounts/{name}/memory`` under root."""
        d = user_memory_dir(name, root=_ROOT)
        assert d == _ROOT / "accounts" / name / "memory"
        assert d.parts[-3:] == ("accounts", name, "memory")

    @given(pid=project_ids)
    def test_project_dir_shape(self, pid: str) -> None:
        """Project memory dir ends with ``projects/{id}/memory`` under root."""
        d = project_memory_dir(pid, root=_ROOT)
        assert d == _ROOT / "projects" / pid / "memory"
        assert d.parts[-3:] == ("projects", pid, "memory")


class TestResolveKeyContainment:
    """``resolve_key`` keeps safe keys in-tree and is stable."""

    @given(pid=project_ids, key=safe_keys)
    def test_safe_key_stays_in_scope(self, pid: str, key: str) -> None:
        """Any non-escaping key resolves strictly under the scope dir."""
        scope = project_memory_dir(pid, root=_ROOT)
        resolved = resolve_key(scope, key)
        assert scope in resolved.parents

    @given(pid=project_ids, key=safe_keys)
    def test_idempotent(self, pid: str, key: str) -> None:
        """``resolve_key`` returns the same path for the same inputs."""
        scope = project_memory_dir(pid, root=_ROOT)
        assert resolve_key(scope, key) == resolve_key(scope, key)

    @given(depth=st.integers(min_value=1, max_value=30))
    def test_escaping_key_always_raises(self, depth: int) -> None:
        """Enough leading ``..`` segments always escape and raise."""
        scope = _ROOT / "projects" / "1" / "memory"
        key = "/".join([".."] * (depth + len(scope.parts))) + "/x"
        with pytest.raises(ValueError):
            resolve_key(scope, key)


class TestValidatorRejection:
    """Invalid identifiers always raise, regardless of anything else."""

    @given(bad=st.text(min_size=1).filter(lambda s: not s.isdigit() or len(s) > 20))
    def test_invalid_project_id_raises(self, bad: str) -> None:
        """Non-numeric or over-long project ids always raise."""
        with pytest.raises(ValueError):
            validate_project_id(bad)

    @given(
        name=st.text(min_size=0, max_size=80).filter(
            lambda s: not (0 < len(s) <= 64 and all(c in _NAME_ALPHABET for c in s))
        )
    )
    def test_invalid_account_name_raises(self, name: str) -> None:
        """Names outside ``^[a-zA-Z0-9_-]{1,64}$`` always raise."""
        with pytest.raises(ValueError):
            validate_account_name(name)
