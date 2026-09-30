"""Shared fixtures for the 042 auth-redesign live QA module.

Provides:
- Tmp v3 home isolation (so the user's real ~/.mp/ is never touched)
- Helpers to copy the OAuth tokens of the ``MP_LIVE_ACCOUNT`` account into
  the tmp layout, and to read that account's region and default project
- Per-mode skip fixtures that gate tests on credential availability

The OAuth browser tests use only the account that ``MP_LIVE_ACCOUNT``
names. They never read the active account or project of the real config,
so they cannot fall back to the default session.

Reference: ~/.claude/plans/design-a-qa-plan-vast-wall.md.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mixpanel_headless._internal.auth.account import Region
from mixpanel_headless._internal.auth.storage import account_dir, accounts_root
from tests.live._live_settings import LIVE_ACCOUNT_ENV

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found, unused-ignore]

# The real per-account state directory and config file, captured at import
# time: the ``tmp_mp_home`` fixture points HOME at a tmp directory later.
REAL_ACCOUNTS_ROOT = accounts_root()
REAL_CONFIG_PATH = Path(
    os.environ.get("MP_CONFIG_PATH") or (Path.home() / ".mp" / "config.toml")
)


# =============================================================================
# Tmp v3 home isolation
# =============================================================================


@pytest.fixture
def tmp_mp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Yield a tmp ``$HOME`` with isolated v3 ``~/.mp/`` and ``MP_CONFIG_PATH``.

    Sets HOME, MP_CONFIG_PATH, MP_OAUTH_STORAGE_DIR; creates ~/.mp/ at
    mode 0o700; yields the tmp HOME path. The dev's real ~/.mp/ is
    completely untouched.

    Yields:
        Path to the tmp $HOME root.
    """
    mp_dir = tmp_path / ".mp"
    mp_dir.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MP_CONFIG_PATH", str(mp_dir / "config.toml"))
    monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", str(mp_dir / "oauth"))
    yield tmp_path


# =============================================================================
# Token-copy helper
# =============================================================================


def live_account_name() -> str:
    """Return the ``MP_LIVE_ACCOUNT`` account name, or skip the test.

    Returns:
        The account name.
    """
    account = os.environ.get(LIVE_ACCOUNT_ENV)
    if not account:
        pytest.skip(
            f"{LIVE_ACCOUNT_ENV} is not set; the OAuth browser tests use that "
            "account's tokens"
        )
    return account


def live_account_tokens_path() -> Path:
    """Return the real ``tokens.json`` path of the ``MP_LIVE_ACCOUNT`` account.

    Returns:
        ``<real accounts root>/<account>/tokens.json``. The file may not exist.
    """
    return REAL_ACCOUNTS_ROOT / live_account_name() / "tokens.json"


def _live_account_record() -> dict[str, Any]:
    """Read the ``MP_LIVE_ACCOUNT`` entry of the real config file.

    Returns:
        The ``[accounts.<name>]`` table, or an empty dict when the config is
        missing or has no such account.

    Raises:
        OSError: If the config file exists but cannot be read.
        UnicodeDecodeError: If the config file is not UTF-8.
        tomllib.TOMLDecodeError: If the config file is not valid TOML.
    """
    account = live_account_name()
    if not REAL_CONFIG_PATH.exists():
        return {}
    raw: dict[str, Any] = tomllib.loads(REAL_CONFIG_PATH.read_text(encoding="utf-8"))
    accounts = raw.get("accounts", {})
    record = accounts.get(account) if isinstance(accounts, dict) else None
    return record if isinstance(record, dict) else {}


def live_account_project_id() -> str:
    """Return the default project of the ``MP_LIVE_ACCOUNT`` account, or skip.

    Returns:
        The project id from the account's ``default_project``.
    """
    project = _live_account_record().get("default_project")
    if isinstance(project, int):
        project = str(project)
    if not isinstance(project, str) or not project:
        pytest.skip(f"account {live_account_name()!r} has no default_project")
    return project


def live_account_region() -> Region:
    """Return the region of the ``MP_LIVE_ACCOUNT`` account.

    Returns:
        The account's ``region`` (``us`` when the record has none or an
        unknown value).
    """
    region = _live_account_record().get("region")
    if region == "eu":
        return "eu"
    if region == "in":
        return "in"
    return "us"


