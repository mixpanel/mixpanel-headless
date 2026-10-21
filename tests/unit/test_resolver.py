"""Unit tests for the single ``resolve_session`` (T020).

Per FR-017, the resolver consults sources in this priority per axis:
**env → param → target → config**. Each axis is independent —
setting a project override does NOT affect account or workspace resolution.
"""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import SecretStr

from mixpanel_headless._internal.auth.account import (
    OAuthTokenAccount,
    ServiceAccount,
)
from mixpanel_headless._internal.auth.resolver import (
    format_no_account_error,
    resolve_account_axis,
    resolve_project_axis,
    resolve_session,
    resolve_workspace_axis,
)
from mixpanel_headless._internal.config import ConfigManager
from mixpanel_headless.exceptions import ConfigError


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate ``$HOME`` under ``tmp_path`` for every test.

    No test reads files from the developer's real home directory, and the
    stray auth file tests plant their home-directory file here.
    """
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def cm(tmp_path: Path) -> ConfigManager:
    """Return a v3 ConfigManager pointing at a tmp config path with one SA."""
    cm = ConfigManager(config_path=tmp_path / "config.toml")
    cm.add_account(
        "team",
        type="service_account",
        region="us",
        default_project="3713224",
        username="team.sa",
        secret=SecretStr("team-secret"),
    )
    return cm


@pytest.fixture
def cm_with_active(cm: ConfigManager) -> ConfigManager:
    """Return a ConfigManager with ``[active].account`` set; project on the account."""
    cm.set_active(account="team")
    return cm


class TestAccountAxisPriority:
    """Order: env → param → target → config."""

    def test_explicit_param_beats_active(self, cm_with_active: ConfigManager) -> None:
        """``account=NAME`` param overrides ``[active].account``."""
        cm_with_active.add_account(
            "other",
            type="service_account",
            region="us",
            default_project="9999999",
            username="o",
            secret=SecretStr("o"),
        )
        s = resolve_session(account="other", config=cm_with_active)
        assert s.account.name == "other"

    def test_active_used_when_no_param(self, cm_with_active: ConfigManager) -> None:
        """No env / no param / no target → use ``[active].account``."""
        s = resolve_session(config=cm_with_active)
        assert s.account.name == "team"

    def test_env_quad_synthesizes_service_account(
        self,
        cm: ConfigManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Full SA env quad synthesizes a ServiceAccount, beating ``[active]``."""
        monkeypatch.setenv("MP_USERNAME", "env.user")
        monkeypatch.setenv("MP_SECRET", "env-secret")
        monkeypatch.setenv("MP_PROJECT_ID", "999")
        monkeypatch.setenv("MP_REGION", "eu")
        cm.set_active(account="team")
        s = resolve_session(config=cm)
        assert isinstance(s.account, ServiceAccount)
        assert s.account.region == "eu"
        assert s.account.username == "env.user"

    def test_oauth_token_env_synthesizes(
        self,
        cm: ConfigManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``MP_OAUTH_TOKEN`` env synthesizes an OAuthTokenAccount."""
        monkeypatch.setenv("MP_OAUTH_TOKEN", "env-bearer-tok")
        monkeypatch.setenv("MP_PROJECT_ID", "999")
        monkeypatch.setenv("MP_REGION", "us")
        s = resolve_session(config=cm)
        assert isinstance(s.account, OAuthTokenAccount)

    def test_sa_env_quad_beats_oauth_token_env(
        self,
        cm: ConfigManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When both SA quad AND OAuth token are set, SA wins (preserves PR #125)."""
        monkeypatch.setenv("MP_USERNAME", "env.user")
        monkeypatch.setenv("MP_SECRET", "env-secret")
        monkeypatch.setenv("MP_OAUTH_TOKEN", "env-bearer")
        monkeypatch.setenv("MP_PROJECT_ID", "999")
        monkeypatch.setenv("MP_REGION", "us")
        s = resolve_session(config=cm)
        assert isinstance(s.account, ServiceAccount)


class TestProjectAxisPriority:
    """Order: env → param → target → config."""

    def test_explicit_param_beats_active(self, cm_with_active: ConfigManager) -> None:
        """``project=ID`` param overrides ``account.default_project``."""
        s = resolve_session(project="888", config=cm_with_active)
        assert s.project.id == "888"

    def test_env_beats_param(
        self,
        cm_with_active: ConfigManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Per FR-017 + spec, env wins over the explicit param too.

        ``MP_PROJECT_ID`` overrides any project= argument.
        """
        monkeypatch.setenv("MP_PROJECT_ID", "777")
        s = resolve_session(project="888", config=cm_with_active)
        assert s.project.id == "777"

    def test_active_used_when_no_param(self, cm_with_active: ConfigManager) -> None:
        """Account's ``default_project`` used when no override."""
        s = resolve_session(config=cm_with_active)
        assert s.project.id == "3713224"

    def test_missing_project_axis_raises(self, tmp_path: Path) -> None:
        """No env / param / target AND account has no default_project → ConfigError."""
        cm = ConfigManager(config_path=tmp_path / "config.toml")
        # Add an oauth_browser account (default_project optional) so the
        # account axis resolves but the project axis cannot.
        cm.add_account("personal", type="oauth_browser", region="us")
        cm.set_active(account="personal")
        with pytest.raises(ConfigError):
            resolve_session(config=cm)


class TestWorkspaceAxisPriority:
    """Workspace axis can be None (lazy-resolve later)."""

    def test_param_overrides_active(self, cm_with_active: ConfigManager) -> None:
        """``workspace=N`` param overrides ``[active].workspace``."""
        cm_with_active.set_active(workspace=99)
        s = resolve_session(workspace=42, config=cm_with_active)
        assert s.workspace is not None
        assert s.workspace.id == 42

    def test_env_overrides_param(
        self,
        cm_with_active: ConfigManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``MP_WORKSPACE_ID`` env overrides any param."""
        monkeypatch.setenv("MP_WORKSPACE_ID", "100")
        s = resolve_session(workspace=42, config=cm_with_active)
        assert s.workspace is not None
        assert s.workspace.id == 100

    def test_workspace_none_when_unset(self, cm_with_active: ConfigManager) -> None:
        """No source → workspace remains None (lazy-resolve)."""
        s = resolve_session(config=cm_with_active)
        assert s.workspace is None


class TestTargetMutualExclusion:
    """``target=`` must not combine with ``account=``/``project=``/``workspace=``."""

    def test_target_with_account_raises(self, cm_with_active: ConfigManager) -> None:
        """``target=`` + ``account=`` raises ValueError."""
        cm_with_active.add_target("ecom", account="team", project="3018488")
        with pytest.raises(ValueError):
            resolve_session(target="ecom", account="team", config=cm_with_active)

    def test_target_with_project_raises(self, cm_with_active: ConfigManager) -> None:
        """``target=`` + ``project=`` raises ValueError."""
        cm_with_active.add_target("ecom", account="team", project="3018488")
        with pytest.raises(ValueError):
            resolve_session(target="ecom", project="999", config=cm_with_active)

    def test_target_with_workspace_raises(self, cm_with_active: ConfigManager) -> None:
        """``target=`` + ``workspace=`` raises ValueError."""
        cm_with_active.add_target("ecom", account="team", project="3018488")
        with pytest.raises(ValueError):
            resolve_session(target="ecom", workspace=42, config=cm_with_active)

    def test_target_alone_resolves(self, cm_with_active: ConfigManager) -> None:
        """``target=`` alone applies all three axes from the target block."""
        cm_with_active.add_target(
            "ecom", account="team", project="3018488", workspace=42
        )
        s = resolve_session(target="ecom", config=cm_with_active)
        assert s.account.name == "team"
        assert s.project.id == "3018488"
        assert s.workspace is not None
        assert s.workspace.id == 42


class TestNoSideEffects:
    """Resolver is pure — no env mutation, no /me HTTP, no token reads."""

    def test_does_not_mutate_environ(
        self,
        cm_with_active: ConfigManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``resolve_session`` never modifies ``os.environ``."""
        monkeypatch.setenv("UNRELATED_VAR", "untouched")
        before: dict[str, str] = dict(os.environ)
        resolve_session(config=cm_with_active)
        after: dict[str, str] = dict(os.environ)
        assert before == after

    def test_does_not_read_oauth_tokens(self, cm: ConfigManager) -> None:
        """``resolve_session`` does not read on-disk token files.

        For ``oauth_browser`` accounts, the resolver returns a Session whose
        ``account`` references the account; the actual token is fetched
        lazily by ``MixpanelAPIClient`` when a request goes out, not at
        Session construction time.
        """
        cm.add_account(
            "personal", type="oauth_browser", region="us", default_project="3713224"
        )
        cm.set_active(account="personal")
        # No tokens.json at any path — should still construct a Session.
        s = resolve_session(config=cm)
        assert s.account.name == "personal"


class TestErrorMessages:
    """ConfigError messages match the multi-line format from FR-024."""

    def test_no_account_lists_options(self, cm: ConfigManager) -> None:
        """No env / no param / no target / no config → multi-line error."""
        # cm has accounts but no [active].account; no env vars set.
        with pytest.raises(ConfigError) as excinfo:
            resolve_session(config=cm)
        msg = str(excinfo.value)
        # Should mention every fix path (per spec FR-024).
        assert "account" in msg.lower()


class TestCrossSourceOrdering:
    """Inter-source priority for the resolver chain (env > param > target > config).

    The per-axis priority tests above lock the *first* source that wins for a
    given case. This class locks the *interaction* between sources — env
    beating target — which is the real-world matrix that powers the
    redesign's "single source of truth" promise. Without these, a future
    refactor could swap two layers in ``_resolve_*_axis`` and no per-axis
    test would fail.
    """

    # ── Account axis ──────────────────────────────────────────────────

    def test_env_sa_quad_beats_target(
        self,
        cm_with_active: ConfigManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SA env quad synthesizes an account that wins over target.account."""
        cm_with_active.add_target(
            "ecom", account="team", project="3713224", workspace=42
        )
        monkeypatch.setenv("MP_USERNAME", "env.user")
        monkeypatch.setenv("MP_SECRET", "env-secret")
        monkeypatch.setenv("MP_PROJECT_ID", "999")
        monkeypatch.setenv("MP_REGION", "us")
        s = resolve_session(target="ecom", config=cm_with_active)
        # Env quad synthesizes a synthetic name; the important assertion is
        # that ``team`` (from the target) is NOT what we got.
        assert s.account.name != "team"

    # ── Project axis ──────────────────────────────────────────────────

    def test_env_project_beats_target(
        self,
        cm_with_active: ConfigManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``MP_PROJECT_ID`` env beats target.project."""
        cm_with_active.add_target(
            "ecom", account="team", project="3018488", workspace=42
        )
        monkeypatch.setenv("MP_PROJECT_ID", "5555555")
        s = resolve_session(target="ecom", config=cm_with_active)
        assert s.project.id == "5555555"

    # ── Workspace axis ────────────────────────────────────────────────

    def test_env_workspace_beats_target(
        self,
        cm_with_active: ConfigManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``MP_WORKSPACE_ID`` env beats target.workspace."""
        cm_with_active.add_target(
            "ecom", account="team", project="3713224", workspace=77
        )
        monkeypatch.setenv("MP_WORKSPACE_ID", "999")
        s = resolve_session(target="ecom", config=cm_with_active)
        assert s.workspace is not None
        assert s.workspace.id == 999


# ── Stray credential files ────────────────────────────────────────────

_StrayLocation = Literal["env_var", "home", "cwd"]

_STRAY_LOCATIONS = [
    pytest.param(("env_var",), id="env-var"),
    pytest.param(("home",), id="home"),
    pytest.param(("cwd",), id="cwd"),
    pytest.param(("env_var", "home", "cwd"), id="all-three"),
]


def _stray_auth_payload() -> dict[str, Any]:
    """Return a valid v2 credential file payload for a stray service account.

    Returns:
        A JSON-ready dict with an account, a project, a workspace, and a
        header that no config source supplies.
    """
    return {
        "version": 2,
        "account": {
            "type": "service_account",
            "name": "stray",
            "region": "eu",
            "username": "stray.user",
            "secret": "stray-secret",
        },
        "project": "5550001",
        "workspace": 777,
        "headers": {"X-Stray-Header": "planted"},
    }


def _write_stray_auth_file(path: Path) -> None:
    """Write the stray credential payload to ``path`` with mode 0o600.

    Args:
        path: Destination file; missing parent directories are created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_stray_auth_payload()), encoding="utf-8")
    path.chmod(0o600)


def _plant_stray_auth_files(
    locations: tuple[_StrayLocation, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write the stray credential file at each named location.

    The current directory always moves to an isolated directory under
    ``tmp_path``, so no file from the real working directory is in scope.

    Args:
        locations: ``"env_var"`` writes a file and points ``MP_AUTH_FILE``
            at it; ``"home"`` writes ``$HOME/.claude/mixpanel/auth.json``;
            ``"cwd"`` writes ``<cwd>/mixpanel_auth.json``.
        tmp_path: Test temp directory; ``$HOME`` already points here.
        monkeypatch: Used to set ``MP_AUTH_FILE`` and change directory.
    """
    work_dir = tmp_path / "cloned-repo"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)
    if "env_var" in locations:
        env_path = tmp_path / "planted" / "auth.json"
        _write_stray_auth_file(env_path)
        monkeypatch.setenv("MP_AUTH_FILE", str(env_path))
    if "home" in locations:
        _write_stray_auth_file(tmp_path / ".claude" / "mixpanel" / "auth.json")
    if "cwd" in locations:
        _write_stray_auth_file(work_dir / "mixpanel_auth.json")


class TestStrayAuthFileIgnored:
    """A credential file on disk never feeds ``resolve_session``.

    Three paths once held a JSON credential file that the resolver read
    with no prompt: the path in ``MP_AUTH_FILE``,
    ``~/.claude/mixpanel/auth.json``, and ``<cwd>/mixpanel_auth.json``. A
    cloned repository can plant the last one. Each test writes a valid file
    and checks that credentials come from env and config only.
    """

    @pytest.mark.parametrize("locations", _STRAY_LOCATIONS)
    def test_config_supplies_every_axis(
        self,
        locations: tuple[_StrayLocation, ...],
        cm_with_active: ConfigManager,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Account, project, workspace, and headers come from config only."""
        cm_with_active.set_active(workspace=42)
        cm_with_active.set_custom_header(name="X-Config-Header", value="kept")
        _plant_stray_auth_files(locations, tmp_path, monkeypatch)

        s = resolve_session(config=cm_with_active)

        assert s.account.name == "team"
        assert s.project.id == "3713224"
        assert s.workspace is not None
        assert s.workspace.id == 42
        assert s.headers == {"X-Config-Header": "kept"}

    @pytest.mark.parametrize("locations", _STRAY_LOCATIONS)
    def test_empty_config_raises_no_account(
        self,
        locations: tuple[_StrayLocation, ...],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With no configured account, the standard no-account error is raised."""
        empty = ConfigManager(config_path=tmp_path / "config.toml")
        _plant_stray_auth_files(locations, tmp_path, monkeypatch)

        with pytest.raises(ConfigError) as excinfo:
            resolve_session(config=empty)

        assert str(excinfo.value) == format_no_account_error()


class TestResolverSignature:
    """The resolver entry points take env, param, target, and config only."""

    @pytest.mark.parametrize(
        "func",
        [
            resolve_session,
            resolve_account_axis,
            resolve_project_axis,
            resolve_workspace_axis,
        ],
        ids=lambda f: f.__name__,
    )
    def test_takes_no_credential_file_parameter(
        self, func: Callable[..., object]
    ) -> None:
        """The function has no parameter for a pre-loaded credential file."""
        assert "bridge" not in inspect.signature(func).parameters
