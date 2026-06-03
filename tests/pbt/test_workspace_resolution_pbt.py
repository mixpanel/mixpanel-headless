"""Property-based tests for auto-workspace resolution (PR1).

Invariants:
- If any workspace for the project is global, the resolved id is one of the
  global workspaces' ids.
- Resolution is deterministic for identical inputs.
- A workspace belonging to another project is never selected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.me import MeCache, MeService

_PID = 4025120


def _build_service(tmp: Path, workspaces: list[dict[str, Any]]) -> MeService:
    """Build a MeService whose warm /me carries ``workspaces``."""
    api = MagicMock()
    api.me.return_value = {
        "user_id": 1,
        "projects": {str(_PID): {"name": "demo", "organization_id": 1}},
        "workspaces": {str(w["id"]): w for w in workspaces},
    }
    cache = MeCache(account_name="pbt", storage_dir=tmp / "pbt")
    svc = MeService(api, cache, "us")
    svc.fetch()  # resolve_workspace is peek-only; warm the cache first
    return svc


_workspaces = st.lists(
    st.fixed_dictionaries(
        {
            "id": st.integers(min_value=1, max_value=10_000),
            "name": st.text(min_size=1, max_size=12),
            "project_id": st.sampled_from([_PID, 777]),
            "is_default": st.booleans(),
            "is_global": st.booleans(),
            "is_visible": st.booleans(),
        }
    ),
    min_size=1,
    max_size=6,
    unique_by=lambda w: w["id"],
)


@given(workspaces=_workspaces)
def test_global_workspace_is_chosen_when_present(
    tmp_path_factory: Any, workspaces: list[dict[str, Any]]
) -> None:
    """Any global workspace for the project => resolved id is a global id."""
    tmp = tmp_path_factory.mktemp("pbt")
    resolved = _build_service(tmp, workspaces).resolve_workspace(str(_PID))
    global_ids = {
        w["id"] for w in workspaces if w["project_id"] == _PID and w["is_global"]
    }
    if global_ids:
        assert resolved in global_ids


@given(workspaces=_workspaces)
def test_resolution_is_deterministic(
    tmp_path_factory: Any, workspaces: list[dict[str, Any]]
) -> None:
    """Resolving the same project twice yields the same workspace id."""
    tmp = tmp_path_factory.mktemp("pbt")
    svc = _build_service(tmp, workspaces)
    assert svc.resolve_workspace(str(_PID)) == svc.resolve_workspace(str(_PID))


@given(workspaces=_workspaces)
def test_never_selects_other_project(
    tmp_path_factory: Any, workspaces: list[dict[str, Any]]
) -> None:
    """The resolved id always belongs to the requested project (or is None)."""
    tmp = tmp_path_factory.mktemp("pbt")
    resolved = _build_service(tmp, workspaces).resolve_workspace(str(_PID))
    own_ids = {w["id"] for w in workspaces if w["project_id"] == _PID}
    assert resolved is None or resolved in own_ids
