"""Live integration tests for report links (045-report-links).

Skipped by default — set ``MP_LIVE_TESTS=1`` and point auth at a project that
has at least one event and one saved report. These tests round-trip against
the real ``bookmark-urls`` endpoints and the real query engines
(quickstart.md Part 2).

Environment:
- ``MP_LIVE_TESTS=1`` — enable.
- ``MP_TEST_EVENT`` — an event name in the project (default ``Login``).
- ``MP_TEST_BOOKMARK_ID`` — a saved report id in the project; the bookmark
  cases skip when unset.
- ``MP_TEST_SHORT_LINK`` — a ``https://mixpanel.com/s/...`` fixture; the
  shortlink case skips when unset.

Markers:
- ``@pytest.mark.live`` lets the rest of the suite skip them via
  ``-m "not live"``.
- ``@pytest.mark.skipif`` short-circuits when ``MP_LIVE_TESTS`` is absent.
"""

from __future__ import annotations

import os

import pytest

import mixpanel_headless as mp
from mixpanel_headless.types import FlowQueryResult, QueryResult

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MP_LIVE_TESTS") != "1",
        reason="MP_LIVE_TESTS=1 not set — live tests skipped by default",
    ),
]

_EVENT = os.environ.get("MP_TEST_EVENT", "Login")


def _contains(expected: object, actual: object) -> bool:
    """Return whether ``expected`` is contained in ``actual``, recursively.

    The server normalizes stored params: it adds default keys such as
    ``displayOptions.primaryYAxisOptions``, ``behavior.behaviors``, and
    ``executedMigrations``. Every key and value the client sent must survive,
    but the record may carry more.

    Args:
        expected: The params the client sent.
        actual: The params the server returned.

    Returns:
        ``True`` when every dict key in ``expected`` exists in ``actual`` with
        a contained value, lists match element-wise, and scalars are equal.
    """
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_contains(e, a) for e, a in zip(expected, actual, strict=True))
        )
    return bool(expected == actual)


_BOOKMARK_ID = os.environ.get("MP_TEST_BOOKMARK_ID")
_SHORT_LINK = os.environ.get("MP_TEST_SHORT_LINK")


@pytest.fixture(scope="module")
def ws() -> mp.Workspace:
    """One Workspace on the active account for the whole module."""
    return mp.Workspace()


@pytest.fixture(scope="module")
def insights_params(ws: mp.Workspace) -> dict[str, object]:
    """Insights params for the fixture event over the last 7 days."""
    return ws.build_params(_EVENT, last=7)


@pytest.fixture(scope="module")
def created_link(ws: mp.Workspace, insights_params: dict[str, object]) -> mp.ReportLink:
    """Create one Insights link for the module (quickstart Part 2, case 1)."""
    return ws.create_report_link(insights_params, name="headless live test")


class TestCreateAndResolve:
    """quickstart.md Part 2, cases 1 to 3 and 5."""

    def test_create_link_shape(self, created_link: mp.ReportLink) -> None:
        """Case 1: the link has a URL, a 12-char slug, the type, and the project."""
        assert created_link.url.startswith("https://")
        assert f"#{created_link.slug}" in created_link.url
        assert len(created_link.slug) == 12
        assert created_link.report_type == "insights"
        assert created_link.project_id > 0

    def test_resolve_url_round_trips_params(
        self,
        ws: mp.Workspace,
        created_link: mp.ReportLink,
        insights_params: dict[str, object],
    ) -> None:
        """Case 2: resolving the URL returns the canonical form of the params.

        The server canonicalizes an Insights record on write: it rewrites
        ``behavior.type`` (``event`` → ``simple``), may replace an
        auto-captured event name with its display name, and drops
        ``filtersDeterminer``. The time section and the metric count survive
        unchanged, and the record runs (see ``test_run_resolved_report``).
        """
        resolved = ws.resolve_report_link(created_link.url)

        assert resolved.report_type == "insights"
        sent = insights_params["sections"]
        got = resolved.params["sections"]
        assert isinstance(sent, dict) and isinstance(got, dict)
        assert _contains(sent["time"], got["time"])
        assert len(got["show"]) == len(sent["show"])
        assert got["show"][0]["behavior"]["name"]
        assert resolved.slug == created_link.slug
        assert resolved.source == "slug"

    def test_resolve_bare_slug_matches_url(
        self, ws: mp.Workspace, created_link: mp.ReportLink
    ) -> None:
        """Case 3: the bare slug resolves to the same params as the URL."""
        by_url = ws.resolve_report_link(created_link.url)
        by_slug = ws.resolve_report_link(created_link.slug)

        assert by_slug.params == by_url.params
        assert by_slug.report_type == by_url.report_type

    def test_run_resolved_report(
        self, ws: mp.Workspace, created_link: mp.ReportLink
    ) -> None:
        """Case 5: running the resolved report yields a QueryResult."""
        resolved = ws.resolve_report_link(created_link.url)

        result = ws.query_report_link(resolved)

        assert isinstance(result, QueryResult)
        assert result.df is not None


class TestBookmarkLinks:
    """quickstart.md Part 2, case 4."""

    @pytest.mark.skipif(_BOOKMARK_ID is None, reason="MP_TEST_BOOKMARK_ID not set")
    def test_resolve_saved_report_url(self, ws: mp.Workspace) -> None:
        """Case 4: a saved-report URL resolves with the bookmark's own type."""
        assert _BOOKMARK_ID is not None
        bookmark = ws.get_bookmark(int(_BOOKMARK_ID))
        url = ws.saved_report_link(
            bookmark.id,
            report_type=bookmark.bookmark_type,  # type: ignore[arg-type]
        )

        resolved = ws.resolve_report_link(url)

        assert resolved.source == "bookmark"
        assert resolved.bookmark_id == bookmark.id
        assert resolved.report_type == bookmark.bookmark_type
        assert resolved.bookmark is not None


class TestFlowsLink:
    """quickstart.md Part 2, case 6."""

    def test_create_and_resolve_flows_link(self, ws: mp.Workspace) -> None:
        """Case 6: a Flows link round-trips and runs as a FlowQueryResult."""
        params = ws.build_flow_params(_EVENT, last=30)

        link = ws.create_report_link(params, report_type="flows")
        resolved = ws.resolve_report_link(link.url)

        assert "/app/flows#" in link.url
        assert resolved.report_type == "flows"
        assert _contains(params, resolved.params)
        assert isinstance(ws.query_report_link(resolved), FlowQueryResult)


class TestShortLink:
    """quickstart.md Part 2, case 7 (optional fixture)."""

    @pytest.mark.skipif(_SHORT_LINK is None, reason="MP_TEST_SHORT_LINK not set")
    def test_resolve_short_link(self, ws: mp.Workspace) -> None:
        """Case 7: a shortlink expands once and resolves like its target."""
        assert _SHORT_LINK is not None

        resolved = ws.resolve_report_link(_SHORT_LINK)

        assert resolved.expanded_url is not None
        assert resolved.input == _SHORT_LINK
        assert resolved.report_type in {"insights", "funnels", "retention", "flows"}
        direct = ws.resolve_report_link(resolved.expanded_url)
        assert direct.params == resolved.params
