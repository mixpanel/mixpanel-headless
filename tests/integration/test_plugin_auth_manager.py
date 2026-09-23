"""Integration tests for the mixpanel-plugin auth_manager.py script.

Each subcommand is exercised via subprocess against a fixture config in
a tmp ``~/.mp/``. Tests assert the JSON output shape: one object per
run, with ``schema_version: 1`` and a discriminated ``state``.

Subprocess isolation is mandatory: ``auth_manager.py`` is shipped as a
standalone script invoked from a Claude Code skill, so the
publish-time invocation pattern is exactly ``python <path> <args>``
with ``HOME`` pointing at a hermetic tmp dir.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_AUTH_MANAGER = (
    REPO_ROOT / "mixpanel-plugin" / "skills" / "auth" / "scripts" / "auth_manager.py"
)


def _hermetic_env(tmp_home: Path, env_extra: dict[str, str] | None) -> dict[str, str]:
    """Build the near-empty subprocess env shared by every test subprocess.

    Starts from a near-empty env so MP_* leakage from the developer shell
    cannot bleed into the subprocess. Keeps PATH (so ``python`` resolves)
    and the venv-related vars so the subprocess reaches the same
    ``mixpanel_headless`` install that the parent test process imported.

    Args:
        tmp_home: Tmp ``$HOME`` containing isolated ``.mp/``.
        env_extra: Extra env vars layered on top, or ``None``.

    Returns:
        The env mapping for ``subprocess.run``.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_home),
        "MP_CONFIG_PATH": str(tmp_home / ".mp" / "config.toml"),
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }
    for key in ("VIRTUAL_ENV", "PYTHONUSERBASE", "PYTHONHOME"):
        if key in os.environ:
            env[key] = os.environ[key]
    if env_extra:
        env.update(env_extra)
    return env


_LIBRARY_SESSION_SNIPPET = """
import json
from mixpanel_headless._internal.auth.resolver import resolve_session
from mixpanel_headless._internal.config import ConfigManager
s = resolve_session(config=ConfigManager())
print(json.dumps({
    "account": s.account.name,
    "project": s.project.id,
    "workspace": s.workspace.id if s.workspace is not None else None,
}))
"""


