# ruff: noqa: ARG001, ARG005
"""Tests over the recorded App API responses for saved metrics and behaviors.

The fixtures in ``tests/fixtures/saved_metrics/`` are redacted responses of a
live probe of the ``/metrics`` and ``/behaviors`` endpoints. Emails, person
names, and user ids are replaced; keys and structure are exact. These tests
check that:

- every recorded list, get, create, and update row parses into
  ``SavedMetric`` or ``SavedBehavior``, with the accessors and conditional
  keys that the server sends for that response;
- the recorded 404 (unknown and deleted metric), 500 (unknown behavior,
  whose body has ``message``, not ``error``), and 501 (single-metric DELETE)
  bodies map to the expected exceptions;
- the recorded bulk DELETE bodies are accepted.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless.exceptions import ParamValidationError, QueryError, ServerError
from mixpanel_headless.types import SavedBehavior, SavedMetric
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "saved_metrics"

_SESSION = Session(
    account=ServiceAccount(
        name="test_account",
        region="us",
        username="test_user",
        secret=SecretStr("test_secret"),
        default_project="12345",
    ),
    project=Project(id="12345"),
)


def _load(name: str) -> Any:
    """Load one recorded response body.

    Args:
        name: The fixture file name without ``.json``.

    Returns:
        The decoded JSON body.
    """
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _rows(name: str) -> list[dict[str, Any]]:
    """Return the entity rows of a recorded id-keyed response.

    Args:
        name: The fixture file name without ``.json``.

    Returns:
        The values of the ``results`` map.
    """
    return list(_load(name)["results"].values())


def _workspace(handler: Any) -> Workspace:
    """Create a Workspace wired to a mock transport.

    Args:
        handler: Handler function for httpx.MockTransport.

    Returns:
        The Workspace.
    """
    creds = make_session(project_id="12345", region="us", oauth_token="test-token")
    client = MixpanelAPIClient(session=creds, _transport=httpx.MockTransport(handler))
    return Workspace(session=_SESSION, _api_client=client)


def _replay(status: int, name: str) -> Any:
    """Build a handler that answers every request with a recorded body.

    Args:
        status: The HTTP status to return.
        name: The fixture file name without ``.json``.

    Returns:
        A MockTransport handler.
    """
    body = _load(name)

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the recorded body."""
        return httpx.Response(status, json=body)

    return handler


# =============================================================================
# Recorded rows parse
# =============================================================================


_METRIC_FIXTURES = [
    "create_metric",
    "create_formula_id_operands",
    "create_metric_post_drops_verified_owner",
    "create_metric_warehouse",
    "get_metric",
    "list_metrics",
    "patch_metric_owned_by",
    "patch_metric_unverified",
    "patch_metric_verified",
]
"""Recorded responses whose rows are saved metrics."""

_BEHAVIOR_FIXTURES = ["create_behavior", "list_behaviors", "patch_behavior_verified"]
"""Recorded responses whose rows are saved behaviors."""


@pytest.mark.parametrize("name", _METRIC_FIXTURES)
def test_every_recorded_metric_row_parses(name: str) -> None:
    """Each recorded metric row parses, keeps its keys, and reads safely.

    Args:
        name: The fixture file name.
    """
    for row in _rows(name):
        metric = SavedMetric.model_validate(row)
        assert metric.id == row["id"]
        assert metric.type in ("metric", "formula", "warehouse")
        assert isinstance(metric.created, datetime)
        assert metric.created_by is not None
        assert metric.model_dump()["is_superadmin"] == row["is_superadmin"]
        _ = (metric.behavior_type, metric.math, metric.formula_expression)
        _ = (metric.referenced_metric_ids, metric.display, metric.goals)


@pytest.mark.parametrize("name", _BEHAVIOR_FIXTURES)
def test_every_recorded_behavior_row_parses(name: str) -> None:
    """Each recorded behavior row parses and has a behavior type.

    Args:
        name: The fixture file name.
    """
    for row in _rows(name):
        behavior = SavedBehavior.model_validate(row)
        assert behavior.type in ("simple", "funnel", "retention")
        assert behavior.behavior_type == behavior.type
        assert "contacts" not in row
        assert "owned_by" not in row


