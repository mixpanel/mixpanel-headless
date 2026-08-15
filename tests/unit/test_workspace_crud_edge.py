"""Edge case tests for Phase 024 Workspace CRUD methods.

Verifies HTTP request body serialization, empty response handling,
and method delegation for dashboard, bookmark, and cohort operations.

These tests capture the ACTUAL HTTP request body sent through the mock
transport, ensuring the Workspace correctly serializes Pydantic models
before calling the API.
"""
# ruff: noqa: ARG001, ARG005

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless.exceptions import ResponseValidationError
from mixpanel_headless.types import (
    BlueprintCard,
    BlueprintFinishParams,
    BulkUpdateBookmarkEntry,
    BulkUpdateCohortEntry,
    CreateBookmarkParams,
    CreateCohortParams,
    CreateCustomEventParams,
    CreateDashboardParams,
    CreateRcaDashboardParams,
    CreateTagParams,
    CreateWebhookParams,
    RcaSourceData,
    UpdateDashboardParams,
    UpdateReportLinkParams,
)
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session
from tests.unit._bookmark_fixtures import MINIMAL_FUNNEL_PARAMS

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


def _make_creds() -> Session:
    """Create OAuth Credentials for testing.

    Returns:
        A Credentials instance with auth_method=oauth.
    """
    return make_session(project_id="12345", region="us", oauth_token="test-token")


# _make_config removed in B1 (Fix 9): the legacy v1 add_account signature
# is gone and ``_make_workspace`` now uses ``session=_TEST_SESSION``
# instead of resolving through ConfigManager.


def _make_workspace(temp_dir: Path, handler: Any) -> Workspace:
    """Create a Workspace with a mock HTTP transport.

    Args:
        temp_dir: Temporary directory for config and storage.
        handler: Mock transport handler function.

    Returns:
        A Workspace using the mock transport.
    """
    creds = _make_creds()
    transport = httpx.MockTransport(handler)
    client = MixpanelAPIClient(session=creds, _transport=transport)
    return Workspace(
        session=_TEST_SESSION,
        _api_client=client,
    )


class TestRequestBodySerialization:
    """Tests verifying correct HTTP request body serialization (Bug B5)."""

    def test_create_bookmark_sends_type_not_bookmark_type(self, temp_dir: Path) -> None:
        """Verify create_bookmark serializes bookmark_type as 'type' in the request body."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture request body and return a valid bookmark response."""
            if request.method == "POST" and "bookmarks" in str(request.url):
                captured["body"] = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": {
                            "id": 1,
                            "name": "X",
                            "type": "funnels",
                            "params": {},
                        },
                    },
                )
            # Handle PATCH for add_report_to_dashboard
            if request.method == "PATCH":
                return httpx.Response(
                    200, json={"status": "ok", "results": {"id": 99, "title": "T"}}
                )
            return httpx.Response(200, json={"status": "ok", "results": []})

        # Use minimal valid funnel params so client-side schema
        # validation passes; this test is about request body
        # serialization (``bookmark_type`` → ``type`` alias), not about
        # validation behavior.
        ws = _make_workspace(temp_dir, handler)
        ws.create_bookmark(
            CreateBookmarkParams(
                name="X",
                bookmark_type="funnels",
                params=MINIMAL_FUNNEL_PARAMS,
                dashboard_id=99,
            )
        )

        body = captured["body"]
        assert "type" in body
        assert "bookmark_type" not in body
        assert body["type"] == "funnels"

    def test_create_cohort_sends_flattened_definition(self, temp_dir: Path) -> None:
        """Verify create_cohort flattens definition into the top-level request body."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture request body and return a valid cohort response."""
            if request.method == "POST" and "cohorts" in str(request.url):
                captured["body"] = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": {"id": 1, "name": "X"},
                    },
                )
            return httpx.Response(200, json={"status": "ok", "results": []})

        ws = _make_workspace(temp_dir, handler)
        ws.create_cohort(
            CreateCohortParams(
                name="X",
                definition={"behavioral_filter": {"op": "and"}},
            )
        )

        body = captured["body"]
        assert "behavioral_filter" in body
        assert "definition" not in body

    def test_finalize_blueprint_sends_card_type_as_type(self, temp_dir: Path) -> None:
        """Verify finalize_blueprint serializes card_type as 'type' in card entries."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture request body and return a finalized dashboard response."""
            if request.method == "POST" and "blueprints" in str(request.url):
                captured["body"] = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": {"id": 1, "title": "X"},
                    },
                )
            return httpx.Response(200, json={"status": "ok", "results": []})

        ws = _make_workspace(temp_dir, handler)
        ws.finalize_blueprint(
            BlueprintFinishParams(
                dashboard_id=1,
                cards=[BlueprintCard(card_type="report", bookmark_id=42)],
            )
        )

        body = captured["body"]
        assert body["cards"][0]["type"] == "report"
        assert "card_type" not in body["cards"][0]

    def test_create_rca_sends_source_type_as_type(self, temp_dir: Path) -> None:
        """Verify create_rca_dashboard serializes source_type as 'type' in rca_source_data."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture request body and return an RCA dashboard response."""
            if request.method == "POST" and "rca" in str(request.url):
                captured["body"] = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": {"id": 1, "title": "RCA"},
                    },
                )
            return httpx.Response(200, json={"status": "ok", "results": []})

        ws = _make_workspace(temp_dir, handler)
        ws.create_rca_dashboard(
            CreateRcaDashboardParams(
                rca_source_id=42,
                rca_source_data=RcaSourceData(source_type="anomaly"),
            )
        )

        body = captured["body"]
        assert body["rca_source_data"]["type"] == "anomaly"
        assert "source_type" not in body["rca_source_data"]

    def test_update_report_link_sends_type(self, temp_dir: Path) -> None:
        """Verify update_report_link serializes link_type as 'type' in the request body."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture request body and return 204 No Content."""
            if request.method == "PATCH" and "report-links" in str(request.url):
                captured["body"] = json.loads(request.content)
                return httpx.Response(204)
            return httpx.Response(200, json={"status": "ok", "results": []})

        ws = _make_workspace(temp_dir, handler)
        ws.update_report_link(1, 42, UpdateReportLinkParams(link_type="embedded"))

        body = captured["body"]
        assert body["type"] == "embedded"
        assert "link_type" not in body


