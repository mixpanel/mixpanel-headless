"""Property-based tests for auto-workspace resolution (PR1).

Invariants:
- If any workspace for the project is global, the resolved id is one of the
  global workspaces' ids.
- Resolution is deterministic for identical inputs.
- A workspace belonging to another project is never selected.
- ``select_workspace_id`` always returns one of the input views' ids for a
  non-empty input (never a foreign id or ``None``).
- With no global view present, an "All Project Data"-named view is chosen.

The flag strategies are tri-state (``None | bool``) on purpose: the selection
ladder treats an unset flag differently from ``False``, so the properties must
exercise ``None`` to have teeth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.me import (
    MeCache,
    MeService,
    WorkspaceView,
    select_workspace_id,
)

_PID = 4025120

# The conventional global-view name select_workspace_id prefers, pinned here as
# a literal so the test guards the contract rather than re-importing a private.
_GLOBAL_WORKSPACE_NAME = "All Project Data"

# Unset-or-bool: an unset flag (None) must be distinguishable from False.
_tristate = st.none() | st.booleans()


def _build_service(tmp: Path, workspaces: list[dict[str, Any]]) -> MeService:
    """Build a MeService whose warm /me carries ``workspaces``.

    Args:
        tmp: A temp dir backing the on-disk MeCache.
        workspaces: Raw workspace dicts for the /me ``workspaces`` block.

    Returns:
        A MeService with a warmed /me cache (``resolve_workspace`` is peek-only).
    """
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
            "is_default": _tristate,
            "is_global": _tristate,
            "is_visible": _tristate,
        }
    ),
    min_size=1,
    max_size=6,
    unique_by=lambda w: w["id"],
)

# WorkspaceView lists for exercising the pure selection ladder directly. Names
# are biased toward the global-view name so the "All Project Data" rung is hit.
_views = st.lists(
    st.builds(
        WorkspaceView,
        id=st.integers(min_value=1, max_value=10_000),
        name=st.sampled_from([_GLOBAL_WORKSPACE_NAME, "Console", "Main"])
        | st.text(min_size=1, max_size=8),
        is_global=_tristate,
        is_default=_tristate,
        is_visible=_tristate,
    ),
    min_size=1,
    max_size=6,
    unique_by=lambda v: v.id,
)


@st.composite
def _views_no_global_with_apd(draw: st.DrawFn) -> list[WorkspaceView]:
    """Build a view list with no global flag and a guaranteed "All Project Data".

    ``is_global`` is never ``True`` (so the global rung never fires) and exactly
    one view (at a random position) is named "All Project Data", so the name rung
    is always the deciding one — no ``assume`` filtering needed.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A non-empty list of :class:`WorkspaceView` with one global-named view.
    """
    non_true = st.none() | st.just(False)
    ids = draw(
        st.lists(
            st.integers(min_value=1, max_value=10_000),
            min_size=1,
            max_size=6,
            unique=True,
        )
    )
    views = [
        WorkspaceView(
            id=wid,
            name=draw(st.text(min_size=1, max_size=8)),
            is_global=draw(non_true),
            is_default=draw(_tristate),
            is_visible=draw(_tristate),
        )
        for wid in ids
    ]
    apd_index = draw(st.integers(min_value=0, max_value=len(views) - 1))
    chosen = views[apd_index]
    views[apd_index] = WorkspaceView(
        id=chosen.id,
        name=_GLOBAL_WORKSPACE_NAME,
        is_global=chosen.is_global,
        is_default=chosen.is_default,
        is_visible=chosen.is_visible,
    )
    return views


@given(workspaces=_workspaces)
def test_global_workspace_is_chosen_when_present(
    tmp_path_factory: Any, workspaces: list[dict[str, Any]]
) -> None:
    """Any global workspace for the project => resolved id is a global id."""
    tmp = tmp_path_factory.mktemp("pbt")
    resolved = _build_service(tmp, workspaces).resolve_workspace(str(_PID))
    global_ids = {
        w["id"]
        for w in workspaces
        if w["project_id"] == _PID and w["is_global"] is True
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


@given(views=_views)
def test_select_result_belongs_to_input(views: list[WorkspaceView]) -> None:
    """For a non-empty input, the chosen id is always one of the views' ids."""
    assert select_workspace_id(views) in {v.id for v in views}


@given(views=_views_no_global_with_apd())
def test_all_project_data_name_chosen_without_global(
    views: list[WorkspaceView],
) -> None:
    """With no global view, an 'All Project Data'-named view wins over the rest."""
    apd_ids = {v.id for v in views if v.name == _GLOBAL_WORKSPACE_NAME}
    assert select_workspace_id(views) in apd_ids
