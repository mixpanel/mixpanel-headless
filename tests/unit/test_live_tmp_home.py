"""Unit tests for the tmp home isolation of the 042 live suite.

``tests/live/conftest_042.py`` points HOME and the storage roots at a tmp
directory so the OAuth browser tests never touch the real ``~/.mp/``. These
offline tests check that both storage roots stay inside the tmp home, also
when a run exports ``MP_STORAGE_DIR``, and that the token copy lands there.
No test builds a Workspace or reaches the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tests.live.conftest_042 as conftest_042
from mixpanel_headless._internal.auth.storage import account_dir, accounts_root


class TestIsolateMpHome:
    """isolate_mp_home() keeps every storage root inside the tmp home."""

    def test_sets_home_config_and_both_storage_roots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HOME, the config path, and both storage roots point into the tmp home."""
        home = conftest_042.isolate_mp_home(tmp_path, monkeypatch)
        assert home == tmp_path
        assert (tmp_path / ".mp").is_dir()
        assert accounts_root().is_relative_to(tmp_path)
        assert account_dir("personal").is_relative_to(tmp_path)

    def test_exported_storage_dir_is_replaced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exported MP_STORAGE_DIR, which account_dir() prefers, is replaced too."""
        outside = tmp_path / "outside-storage"
        monkeypatch.setenv("MP_STORAGE_DIR", str(outside))
        home = tmp_path / "home"
        home.mkdir()

        conftest_042.isolate_mp_home(home, monkeypatch)

        assert account_dir("personal").is_relative_to(home)
        assert not account_dir("personal").is_relative_to(outside)


class TestCopyLiveAccountTokens:
    """copy_live_account_tokens() writes where the resolver reads, inside the tmp home."""

    def test_copy_lands_in_tmp_home_with_exported_storage_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With MP_STORAGE_DIR exported, the tokens still land inside the tmp home."""
        real_root = tmp_path / "real-accounts"
        (real_root / "live-oauth").mkdir(parents=True)
        (real_root / "live-oauth" / "tokens.json").write_text(
            json.dumps(
                {"access_token": "a", "expires_at": "2099-01-01T00:00:00+00:00"}
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(conftest_042, "REAL_ACCOUNTS_ROOT", real_root)
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        monkeypatch.setenv("MP_STORAGE_DIR", str(tmp_path / "outside-storage"))
        home = tmp_path / "home"
        home.mkdir()
        conftest_042.isolate_mp_home(home, monkeypatch)

        dst = conftest_042.copy_live_account_tokens(home, "personal")

        assert dst == account_dir("personal") / "tokens.json"
        assert dst.is_relative_to(home)
        assert json.loads(dst.read_text(encoding="utf-8"))["access_token"] == "a"

    def test_destination_outside_home_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without isolation, a destination outside the tmp home fails the test."""
        real_root = tmp_path / "real-accounts"
        (real_root / "live-oauth").mkdir(parents=True)
        (real_root / "live-oauth" / "tokens.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(conftest_042, "REAL_ACCOUNTS_ROOT", real_root)
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        monkeypatch.setenv("MP_STORAGE_DIR", str(tmp_path / "outside-storage"))
        home = tmp_path / "home"
        home.mkdir()

        with pytest.raises(pytest.fail.Exception, match="outside the tmp home"):
            conftest_042.copy_live_account_tokens(home, "personal")