class TestEmptyResponseHandling:
    """Tests verifying behavior when API returns empty or minimal responses (Bug B3)."""

    def test_create_dashboard_empty_response_raises(self, temp_dir: Path) -> None:
        """Verify create_dashboard raises ResponseValidationError on empty dict.

        An empty dict ``{}`` passes the ``is None`` check but fails Pydantic
        validation because required fields (``id``, ``title``) are missing.
        The response-validation seam wraps that failure in
        ``ResponseValidationError`` (E2 coding pass, design §1.7).
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Return an empty results dict for dashboard creation."""
            return httpx.Response(200, json={"status": "ok", "results": {}})

        ws = _make_workspace(temp_dir, handler)
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.create_dashboard(CreateDashboardParams(title="X"))
        assert excinfo.value.code == "RESPONSE_VALIDATION_ERROR"

    def test_get_bookmark_empty_response_raises(self, temp_dir: Path) -> None:
        """Verify get_bookmark raises ResponseValidationError on empty dict.

        An empty dict ``{}`` passes the ``is None`` check but fails Pydantic
        validation because required fields (``id``, ``name``, ``type``) are
        missing. The response-validation seam wraps that failure in
        ``ResponseValidationError`` (E2 coding pass, design §1.7).
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Return an empty results dict for bookmark retrieval."""
            return httpx.Response(200, json={"status": "ok", "results": {}})

        ws = _make_workspace(temp_dir, handler)
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_bookmark(1)
        assert excinfo.value.code == "RESPONSE_VALIDATION_ERROR"

    def test_list_dashboards_empty_list_ok(self, temp_dir: Path) -> None:
        """Verify list_dashboards returns empty list when API returns empty results."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return an empty results list for dashboard listing."""
            return httpx.Response(200, json={"status": "ok", "results": []})

        ws = _make_workspace(temp_dir, handler)
        result = ws.list_dashboards()
        assert result == []


