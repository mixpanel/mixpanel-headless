"""Settings that choose where the live suites run and what they may change.

Two environment variables control every suite in ``tests/live`` that is not
driven by its own explicit credentials:

- ``MP_LIVE_ACCOUNT`` names a configured account. A suite skips its
  Workspace tests when it is unset, so no suite falls back to the default
  session (the active account, project, and workspace in the config, or a
  bridge file).
- ``MP_LIVE_WRITE_PROJECT`` names the one project that write suites may
  change. A write suite skips unless it is set.

A suite applies :data:`requires_live_account` (and, if it writes,
:data:`requires_write_project`) so its tests skip at collection time,
before any fixture builds a Workspace. Its Workspace fixture calls
:func:`live_workspace`, which checks the same settings again.

:func:`live_workspace` builds the Workspace from a pinned
:class:`~mixpanel_headless.Session` instead of the session resolver, so the
account, the project, and the workspace come only from these settings: the
resolver would rank ``MP_PROJECT_ID``, ``MP_WORKSPACE_ID``, credential
variables, a bridge file, and the config's ``[active]`` workspace above or
beside the account. The project is ``MP_LIVE_WRITE_PROJECT`` for a write
suite and the account's default project otherwise. The workspace is never
inherited: it resolves on first use to a workspace of the pinned project.

Subprocess ``mp`` calls use :func:`live_cli_command` and
:func:`live_cli_env`. The command passes the pinned account, project, and
workspace as global flags. The environment drops the variables that would
override them, points ``MP_AUTH_FILE`` at a path that does not exist (so no
bridge file applies), and puts back the config and storage locations.

The autouse cleanup in ``tests/conftest.py`` removes ``MP_STORAGE_DIR`` and
``MP_OAUTH_STORAGE_DIR`` before each test. This module captures the config
and storage locations at import, before any cleanup runs, and
``tests/live/conftest.py`` puts them back for every live test.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from mixpanel_headless import Project, Session, Workspace
from mixpanel_headless._internal.config import ConfigManager

LIVE_ACCOUNT_ENV: Final[str] = "MP_LIVE_ACCOUNT"
"""Names the configured account that the live suites run as."""

WRITE_PROJECT_ENV: Final[str] = "MP_LIVE_WRITE_PROJECT"
"""Names the only project id that the write suites may change."""

OVERRIDE_ENV: Final[tuple[str, ...]] = (
    "MP_USERNAME",
    "MP_SECRET",
    "MP_OAUTH_TOKEN",
    "MP_PROJECT_ID",
    "MP_REGION",
    "MP_WORKSPACE_ID",
    "MP_AUTH_FILE",
    "MP_ACCOUNT",
    "MP_TARGET",
)
"""Environment variables that rank above an account or feed the CLI's global flags.