def _library_session(
    tmp_home: Path, env_extra: dict[str, str] | None = None
) -> dict[str, Any]:
    """Resolve the session with the library itself, in the same hermetic env.

    Args:
        tmp_home: Tmp ``$HOME`` containing isolated ``.mp/``.
        env_extra: Extra env vars layered on top, or ``None``.

    Returns:
        ``{"account": name, "project": id, "workspace": id | None}`` as the
        library's ``resolve_session`` reports it.
    """
    result = subprocess.run(
        [sys.executable, "-c", _LIBRARY_SESSION_SNIPPET],
        capture_output=True,
        text=True,
        env=_hermetic_env(tmp_home, env_extra),
        check=True,
    )
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def _run(
    *args: str,
    tmp_home: Path,
    env_extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run ``auth_manager.py`` with ``args``; return parsed JSON from stdout.

    Hermetic: starts from a clean env containing only PATH/HOME-derived
    essentials, sets ``HOME``/``MP_CONFIG_PATH`` to ``tmp_home``, then
    layers in ``env_extra``. Asserts the process emitted exactly one JSON
    object, and that every response carries ``schema_version`` and
    ``state``.

    Args:
        *args: CLI args after the script path.
        tmp_home: Tmp ``$HOME`` containing isolated ``.mp/``.
        env_extra: Extra env vars (e.g. ``MP_OAUTH_TOKEN`` for env-auth tests).

    Returns:
        Parsed JSON dict from stdout.
    """
    result = subprocess.run(
        [sys.executable, str(PLUGIN_AUTH_MANAGER), *args],
        capture_output=True,
        text=True,
        env=_hermetic_env(tmp_home, env_extra),
        check=False,
    )
    if not result.stdout.strip():
        pytest.fail(
            f"auth_manager produced no JSON; stderr={result.stderr!r} args={args!r}"
        )
    try:
        payload: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"auth_manager stdout is not valid JSON: {exc}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    # Every response carries schema_version.
    assert payload.get("schema_version") == 1, (
        f"missing schema_version=1 in {payload!r}"
    )
    # Every response carries a discriminated state.
    assert payload.get("state") in {
        "ok",
        "needs_account",
        "needs_project",
        "error",
    }, f"unknown state in {payload!r}"
    return payload


@pytest.fixture
def tmp_home(tmp_path: Path) -> Generator[Path, None, None]:
    """Provide a tmp ``$HOME`` with an isolated ``.mp/`` directory."""
    (tmp_path / ".mp").mkdir(mode=0o700, exist_ok=True)
    yield tmp_path


@pytest.fixture
def populated_home(tmp_home: Path) -> Path:
    """Tmp home seeded with a single service-account v3 config."""
    config = tmp_home / ".mp" / "config.toml"
    config.write_text(
        "\n".join(
            [
                "[active]",
                'account = "team"',
                "",
                "[accounts.team]",
                'type = "service_account"',
                'region = "us"',
                'default_project = "3713224"',
                'username = "sa.user"',
                'secret = "fake-secret"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    return tmp_home


# =============================================================================
# `session` — discriminated state
# =============================================================================


class TestSessionSubcommand:
    """``session`` subcommand emits the right state for each config posture."""

    def test_empty_config_returns_needs_account(self, tmp_home: Path) -> None:
        """An empty ``~/.mp/`` produces ``state="needs_account"`` + onboarding hints."""
        payload = _run("session", tmp_home=tmp_home)
        assert payload["state"] == "needs_account"
        assert isinstance(payload.get("next"), list)
        assert payload["next"], "needs_account should suggest a next command"
        # The first suggestion must be a usable mp command. ``mp login``
        # is the one-shot onboarding default, ahead of the multi-step
        # ``mp account add``.
        assert payload["next"][0]["command"].startswith("mp login")

    def test_populated_config_returns_ok(self, populated_home: Path) -> None:
        """A configured account + default_project yields ``state="ok"``."""
        payload = _run("session", tmp_home=populated_home)
        assert payload["state"] == "ok"
        # The account always has {name, type, region}.
        assert payload["account"]["name"] == "team"
        assert payload["account"]["type"] == "service_account"
        assert payload["account"]["region"] == "us"
        # The project always has {id} when present.
        assert payload["project"]["id"] == "3713224"

    def test_oauth_browser_without_project_returns_needs_project(
        self, tmp_home: Path
    ) -> None:
        """OAuth browser account without ``default_project`` → ``needs_project``."""
        config = tmp_home / ".mp" / "config.toml"
        config.write_text(
            "\n".join(
                [
                    "[active]",
                    'account = "personal"',
                    "",
                    "[accounts.personal]",
                    'type = "oauth_browser"',
                    'region = "us"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        config.chmod(0o600)
        payload = _run("session", tmp_home=tmp_home)
        assert payload["state"] == "needs_project"
        assert payload["account"]["name"] == "personal"
        assert isinstance(payload.get("next"), list)
        assert payload["next"], "needs_project should suggest a next command"

    def test_invalid_project_id_reports_error_not_onboarding(
        self, populated_home: Path
    ) -> None:
        """A malformed ``MP_PROJECT_ID`` is reported as the config error it is.

        The account resolves fine, so the answer must not be
        ``needs_account`` onboarding; the user needs the resolver's own
        message, which names the invalid variable.
        """
        payload = _run(
            "session",
            tmp_home=populated_home,
            env_extra={"MP_PROJECT_ID": "abc"},
        )
        assert payload["state"] == "error"
        assert "MP_PROJECT_ID" in payload["error"]["message"]
        assert payload["error"]["actionable"] is True

    def test_env_only_auth_returns_ok_with_populated_axes(self, tmp_home: Path) -> None:
        """Env-only auth (no ``[active]``) MUST resolve to a fully populated ok.

        Regression: prior implementation returned ``state="ok"`` with
        ``account=None`` / ``project=None`` / ``workspace=None`` because it
        bypassed the resolver and read ``[active]`` directly.
        ``state="ok"`` requires a populated account and project.
        """
        payload = _run(
            "session",
            tmp_home=tmp_home,
            env_extra={
                "MP_USERNAME": "u",
                "MP_SECRET": "s",
                "MP_PROJECT_ID": "3713224",
                "MP_REGION": "us",
            },
        )
        assert payload["state"] == "ok"
        assert payload["account"] is not None
        assert payload["account"]["type"] == "service_account"
        assert payload["account"]["region"] == "us"
        assert payload["project"]["id"] == "3713224"
        # Source map: env supplied account + project; workspace unset → lazy.
        assert payload["source"]["account"] == "env"
        assert payload["source"]["project"] == "env"
        assert payload["source"]["workspace"] == "unset"

    def test_session_matches_library_resolution(self, tmp_home: Path) -> None:
        """``session`` reports exactly what the library's resolver returns.

        The config has no ``[active]`` block and no MP_* credentials, so the
        axes come from a source the script does not read itself (an auth
        file named by ``MP_AUTH_FILE``). The script must still report
        ``state="ok"`` with the same account / project / workspace as
        ``resolve_session``.
        """
        auth_file = tmp_home / "auth.json"
        auth_file.write_text(
            json.dumps(
                {
                    "version": 2,
                    "account": {
                        "type": "service_account",
                        "name": "courier",
                        "region": "us",
                        "username": "u",
                        "secret": "s",
                    },
                    "project": "3713224",
                    "workspace": 3448413,
                }
            ),
            encoding="utf-8",
        )
        auth_file.chmod(0o600)
        env_extra = {"MP_AUTH_FILE": str(auth_file)}
        payload = _run("session", tmp_home=tmp_home, env_extra=env_extra)
        expected = _library_session(tmp_home, env_extra)
        assert payload["state"] == "ok"
        assert payload["account"]["name"] == expected["account"] == "courier"
        assert payload["account"]["type"] == "service_account"
        assert payload["project"]["id"] == expected["project"] == "3713224"
        assert payload["workspace"]["id"] == expected["workspace"] == 3448413


# =============================================================================
# `account list/add/use` — list and mutation responses
# =============================================================================


class TestAccountListSubcommand:
    """``account list`` always returns an ``items`` list, possibly empty."""

    def test_empty_returns_items_empty(self, tmp_home: Path) -> None:
        """No accounts → ``items: []`` + onboarding suggestion."""
        payload = _run("account", "list", tmp_home=tmp_home)
        assert payload["state"] == "ok"
        assert payload["items"] == []
        # An empty list also surfaces onboarding hints.
        assert isinstance(payload.get("next"), list)

    def test_populated_returns_one_item_with_required_fields(
        self, populated_home: Path
    ) -> None:
        """Populated config → one item with {name, type, region, is_active}."""
        payload = _run("account", "list", tmp_home=populated_home)
        assert payload["state"] == "ok"
        assert len(payload["items"]) == 1
        item = payload["items"][0]
        assert item["name"] == "team"
        assert item["type"] == "service_account"
        assert item["region"] == "us"
        assert item["is_active"] is True
        # Items also carry ``referenced_by_targets``.
        assert item["referenced_by_targets"] == []


class TestAccountUseSubcommand:
    """``account use NAME`` switches the active account."""

    def test_use_existing_account(self, populated_home: Path) -> None:
        """Switching to an existing account writes ``[active].account``."""
        payload = _run("account", "use", "team", tmp_home=populated_home)
        assert payload["state"] == "ok"
        assert payload["active"]["account"] == "team"

    def test_use_missing_account_returns_error(self, tmp_home: Path) -> None:
        """Unknown name → ``state="error"``."""
        payload = _run("account", "use", "ghost", tmp_home=tmp_home)
        assert payload["state"] == "error"
        # An error response has {code, message, actionable}.
        assert payload["error"]["code"]  # non-empty class name
        assert payload["error"]["message"]
        assert isinstance(payload["error"]["actionable"], bool)


class TestErrorOutput:
    """Failures outside a handler still print one JSON error with exit 0."""

    def test_usage_error_is_json(self, tmp_home: Path) -> None:
        """A missing positional argument yields a ``USAGE_ERROR`` envelope."""
        payload = _run("account", "test", tmp_home=tmp_home)
        assert payload["state"] == "error"
        assert payload["error"]["code"] == "USAGE_ERROR"
        assert "name" in payload["error"]["message"]
        assert payload["error"]["actionable"] is False
        assert payload["error"]["usage"].startswith("usage: auth_manager.py")

    def test_account_add_is_not_a_subcommand(self, tmp_home: Path) -> None:
        """``account add`` is gone: the script never handles account secrets."""
        payload = _run("account", "add", tmp_home=tmp_home)
        assert payload["state"] == "error"
        assert payload["error"]["code"] == "USAGE_ERROR"

    def test_missing_library_is_json(self, tmp_home: Path) -> None:
        """An import failure yields an actionable error that names setup."""
        shadow = tmp_home / "shadow" / "mixpanel_headless"
        shadow.mkdir(parents=True)
        (shadow / "__init__.py").write_text(
            'raise ImportError("simulated missing library")\n', encoding="utf-8"
        )
        payload = _run(
            "session",
            tmp_home=tmp_home,
            env_extra={"PYTHONPATH": str(shadow.parent)},
        )
        assert payload["state"] == "error"
        assert payload["error"]["code"] == "LIBRARY_NOT_INSTALLED"
        assert payload["error"]["actionable"] is True
        assert "/mixpanel-headless:setup" in payload["error"]["message"]


# =============================================================================
# `target list/add/use` — referential integrity
# =============================================================================


class TestTargetSubcommand:
    """``target list/add/use`` return list and mutation responses."""

    def test_list_empty_returns_items_empty(self, tmp_home: Path) -> None:
        """No targets → empty items array."""
        payload = _run("target", "list", tmp_home=tmp_home)
        assert payload["state"] == "ok"
        assert payload["items"] == []

    def test_add_target_then_list(self, populated_home: Path) -> None:
        """Add a target → ``account list`` shows it in ``referenced_by_targets``."""
        added = _run(
            "target",
            "add",
            "ecom",
            "--account",
            "team",
            "--project",
            "3713224",
            tmp_home=populated_home,
        )
        assert added["state"] == "ok"
        assert added["added"]["name"] == "ecom"

        listing = _run("target", "list", tmp_home=populated_home)
        assert listing["state"] == "ok"
        assert len(listing["items"]) == 1
        assert listing["items"][0]["name"] == "ecom"
        assert listing["items"][0]["account"] == "team"
        assert listing["items"][0]["project"] == "3713224"

    def test_use_target_writes_active(self, populated_home: Path) -> None:
        """``target use ecom`` writes [active] atomically."""
        _run(
            "target",
            "add",
            "ecom",
            "--account",
            "team",
            "--project",
            "3713224",
            "--workspace",
            "3448413",
            tmp_home=populated_home,
        )
        used = _run("target", "use", "ecom", tmp_home=populated_home)
        assert used["state"] == "ok"
        assert used["active"]["account"] == "team"
        assert used["active"]["project"] == "3713224"
        assert used["active"]["workspace"] == 3448413


# =============================================================================
# Static guards — LoC budget + zero version branches
# =============================================================================


class TestStaticGuards:
    """Static guards on the script source."""

    def test_loc_budget_at_or_below_320(self) -> None:
        """``auth_manager.py`` body must stay ≤ 320 lines.

        The cap accommodates the enriched ``_err()`` envelope (actionable
        code derivation, cause preservation, opt-in MP_VERBOSE traceback).
        Further growth should be considered a real signal that the script
        is doing too much.
        """
        lines = PLUGIN_AUTH_MANAGER.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 320, (
            f"auth_manager.py grew to {len(lines)} lines; target is ≤ 320."
        )

    def test_zero_version_branches(self) -> None:
        """Zero ``config_version`` / ``version >= 2`` branches anywhere."""
        text = PLUGIN_AUTH_MANAGER.read_text(encoding="utf-8")
        for needle in ("config_version", "version >= 2", "if version >="):
            assert needle not in text, (
                f"auth_manager.py contains banned legacy marker {needle!r}"
            )