class TestWorkspaceMethodDelegation:
    """Tests verifying Workspace methods correctly delegate and serialize to API client."""

    def test_bulk_update_bookmarks_serializes_entries(self, temp_dir: Path) -> None:
        """Verify bulk_update_bookmarks sends correctly serialized entries with no None fields."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture request body for bulk bookmark update."""
            if request.method == "POST" and "bookmarks/bulk-update" in str(request.url):
                captured["body"] = json.loads(request.content)
                return httpx.Response(204)
            return httpx.Response(200, json={"status": "ok", "results": []})

        ws = _make_workspace(temp_dir, handler)
        ws.bulk_update_bookmarks([BulkUpdateBookmarkEntry(id=1, name="Renamed")])

        body = captured["body"]
        assert body == {"bookmarks": [{"id": 1, "name": "Renamed"}]}

    def test_bulk_update_cohorts_serializes_entries_with_definition(
        self, temp_dir: Path
    ) -> None:
        """Verify bulk_update_cohorts flattens definition into each entry."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture request body for bulk cohort update."""
            if request.method == "POST" and "cohorts/bulk-update" in str(request.url):
                captured["body"] = json.loads(request.content)
                return httpx.Response(204)
            return httpx.Response(200, json={"status": "ok", "results": []})

        ws = _make_workspace(temp_dir, handler)
        ws.bulk_update_cohorts(
            [BulkUpdateCohortEntry(id=1, definition={"filter": "x"})]
        )

        body = captured["body"]
        entry = body["cohorts"][0]
        assert entry["id"] == 1
        assert entry["filter"] == "x"
        assert "definition" not in entry

    def test_update_dashboard_exclude_none(self, temp_dir: Path) -> None:
        """Verify update_dashboard sends only non-None fields in request body."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture request body for dashboard update."""
            if request.method == "PATCH" and "dashboards" in str(request.url):
                captured["body"] = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": {"id": 1, "title": "New"},
                    },
                )
            return httpx.Response(200, json={"status": "ok", "results": []})

        ws = _make_workspace(temp_dir, handler)
        ws.update_dashboard(1, UpdateDashboardParams(title="New"))

        body = captured["body"]
        assert body == {"title": "New"}

    def test_list_bookmarks_v2_no_filters(self, temp_dir: Path) -> None:
        """Verify list_bookmarks_v2 with no args sends no type or ids query params."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture request URL for bookmark listing."""
            if "/bookmarks" in str(request.url):
                captured["url"] = str(request.url)
                return httpx.Response(200, json={"status": "ok", "results": []})
            return httpx.Response(200, json={"status": "ok", "results": []})

        ws = _make_workspace(temp_dir, handler)
        ws.list_bookmarks_v2()

        url = captured["url"]
        assert "type=" not in url
        assert "ids=" not in url


# =============================================================================
# Coded response-validation seams (E2 coding pass, design §1.7)
# =============================================================================


def _make_results_workspace(
    results: Any, *, workspace_id: int | None = None
) -> Workspace:
    """Create a Workspace whose transport always returns ``results``.

    Args:
        results: The JSON value placed under the ``results`` envelope key
            for every request.
        workspace_id: Optional workspace ID to pin on the client so
            workspace-scoped methods skip workspace resolution.

    Returns:
        A Workspace wired to the canned-response mock transport.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the canned results envelope for any request."""
        return httpx.Response(200, json={"status": "ok", "results": results})

    creds = _make_creds()
    transport = httpx.MockTransport(handler)
    client = MixpanelAPIClient(session=creds, _transport=transport)
    if workspace_id is not None:
        client.set_workspace_id(workspace_id)
    return Workspace(session=_TEST_SESSION, _api_client=client)