def copy_live_account_tokens(home: Path, account_name: str) -> Path:
    """Copy the ``MP_LIVE_ACCOUNT`` account's OAuth tokens into the tmp layout.

    Reads the account's real ``tokens.json`` and writes it to the
    ``tokens.json`` of ``account_name`` under the storage root that the
    library uses now: :func:`account_dir` reads the same environment as the
    token resolver, which ``tmp_mp_home`` points into the tmp home.

    Args:
        home: The tmp $HOME path (from the ``tmp_mp_home`` fixture). The
            destination must be inside it, so real tokens are never
            overwritten.
        account_name: V3 account name to host the tokens under.

    Returns:
        Path to the new tokens.json.

    Raises:
        FileNotFoundError: If the account has no tokens on disk.
    """
    source = live_account_tokens_path()
    if not source.exists():
        raise FileNotFoundError(
            f"OAuth tokens not found at {source}. Live OAuth tests require a "
            f"prior `mp account login {live_account_name()}`."
        )
    payload: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    payload.pop("project_id", None)  # v3 drops this field

    dst_dir = account_dir(account_name)
    if not dst_dir.is_relative_to(home):
        pytest.fail(
            f"token destination {dst_dir} is outside the tmp home {home}; "
            "use the tmp_mp_home fixture"
        )
    dst_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    dst = dst_dir / "tokens.json"
    dst.write_text(json.dumps(payload), encoding="utf-8")
    dst.chmod(0o600)
    return dst


# =============================================================================
# Per-mode skip fixtures
# =============================================================================


def _oauth_token_is_fresh(tokens_path: Path) -> bool:
    """Check whether the OAuth token in ``tokens_path`` is unexpired.

    Args:
        tokens_path: A ``tokens.json`` file.

    Returns:
        ``True`` if the tokens file exists and its ``expires_at`` is in the
        future (with 60s buffer). ``False`` otherwise.
    """
    from datetime import datetime, timedelta, timezone

    if not tokens_path.exists():
        return False
    try:
        payload: dict[str, Any] = json.loads(tokens_path.read_text(encoding="utf-8"))
        expires_raw = payload.get("expires_at")
        if not isinstance(expires_raw, str):
            return False
        expires_at = datetime.fromisoformat(expires_raw)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > datetime.now(timezone.utc) + timedelta(seconds=60)
    except (json.JSONDecodeError, ValueError, OSError):
        return False


@pytest.fixture
def require_oauth_browser_available() -> None:
    """Skip unless ``MP_LIVE_ACCOUNT`` names an OAuth browser account with fresh tokens.

    We check the account type, the default project, and both presence AND
    freshness of the tokens — an expired token would cause the Mixpanel
    server to return 401 even though our code is sending the right bearer,
    and we'd misread the failure as a code bug.
    """
    account = live_account_name()
    account_type = _live_account_record().get("type")
    if account_type != "oauth_browser":
        pytest.skip(
            f"{LIVE_ACCOUNT_ENV}={account!r} is not an oauth_browser account "
            f"(type {account_type!r})"
        )
    live_account_project_id()
    tokens_path = live_account_tokens_path()
    if not tokens_path.exists():
        pytest.skip(
            f"OAuth browser mode requires tokens at {tokens_path} "
            f"(run `mp account login {account}` first)."
        )
    if not _oauth_token_is_fresh(tokens_path):
        pytest.skip(
            f"OAuth tokens at {tokens_path} are expired. "
            f"Run `mp account login {account}` to refresh, then re-run these tests."
        )


_SA_CHECK_RESULT: tuple[bool, str | None] | None = None
_TOKEN_CHECK_RESULT: tuple[bool, str | None] | None = None


def _probe_sa_credentials() -> tuple[bool, str | None]:
    """One-time live probe: are the MP_LIVE_SA_* creds accepted by Mixpanel?

    Caches the result for the rest of the pytest session.

    Returns:
        ``(True, None)`` if the SA creds authenticate against the events
        endpoint. ``(False, reason)`` otherwise.
    """
    global _SA_CHECK_RESULT
    if _SA_CHECK_RESULT is not None:
        return _SA_CHECK_RESULT
    required = (
        "MP_LIVE_SA_USERNAME",
        "MP_LIVE_SA_SECRET",
        "MP_LIVE_SA_PROJECT_ID",
        "MP_LIVE_SA_REGION",
    )
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        _SA_CHECK_RESULT = (False, f"missing env vars: {missing}")
        return _SA_CHECK_RESULT
    # Live probe — make a single events() call to confirm Mixpanel accepts.
    import os as _os

    saved_env = {
        k: _os.environ.get(k)
        for k in ("MP_USERNAME", "MP_SECRET", "MP_PROJECT_ID", "MP_REGION")
    }
    try:
        _os.environ["MP_USERNAME"] = _os.environ["MP_LIVE_SA_USERNAME"]
        _os.environ["MP_SECRET"] = _os.environ["MP_LIVE_SA_SECRET"]
        _os.environ["MP_PROJECT_ID"] = _os.environ["MP_LIVE_SA_PROJECT_ID"]
        _os.environ["MP_REGION"] = _os.environ["MP_LIVE_SA_REGION"]
        from mixpanel_headless import Workspace as _Workspace

        ws = _Workspace()
        try:
            ws.events()
            _SA_CHECK_RESULT = (True, None)
        finally:
            ws.close()
    except Exception as exc:  # noqa: BLE001 — capture any auth-related failure
        _SA_CHECK_RESULT = (False, f"Mixpanel rejected credentials: {exc}")
    finally:
        for k, v in saved_env.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v
    return _SA_CHECK_RESULT


