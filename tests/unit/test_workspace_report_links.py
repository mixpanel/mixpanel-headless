"""Tests for the Workspace report-link methods (045-report-links).

Covers ``create_report_link``, ``resolve_report_link``, ``query_report_link``,
and ``saved_report_link`` with a mocked API client and a mocked
``LiveQueryService``. Fixtures copy ``tests/unit/test_workspace_bookmarks.py``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

import mixpanel_headless as mp
from mixpanel_headless import Workspace
from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session, WorkspaceRef
from mixpanel_headless.exceptions import (
    BookmarkValidationError,
    ParamValidationError,
    QueryError,
    ReportLinkNotFoundError,
    ReportLinkParseError,
    ReportLinkScopeMismatchError,
    ResponseValidationError,
    ShortLinkResolutionError,
    UnsupportedReportLinkError,
    ValidationError,
    WorkspaceScopeError,
)
from mixpanel_headless.types import (
    FlowQueryResult,
    FunnelQueryResult,
    QueryResult,
    ReportLink,
    ResolvedReport,
    RetentionQueryResult,
)

_SLUG = "EBrV5bW2u9Mw"

# ---- 042 redesign: canonical fake Session for Workspace(session=…) ----
_TEST_SESSION = Session(
    account=ServiceAccount(
        name="test_account",
        region="us",
        username="test_user",
        secret=SecretStr("test_secret"),
        default_project="12345",
    ),
    project=Project(id="12345"),
)
_PINNED_SESSION = _TEST_SESSION.replace(workspace=WorkspaceRef(id=75))
_EU_SESSION = Session(
    account=ServiceAccount(
        name="eu_account",
        region="eu",
        username="test_user",
        secret=SecretStr("test_secret"),
        default_project="12345",
    ),
    project=Project(id="12345"),
)


@pytest.fixture
def mock_api_client() -> MagicMock:
    """Create a spec'd mock API client whose slug POST echoes a record."""
    client = MagicMock(spec=MixpanelAPIClient)
    client.close = MagicMock()
    client.create_bookmark_url.side_effect = lambda body: {
        **body,
        "project_id": 12345,
        "created_at": "2026-09-02T10:00:00",
    }
    client.resolve_workspace_id.return_value = 99
    return client


@pytest.fixture
def workspace_factory(
    mock_api_client: MagicMock,
) -> Iterator[Callable[..., Workspace]]:
    """Factory for Workspace instances with the mocked client; closes them."""
    created: list[Workspace] = []

    def factory(**kwargs: Any) -> Workspace:
        """Build a Workspace bound to ``_TEST_SESSION`` unless overridden.

        Args:
            **kwargs: Overrides for the Workspace constructor.

        Returns:
            The new Workspace.
        """
        defaults: dict[str, Any] = {
            "session": _TEST_SESSION,
            "_api_client": mock_api_client,
        }
        defaults.update(kwargs)
        ws = Workspace(**defaults)
        created.append(ws)
        return ws

    yield factory
    for ws in created:
        ws.close()


@pytest.fixture
def ws(workspace_factory: Callable[..., Workspace]) -> Workspace:
    """A Workspace on the default US session with no pinned workspace."""
    return workspace_factory()


def _posted_body(mock_api_client: MagicMock) -> dict[str, Any]:
    """Return the body of the single ``create_bookmark_url`` call.

    Args:
        mock_api_client: The mocked client.

    Returns:
        The posted body dict.
    """
    mock_api_client.create_bookmark_url.assert_called_once()
    body: dict[str, Any] = mock_api_client.create_bookmark_url.call_args.args[0]
    return body


# =============================================================================
# create_report_link (US1)
# =============================================================================


