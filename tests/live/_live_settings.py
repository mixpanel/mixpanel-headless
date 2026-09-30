"""Settings that choose where the live suites run and what they may change.

Two environment variables control every suite in ``tests/live`` that is not
driven by its own explicit credentials:

- ``MP_LIVE_ACCOUNT`` names a configured account. A suite skips every test
  when it is unset, so no suite falls back to the default session (the
  active account and project in ``~/.mp/config.toml``).
- ``MP_LIVE_WRITE_PROJECT`` names the one project that write suites may
  change. A write suite skips unless it is set and the Workspace resolves
  to that project id.

A suite applies :data:`requires_live_account` (and, if it writes,
:data:`requires_write_project`) in ``pytestmark``, so its tests skip at
collection time, before any fixture builds a Workspace. Its Workspace
fixture calls :func:`live_workspace`, which checks the same settings again
and also skips when credentials in the environment override the account.

Subprocess ``mp`` calls use :func:`live_cli_command` and
:func:`live_cli_env`, which pin the account and project with global flags
and drop the environment variables that would override them.
"""

from __future__ import annotations

import os
from typing import Final

import pytest

from mixpanel_headless import Workspace

LIVE_ACCOUNT_ENV: Final[str] = "MP_LIVE_ACCOUNT"
"""Names the configured account that the live suites run as."""

WRITE_PROJECT_ENV: Final[str] = "MP_LIVE_WRITE_PROJECT"
"""Names the only project id that the write suites may change."""

_OVERRIDE_ENV: Final[tuple[str, ...]] = (
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

requires_live_account = pytest.mark.skipif(
    not os.environ.get(LIVE_ACCOUNT_ENV),
    reason=f"{LIVE_ACCOUNT_ENV} is not set",
)
"""Skip marker for a suite that runs as the ``MP_LIVE_ACCOUNT`` account."""

requires_write_project = pytest.mark.skipif(
    not os.environ.get(WRITE_PROJECT_ENV),
    reason=f"{WRITE_PROJECT_ENV} is not set; this suite writes to the project",
)
"""Skip marker for a suite that creates, changes, or deletes entities."""


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


def live_workspace(*, write: bool = False) -> Workspace:
    """Build a Workspace on the ``MP_LIVE_ACCOUNT`` account, or skip.

    Every setting is checked before the Workspace is built, so a missing
    setting never reaches the network. After the build, the resolved
    account must be ``MP_LIVE_ACCOUNT`` (credentials in the environment rank
    above an account and would replace it), and for a write suite the
    resolved project must be ``MP_LIVE_WRITE_PROJECT``.

    Args:
        write: Whether the suite creates, changes, or deletes entities.

    Returns:
        The Workspace.
    """
    account = live_account()
    expected_project = write_project() if write else None
    ws = Workspace(account=account)
    if ws.account.name != account:
        resolved = ws.account.name
        ws.close()
        pytest.skip(
            f"credentials in the environment override {LIVE_ACCOUNT_ENV} "
            f"(resolved account {resolved!r}); unset the MP_USERNAME, "
            f"MP_SECRET, MP_OAUTH_TOKEN, MP_PROJECT_ID, MP_REGION, "
            f"MP_WORKSPACE_ID, and MP_AUTH_FILE variables for live runs"
        )
    if expected_project is not None and str(ws.project.id) != expected_project:
        resolved_project = ws.project.id
        ws.close()
        pytest.skip(
            f"account {account!r} resolves to project {resolved_project}, "
            f"not {WRITE_PROJECT_ENV}={expected_project}; this suite writes "
            f"only to that project"
        )
    return ws


def live_cli_command(*args: str) -> list[str]:
    """Return an ``mp`` command line pinned to the live account and project.

    The account comes from ``MP_LIVE_ACCOUNT``. The project comes from
    ``MP_LIVE_WRITE_PROJECT`` when it is set; otherwise the account's
    default project applies.

    Args:
        *args: CLI arguments after the global flags.

    Returns:
        The command line for :func:`subprocess.run`.
    """
    command = ["uv", "run", "mp", "--account", live_account()]
    project = os.environ.get(WRITE_PROJECT_ENV)
    if project:
        command += ["--project", project]
    return [*command, *args]


def live_cli_env() -> dict[str, str]:
    """Return the environment for a subprocess ``mp`` call.

    Returns:
        A copy of ``os.environ`` without the variables that rank above the
        account and project flags.
    """
    return {k: v for k, v in os.environ.items() if k not in _OVERRIDE_ENV}