def _probe_static_token() -> tuple[bool, str | None]:
    """One-time live probe: is MP_LIVE_OAUTH_TOKEN accepted by Mixpanel?

    Returns:
        ``(True, None)`` on success, ``(False, reason)`` otherwise.
    """
    global _TOKEN_CHECK_RESULT
    if _TOKEN_CHECK_RESULT is not None:
        return _TOKEN_CHECK_RESULT
    required = ("MP_LIVE_OAUTH_TOKEN", "MP_LIVE_PROJECT_ID", "MP_LIVE_REGION")
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        _TOKEN_CHECK_RESULT = (False, f"missing env vars: {missing}")
        return _TOKEN_CHECK_RESULT
    import os as _os

    saved_env = {
        k: _os.environ.get(k) for k in ("MP_OAUTH_TOKEN", "MP_PROJECT_ID", "MP_REGION")
    }
    try:
        _os.environ["MP_OAUTH_TOKEN"] = _os.environ["MP_LIVE_OAUTH_TOKEN"]
        _os.environ["MP_PROJECT_ID"] = _os.environ["MP_LIVE_PROJECT_ID"]
        _os.environ["MP_REGION"] = _os.environ["MP_LIVE_REGION"]
        from mixpanel_headless import Workspace as _Workspace

        ws = _Workspace()
        try:
            ws.events()
            _TOKEN_CHECK_RESULT = (True, None)
        finally:
            ws.close()
    except Exception as exc:  # noqa: BLE001
        _TOKEN_CHECK_RESULT = (False, f"Mixpanel rejected bearer: {exc}")
    finally:
        for k, v in saved_env.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v
    return _TOKEN_CHECK_RESULT


@pytest.fixture
def require_sa_env_available() -> None:
    """Skip unless MP_LIVE_SA_* env vars are set AND Mixpanel accepts them.

    The probe runs once per pytest session; subsequent tests reuse the
    cached result.
    """
    ok, reason = _probe_sa_credentials()
    if not ok:
        pytest.skip(f"SA mode unavailable: {reason}")


@pytest.fixture
def require_oauth_token_available() -> None:
    """Skip unless MP_LIVE_OAUTH_TOKEN is set AND Mixpanel accepts it.

    The probe runs once per pytest session; subsequent tests reuse the
    cached result.
    """
    ok, reason = _probe_static_token()
    if not ok:
        pytest.skip(f"OAuth token mode unavailable: {reason}")


@pytest.fixture
def live_sa_creds(require_sa_env_available: None) -> dict[str, str]:
    """Return the SA credentials from ``MP_LIVE_SA_*`` env vars.

    Args:
        require_sa_env_available: Skip-fixture dependency.

    Returns:
        Dict with username / secret / project_id / region keys.
    """
    return {
        "username": os.environ["MP_LIVE_SA_USERNAME"],
        "secret": os.environ["MP_LIVE_SA_SECRET"],
        "project_id": os.environ["MP_LIVE_SA_PROJECT_ID"],
        "region": os.environ["MP_LIVE_SA_REGION"],
    }


@pytest.fixture
def live_oauth_token_creds(
    require_oauth_token_available: None,
) -> dict[str, str]:
    """Return the static OAuth token credentials from ``MP_LIVE_*`` env vars.

    Args:
        require_oauth_token_available: Skip-fixture dependency.

    Returns:
        Dict with token / project_id / region keys.
    """
    return {
        "token": os.environ["MP_LIVE_OAUTH_TOKEN"],
        "project_id": os.environ["MP_LIVE_PROJECT_ID"],
        "region": os.environ["MP_LIVE_REGION"],
    }