class TestRecordedMetricShapes:
    """Accessors and conditional keys of specific recorded responses."""

    def test_event_metric(self) -> None:
        """A created event metric has behavior type event and math total."""
        (row,) = _rows("create_metric")
        metric = SavedMetric.model_validate(row)
        assert metric.behavior_type == "event"
        assert metric.math == "total"
        assert metric.verified is False
        assert metric.can_update_basic is True

    def test_formula_with_id_operands(self) -> None:
        """The server adds a string metric_id to each id operand; both read back."""
        (row,) = _rows("create_formula_id_operands")
        metric = SavedMetric.model_validate(row)
        assert metric.type == "formula"
        assert metric.formula_expression == "A / B"
        operands = row["definition"]["formula"]["referencedMetrics"]
        assert all(op["metric_id"] == str(op["id"]) for op in operands)
        assert metric.referenced_metric_ids == [op["id"] for op in operands]

    def test_warehouse_metric_keeps_the_raw_definition(self) -> None:
        """A warehouse create stores no aggregation or syncInterval unless sent."""
        (row,) = _rows("create_metric_warehouse")
        metric = SavedMetric.model_validate(row)
        assert metric.type == "warehouse"
        assert metric.warehouse_source_id == row["warehouse_source_id"]
        assert "aggregation" not in metric.definition
        assert "syncInterval" not in metric.definition

    def test_create_drops_verified_and_owner(self) -> None:
        """A create that sent verified and owned_by comes back without them."""
        (row,) = _rows("create_metric_post_drops_verified_owner")
        metric = SavedMetric.model_validate(row)
        assert metric.verified is False
        assert metric.owned_by is None
        assert metric.contacts == []

    def test_patch_verified(self) -> None:
        """A verified PATCH adds verified, last_verified, and last_verified_by."""
        (row,) = _rows("patch_metric_verified")
        metric = SavedMetric.model_validate(row)
        assert metric.verified is True
        assert isinstance(metric.last_verified, datetime)
        assert metric.last_verified_by is not None

    def test_patch_owner_sets_contacts(self) -> None:
        """An owner PATCH adds owned_by and puts the owner email in contacts."""
        (row,) = _rows("patch_metric_owned_by")
        metric = SavedMetric.model_validate(row)
        assert metric.owned_by is not None
        assert metric.contacts == [metric.owned_by.email]

    def test_patch_unverified_removes_the_keys(self) -> None:
        """An unverified PATCH removes verified, last_verified, and last_verified_by."""
        (row,) = _rows("patch_metric_unverified")
        assert "verified" not in row
        metric = SavedMetric.model_validate(row)
        assert metric.verified is False
        assert metric.last_verified is None
        assert metric.last_verified_by is None

    def test_behavior_description_is_null(self) -> None:
        """A behavior created without a description reads back with None."""
        (row,) = _rows("create_behavior")
        assert SavedBehavior.model_validate(row).description is None

    def test_patch_behavior_verified(self) -> None:
        """A verified behavior PATCH adds the verified keys."""
        (row,) = _rows("patch_behavior_verified")
        behavior = SavedBehavior.model_validate(row)
        assert behavior.verified is True
        assert behavior.last_verified_by is not None


class TestRecordedListsThroughTheWorkspace:
    """The recorded list responses flow through the Workspace list methods."""

    def test_list_metrics(self) -> None:
        """list_metrics parses every recorded row, in server order."""
        ws = _workspace(_replay(200, "list_metrics"))
        metrics = ws.list_metrics()
        assert [m.id for m in metrics] == [r["id"] for r in _rows("list_metrics")]

    def test_list_behaviors(self) -> None:
        """list_behaviors parses every recorded row."""
        ws = _workspace(_replay(200, "list_behaviors"))
        assert len(ws.list_behaviors()) == len(_rows("list_behaviors"))


# =============================================================================
# Recorded error bodies map to exceptions
# =============================================================================


class TestRecordedErrors:
    """The recorded error bodies map to the library's exceptions."""

    @pytest.mark.parametrize(
        "name", ["error_404_unknown_metric", "error_404_deleted_metric"]
    )
    def test_404_metric_get(self, name: str) -> None:
        """An unknown or deleted metric id raises QueryError 404 with the server text.

        Args:
            name: The fixture file name.
        """
        ws = _workspace(_replay(404, name))
        with pytest.raises(QueryError) as exc_info:
            ws.get_metric(1)
        assert exc_info.value.status_code == 404
        assert exc_info.value.message == _load(name)["error"]

    def test_404_metric_delete_is_refused(self) -> None:
        """A deleted metric id makes delete_metric refuse with SM5."""
        ws = _workspace(_replay(404, "error_404_deleted_metric"))
        with pytest.raises(ParamValidationError) as exc_info:
            ws.delete_metric(162521)
        assert exc_info.value.code == "SM5_NOT_FOUND_FOR_DELETE"

    def test_500_unknown_behavior(self) -> None:
        """The unknown-behavior 500 (key ``message``) raises ServerError with the body."""
        body = _load("error_500_unknown_behavior")
        assert "error" not in body
        ws = _workspace(_replay(500, "error_500_unknown_behavior"))
        with pytest.raises(ServerError) as exc_info:
            ws.get_behavior(999999999)
        assert exc_info.value.status_code == 500
        assert exc_info.value.response_body == body

    def test_500_unknown_behavior_stops_a_delete(self) -> None:
        """delete_behavior of an unknown id fails on its read and sends no DELETE."""
        methods: list[str] = []
        body = _load("error_500_unknown_behavior")

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the method and return the recorded 500."""
            methods.append(request.method)
            return httpx.Response(500, json=body)

        ws = _workspace(handler)
        with pytest.raises(ServerError):
            ws.delete_behavior(999999999)
        assert methods == ["GET"]

    def test_501_single_metric_delete(self) -> None:
        """The single-metric DELETE route answers 501, so the library never uses it."""
        body = _load("error_501_single_delete")
        creds = make_session(project_id="12345", region="us", oauth_token="t")
        client = MixpanelAPIClient(
            session=creds,
            _transport=httpx.MockTransport(
                lambda request: httpx.Response(501, json=body)
            ),
        )
        with pytest.raises(ServerError) as exc_info:
            client.app_request("DELETE", "/projects/12345/metrics/1")
        assert exc_info.value.status_code == 501
        assert "NOT IMPLEMENTED" in exc_info.value.message

    @pytest.mark.parametrize(
        ("name", "call"),
        [
            ("delete_metrics_bulk", "delete_metrics"),
            ("delete_behaviors_bulk", "delete_behaviors"),
        ],
    )
    def test_bulk_delete_bodies(self, name: str, call: str) -> None:
        """The recorded bulk DELETE body (an empty results map) is accepted.

        Args:
            name: The fixture file name.
            call: The client method to run.
        """
        assert _load(name) == {"results": {}, "status": "ok"}
        creds = make_session(project_id="12345", region="us", oauth_token="t")
        client = MixpanelAPIClient(
            session=creds, _transport=httpx.MockTransport(_replay(200, name))
        )
        assert getattr(client, call)([1]) is None