The session resolver ranks the credential, project, workspace, and bridge
variables above an account. The CLI binds ``MP_ACCOUNT``, ``MP_PROJECT_ID``,
``MP_WORKSPACE_ID``, and ``MP_TARGET`` to its global flags, and a target
from the environment would conflict with ``--account``.
"""

LOCATION_ENV: Final[tuple[str, ...]] = (
    "MP_CONFIG_PATH",
    "MP_STORAGE_DIR",
    "MP_OAUTH_STORAGE_DIR",
)
"""Environment variables that locate the config file and the account storage."""

LOCATION_OVERRIDES: Mapping[str, str] = MappingProxyType(
    {name: os.environ[name] for name in LOCATION_ENV if os.environ.get(name)}
)
"""The config and storage locations set when this module was imported."""

NO_BRIDGE_PATH: Final[Path] = (
    Path(tempfile.gettempdir()) / "mp-live-no-bridge" / "auth.json"
)
"""A bridge path that must not exist; ``MP_AUTH_FILE`` points here for CLI calls."""

requires_live_account = pytest.mark.skipif(
    not os.environ.get(LIVE_ACCOUNT_ENV),
    reason=f"{LIVE_ACCOUNT_ENV} is not set",
)
"""Skip marker for tests that run as the ``MP_LIVE_ACCOUNT`` account."""

requires_write_project = pytest.mark.skipif(
    not os.environ.get(WRITE_PROJECT_ENV),
    reason=f"{WRITE_PROJECT_ENV} is not set; this suite writes to the project",
)
"""Skip marker for a suite that creates, changes, or deletes entities."""


@dataclass(frozen=True)
class LiveTarget:
    """The account, project, and workspace that subprocess ``mp`` calls use.

    Attributes:
        account: The ``MP_LIVE_ACCOUNT`` account name.
        project: The pinned project id.
        workspace: The workspace id that the pinned project resolved to.
    """

    account: str
    """The ``MP_LIVE_ACCOUNT`` account name."""

    project: str
    """The pinned project id."""

    workspace: int
    """The workspace id that the pinned project resolved to."""


_cli_target: LiveTarget | None = None
"""The target of the current write suite, set by :func:`live_workspace`."""


def live_account() -> str:
    """Return the ``MP_LIVE_ACCOUNT`` account name, or skip the test.

    Returns:
        The account name.
    """
    account = os.environ.get(LIVE_ACCOUNT_ENV)
    if not account:
        pytest.skip(f"{LIVE_ACCOUNT_ENV} is not set")
    return account


def write_project() -> str:
    """Return the ``MP_LIVE_WRITE_PROJECT`` project id, or skip the test.

    Returns:
        The project id that write suites may change.
    """
    project = os.environ.get(WRITE_PROJECT_ENV)
    if not project:
        pytest.skip(f"{WRITE_PROJECT_ENV} is not set; this suite writes to the project")
    return project


def live_config() -> ConfigManager:
    """Return a ConfigManager on the config location captured at import.

    Returns:
        A ConfigManager on the captured ``MP_CONFIG_PATH``, or on the default
        location when none was set.
    """
    path = LOCATION_OVERRIDES.get("MP_CONFIG_PATH")
    return ConfigManager(config_path=Path(path) if path else None)


def live_session(*, write: bool = False) -> Session:
    """Build the pinned session of a live suite, or skip.

    Every setting is checked before anything is built. The account comes
    from the config; the project is ``MP_LIVE_WRITE_PROJECT`` for a write
    suite and the account's default project otherwise; the workspace is
    ``None``, so it resolves on first use to a workspace of that project.
    No environment variable, bridge file, or ``[active]`` entry is read.

    Args:
        write: Whether the suite creates, changes, or deletes entities.

    Returns:
        The pinned session.

    Raises:
        ConfigError: If ``MP_LIVE_ACCOUNT`` names an account that the config
            does not have.
    """
    account = live_account()
    pinned_project = write_project() if write else None
    account_obj = live_config().get_account(account)
    project = pinned_project or account_obj.default_project
    if not project:
        pytest.skip(
            f"account {account!r} has no default_project; set "
            f"{WRITE_PROJECT_ENV} or give the account a default project"
        )
    return Session(account=account_obj, project=Project(id=project), workspace=None)


def live_workspace(*, write: bool = False) -> Workspace:
    """Build a Workspace on the pinned live session, or skip.

    After the build, the Workspace must report the pinned account and
    project and no workspace; anything else fails the test. For a write
    suite, the workspace of the pinned project is resolved (a read-only
    call) and recorded for :func:`live_cli_command`.

    Args:
        write: Whether the suite creates, changes, or deletes entities.

    Returns:
        The Workspace.
    """
    global _cli_target
    session = live_session(write=write)
    ws = Workspace(session=session)
    resolved = (ws.account.name, ws.project.id, ws.workspace)
    expected = (session.account.name, session.project.id, None)
    if resolved != expected:
        ws.close()
        pytest.fail(f"live Workspace resolved to {resolved}, not the pinned {expected}")
    if write:
        _cli_target = LiveTarget(
            account=session.account.name,
            project=session.project.id,
            workspace=ws.resolve_workspace_id(),
        )
    return ws


def live_cli_command(*args: str) -> list[str]:
    """Return an ``mp`` command line pinned to the current write suite's target.

    Args:
        *args: CLI arguments after the global flags.

    Returns:
        The command line for :func:`subprocess.run`, with ``--account``,
        ``--project``, and ``--workspace`` set to the pinned target.
    """
    if _cli_target is None:
        pytest.fail(
            "live_cli_command runs only after live_workspace(write=True) pinned "
            "the target"
        )
    return [
        "uv",
        "run",
        "mp",
        "--account",
        _cli_target.account,
        "--project",
        _cli_target.project,
        "--workspace",
        str(_cli_target.workspace),
        *args,
    ]


def live_cli_env() -> dict[str, str]:
    """Return the environment for a subprocess ``mp`` call.

    Returns:
        A copy of ``os.environ`` without the variables in
        :data:`OVERRIDE_ENV` and :data:`LOCATION_ENV`, plus the config and
        storage locations captured at import, plus ``MP_AUTH_FILE`` set to
        :data:`NO_BRIDGE_PATH`.
    """
    if NO_BRIDGE_PATH.exists():
        pytest.fail(f"{NO_BRIDGE_PATH} exists; the live CLI env needs it absent")
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in OVERRIDE_ENV and name not in LOCATION_ENV
    }
    env.update(LOCATION_OVERRIDES)
    env["MP_AUTH_FILE"] = str(NO_BRIDGE_PATH)
    return env