class TestCodedResponseValidationCodes:
    """Response seams raise ResponseValidationError with the generic code.

    One test pair per swept ``model_validate`` method family (design §1.7).
    Assertions are class + ``.code`` only — never message text (R5.4).
    """

    def _assert_coded(self, exc: ResponseValidationError) -> None:
        """Assert the generic response-validation contract on *exc*.

        Args:
            exc: The captured ResponseValidationError.
        """
        assert exc.code == "RESPONSE_VALIDATION_ERROR"

    def test_list_dashboards_invalid_item_raises_coded_error(self) -> None:
        """Dashboards family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_dashboards()
        self._assert_coded(excinfo.value)

    def test_list_bookmarks_v2_invalid_item_raises_coded_error(self) -> None:
        """Bookmarks family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_bookmarks_v2()
        self._assert_coded(excinfo.value)

    def test_get_cohort_invalid_response_raises_coded_error(self) -> None:
        """Cohorts family (single member): empty dict response is wrapped."""
        ws = _make_results_workspace({})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_cohort(1)
        self._assert_coded(excinfo.value)

    def test_list_cohorts_full_invalid_item_raises_coded_error(self) -> None:
        """Cohorts family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_cohorts_full()
        self._assert_coded(excinfo.value)

    def test_get_feature_flag_invalid_response_raises_coded_error(self) -> None:
        """Flags family (single member): empty dict response is wrapped."""
        ws = _make_results_workspace({}, workspace_id=777)
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_feature_flag("f1")
        self._assert_coded(excinfo.value)

    def test_list_feature_flags_invalid_item_raises_coded_error(self) -> None:
        """Flags family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}], workspace_id=777)
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_feature_flags()
        self._assert_coded(excinfo.value)

    def test_get_experiment_invalid_response_raises_coded_error(self) -> None:
        """Experiments family (single member): empty dict is wrapped."""
        ws = _make_results_workspace({})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_experiment("e1")
        self._assert_coded(excinfo.value)

    def test_list_experiments_invalid_item_raises_coded_error(self) -> None:
        """Experiments family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_experiments()
        self._assert_coded(excinfo.value)

    def test_get_annotation_invalid_response_raises_coded_error(self) -> None:
        """Annotations family (single member): empty dict is wrapped."""
        ws = _make_results_workspace({})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_annotation(1)
        self._assert_coded(excinfo.value)

    def test_list_annotations_invalid_item_raises_coded_error(self) -> None:
        """Annotations family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_annotations()
        self._assert_coded(excinfo.value)

    def test_create_webhook_invalid_response_raises_coded_error(self) -> None:
        """Webhooks family (single member): empty dict is wrapped."""
        ws = _make_results_workspace({})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.create_webhook(CreateWebhookParams(name="W", url="https://x.test/h"))
        self._assert_coded(excinfo.value)

    def test_list_webhooks_invalid_item_raises_coded_error(self) -> None:
        """Webhooks family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_webhooks()
        self._assert_coded(excinfo.value)

    def test_get_alert_invalid_response_raises_coded_error(self) -> None:
        """Alerts family (single member): empty dict is wrapped."""
        ws = _make_results_workspace({})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_alert(1)
        self._assert_coded(excinfo.value)

    def test_list_alerts_invalid_item_raises_coded_error(self) -> None:
        """Alerts family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_alerts()
        self._assert_coded(excinfo.value)

    def test_get_event_definitions_invalid_item_raises_coded_error(self) -> None:
        """Lexicon-definitions family: invalid event definition is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_event_definitions(names=["x"])
        self._assert_coded(excinfo.value)

    def test_get_property_definitions_invalid_item_raises_coded_error(self) -> None:
        """Lexicon-definitions family: invalid property definition is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_property_definitions(names=["p"])
        self._assert_coded(excinfo.value)

    def test_create_lexicon_tag_invalid_response_raises_coded_error(self) -> None:
        """Lexicon-tags family (single member): empty dict is wrapped."""
        ws = _make_results_workspace({})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.create_lexicon_tag(CreateTagParams(name="T"))
        self._assert_coded(excinfo.value)

    def test_list_lexicon_tags_invalid_item_raises_coded_error(self) -> None:
        """Lexicon-tags family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_lexicon_tags()
        self._assert_coded(excinfo.value)

    def test_get_drop_filter_limits_invalid_response_raises_coded_error(self) -> None:
        """Drop-filters family (single member): empty dict is wrapped."""
        ws = _make_results_workspace({})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_drop_filter_limits()
        self._assert_coded(excinfo.value)

    def test_list_drop_filters_invalid_item_raises_coded_error(self) -> None:
        """Drop-filters family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_drop_filters()
        self._assert_coded(excinfo.value)

    def test_get_custom_property_invalid_response_raises_coded_error(self) -> None:
        """Custom-properties family (single member): empty dict is wrapped."""
        ws = _make_results_workspace({})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_custom_property("cp1")
        self._assert_coded(excinfo.value)

    def test_list_custom_properties_invalid_item_raises_coded_error(self) -> None:
        """Custom-properties family (list member): invalid item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_custom_properties()
        self._assert_coded(excinfo.value)

    def test_get_lookup_upload_url_invalid_response_raises_coded_error(self) -> None:
        """Lookup-tables family (single member): type-invalid url is wrapped."""
        ws = _make_results_workspace({"url": 123, "path": "p", "key": "k"})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.get_lookup_upload_url()
        self._assert_coded(excinfo.value)

    def test_list_lookup_tables_invalid_item_raises_coded_error(self) -> None:
        """Lookup-tables family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_lookup_tables()
        self._assert_coded(excinfo.value)

    def test_create_custom_event_invalid_response_raises_coded_error(self) -> None:
        """Custom-events family (single member): empty dict is wrapped."""
        ws = _make_results_workspace({})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.create_custom_event(
                CreateCustomEventParams(name="CE", alternatives=["A"])
            )
        self._assert_coded(excinfo.value)

    def test_list_custom_events_invalid_item_raises_coded_error(self) -> None:
        """Custom-events family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_custom_events()
        self._assert_coded(excinfo.value)

    def test_delete_schemas_invalid_response_raises_coded_error(self) -> None:
        """Schemas family (single member): empty dict is wrapped."""
        ws = _make_results_workspace({})
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.delete_schemas()
        self._assert_coded(excinfo.value)

    def test_list_schema_registry_invalid_item_raises_coded_error(self) -> None:
        """Schemas family (list member): invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_schema_registry()
        self._assert_coded(excinfo.value)

    def test_cancel_deletion_request_invalid_item_raises_coded_error(self) -> None:
        """Governance-monitoring family: invalid deletion entry is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.cancel_deletion_request(42)
        self._assert_coded(excinfo.value)

    def test_list_deletion_requests_invalid_item_raises_coded_error(self) -> None:
        """Governance-monitoring family: invalid list item is wrapped."""
        ws = _make_results_workspace([{}])
        with pytest.raises(ResponseValidationError) as excinfo:
            ws.list_deletion_requests()
        self._assert_coded(excinfo.value)
