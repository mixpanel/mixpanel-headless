"""Unit tests for the live-suite settings in ``tests/live/_live_settings.py``.

The helpers decide which account, project, and workspace a live suite uses,
so they get offline tests of their own. No test here builds a real
Workspace or reaches the network: Workspace is replaced by a fake, and the
config is a tmp file with fake accounts.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import tests.live._live_settings as live_settings
from mixpanel_headless import Session
from mixpanel_headless.exceptions import ConfigError

_CONFIG = """
[accounts.live-oauth]
type = "oauth_browser"
region = "us"
default_project = "111"

[accounts.no-project]
type = "oauth_browser"
region = "us"

[active]
account = "live-oauth"
workspace = 999
"""
"""A config with one usable account, one without a project, and an active workspace."""

_SETTINGS_FILE = Path(live_settings.__file__)


class _FakeWorkspace:
    """Stands in for Workspace: keeps the session and never reaches the network."""

    def __init__(self, session: Session, *, report_project: str | None = None) -> None:
        """Keep the session; ``report_project`` fakes a different resolved project.

        Args:
            session: The session the helper built.
            report_project: A project id to report instead of the session's.
        """
        self.session = session
        self._report_project = report_project
        self.closed = False

    @property
    def account(self) -> Any:
        """Return the session account."""
        return self.session.account

    @property
    def project(self) -> Any:
        """Return the session project, or a fake one when asked to."""
        if self._report_project is not None:
            return type("P", (), {"id": self._report_project})()
        return self.session.project

    @property
    def workspace(self) -> Any:
        """Return the session workspace."""
        return self.session.workspace

    def resolve_workspace_id(self) -> int:
        """Return a fixed workspace id, as the pinned project would resolve it."""
        return 77

    def close(self) -> None:
        """Record the close."""
        self.closed = True


@pytest.fixture
def live_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the helpers at a tmp config and clear the live settings.

    Returns:
        The tmp config path.
    """
    path = tmp_path / "config.toml"
    path.write_text(_CONFIG, encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(
        live_settings, "LOCATION_OVERRIDES", {"MP_CONFIG_PATH": str(path)}
    )
    monkeypatch.setattr(live_settings, "_cli_target", None)
    for name in (live_settings.LIVE_ACCOUNT_ENV, live_settings.WRITE_PROJECT_ENV):
        monkeypatch.delenv(name, raising=False)
    return path


@pytest.fixture
def fake_workspaces(monkeypatch: pytest.MonkeyPatch) -> list[_FakeWorkspace]:
    """Replace Workspace in the helper module with the fake; collect instances.

    Returns:
        The fake Workspaces built so far.
    """
    built: list[_FakeWorkspace] = []

    def factory(*, session: Session) -> _FakeWorkspace:
        """Build and record a fake Workspace."""
        ws = _FakeWorkspace(session)
        built.append(ws)
        return ws

    monkeypatch.setattr(live_settings, "Workspace", factory)
    return built


def _load_fresh_settings(name: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import a separate copy of the settings module under the current environment.

    Args:
        name: The module name for the copy; registered in ``sys.modules``
            for the test only.
        monkeypatch: Removes the registration after the test.

    Returns:
        The freshly executed module; the real module is not touched.
    """
    spec = importlib.util.spec_from_file_location(name, _SETTINGS_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


# =============================================================================
# Account and write project settings
# =============================================================================


class TestLiveAccount:
    """live_account() reads MP_LIVE_ACCOUNT and skips when it is unset."""

    def test_unset_skips(self, live_config: Path) -> None:
        """An unset account skips the test."""
        with pytest.raises(pytest.skip.Exception, match="MP_LIVE_ACCOUNT is not set"):
            live_settings.live_account()

    def test_set_returns_name(
        self, live_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A set account returns its name."""
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        assert live_settings.live_account() == "live-oauth"


class TestWriteProject:
    """write_project() reads MP_LIVE_WRITE_PROJECT and skips when it is unset."""

    def test_unset_skips(self, live_config: Path) -> None:
        """An unset write project skips the test."""
        with pytest.raises(pytest.skip.Exception, match="MP_LIVE_WRITE_PROJECT"):
            live_settings.write_project()


class TestSkipMarks:
    """The skip marks read the environment when the module is imported."""

    def test_marks_skip_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both marks skip when their variables are unset."""
        monkeypatch.delenv("MP_LIVE_ACCOUNT", raising=False)
        monkeypatch.delenv("MP_LIVE_WRITE_PROJECT", raising=False)
        module = _load_fresh_settings("_live_settings_unset", monkeypatch)
        assert module.requires_live_account.args == (True,)
        assert module.requires_write_project.args == (True,)

    def test_marks_run_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both marks let tests run when their variables are set."""
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        monkeypatch.setenv("MP_LIVE_WRITE_PROJECT", "222")
        module = _load_fresh_settings("_live_settings_set", monkeypatch)
        assert module.requires_live_account.args == (False,)
        assert module.requires_write_project.args == (False,)

    def test_location_overrides_captured_at_import(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The config and storage locations are captured when the module loads."""
        monkeypatch.setenv("MP_CONFIG_PATH", str(tmp_path / "c.toml"))
        monkeypatch.setenv("MP_STORAGE_DIR", str(tmp_path / "store"))
        monkeypatch.delenv("MP_OAUTH_STORAGE_DIR", raising=False)
        module = _load_fresh_settings("_live_settings_locations", monkeypatch)
        assert dict(module.LOCATION_OVERRIDES) == {
            "MP_CONFIG_PATH": str(tmp_path / "c.toml"),
            "MP_STORAGE_DIR": str(tmp_path / "store"),
        }


# =============================================================================
# The pinned session
# =============================================================================


class TestLiveSession:
    """live_session() pins account, project, and workspace from the settings only."""

    def test_read_suite_uses_default_project(
        self, live_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A read suite takes the account's default project and no workspace."""
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        session = live_settings.live_session()
        assert session.account.name == "live-oauth"
        assert session.project.id == "111"
        assert session.workspace is None

    def test_active_workspace_is_not_inherited(
        self, live_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The config's [active] workspace never reaches the pinned session."""
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        monkeypatch.setenv("MP_LIVE_WRITE_PROJECT", "222")
        assert live_settings.live_session(write=True).workspace is None

    def test_write_suite_pins_write_project(
        self, live_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A write suite uses MP_LIVE_WRITE_PROJECT, not the default project."""
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        monkeypatch.setenv("MP_LIVE_WRITE_PROJECT", "222")
        session = live_settings.live_session(write=True)
        assert (session.account.name, session.project.id) == ("live-oauth", "222")

    def test_environment_overrides_are_ignored(
        self, live_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Credential, project, workspace, and bridge variables change nothing."""
        bridge = tmp_path / "bridge.json"
        bridge.write_text("not json", encoding="utf-8")
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        monkeypatch.setenv("MP_USERNAME", "env-user")
        monkeypatch.setenv("MP_SECRET", "env-secret")
        monkeypatch.setenv("MP_OAUTH_TOKEN", "env-token")
        monkeypatch.setenv("MP_PROJECT_ID", "3")
        monkeypatch.setenv("MP_REGION", "eu")
        monkeypatch.setenv("MP_WORKSPACE_ID", "5")
        monkeypatch.setenv("MP_AUTH_FILE", str(bridge))
        session = live_settings.live_session()
        assert session.account.name == "live-oauth"
        assert session.account.region == "us"
        assert session.project.id == "111"
        assert session.workspace is None

    def test_write_suite_without_write_project_skips(
        self, live_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A write suite skips before it reads the config when the project is unset."""
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        monkeypatch.setattr(
            live_settings,
            "LOCATION_OVERRIDES",
            {"MP_CONFIG_PATH": "/nonexistent/c.toml"},
        )
        with pytest.raises(pytest.skip.Exception, match="MP_LIVE_WRITE_PROJECT"):
            live_settings.live_session(write=True)

    def test_account_unset_skips(self, live_config: Path) -> None:
        """No account skips the test."""
        with pytest.raises(pytest.skip.Exception, match="MP_LIVE_ACCOUNT"):
            live_settings.live_session()

    def test_account_without_project_skips(
        self, live_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A read suite skips when the account has no default project."""
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "no-project")
        with pytest.raises(pytest.skip.Exception, match="no default_project"):
            live_settings.live_session()

    def test_unknown_account_raises(
        self, live_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An account that the config lacks is an error, not a skip."""
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "missing")
        with pytest.raises(ConfigError):
            live_settings.live_session()


# =============================================================================
# The Workspace and the CLI target
# =============================================================================


class TestLiveWorkspace:
    """live_workspace() builds from the pinned session and records the CLI target."""

    def test_read_suite(
        self,
        live_config: Path,
        fake_workspaces: list[_FakeWorkspace],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A read suite gets the pinned Workspace and records no CLI target."""
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        ws: object = live_settings.live_workspace()
        assert ws is fake_workspaces[0]
        assert fake_workspaces[0].session.project.id == "111"
        assert live_settings._cli_target is None

    def test_write_suite_records_target(
        self,
        live_config: Path,
        fake_workspaces: list[_FakeWorkspace],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A write suite records the account, project, and resolved workspace."""
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        monkeypatch.setenv("MP_LIVE_WRITE_PROJECT", "222")
        live_settings.live_workspace(write=True)
        assert live_settings._cli_target == live_settings.LiveTarget(
            account="live-oauth", project="222", workspace=77
        )

    def test_mismatch_fails_and_closes(
        self, live_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Workspace that reports another project fails the test and is closed."""
        built: list[_FakeWorkspace] = []

        def factory(*, session: Session) -> _FakeWorkspace:
            """Build a fake that reports project 3."""
            ws = _FakeWorkspace(session, report_project="3")
            built.append(ws)
            return ws

        monkeypatch.setattr(live_settings, "Workspace", factory)
        monkeypatch.setenv("MP_LIVE_ACCOUNT", "live-oauth")
        with pytest.raises(pytest.fail.Exception, match="not the pinned"):
            live_settings.live_workspace()
        assert built[0].closed is True


class TestLiveCliCommand:
    """live_cli_command() pins account, project, and workspace as global flags."""

    def test_without_target_fails(self, live_config: Path) -> None:
        """The CLI helper refuses to run before a write suite pinned the target."""
        with pytest.raises(pytest.fail.Exception, match="live_workspace"):
            live_settings.live_cli_command("lexicon", "tags", "list")

    def test_with_target(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The command carries the pinned flags before the arguments."""
        monkeypatch.setattr(
            live_settings,
            "_cli_target",
            live_settings.LiveTarget(account="live-oauth", project="222", workspace=77),
        )
        assert live_settings.live_cli_command("lexicon", "tags", "list") == [
            "uv",
            "run",
            "mp",
            "--account",
            "live-oauth",
            "--project",
            "222",
            "--workspace",
            "77",
            "lexicon",
            "tags",
            "list",
        ]


class TestLiveCliEnv:
    """live_cli_env() removes overrides and neutralizes the bridge."""

    def test_removes_overrides_and_sets_locations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Override and location variables are dropped; captured locations return."""
        for name in live_settings.OVERRIDE_ENV:
            monkeypatch.setenv(name, "from-shell")
        for name in live_settings.LOCATION_ENV:
            monkeypatch.setenv(name, "scrubbed-or-changed")
        monkeypatch.setenv("KEEP_ME", "yes")
        captured = {"MP_CONFIG_PATH": str(tmp_path / "c.toml")}
        monkeypatch.setattr(live_settings, "LOCATION_OVERRIDES", captured)
        monkeypatch.setattr(live_settings, "NO_BRIDGE_PATH", tmp_path / "none.json")

        env = live_settings.live_cli_env()

        for name in live_settings.OVERRIDE_ENV:
            if name != "MP_AUTH_FILE":
                assert name not in env
        assert env["MP_AUTH_FILE"] == str(tmp_path / "none.json")
        assert env["MP_CONFIG_PATH"] == str(tmp_path / "c.toml")
        assert "MP_STORAGE_DIR" not in env
        assert "MP_OAUTH_STORAGE_DIR" not in env
        assert env["KEEP_ME"] == "yes"

    def test_override_list(self) -> None:
        """The removal list covers credentials, axes, the bridge, and CLI flags."""
        assert set(live_settings.OVERRIDE_ENV) == {
            "MP_USERNAME",
            "MP_SECRET",
            "MP_OAUTH_TOKEN",
            "MP_PROJECT_ID",
            "MP_REGION",
            "MP_WORKSPACE_ID",
            "MP_AUTH_FILE",
            "MP_ACCOUNT",
            "MP_TARGET",
        }

    def test_existing_no_bridge_path_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The helper refuses to run when the no-bridge path exists."""
        present = tmp_path / "auth.json"
        present.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(live_settings, "NO_BRIDGE_PATH", present)
        with pytest.raises(pytest.fail.Exception, match="needs it absent"):
            live_settings.live_cli_env()
