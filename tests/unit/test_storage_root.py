"""Unit tests for the shared ``storage_root`` resolver.

Verifies:
- ``$MP_OAUTH_STORAGE_DIR`` override wins when set.
- Falls back to ``$HOME/.mp`` when the override is unset.
- Resolves at call time (env change between calls is honored).
- ``auth.storage._storage_root`` delegates to it (backward-compat alias).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mixpanel_headless._internal.auth.storage import _storage_root
from mixpanel_headless._internal.storage_root import storage_root


class TestStorageRootResolution:
    """``storage_root`` resolution semantics."""

    def test_env_override_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``MP_OAUTH_STORAGE_DIR`` overrides the home-based default."""
        monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", str(tmp_path))
        assert storage_root() == tmp_path

    def test_home_fallback_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the override unset, the root is ``$HOME/.mp``."""
        monkeypatch.delenv("MP_OAUTH_STORAGE_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert storage_root() == tmp_path / ".mp"

    def test_empty_override_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty override string is ignored in favor of the home default."""
        monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", "")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert storage_root() == tmp_path / ".mp"

    def test_resolves_at_call_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A change to the env var between calls is reflected immediately."""
        first = tmp_path / "one"
        second = tmp_path / "two"
        monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", str(first))
        assert storage_root() == first
        monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", str(second))
        assert storage_root() == second


class TestBackwardCompatAlias:
    """``auth.storage._storage_root`` remains a working alias."""

    def test_alias_matches_shared_resolver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The auth alias returns the same value as the shared resolver."""
        monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", str(tmp_path))
        assert _storage_root() == storage_root() == tmp_path