class TestCreateReportLinkFromDict:
    """A plain params dict defaults to the insights type."""

    def test_dict_defaults_to_insights(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """Type is insights, the slug is minted, params are sent as given."""
        params = ws.build_params("Login", last=7)

        link = ws.create_report_link(params)

        body = _posted_body(mock_api_client)
        assert body["type"] == "insights"
        assert body["params"] == params
        assert len(body["slug"]) == 12
        assert isinstance(link, ReportLink)
        assert link.report_type == "insights"
        assert link.slug == body["slug"]
        assert link.project_id == 12345

    def test_explicit_type_on_dict(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """An explicit ``report_type`` is used for a dict."""
        params = ws.build_funnel_params(
            [mp.FunnelStep("Login"), mp.FunnelStep("Purchase")], last=30
        )

        link = ws.create_report_link(params, report_type="funnels")

        assert _posted_body(mock_api_client)["type"] == "funnels"
        assert link.report_type == "funnels"

    @patch("mixpanel_headless.workspace.generate_slug", return_value=_SLUG)
    def test_url_uses_resolved_workspace(
        self, _gen: MagicMock, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """With no explicit or pinned workspace, ``resolve_workspace_id`` is used."""
        link = ws.create_report_link(ws.build_params("Login", last=7))

        mock_api_client.resolve_workspace_id.assert_called_once()
        assert link.workspace_id == 99
        assert link.url == (
            f"https://mixpanel.com/project/12345/view/99/app/insights#{_SLUG}"
        )
        assert str(link) == link.url

    def test_created_at_name_description_bookmark_id(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """Optional fields reach the body and the result; created_at is copied."""
        link = ws.create_report_link(
            ws.build_params("Login", last=7),
            name="Logins",
            description="last 7 days",
            bookmark_id=9,
        )

        body = _posted_body(mock_api_client)
        assert body["name"] == "Logins"
        assert body["description"] == "last 7 days"
        assert body["bookmark_id"] == 9
        assert link.name == "Logins"
        assert link.description == "last 7 days"
        assert link.bookmark_id == 9
        assert link.created_at == "2026-09-02T10:00:00"

    def test_body_omits_empty_optionals_and_workspace_id(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """Empty name/description and None bookmark_id are not sent; no workspace_id."""
        ws.create_report_link(ws.build_params("Login", last=7), workspace_id=5)

        body = _posted_body(mock_api_client)
        assert set(body) == {"slug", "type", "params"}

    def test_missing_created_at_is_none(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A response without ``created_at`` yields None."""
        mock_api_client.create_bookmark_url.side_effect = lambda body: dict(body)

        link = ws.create_report_link(ws.build_params("Login", last=7))

        assert link.created_at is None


class TestCreateReportLinkFromResults:
    """Typed results infer the report type."""

    def test_query_result_is_insights(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """QueryResult infers insights and uses ``result.params``."""
        params = ws.build_params("Login", last=7)
        result = QueryResult(
            computed_at="2026-09-02T10:00:00",
            from_date="2026-08-26",
            to_date="2026-09-02",
            params=params,
        )

        link = ws.create_report_link(result)

        body = _posted_body(mock_api_client)
        assert body["type"] == "insights"
        assert body["params"] == params
        assert link.report_type == "insights"

    def test_funnel_result_is_funnels(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """FunnelQueryResult infers funnels."""
        params = ws.build_funnel_params(
            [mp.FunnelStep("Login"), mp.FunnelStep("Purchase")], last=30
        )
        result = FunnelQueryResult(
            computed_at="2026-09-02T10:00:00",
            from_date="2026-08-03",
            to_date="2026-09-02",
            params=params,
        )

        link = ws.create_report_link(result)

        assert _posted_body(mock_api_client)["type"] == "funnels"
        assert link.report_type == "funnels"
        assert "/app/insights#" in link.url

    def test_retention_result_is_retention(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """RetentionQueryResult infers retention."""
        params = ws.build_retention_params("Login", "Purchase", last=30)
        result = RetentionQueryResult(
            computed_at="2026-09-02T10:00:00",
            from_date="2026-08-03",
            to_date="2026-09-02",
            params=params,
        )

        link = ws.create_report_link(result)

        assert _posted_body(mock_api_client)["type"] == "retention"
        assert link.report_type == "retention"

    def test_flow_result_is_flows(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """FlowQueryResult infers flows and links under the flows app."""
        params = ws.build_flow_params("Login", last=30)
        result = FlowQueryResult(computed_at="2026-09-02T10:00:00", params=params)

        link = ws.create_report_link(result)

        assert _posted_body(mock_api_client)["type"] == "flows"
        assert link.report_type == "flows"
        assert "/app/flows#" in link.url

    def test_matching_explicit_type_is_accepted(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """An explicit type equal to the inferred type does not raise."""
        result = FlowQueryResult(
            computed_at="2026-09-02T10:00:00",
            params=ws.build_flow_params("Login", last=30),
        )

        link = ws.create_report_link(result, report_type="flows")

        assert link.report_type == "flows"

    def test_contradicting_type_raises_rl4_before_post(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A contradicting ``report_type`` raises RL4 with no network call."""
        result = FunnelQueryResult(
            computed_at="2026-09-02T10:00:00",
            from_date="2026-08-03",
            to_date="2026-09-02",
            params=ws.build_funnel_params(
                [mp.FunnelStep("Login"), mp.FunnelStep("Purchase")], last=30
            ),
        )

        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_report_link(result, report_type="insights")

        assert exc_info.value.code == "RL4_REPORT_TYPE_CONFLICT"
        assert str(exc_info.value) == (
            "report_type='insights' contradicts the FunnelQueryResult result, "
            "which is 'funnels'. Omit report_type or pass a plain params dict."
        )
        mock_api_client.create_bookmark_url.assert_not_called()


class TestCreateReportLinkValidation:
    """Schema validation runs before the POST unless disabled."""

    def test_validation_failure_raises_before_post(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """Invalid params raise BookmarkValidationError with no network call."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.create_report_link({"sections": {"show": []}, "bogus": 1})

        assert exc_info.value.error_count >= 1
        mock_api_client.create_bookmark_url.assert_not_called()

    def test_validate_false_skips_validation(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """``validate=False`` sends the params as given."""
        link = ws.create_report_link({"bogus": 1}, validate=False)

        assert _posted_body(mock_api_client)["params"] == {"bogus": 1}
        assert link.report_type == "insights"

    def test_validation_warnings_do_not_block(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """Warning-severity findings are logged, not raised."""
        warning = ValidationError(
            path="sorting", message="soft", code="S4", severity="warning"
        )
        with patch.object(
            Workspace, "_validate_bookmark_params_schema", return_value=[warning]
        ):
            ws.create_report_link({"anything": 1})

        mock_api_client.create_bookmark_url.assert_called_once()


class TestCreateReportLinkWorkspacePrecedence:
    """Explicit, then pinned, then resolved; scope error falls back to None."""

    @patch("mixpanel_headless.workspace.generate_slug", return_value=_SLUG)
    def test_explicit_wins(
        self, _gen: MagicMock, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """An explicit workspace_id is used and nothing is resolved."""
        link = ws.create_report_link(ws.build_params("Login", last=7), workspace_id=5)

        assert link.workspace_id == 5
        assert "/view/5/" in link.url
        mock_api_client.resolve_workspace_id.assert_not_called()

    @patch("mixpanel_headless.workspace.generate_slug", return_value=_SLUG)
    def test_pinned_session_workspace(
        self,
        _gen: MagicMock,
        workspace_factory: Callable[..., Workspace],
        mock_api_client: MagicMock,
    ) -> None:
        """A pinned session workspace beats resolution."""
        ws = workspace_factory(session=_PINNED_SESSION)

        link = ws.create_report_link(ws.build_params("Login", last=7))

        assert link.workspace_id == 75
        assert "/view/75/" in link.url
        mock_api_client.resolve_workspace_id.assert_not_called()

    @patch("mixpanel_headless.workspace.generate_slug", return_value=_SLUG)
    def test_explicit_beats_pinned(
        self,
        _gen: MagicMock,
        workspace_factory: Callable[..., Workspace],
    ) -> None:
        """An explicit workspace_id beats the pinned session workspace."""
        ws = workspace_factory(session=_PINNED_SESSION)

        link = ws.create_report_link(ws.build_params("Login", last=7), workspace_id=5)

        assert link.workspace_id == 5

    @patch("mixpanel_headless.workspace.generate_slug", return_value=_SLUG)
    def test_scope_error_falls_back_to_project_only(
        self, _gen: MagicMock, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A WorkspaceScopeError yields a project-only URL, not a failure."""
        mock_api_client.resolve_workspace_id.side_effect = WorkspaceScopeError(
            "no workspaces"
        )

        link = ws.create_report_link(ws.build_params("Login", last=7))

        assert link.workspace_id is None
        assert link.url == f"https://mixpanel.com/project/12345/app/insights#{_SLUG}"


class TestCreateReportLinkUrlShape:
    """URL host and app follow the region and the type table."""

    @pytest.mark.parametrize(
        ("report_type", "app"),
        [
            ("insights", "insights"),
            ("funnels", "insights"),
            ("retention", "insights"),
            ("flows", "flows"),
        ],
    )
    @patch("mixpanel_headless.workspace.generate_slug", return_value=_SLUG)
    def test_eu_session_per_type(
        self,
        _gen: MagicMock,
        report_type: str,
        app: str,
        workspace_factory: Callable[..., Workspace],
    ) -> None:
        """An EU session emits the EU host and the app for the type."""
        ws = workspace_factory(session=_EU_SESSION)

        link = ws.create_report_link(
            {"any": 1},
            report_type=report_type,  # type: ignore[arg-type]
            validate=False,
            workspace_id=None,
        )

        assert link.url == (
            f"https://eu.mixpanel.com/project/12345/view/99/app/{app}#{_SLUG}"
        )
        assert link.report_type == report_type


# =============================================================================
# resolve_report_link (US2)
# =============================================================================

_INSIGHTS_PARAMS = {"sections": {"show": []}, "displayOptions": {"chartType": "line"}}
_FLOW_PARAMS = {"chartType": "paths", "steps": []}
_BOOKMARK_RAW = {
    "id": 123,
    "name": "Weekly actives",
    "type": "funnels",
    "params": {"steps": [{"event": "Login"}]},
    "description": "desc",
}


def _slug_record(**extra: Any) -> dict[str, Any]:
    """Build a server slug record for ``get_bookmark_url``.

    Args:
        **extra: Keys merged over the defaults.

    Returns:
        A record dict.
    """
    return {
        "slug": _SLUG,
        "type": "insights",
        "params": _INSIGHTS_PARAMS,
        "project_id": 12345,
        "name": "Logins",
        "created_at": "2026-09-02T10:00:00",
        **extra,
    }


class TestResolveSlugLinks:
    """Bare slugs and slug URLs fetch the slug record."""

    def test_bare_slug(self, ws: Workspace, mock_api_client: MagicMock) -> None:
        """A bare slug is looked up in the active project; no workspace resolve."""
        mock_api_client.get_bookmark_url.return_value = _slug_record()

        resolved = ws.resolve_report_link(_SLUG)

        mock_api_client.get_bookmark_url.assert_called_once_with(_SLUG)
        mock_api_client.resolve_workspace_id.assert_not_called()
        assert isinstance(resolved, ResolvedReport)
        assert resolved.source == "slug"
        assert resolved.report_type == "insights"
        assert resolved.params == _INSIGHTS_PARAMS
        assert resolved.project_id == 12345
        assert resolved.workspace_id is None
        assert resolved.region == "us"
        assert resolved.url == (
            f"https://mixpanel.com/project/12345/app/insights#{_SLUG}"
        )
        assert resolved.input == _SLUG
        assert resolved.expanded_url is None
        assert resolved.slug == _SLUG
        assert resolved.bookmark_id is None
        assert resolved.bookmark is None
        assert resolved.name == "Logins"
        assert resolved.description is None
        assert resolved.overrides is None

    def test_full_url_with_workspace(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """The URL ``wid`` wins and the canonical URL is rebuilt."""
        mock_api_client.get_bookmark_url.return_value = _slug_record(type="funnels")
        link = f"https://mixpanel.com/project/12345/view/75/app/insights/?utm=x#{_SLUG}"

        resolved = ws.resolve_report_link(link)

        assert resolved.workspace_id == 75
        assert resolved.report_type == "funnels"
        assert resolved.url == (
            f"https://mixpanel.com/project/12345/view/75/app/insights#{_SLUG}"
        )
        assert resolved.input == link

    def test_project_only_url_uses_pinned_workspace(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """Without a URL ``wid`` the pinned session workspace is used."""
        ws = workspace_factory(session=_PINNED_SESSION)
        mock_api_client.get_bookmark_url.return_value = _slug_record()

        resolved = ws.resolve_report_link(
            f"https://mixpanel.com/project/12345/app/insights#{_SLUG}"
        )

        assert resolved.workspace_id == 75
        assert "/view/75/" in resolved.url
        mock_api_client.resolve_workspace_id.assert_not_called()

    def test_project_only_url_without_pin_is_none(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """Without a URL ``wid`` or a pin, workspace_id is None (never resolved)."""
        mock_api_client.get_bookmark_url.return_value = _slug_record()

        resolved = ws.resolve_report_link(
            f"https://mixpanel.com/project/12345/app/insights#{_SLUG}"
        )

        assert resolved.workspace_id is None
        mock_api_client.resolve_workspace_id.assert_not_called()

    def test_slug_record_with_embedded_bookmark(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """An embedded bookmark is surfaced; overrides are data, never merged."""
        mock_api_client.get_bookmark_url.return_value = _slug_record(
            bookmark=_BOOKMARK_RAW, overrides={"originDashboard": 555}
        )

        resolved = ws.resolve_report_link(_SLUG)

        assert resolved.source == "slug"
        assert resolved.bookmark is not None
        assert resolved.bookmark.id == 123
        assert resolved.bookmark_id == 123
        assert resolved.params == _INSIGHTS_PARAMS
        assert resolved.overrides == {"originDashboard": 555}
        mock_api_client.get_bookmark.assert_not_called()

    def test_flows_record_rebuilds_under_flows_app(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """The canonical URL follows the server type, not the URL app."""
        mock_api_client.get_bookmark_url.return_value = _slug_record(
            type="flows", params=_FLOW_PARAMS
        )

        resolved = ws.resolve_report_link(
            f"https://mixpanel.com/project/12345/app/insights#{_SLUG}"
        )

        assert resolved.report_type == "flows"
        assert resolved.url == f"https://mixpanel.com/project/12345/app/flows#{_SLUG}"

    def test_unknown_slug_raises_not_found(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """The client's ReportLinkNotFoundError propagates unchanged."""
        mock_api_client.get_bookmark_url.side_effect = ReportLinkNotFoundError(
            "nope", code="REPORT_LINK_SLUG_NOT_FOUND", details={"slug": _SLUG}
        )

        with pytest.raises(ReportLinkNotFoundError) as exc_info:
            ws.resolve_report_link(_SLUG)

        assert exc_info.value.code == "REPORT_LINK_SLUG_NOT_FOUND"

    def test_malformed_slug_record_raises_response_validation_error(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A record whose ``params`` is not a dict fails response validation."""
        mock_api_client.get_bookmark_url.return_value = _slug_record(params="nope")

        with pytest.raises(ResponseValidationError):
            ws.resolve_report_link(_SLUG)

    def test_slug_record_without_slug_raises_response_validation_error(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A record with no ``slug`` key fails response validation."""
        record = _slug_record()
        del record["slug"]
        mock_api_client.get_bookmark_url.return_value = record

        with pytest.raises(ResponseValidationError):
            ws.resolve_report_link(_SLUG)

    def test_dashboard_edited_bookmark_resolves_slug(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A boards URL with ``edited-bookmark`` resolves that slug."""
        mock_api_client.get_bookmark_url.return_value = _slug_record()

        resolved = ws.resolve_report_link(
            f"https://mixpanel.com/project/12345/app/boards#id=555&edited-bookmark={_SLUG}"
        )

        assert resolved.slug == _SLUG
        mock_api_client.get_bookmark_url.assert_called_once_with(_SLUG)


class TestResolveBookmarkLinks:
    """Saved-report URLs fetch the bookmark; the type comes from the bookmark."""

    def test_bookmark_url_type_from_bookmark_not_hint(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A ``/app/insights#report/123`` link whose bookmark is funnels is funnels."""
        mock_api_client.get_bookmark.return_value = _BOOKMARK_RAW

        resolved = ws.resolve_report_link(
            "https://mixpanel.com/project/12345/app/insights#report/123"
        )

        mock_api_client.get_bookmark.assert_called_once_with(123)
        mock_api_client.get_bookmark_url.assert_not_called()
        assert resolved.source == "bookmark"
        assert resolved.report_type == "funnels"
        assert resolved.params == {"steps": [{"event": "Login"}]}
        assert resolved.bookmark_id == 123
        assert resolved.bookmark is not None
        assert resolved.bookmark.bookmark_type == "funnels"
        assert resolved.slug is None
        assert resolved.name == "Weekly actives"
        assert resolved.description == "desc"
        assert resolved.overrides is None
        assert resolved.url == (
            "https://mixpanel.com/project/12345/app/funnels#view/123"
        )

    def test_bookmark_url_with_workspace(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """The URL ``wid`` is kept in the canonical bookmark URL."""
        mock_api_client.get_bookmark.return_value = {
            **_BOOKMARK_RAW,
            "type": "insights",
        }

        resolved = ws.resolve_report_link(
            "https://mixpanel.com/project/12345/view/75/app/insights#report/123/weekly"
        )

        assert resolved.workspace_id == 75
        assert resolved.url == (
            "https://mixpanel.com/project/12345/view/75/app/insights#report/123"
        )

    def test_overrides_tail_logs_warning_and_returns_base_params(
        self,
        ws: Workspace,
        mock_api_client: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A ``~(...)`` tail is ignored with a warning; base params are returned."""
        mock_api_client.get_bookmark.return_value = _BOOKMARK_RAW

        with caplog.at_level("WARNING", logger="mixpanel_headless.workspace"):
            resolved = ws.resolve_report_link(
                "https://mixpanel.com/project/12345/app/funnels#view/123/~(a~1)"
            )

        assert resolved.params == {"steps": [{"event": "Login"}]}
        assert any(
            "ignoring URL overrides '~(a~1)'" in rec.getMessage()
            and "base params" in rec.getMessage()
            for rec in caplog.records
        )

    def test_unknown_bookmark_raises_not_found(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A 404 QueryError from get_bookmark becomes REPORT_LINK_BOOKMARK_NOT_FOUND."""
        mock_api_client.get_bookmark.side_effect = QueryError(
            "Resource not found", status_code=404
        )

        with pytest.raises(ReportLinkNotFoundError) as exc_info:
            ws.resolve_report_link(
                "https://mixpanel.com/project/12345/app/insights#report/123"
            )

        exc = exc_info.value
        assert exc.code == "REPORT_LINK_BOOKMARK_NOT_FOUND"
        assert str(exc) == "No saved report found with id 123 in project 12345 (us)."
        assert exc.details["bookmark_id"] == 123
        assert exc.details["kind"] == "bookmark"
        assert "session_workspace_id" not in exc.details
        assert exc.details["hint"] == (
            "Check the saved report id, or switch to the project and region that "
            "own it (ws.use(project=...); CLI: mp --project ...) and retry."
        )

    def test_unknown_bookmark_under_pinned_workspace_names_the_workspace(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """Pinned to 75, the GET is workspace-scoped, so the 404 says so."""
        ws = workspace_factory(session=_PINNED_SESSION)
        mock_api_client.get_bookmark.side_effect = QueryError(
            "Resource not found", status_code=404
        )

        with pytest.raises(ReportLinkNotFoundError) as exc_info:
            ws.resolve_report_link(
                "https://mixpanel.com/project/12345/app/insights#report/123"
            )

        exc = exc_info.value
        assert exc.code == "REPORT_LINK_BOOKMARK_NOT_FOUND"
        assert str(exc) == (
            "No saved report found with id 123 in project 12345 (us) under the "
            "pinned workspace 75."
        )
        assert exc.details["session_workspace_id"] == 75
        assert exc.details["hint"] == (
            "The saved report may live in another workspace of this project. "
            "Switch with ws.use(workspace=<id>) (CLI: mp --workspace <id> ...) "
            "or unpin the workspace and retry."
        )

    @pytest.mark.parametrize(
        ("app", "expected_tail"),
        [("insights", "insights#report/123"), ("funnels", "funnels#view/123")],
    )
    def test_unknown_bookmark_type_falls_back_to_url_app_with_warning(
        self,
        ws: Workspace,
        mock_api_client: MagicMock,
        caplog: pytest.LogCaptureFixture,
        app: str,
        expected_tail: str,
    ) -> None:
        """A bookmark type outside the hash table keeps the pasted app and warns."""
        mock_api_client.get_bookmark.return_value = {**_BOOKMARK_RAW, "type": "user"}

        with caplog.at_level("WARNING", logger="mixpanel_headless.workspace"):
            resolved = ws.resolve_report_link(
                f"https://mixpanel.com/project/12345/app/{app}#report/123"
            )

        assert resolved.report_type == "user"
        assert resolved.url == f"https://mixpanel.com/project/12345/app/{expected_tail}"
        assert any(
            "unknown report type 'user'" in rec.getMessage() and app in rec.getMessage()
            for rec in caplog.records
        )

    def test_other_query_error_passes_through(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A non-404 QueryError from get_bookmark is not remapped."""
        mock_api_client.get_bookmark.side_effect = QueryError(
            "Permission denied", status_code=403
        )

        with pytest.raises(QueryError) as exc_info:
            ws.resolve_report_link(
                "https://mixpanel.com/project/12345/app/insights#report/123"
            )

        assert exc_info.value.status_code == 403

    def test_bookmark_without_params_yields_empty_dict(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A bookmark with ``params: null`` resolves to an empty params dict."""
        mock_api_client.get_bookmark.return_value = {**_BOOKMARK_RAW, "params": None}

        resolved = ws.resolve_report_link(
            "https://mixpanel.com/project/12345/app/insights#report/123"
        )

        assert resolved.params == {}


class TestResolveScopeAndUnsupported:
    """Scope checks and unsupported kinds fail before any client call."""

    def _assert_no_client_calls(self, mock_api_client: MagicMock) -> None:
        """Assert neither record reader nor the workspace resolver was called.

        Args:
            mock_api_client: The mocked client.
        """
        mock_api_client.get_bookmark_url.assert_not_called()
        mock_api_client.get_bookmark.assert_not_called()
        mock_api_client.resolve_workspace_id.assert_not_called()

    def test_project_mismatch(self, ws: Workspace, mock_api_client: MagicMock) -> None:
        """A link to project 3 on a project-12345 session names both and the fix."""
        with pytest.raises(ReportLinkScopeMismatchError) as exc_info:
            ws.resolve_report_link(
                f"https://mixpanel.com/project/3/app/insights#{_SLUG}"
            )

        exc = exc_info.value
        assert exc.code == "REPORT_LINK_PROJECT_MISMATCH"
        assert str(exc) == (
            "Report link belongs to project 3 but the active session is project 12345."
        )
        assert exc.details["hint"] == (
            'Switch with ws.use(project="3") (CLI: mp --project 3 ...) and retry.'
        )
        assert exc.details["link_project_id"] == 3
        assert exc.details["session_project_id"] == 12345
        assert exc.details["slug"] == _SLUG
        self._assert_no_client_calls(mock_api_client)

    def test_region_mismatch(self, ws: Workspace, mock_api_client: MagicMock) -> None:
        """An EU link on a US session names both regions and the fix."""
        with pytest.raises(ReportLinkScopeMismatchError) as exc_info:
            ws.resolve_report_link(
                f"https://eu.mixpanel.com/project/12345/app/insights#{_SLUG}"
            )

        exc = exc_info.value
        assert exc.code == "REPORT_LINK_REGION_MISMATCH"
        assert str(exc) == (
            "Report link is on the eu region but the active account is on us."
        )
        assert exc.details["hint"] == (
            "Switch to an account on the eu region with "
            'ws.use(account="<name>") (CLI: mp --account <name> ...) and retry.'
        )
        assert exc.details["link_region"] == "eu"
        assert exc.details["session_region"] == "us"
        self._assert_no_client_calls(mock_api_client)

    def test_region_checked_before_project(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """When both differ, the region mismatch is reported."""
        with pytest.raises(ReportLinkScopeMismatchError) as exc_info:
            ws.resolve_report_link(
                f"https://eu.mixpanel.com/project/3/app/insights#{_SLUG}"
            )

        assert exc_info.value.code == "REPORT_LINK_REGION_MISMATCH"

    def test_dashboard_link_unsupported(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A boards link without an edited-bookmark slug is unsupported."""
        with pytest.raises(UnsupportedReportLinkError) as exc_info:
            ws.resolve_report_link(
                "https://mixpanel.com/project/12345/app/boards#id=555"
            )

        exc = exc_info.value
        assert exc.code == "UNSUPPORTED_DASHBOARD_LINK"
        assert str(exc) == (
            "This link points at dashboard 555, not at a single report."
        )
        assert exc.details["hint"] == (
            "Use ws.get_dashboard(555) (CLI: mp dashboards get 555) to list its "
            "reports, then resolve one report link."
        )
        assert exc.details["dashboard_id"] == 555
        self._assert_no_client_calls(mock_api_client)

    def test_legacy_hash_unsupported(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A ``~(...)`` hash is recognized but cannot be decoded."""
        with pytest.raises(UnsupportedReportLinkError) as exc_info:
            ws.resolve_report_link(
                "https://mixpanel.com/project/12345/app/insights#~(sections~())"
            )

        exc = exc_info.value
        assert exc.code == "UNSUPPORTED_LEGACY_HASH"
        assert str(exc) == (
            "This link uses the legacy JSURL hash format, which mixpanel-headless "
            "cannot decode."
        )
        assert exc.details["hint"] == (
            "Open it in a browser (the app re-mints a shareable link on load) "
            "and copy the new URL."
        )
        self._assert_no_client_calls(mock_api_client)

    def test_unsupported_kinds_win_over_scope_checks(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A dashboard link in another project is reported as unsupported."""
        with pytest.raises(UnsupportedReportLinkError):
            ws.resolve_report_link("https://mixpanel.com/project/3/app/boards#id=555")

    def test_parse_error_propagates(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """Unparseable input raises ReportLinkParseError with no client call."""
        with pytest.raises(ReportLinkParseError):
            ws.resolve_report_link("not a link")

        self._assert_no_client_calls(mock_api_client)


# =============================================================================
# query_report_link (US2)
# =============================================================================


def _resolved(report_type: str, params: dict[str, Any]) -> ResolvedReport:
    """Build a ResolvedReport for the runner tests.

    Args:
        report_type: The report type to dispatch on.
        params: The params to run.

    Returns:
        A ResolvedReport on project 12345.
    """
    return ResolvedReport(
        source="slug",
        report_type=report_type,
        params=params,
        project_id=12345,
        workspace_id=None,
        region="us",
        url=f"https://mixpanel.com/project/12345/app/insights#{_SLUG}",
        input=_SLUG,
        slug=_SLUG,
    )


@pytest.fixture
def mock_live_query(ws: Workspace) -> MagicMock:
    """Install a spec'd LiveQueryService mock on the workspace."""
    from mixpanel_headless._internal.services.live_query import LiveQueryService

    svc = MagicMock(spec=LiveQueryService)
    ws._live_query = svc
    return svc


class TestQueryReportLink:
    """Dispatch per report type with ``int(project.id)``."""

    def test_insights(self, ws: Workspace, mock_live_query: MagicMock) -> None:
        """insights dispatches to LiveQueryService.query."""
        sentinel = QueryResult(computed_at="t", from_date="d", to_date="d")
        mock_live_query.query.return_value = sentinel

        result = ws.query_report_link(_resolved("insights", _INSIGHTS_PARAMS))

        assert result is sentinel
        mock_live_query.query.assert_called_once_with(
            _INSIGHTS_PARAMS, 12345, workspace_id=None
        )

    def test_funnels(self, ws: Workspace, mock_live_query: MagicMock) -> None:
        """funnels dispatches to query_funnel."""
        sentinel = FunnelQueryResult(computed_at="t", from_date="d", to_date="d")
        mock_live_query.query_funnel.return_value = sentinel

        result = ws.query_report_link(_resolved("funnels", {"steps": []}))

        assert result is sentinel
        mock_live_query.query_funnel.assert_called_once_with(
            {"steps": []}, 12345, workspace_id=None
        )

    def test_retention(self, ws: Workspace, mock_live_query: MagicMock) -> None:
        """retention dispatches to query_retention."""
        sentinel = RetentionQueryResult(computed_at="t", from_date="d", to_date="d")
        mock_live_query.query_retention.return_value = sentinel

        result = ws.query_report_link(_resolved("retention", {"r": 1}))

        assert result is sentinel
        mock_live_query.query_retention.assert_called_once_with(
            {"r": 1}, 12345, workspace_id=None
        )

    @pytest.mark.parametrize(
        ("params", "expected_mode"),
        [
            ({"chartType": "paths"}, "paths"),
            ({"chartType": "tree"}, "tree"),
            ({"chartType": "sankey"}, "sankey"),
            ({"chartType": "bar"}, "sankey"),
            ({}, "sankey"),
        ],
    )
    def test_flows_mode_derived_from_params(
        self,
        ws: Workspace,
        mock_live_query: MagicMock,
        params: dict[str, Any],
        expected_mode: str,
    ) -> None:
        """flows derives mode from chartType when valid, else sankey."""
        sentinel = FlowQueryResult(computed_at="t")
        mock_live_query.query_flow.return_value = sentinel

        result = ws.query_report_link(_resolved("flows", params))

        assert result is sentinel
        mock_live_query.query_flow.assert_called_once_with(
            params, 12345, mode=expected_mode, workspace_id=None
        )

    def test_flows_explicit_mode_wins(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """An explicit mode overrides chartType."""
        mock_live_query.query_flow.return_value = FlowQueryResult(computed_at="t")

        ws.query_report_link(_resolved("flows", {"chartType": "paths"}), mode="tree")

        mock_live_query.query_flow.assert_called_once_with(
            {"chartType": "paths"}, 12345, mode="tree", workspace_id=None
        )

    def test_launch_analysis_unsupported(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """launch-analysis cannot be run."""
        with pytest.raises(UnsupportedReportLinkError) as exc_info:
            ws.query_report_link(_resolved("launch-analysis", {}))

        exc = exc_info.value
        assert exc.code == "UNSUPPORTED_REPORT_TYPE"
        assert str(exc) == (
            "Report type 'launch-analysis' cannot be run through mixpanel-headless."
        )
        assert exc.details["hint"] == (
            "Supported types are insights, funnels, retention, and flows."
        )
        mock_live_query.query.assert_not_called()

    def test_resolved_input_does_not_refetch(
        self, ws: Workspace, mock_live_query: MagicMock, mock_api_client: MagicMock
    ) -> None:
        """A ResolvedReport input triggers no record fetch."""
        mock_live_query.query.return_value = QueryResult(
            computed_at="t", from_date="d", to_date="d"
        )

        ws.query_report_link(_resolved("insights", _INSIGHTS_PARAMS))

        mock_api_client.get_bookmark_url.assert_not_called()
        mock_api_client.get_bookmark.assert_not_called()

    def test_str_input_resolves_first(
        self, ws: Workspace, mock_live_query: MagicMock, mock_api_client: MagicMock
    ) -> None:
        """A string input is resolved, then run."""
        mock_api_client.get_bookmark_url.return_value = _slug_record()
        sentinel = QueryResult(computed_at="t", from_date="d", to_date="d")
        mock_live_query.query.return_value = sentinel

        result = ws.query_report_link(_SLUG)

        assert result is sentinel
        mock_api_client.get_bookmark_url.assert_called_once_with(_SLUG)
        mock_live_query.query.assert_called_once_with(
            _INSIGHTS_PARAMS, 12345, workspace_id=None
        )


# =============================================================================
# shortlinks (US3)
# =============================================================================

_SHORT = "https://mixpanel.com/s/AbC123"
_SHORT_TARGET = f"https://mixpanel.com/project/12345/view/75/app/insights#{_SLUG}"


class TestResolveShortLinks:
    """A shortlink expands once and then resolves like its target."""

    def test_short_link_resolves_like_its_target(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """The result equals a direct resolve plus ``expanded_url`` and ``input``."""
        mock_api_client.resolve_short_link.return_value = _SHORT_TARGET
        mock_api_client.get_bookmark_url.return_value = _slug_record()

        direct = ws.resolve_report_link(_SHORT_TARGET)
        via_short = ws.resolve_report_link(_SHORT)

        mock_api_client.resolve_short_link.assert_called_once_with("AbC123")
        assert via_short.expanded_url == _SHORT_TARGET
        assert via_short.input == _SHORT
        assert (
            dataclasses.replace(via_short, expanded_url=None, input=_SHORT_TARGET)
            == direct
        )

    def test_short_link_to_bookmark(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A shortlink whose target is a saved report resolves that bookmark."""
        mock_api_client.resolve_short_link.return_value = (
            "https://mixpanel.com/project/12345/app/insights#report/123"
        )
        mock_api_client.get_bookmark.return_value = _BOOKMARK_RAW

        resolved = ws.resolve_report_link(_SHORT)

        assert resolved.source == "bookmark"
        assert resolved.bookmark_id == 123
        assert resolved.expanded_url == (
            "https://mixpanel.com/project/12345/app/insights#report/123"
        )

    def test_short_link_chain_raises(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A shortlink whose target is another shortlink stops with SHORT_LINK_CHAIN."""
        mock_api_client.resolve_short_link.return_value = "https://mixpanel.com/s/XyZ"

        with pytest.raises(ShortLinkResolutionError) as exc_info:
            ws.resolve_report_link(_SHORT)

        exc = exc_info.value
        assert exc.code == "SHORT_LINK_CHAIN"
        assert str(exc) == (
            "Shortlink /s/AbC123 redirects to another shortlink "
            "(https://mixpanel.com/s/XyZ). mixpanel-headless follows one redirect "
            "only."
        )
        assert exc.details["hint"] == "Resolve the target shortlink directly."
        assert exc.details["target"] == "https://mixpanel.com/s/XyZ"
        mock_api_client.resolve_short_link.assert_called_once()
        mock_api_client.get_bookmark_url.assert_not_called()

    def test_short_link_to_dashboard_unsupported(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A shortlink whose target is a dashboard is unsupported."""
        mock_api_client.resolve_short_link.return_value = (
            "https://mixpanel.com/project/12345/app/boards#id=555"
        )

        with pytest.raises(UnsupportedReportLinkError) as exc_info:
            ws.resolve_report_link(_SHORT)

        assert exc_info.value.code == "UNSUPPORTED_DASHBOARD_LINK"
        mock_api_client.get_bookmark_url.assert_not_called()

    def test_short_link_target_in_other_project(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A target in another project fails before any record fetch."""
        mock_api_client.resolve_short_link.return_value = (
            f"https://mixpanel.com/project/3/app/insights#{_SLUG}"
        )

        with pytest.raises(ReportLinkScopeMismatchError) as exc_info:
            ws.resolve_report_link(_SHORT)

        assert exc_info.value.code == "REPORT_LINK_PROJECT_MISMATCH"
        mock_api_client.get_bookmark_url.assert_not_called()
        mock_api_client.get_bookmark.assert_not_called()

    def test_short_link_region_mismatch_before_network(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """An EU shortlink on a US session fails before the redirect GET."""
        with pytest.raises(ReportLinkScopeMismatchError) as exc_info:
            ws.resolve_report_link("https://eu.mixpanel.com/s/AbC123")

        assert exc_info.value.code == "REPORT_LINK_REGION_MISMATCH"
        mock_api_client.resolve_short_link.assert_not_called()

    def test_short_link_errors_propagate(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """Client errors from the redirect GET propagate unchanged."""
        mock_api_client.resolve_short_link.side_effect = ReportLinkNotFoundError(
            "gone", code="SHORT_LINK_NOT_FOUND"
        )

        with pytest.raises(ReportLinkNotFoundError) as exc_info:
            ws.resolve_report_link(_SHORT)

        assert exc_info.value.code == "SHORT_LINK_NOT_FOUND"

    def test_query_report_link_through_short_link(
        self, ws: Workspace, mock_live_query: MagicMock, mock_api_client: MagicMock
    ) -> None:
        """``query_report_link`` on a shortlink expands, fetches, and runs."""
        mock_api_client.resolve_short_link.return_value = _SHORT_TARGET
        mock_api_client.get_bookmark_url.return_value = _slug_record()
        sentinel = QueryResult(computed_at="t", from_date="d", to_date="d")
        mock_live_query.query.return_value = sentinel

        assert ws.query_report_link(_SHORT) is sentinel
        # The expanded target names /view/75/, so the report runs under 75.
        mock_live_query.query.assert_called_once_with(
            _INSIGHTS_PARAMS, 12345, workspace_id=75
        )


# =============================================================================
# saved_report_link (US5)
# =============================================================================


class TestSavedReportLink:
    """A pure URL builder for saved reports: no network, no resolution."""

    @pytest.mark.parametrize(
        ("report_type", "tail"),
        [
            ("insights", "insights#report/123"),
            ("funnels", "funnels#view/123"),
            ("retention", "retention#report/123"),
            ("flows", "flows#report/123"),
            ("launch-analysis", "impact#report/123"),
        ],
    )
    def test_url_shape_per_type(
        self, ws: Workspace, mock_api_client: MagicMock, report_type: str, tail: str
    ) -> None:
        """Each BookmarkType maps to its app and hash form."""
        url = ws.saved_report_link(123, report_type=report_type)  # type: ignore[arg-type]

        assert url == f"https://mixpanel.com/project/12345/app/{tail}"
        assert mock_api_client.method_calls == []

    def test_default_type_is_insights(self, ws: Workspace) -> None:
        """No ``report_type`` means insights."""
        assert ws.saved_report_link(123) == (
            "https://mixpanel.com/project/12345/app/insights#report/123"
        )

    def test_singular_funnel_normalizes(self, ws: Workspace) -> None:
        """``SavedReportResult.report_type`` yields ``funnel``; it is accepted."""
        assert ws.saved_report_link(456, report_type="funnel") == (
            "https://mixpanel.com/project/12345/app/funnels#view/456"
        )

    def test_explicit_workspace(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """An explicit workspace_id is embedded; nothing is resolved."""
        url = ws.saved_report_link(123, workspace_id=5)

        assert (
            url == "https://mixpanel.com/project/12345/view/5/app/insights#report/123"
        )
        mock_api_client.resolve_workspace_id.assert_not_called()

    def test_pinned_workspace(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """The pinned session workspace is used when no explicit one is given."""
        ws = workspace_factory(session=_PINNED_SESSION)

        url = ws.saved_report_link(123)

        assert "/view/75/" in url
        mock_api_client.resolve_workspace_id.assert_not_called()

    def test_explicit_beats_pinned(
        self, workspace_factory: Callable[..., Workspace]
    ) -> None:
        """Explicit wins over pinned."""
        ws = workspace_factory(session=_PINNED_SESSION)

        assert "/view/5/" in ws.saved_report_link(123, workspace_id=5)

    def test_no_workspace_is_omitted_never_resolved(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """Without explicit or pinned workspace the segment is omitted."""
        url = ws.saved_report_link(123)

        assert "/view/" not in url
        mock_api_client.resolve_workspace_id.assert_not_called()

    def test_eu_session_host(self, workspace_factory: Callable[..., Workspace]) -> None:
        """An EU session uses eu.mixpanel.com."""
        ws = workspace_factory(session=_EU_SESSION)

        assert ws.saved_report_link(123).startswith("https://eu.mixpanel.com/")

    def test_unknown_type_raises_rl1(self, ws: Workspace) -> None:
        """An unknown type raises RL1_UNKNOWN_REPORT_TYPE."""
        with pytest.raises(ParamValidationError) as exc_info:
            ws.saved_report_link(123, report_type="boards")  # type: ignore[arg-type]

        assert exc_info.value.code == "RL1_UNKNOWN_REPORT_TYPE"

    def test_client_records_zero_calls(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """The API client is never touched."""
        ws.saved_report_link(1)
        ws.saved_report_link(2, report_type="flows", workspace_id=3)

        assert mock_api_client.method_calls == []


# =============================================================================
# review follow-ups (PR #223)
# =============================================================================


class TestQueryReportLinkScopeOnResolvedInput:
    """A retained ResolvedReport must not run against a different session scope."""

    def test_project_mismatch_raises_before_query(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """A ResolvedReport from project 3 on a project-12345 session is rejected."""
        resolved = dataclasses.replace(
            _resolved("insights", _INSIGHTS_PARAMS), project_id=3
        )

        with pytest.raises(ReportLinkScopeMismatchError) as exc_info:
            ws.query_report_link(resolved)

        exc = exc_info.value
        assert exc.code == "REPORT_LINK_PROJECT_MISMATCH"
        assert exc.details["link_project_id"] == 3
        assert exc.details["session_project_id"] == 12345
        assert 'ws.use(project="3")' in exc.details["hint"]
        mock_live_query.query.assert_not_called()

    def test_region_mismatch_raises_before_query(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """A ResolvedReport from the EU region on a US session is rejected."""
        resolved = dataclasses.replace(
            _resolved("insights", _INSIGHTS_PARAMS), region="eu"
        )

        with pytest.raises(ReportLinkScopeMismatchError) as exc_info:
            ws.query_report_link(resolved)

        assert exc_info.value.code == "REPORT_LINK_REGION_MISMATCH"
        mock_live_query.query.assert_not_called()

    def test_matching_scope_runs(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """A ResolvedReport that matches the session runs as before."""
        sentinel = QueryResult(computed_at="t", from_date="d", to_date="d")
        mock_live_query.query.return_value = sentinel

        assert ws.query_report_link(_resolved("insights", _INSIGHTS_PARAMS)) is sentinel

    def test_scope_checked_after_use_switch(
        self,
        workspace_factory: Callable[..., Workspace],
        mock_api_client: MagicMock,
    ) -> None:
        """Resolving on one session and running after ``use(project=...)`` is rejected."""
        from mixpanel_headless._internal.services.live_query import LiveQueryService

        ws = workspace_factory()
        svc = MagicMock(spec=LiveQueryService)
        ws._live_query = svc
        mock_api_client.get_bookmark_url.return_value = _slug_record()
        resolved = ws.resolve_report_link(_SLUG)

        other = workspace_factory(
            session=_TEST_SESSION.replace(project=Project(id="777"))
        )
        other._live_query = svc

        with pytest.raises(ReportLinkScopeMismatchError):
            other.query_report_link(resolved)

        svc.query.assert_not_called()


class TestResolveSlugWithUnknownServerType:
    """An unknown record ``type`` resolves; the canonical URL falls back, never RL1."""

    def test_unknown_type_falls_back_to_parsed_app(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A ``user`` record under /app/insights keeps the insights app in the URL."""
        mock_api_client.get_bookmark_url.return_value = _slug_record(type="user")

        resolved = ws.resolve_report_link(
            f"https://mixpanel.com/project/12345/app/insights#{_SLUG}"
        )

        assert resolved.report_type == "user"
        assert (
            resolved.url == f"https://mixpanel.com/project/12345/app/insights#{_SLUG}"
        )

    def test_unknown_type_on_bare_slug_defaults_to_insights_app(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A bare slug carries no app hint, so the URL defaults to the insights app."""
        mock_api_client.get_bookmark_url.return_value = _slug_record(type="user")

        resolved = ws.resolve_report_link(_SLUG)

        assert (
            resolved.url == f"https://mixpanel.com/project/12345/app/insights#{_SLUG}"
        )

    def test_unknown_type_logs_a_warning(
        self,
        ws: Workspace,
        mock_api_client: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The fallback URL is announced, because it may open the wrong app."""
        mock_api_client.get_bookmark_url.return_value = _slug_record(type="user")

        with caplog.at_level("WARNING", logger="mixpanel_headless.workspace"):
            ws.resolve_report_link(_SLUG)

        assert any(
            "unknown report type 'user'" in rec.getMessage()
            and "insights" in rec.getMessage()
            for rec in caplog.records
        )

    def test_unknown_type_cannot_run(
        self, ws: Workspace, mock_api_client: MagicMock, mock_live_query: MagicMock
    ) -> None:
        """Running the unknown type raises UNSUPPORTED_REPORT_TYPE, not RL1."""
        mock_api_client.get_bookmark_url.return_value = _slug_record(type="user")

        with pytest.raises(UnsupportedReportLinkError) as exc_info:
            ws.query_report_link(_SLUG)

        assert exc_info.value.code == "UNSUPPORTED_REPORT_TYPE"


class TestWorkspaceScope:
    """A pinned session workspace must match the link's or report's workspace."""

    def test_url_workspace_differs_from_pinned_raises_before_fetch(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """Pinned to 75, a ``/view/9/`` URL is rejected with no client call."""
        ws = workspace_factory(session=_PINNED_SESSION)

        with pytest.raises(ReportLinkScopeMismatchError) as exc_info:
            ws.resolve_report_link(
                f"https://mixpanel.com/project/12345/view/9/app/insights#{_SLUG}"
            )

        exc = exc_info.value
        assert exc.code == "REPORT_LINK_WORKSPACE_MISMATCH"
        assert exc.details["link_workspace_id"] == 9
        assert exc.details["session_workspace_id"] == 75
        assert str(exc) == (
            "Report link belongs to workspace 9 but the active session is pinned "
            "to workspace 75."
        )
        assert exc.details["hint"] == (
            "Switch with ws.use(workspace=9) (CLI: mp --workspace 9 ...) and retry."
        )
        mock_api_client.get_bookmark_url.assert_not_called()

    def test_url_workspace_equal_to_pinned_is_fine(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """Pinned to 75, a ``/view/75/`` URL resolves."""
        ws = workspace_factory(session=_PINNED_SESSION)
        mock_api_client.get_bookmark_url.return_value = _slug_record()

        resolved = ws.resolve_report_link(
            f"https://mixpanel.com/project/12345/view/75/app/insights#{_SLUG}"
        )

        assert resolved.workspace_id == 75

    def test_unpinned_session_accepts_any_url_workspace(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """Without a pin there is nothing to contradict; the URL wid is kept."""
        mock_api_client.get_bookmark_url.return_value = _slug_record()

        resolved = ws.resolve_report_link(
            f"https://mixpanel.com/project/12345/view/9/app/insights#{_SLUG}"
        )

        assert resolved.workspace_id == 9

    def test_resolved_report_workspace_differs_from_pinned_raises(
        self, workspace_factory: Callable[..., Workspace]
    ) -> None:
        """A report resolved under workspace 9 does not run on a session pinned to 75."""
        from mixpanel_headless._internal.services.live_query import LiveQueryService

        ws = workspace_factory(session=_PINNED_SESSION)
        svc = MagicMock(spec=LiveQueryService)
        ws._live_query = svc
        resolved = dataclasses.replace(
            _resolved("insights", _INSIGHTS_PARAMS), workspace_id=9
        )

        with pytest.raises(ReportLinkScopeMismatchError) as exc_info:
            ws.query_report_link(resolved)

        assert exc_info.value.code == "REPORT_LINK_WORKSPACE_MISMATCH"
        svc.query.assert_not_called()

    def test_resolved_report_without_workspace_runs_on_pinned_session(
        self, workspace_factory: Callable[..., Workspace]
    ) -> None:
        """A report with no recorded workspace runs on a pinned session."""
        from mixpanel_headless._internal.services.live_query import LiveQueryService

        ws = workspace_factory(session=_PINNED_SESSION)
        svc = MagicMock(spec=LiveQueryService)
        ws._live_query = svc
        sentinel = QueryResult(computed_at="t", from_date="d", to_date="d")
        svc.query.return_value = sentinel

        assert ws.query_report_link(_resolved("insights", _INSIGHTS_PARAMS)) is sentinel

    def test_resolved_workspace_is_applied_when_session_is_unpinned(
        self,
        workspace_factory: Callable[..., Workspace],
        mock_api_client: MagicMock,
    ) -> None:
        """Resolve pinned to 75, clear the pin, run: the query still carries 75.

        Greptile P1 on PR #223: a pin-clearing ``use(project=...)`` must not
        silently turn a data-view report into a project-wide one.
        """
        from mixpanel_headless._internal.services.live_query import LiveQueryService

        ws_a = workspace_factory(session=_PINNED_SESSION)
        mock_api_client.get_bookmark_url.return_value = _slug_record()
        resolved = ws_a.resolve_report_link(_SLUG)
        assert resolved.workspace_id == 75

        ws_b = workspace_factory(session=_TEST_SESSION)
        svc = MagicMock(spec=LiveQueryService)
        sentinel = QueryResult(computed_at="t", from_date="d", to_date="d")
        svc.query.return_value = sentinel
        ws_b._live_query = svc

        assert ws_b.query_report_link(resolved) is sentinel
        svc.query.assert_called_once_with(_INSIGHTS_PARAMS, 12345, workspace_id=75)

    def test_url_workspace_is_applied_when_session_is_unpinned(
        self, ws: Workspace, mock_api_client: MagicMock, mock_live_query: MagicMock
    ) -> None:
        """An unpinned session runs a ``/view/9/`` link under workspace 9."""
        mock_api_client.get_bookmark_url.return_value = _slug_record()
        mock_live_query.query.return_value = QueryResult(
            computed_at="t", from_date="d", to_date="d"
        )

        ws.query_report_link(
            f"https://mixpanel.com/project/12345/view/9/app/insights#{_SLUG}"
        )

        mock_live_query.query.assert_called_once_with(
            _INSIGHTS_PARAMS, 12345, workspace_id=9
        )

    def test_pinned_workspace_is_recorded_and_applied(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """A bare slug on a pinned session records 75 and runs under 75."""
        from mixpanel_headless._internal.services.live_query import LiveQueryService

        ws = workspace_factory(session=_PINNED_SESSION)
        mock_api_client.get_bookmark_url.return_value = _slug_record()
        svc = MagicMock(spec=LiveQueryService)
        svc.query.return_value = QueryResult(
            computed_at="t", from_date="d", to_date="d"
        )
        ws._live_query = svc

        ws.query_report_link(_SLUG)

        svc.query.assert_called_once_with(_INSIGHTS_PARAMS, 12345, workspace_id=75)

    def test_scope_checked_after_use_workspace_switch(
        self,
        workspace_factory: Callable[..., Workspace],
        mock_api_client: MagicMock,
    ) -> None:
        """Resolve pinned to 75, then run pinned to 9: rejected before any query."""
        from mixpanel_headless._internal.services.live_query import LiveQueryService

        ws_a = workspace_factory(session=_PINNED_SESSION)
        mock_api_client.get_bookmark_url.return_value = _slug_record()
        resolved = ws_a.resolve_report_link(_SLUG)
        assert resolved.workspace_id == 75

        ws_b = workspace_factory(
            session=_TEST_SESSION.replace(workspace=WorkspaceRef(id=9))
        )
        svc = MagicMock(spec=LiveQueryService)
        ws_b._live_query = svc

        with pytest.raises(ReportLinkScopeMismatchError):
            ws_b.query_report_link(resolved)

        svc.query.assert_not_called()
