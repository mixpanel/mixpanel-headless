# ruff: noqa: ARG001, ARG005
"""Unit tests for the Workspace saved metric and saved behavior write methods.

Tests for:
- ``create_metric``: the exact POST body per definition kind, the follow-up
  PATCH for owner and verified, and the checks that run before any request
- ``update_metric``: the reads it needs, the full definition it sends, and
  the kind-change refusal
- ``bulk_update_metrics``, ``create_behavior``, ``update_behavior``
- The explanation of the server's blank 403 on an update, and the reads
  that it makes

Every refusal test also checks that no request left the client.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr

from mixpanel_headless._internal import saved_definitions
from mixpanel_headless._internal.api_client import (
    DEFAULT_APP_TIMEOUT_S,
    MixpanelAPIClient,
)
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless._internal.query.metric_builders import (
    build_behavior_definition,
    build_formula_definition,
    build_metric_definition,
)
from mixpanel_headless._internal.saved_definitions import (
    find_server_skipped_keys,
    strip_server_skipped_keys,
)
from mixpanel_headless.exceptions import (
    MixpanelHeadlessError,
    ParamValidationError,
    QueryError,
    ResponseValidationError,
)
from mixpanel_headless.types import (
    BulkUpdateMetricEntry,
    CohortMetric,
    CreateBehaviorParams,
    CreateMetricParams,
    Formula,
    FunnelBehavior,
    FunnelMetric,
    Metric,
    MetricDisplay,
    MetricGoal,
    MetricRef,
    RawBehaviorDefinition,
    RawMetricDefinition,
    RetentionBehavior,
    RetentionMetric,
    SavedBehavior,
    SavedMetric,
    SimpleBehavior,
    UpdateBehaviorParams,
    UpdateMetricParams,
    WarehouseMetric,
)
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session
from tests.unit._saved_metric_fixtures import (
    behavior_metric_json,
    envelope,
    formula_metric_json,
    legacy_behavior_json,
    legacy_formula_metric_json,
    legacy_funnel_metric_json,
    saved_behavior_json,
    warehouse_metric_json,
)

# ---- canonical fake Session for Workspace(session=…) ----
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

_METRICS_PATH = "/api/app/projects/12345/metrics"
_BEHAVIORS_PATH = "/api/app/projects/12345/behaviors"

_LOGIN_BEHAVIOR: dict[str, Any] = {
    "type": "event",
    "name": "Login",
    "resourceType": "events",
    "filtersDeterminer": "all",
    "filters": [],
}
"""The behavior block of ``Metric("Login")``."""


# =============================================================================
# Helpers
# =============================================================================


def _make_workspace(temp_dir: Path, handler: Any) -> Workspace:
    """Create a Workspace with a mock HTTP transport.

    Args:
        temp_dir: Temporary directory for config and storage.
        handler: Handler function for httpx.MockTransport.

    Returns:
        A Workspace instance wired to the mock transport.
    """
    creds = make_session(project_id="12345", region="us", oauth_token="test-token")
    transport = httpx.MockTransport(handler)
    client = MixpanelAPIClient(session=creds, _transport=transport)
    return Workspace(session=_TEST_SESSION, _api_client=client)


class _Server:
    """A scripted App API: answers each (method, path) with a canned response."""

    def __init__(self, routes: dict[tuple[str, str], httpx.Response]) -> None:
        """Store the routes and start an empty request log.

        Args:
            routes: Response per ``(method, url path)``.
        """
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Record the request and return its canned response.

        Args:
            request: The outgoing request.

        Returns:
            The response for the request's method and path.
        """
        self.requests.append(request)
        return self.routes[(request.method, request.url.path)]

    def calls(self) -> list[tuple[str, str]]:
        """Return the (method, path) of every request, in order.

        Returns:
            The request log as pairs.
        """
        return [(r.method, r.url.path) for r in self.requests]

    def body(self, index: int) -> Any:
        """Return the decoded JSON body of one logged request.

        Args:
            index: Position in the request log.

        Returns:
            The parsed JSON body.
        """
        return json.loads(self.requests[index].content)


def _ok(*rows: dict[str, Any]) -> httpx.Response:
    """Build a 200 response with an id-keyed results map.

    Args:
        *rows: Entity rows.

    Returns:
        The response.
    """
    return httpx.Response(200, json=envelope(*rows))


# =============================================================================
# create_metric
# =============================================================================


class TestCreateMetric:
    """Tests for Workspace.create_metric()."""

    @pytest.mark.parametrize(
        "stored",
        [behavior_metric_json(1), formula_metric_json(2), warehouse_metric_json(3)],
    )
    def test_copy_from_a_get(self, temp_dir: Path, stored: dict[str, Any]) -> None:
        """A copy made from get_metric with to_raw_definition keeps the source.

        A warehouse metric keeps its source outside the definition;
        ``to_raw_definition`` carries it (``None`` for the other kinds).

        Args:
            temp_dir: Temporary directory fixture.
            stored: The stored metric of one kind.
        """
        metric_id = stored["id"]
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/{metric_id}"): _ok(stored),
                ("POST", _METRICS_PATH): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        source = ws.get_metric(metric_id)
        ws.create_metric(
            CreateMetricParams(
                name=f"{source.name} (copy)",
                definition=source.to_raw_definition(),
            )
        )
        body = server.body(1)
        assert body["type"] == stored["type"]
        assert body["definition"] == stored["definition"]
        assert body.get("warehouse_source_id") == stored.get("warehouse_source_id")

    def test_metric_post_body(self, temp_dir: Path) -> None:
        """A Metric sends {type, name, definition} with its show-clause parts."""
        server = _Server({("POST", _METRICS_PATH): _ok(behavior_metric_json(9))})
        ws = _make_workspace(temp_dir, server)
        metric = ws.create_metric(
            CreateMetricParams(name="  Logins ", definition=Metric("Login"))
        )
        assert isinstance(metric, SavedMetric)
        assert metric.id == 9
        assert server.calls() == [("POST", _METRICS_PATH)]
        assert server.body(0) == {
            "type": "metric",
            "name": "Logins",
            "definition": {
                "behavior": _LOGIN_BEHAVIOR,
                "measurement": {"math": "total"},
            },
        }

    def test_cohort_metric_post_body(self, temp_dir: Path) -> None:
        """A CohortMetric sends a behavior metric over the cohort."""
        server = _Server({("POST", _METRICS_PATH): _ok(behavior_metric_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_metric(
            CreateMetricParams(name="Power users", definition=CohortMetric(7, "Power"))
        )
        body = server.body(0)
        assert body["type"] == "metric"
        assert body["definition"]["behavior"]["type"] == "cohort"
        assert body["definition"]["behavior"]["id"] == 7
        assert body["definition"]["measurement"]["math"] == "unique"

    def test_warehouse_post_body(self, temp_dir: Path) -> None:
        """A WarehouseMetric sends the warehouse kind, source id, and defaults."""
        server = _Server({("POST", _METRICS_PATH): _ok(warehouse_metric_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_metric(
            CreateMetricParams(
                name="Revenue",
                definition=WarehouseMetric(55, "SELECT 1", "numeric"),
                description="From the warehouse.",
            )
        )
        assert server.body(0) == {
            "type": "warehouse",
            "name": "Revenue",
            "description": "From the warehouse.",
            "definition": {
                "query": "SELECT 1",
                "metricType": "numeric",
                "aggregation": "none",
                "syncInterval": "hourly",
            },
            "warehouse_source_id": 55,
        }

    def test_raw_formula_post_body(self, temp_dir: Path) -> None:
        """A raw formula with id operands goes out as given, with type formula."""
        definition = formula_metric_json()["definition"]
        server = _Server({("POST", _METRICS_PATH): _ok(formula_metric_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_metric(
            CreateMetricParams(
                name="Conversion", definition=RawMetricDefinition("formula", definition)
            )
        )
        assert server.body(0) == {
            "type": "formula",
            "name": "Conversion",
            "definition": definition,
        }

    def test_display_and_goals_in_definition(self, temp_dir: Path) -> None:
        """Display and goals from the params go into the definition."""
        server = _Server({("POST", _METRICS_PATH): _ok(behavior_metric_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_metric(
            CreateMetricParams(
                name="Logins",
                definition=Metric("Login"),
                display=MetricDisplay(suffix=" users", precision=0),
                goals=[
                    MetricGoal(
                        id="g1", label="Q4", checkpoints=[("2026-12-31T00:00:00", 10)]
                    )
                ],
            )
        )
        definition = server.body(0)["definition"]
        assert definition["display"] == {"suffix": " users", "precision": 0}
        assert definition["goals"] == [
            {
                "id": "g1",
                "label": "Q4",
                "checkpoints": [["2026-12-31T00:00:00", 10.0]],
                "target_type": "absolute",
            }
        ]

    def test_owner_and_verified_follow_up_patch(self, temp_dir: Path) -> None:
        """owned_by and verified go in a PATCH after the POST; its row comes back."""
        server = _Server(
            {
                ("POST", _METRICS_PATH): _ok(behavior_metric_json(9)),
                ("PATCH", f"{_METRICS_PATH}/9"): _ok(
                    behavior_metric_json(9, verified=True)
                ),
            }
        )
        ws = _make_workspace(temp_dir, server)
        metric = ws.create_metric(
            CreateMetricParams(
                name="Logins", definition=Metric("Login"), owned_by=8, verified=True
            )
        )
        assert server.calls() == [
            ("POST", _METRICS_PATH),
            ("PATCH", f"{_METRICS_PATH}/9"),
        ]
        assert "owned_by" not in server.body(0)
        assert "verified" not in server.body(0)
        assert server.body(1) == {"owned_by": {"id": 8}, "verified": True}
        assert metric.verified is True
        assert metric.owned_by is not None

    def test_verified_false_sends_no_patch(self, temp_dir: Path) -> None:
        """verified=False needs no follow-up: a new metric is unverified."""
        server = _Server({("POST", _METRICS_PATH): _ok(behavior_metric_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_metric(
            CreateMetricParams(name="m", definition=Metric("Login"), verified=False)
        )
        assert server.calls() == [("POST", _METRICS_PATH)]

    def test_failed_follow_up_patch_raises_and_logs_the_id(
        self, temp_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A failed PATCH raises an error that names the created metric; the log too.

        Args:
            temp_dir: Temporary directory fixture.
            caplog: Pytest log capture fixture.
        """
        server = _Server(
            {
                ("POST", _METRICS_PATH): _ok(behavior_metric_json(9)),
                ("PATCH", f"{_METRICS_PATH}/9"): httpx.Response(
                    403, json={"error": "Forbidden"}
                ),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with (
            caplog.at_level(logging.WARNING, logger="mixpanel_headless.workspace"),
            pytest.raises(MixpanelHeadlessError) as exc_info,
        ):
            ws.create_metric(
                CreateMetricParams(
                    name="m", definition=Metric("Login"), owned_by=8, verified=True
                )
            )
        exc = exc_info.value
        assert not isinstance(exc, QueryError)
        assert exc.code == "CREATE_FOLLOW_UP_FAILED"
        assert exc.details == {"metric_id": 9, "fields": ["owned_by", "verified"]}
        assert "created saved metric 9" in exc.message
        assert "Forbidden" in exc.message
        assert isinstance(exc.__cause__, QueryError)
        assert exc.__cause__.status_code == 403
        assert "9" in caplog.text
        assert "created" in caplog.text

    @pytest.mark.parametrize(
        "extra",
        [{}, {"owned_by": 8}, {"verified": True}],
    )
    def test_post_row_without_id_raises_response_validation_error(
        self, temp_dir: Path, extra: dict[str, Any]
    ) -> None:
        """A one-row POST answer without an id raises before any follow-up.

        Args:
            temp_dir: Temporary directory fixture.
            extra: Owner and verified params; each one needs a follow-up.
        """
        row = behavior_metric_json(9)
        del row["id"]
        server = _Server(
            {
                ("POST", _METRICS_PATH): httpx.Response(
                    200, json={"status": "ok", "results": {"9": row}}
                ),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ResponseValidationError) as exc_info:
            ws.create_metric(
                CreateMetricParams(name="m", definition=Metric("Login"), **extra)
            )
        assert exc_info.value.code == "RESPONSE_VALIDATION_ERROR"
        assert server.calls() == [("POST", _METRICS_PATH)]

    def test_non_library_error_in_follow_up_is_not_relabeled(
        self, temp_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An exception outside the library hierarchy propagates as it is.

        Args:
            temp_dir: Temporary directory fixture.
            caplog: Pytest log capture fixture.
        """
        server = _Server({("POST", _METRICS_PATH): _ok(behavior_metric_json(9))})
        ws = _make_workspace(temp_dir, server)
        with (
            caplog.at_level(logging.WARNING, logger="mixpanel_headless.workspace"),
            patch.object(
                MixpanelAPIClient, "update_metric", side_effect=RuntimeError("bug")
            ),
            pytest.raises(RuntimeError, match="bug"),
        ):
            ws.create_metric(
                CreateMetricParams(name="m", definition=Metric("Login"), owned_by=8)
            )
        assert "follow-up" not in caplog.text

    def test_duplicate_name_propagates(self, temp_dir: Path) -> None:
        """A 409 from the server raises QueryError."""
        server = _Server(
            {
                ("POST", _METRICS_PATH): httpx.Response(
                    409, json={"error": "A metric with that name already exists"}
                )
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.create_metric(CreateMetricParams(name="m", definition=Metric("Login")))
        assert exc_info.value.status_code == 409

    @pytest.mark.parametrize(
        ("params", "code"),
        [
            (
                CreateMetricParams(name="   ", definition=Metric("Login")),
                "SM1_EMPTY_NAME",
            ),
            (
                CreateMetricParams(name="n" * 256, definition=Metric("Login")),
                "SM2_NAME_TOO_LONG",
            ),
            (
                CreateMetricParams(
                    name="n", definition=Metric("Login"), description="d" * 256
                ),
                "SM2_NAME_TOO_LONG",
            ),
            (
                CreateMetricParams(
                    name="n",
                    definition=RawMetricDefinition("metric", {"behavior": {"x": 1}}),
                ),
                "SM4_SCHEMA",
            ),
            (
                CreateMetricParams(
                    name="n",
                    definition=RawMetricDefinition("warehouse", {"query": "q"}),
                ),
                "SM4_SCHEMA",
            ),
            (
                CreateMetricParams(
                    name="n",
                    definition=RawMetricDefinition(
                        "formula",
                        {
                            "formula": {
                                "definition": "A",
                                "referencedMetrics": [
                                    {"measurement": {"segmentMethod": "first"}}
                                ],
                            }
                        },
                    ),
                ),
                "FM6_OPERAND_ATTRIBUTION",
            ),
            (
                CreateMetricParams(
                    name="n",
                    definition=Metric("Login"),
                    display=MetricDisplay.model_validate({"chartType": "bar"}),
                ),
                "SM4_SCHEMA",
            ),
        ],
    )
    def test_refusals_send_nothing(
        self, temp_dir: Path, params: CreateMetricParams, code: str
    ) -> None:
        """Each coded refusal fires before any request.

        Args:
            temp_dir: Temporary directory fixture.
            params: Params that break one rule.
            code: The expected registry code.
        """
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_metric(params)
        assert exc_info.value.code == code
        assert server.requests == []

    def test_warehouse_without_source_names_the_field(self, temp_dir: Path) -> None:
        """A raw warehouse definition without a source names warehouse_source_id."""
        ws = _make_workspace(temp_dir, _Server({}))
        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_metric(
                CreateMetricParams(
                    name="n",
                    definition=RawMetricDefinition(
                        "warehouse", {"query": "q", "metricType": "numeric"}
                    ),
                )
            )
        assert exc_info.value.details["path"] == "warehouse_source_id"

    def test_validate_false_skips_the_schema_check(self, temp_dir: Path) -> None:
        """validate=False sends a definition that the mirror would refuse."""
        server = _Server({("POST", _METRICS_PATH): _ok(behavior_metric_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_metric(
            CreateMetricParams(
                name="n",
                definition=RawMetricDefinition("metric", {"behavior": {"x": 1}}),
            ),
            validate=False,
        )
        assert server.body(0)["definition"] == {"behavior": {"x": 1}}


# =============================================================================
# update_metric
# =============================================================================


class TestUpdateMetric:
    """Tests for Workspace.update_metric()."""

    def test_metadata_only_needs_no_read(self, temp_dir: Path) -> None:
        """Name and description changes send one PATCH and no GET."""
        server = _Server(
            {("PATCH", f"{_METRICS_PATH}/1"): _ok(behavior_metric_json(1))}
        )
        ws = _make_workspace(temp_dir, server)
        metric = ws.update_metric(1, UpdateMetricParams(name=" New ", description=""))
        assert isinstance(metric, SavedMetric)
        assert server.calls() == [("PATCH", f"{_METRICS_PATH}/1")]
        assert server.body(0) == {"name": "New", "description": ""}

    def test_owner_and_verified(self, temp_dir: Path) -> None:
        """owned_by goes out as {"id": N}; verified=False clears the flag."""
        server = _Server(
            {("PATCH", f"{_METRICS_PATH}/1"): _ok(behavior_metric_json(1))}
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(1, UpdateMetricParams(owned_by=8, verified=False))
        assert server.body(0) == {"owned_by": {"id": 8}, "verified": False}

    def test_display_sends_the_full_stored_definition(self, temp_dir: Path) -> None:
        """A display change reads the metric and sends its full definition back."""
        stored = behavior_metric_json(1)
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): _ok(stored),
                ("PATCH", f"{_METRICS_PATH}/1"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(1, UpdateMetricParams(display=MetricDisplay(prefix="#")))
        assert server.calls() == [
            ("GET", f"{_METRICS_PATH}/1"),
            ("PATCH", f"{_METRICS_PATH}/1"),
        ]
        assert server.body(1) == {
            "definition": {
                **stored["definition"],
                "display": {"prefix": "#", "suffix": " users", "precision": 0},
            }
        }

    @pytest.mark.parametrize(
        ("display", "expected"),
        [
            (
                MetricDisplay(precision=2),
                {"prefix": "$", "suffix": " usd", "precision": 2},
            ),
            (
                MetricDisplay(prefix=None, precision=2),
                {"suffix": " usd", "precision": 2},
            ),
            (MetricDisplay(suffix=" dollars"), {"prefix": "$", "suffix": " dollars"}),
            (MetricDisplay(), {"prefix": "$", "suffix": " usd"}),
            (
                MetricDisplay(hide_trendline=True),
                {"prefix": "$", "suffix": " usd", "hideTrendline": True},
            ),
        ],
    )
    def test_display_merges_into_the_stored_display(
        self, temp_dir: Path, display: MetricDisplay, expected: dict[str, Any]
    ) -> None:
        """Set keys replace stored ones, a key set to None goes, unset keys stay.

        Args:
            temp_dir: Temporary directory fixture.
            display: The display of the update.
            expected: The display that the PATCH sends.
        """
        stored = behavior_metric_json(1)
        stored["definition"]["display"] = {"prefix": "$", "suffix": " usd"}
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): _ok(stored),
                ("PATCH", f"{_METRICS_PATH}/1"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(1, UpdateMetricParams(display=display))
        assert server.body(1)["definition"]["display"] == expected
        assert server.body(1)["definition"]["goals"] == stored["definition"]["goals"]

    def test_new_definition_merges_the_display_into_the_stored_one(
        self, temp_dir: Path
    ) -> None:
        """A typed definition plus a display merges the display into the stored one."""
        stored = behavior_metric_json(1)
        stored["definition"]["display"] = {"prefix": "$", "suffix": " usd"}
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): _ok(stored),
                ("PATCH", f"{_METRICS_PATH}/1"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(
            1,
            UpdateMetricParams(
                definition=Metric("Login"), display=MetricDisplay(precision=2)
            ),
        )
        definition = server.body(1)["definition"]
        assert definition["behavior"] == _LOGIN_BEHAVIOR
        assert definition["display"] == {
            "prefix": "$",
            "suffix": " usd",
            "precision": 2,
        }

    @pytest.mark.parametrize(
        ("display", "expected"),
        [
            (None, {"suffix": "%"}),
            (MetricDisplay(precision=2), {"suffix": "%", "precision": 2}),
        ],
    )
    def test_new_definition_with_its_own_display(
        self,
        temp_dir: Path,
        display: MetricDisplay | None,
        expected: dict[str, Any],
    ) -> None:
        """A new definition that has a display is the base; the stored display is not.

        Args:
            temp_dir: Temporary directory fixture.
            display: The display of the update, or None.
            expected: The display that the PATCH sends.
        """
        stored = behavior_metric_json(1)
        stored["definition"]["display"] = {"prefix": "$", "suffix": " usd"}
        new = {
            "behavior": _LOGIN_BEHAVIOR,
            "measurement": {"math": "total"},
            "display": {"suffix": "%"},
        }
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): _ok(stored),
                ("PATCH", f"{_METRICS_PATH}/1"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(
            1,
            UpdateMetricParams(
                definition=RawMetricDefinition("metric", new), display=display
            ),
        )
        assert server.body(1)["definition"]["display"] == expected

    def test_new_goals_replace_the_stored_goals(self, temp_dir: Path) -> None:
        """Goals are a list: new goals replace the stored list in full."""
        stored = behavior_metric_json(1)
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): _ok(stored),
                ("PATCH", f"{_METRICS_PATH}/1"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(
            1,
            UpdateMetricParams(
                goals=[MetricGoal(id="g2", label="New", checkpoints=[])]
            ),
        )
        assert server.body(1)["definition"]["goals"] == [
            {"id": "g2", "label": "New", "checkpoints": [], "target_type": "absolute"}
        ]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (
                WarehouseMetric(55, "SELECT 2", "timeseries"),
                {"aggregation": "sum", "syncInterval": "daily"},
            ),
            (
                WarehouseMetric(55, "SELECT 2", "timeseries", aggregation="last_value"),
                {"aggregation": "last_value", "syncInterval": "daily"},
            ),
            (
                WarehouseMetric(
                    55,
                    "SELECT 2",
                    "timeseries",
                    aggregation="none",
                    sync_interval="hourly",
                ),
                {"aggregation": "none", "syncInterval": "hourly"},
            ),
        ],
    )
    def test_warehouse_update_keeps_unset_aggregation_and_sync(
        self, temp_dir: Path, value: WarehouseMetric, expected: dict[str, str]
    ) -> None:
        """An unset aggregation or sync interval keeps the stored value; a set one is written.

        Args:
            temp_dir: Temporary directory fixture.
            value: The new warehouse definition.
            expected: The aggregation and sync interval that the PATCH sends.
        """
        stored = warehouse_metric_json(4)
        stored["definition"]["aggregation"] = "sum"
        stored["definition"]["syncInterval"] = "daily"
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/4"): _ok(stored),
                ("PATCH", f"{_METRICS_PATH}/4"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(4, UpdateMetricParams(definition=value))
        definition = server.body(1)["definition"]
        assert definition["query"] == "SELECT 2"
        assert {
            "aggregation": definition["aggregation"],
            "syncInterval": definition["syncInterval"],
        } == expected

    def test_bulk_warehouse_update_keeps_unset_aggregation_and_sync(
        self, temp_dir: Path
    ) -> None:
        """A bulk entry with a SQL-only warehouse definition keeps the stored values."""
        stored = warehouse_metric_json(4)
        stored["definition"]["aggregation"] = "sum"
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/4"): _ok(stored),
                ("PATCH", _METRICS_PATH): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.bulk_update_metrics(
            [
                BulkUpdateMetricEntry(
                    id=4, definition=WarehouseMetric(55, "SELECT 2", "timeseries")
                )
            ]
        )
        (entry,) = server.body(1)["metrics"]
        assert entry["definition"]["aggregation"] == "sum"
        assert entry["definition"]["syncInterval"] == "daily"

    def test_goals_empty_list_removes_goals(self, temp_dir: Path) -> None:
        """goals=[] sends the stored definition with an empty goal list."""
        stored = behavior_metric_json(1)
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): _ok(stored),
                ("PATCH", f"{_METRICS_PATH}/1"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(1, UpdateMetricParams(goals=[]))
        assert server.body(1)["definition"]["goals"] == []
        assert (
            server.body(1)["definition"]["behavior"] == stored["definition"]["behavior"]
        )

    def test_new_definition_keeps_stored_presentation(self, temp_dir: Path) -> None:
        """A new typed definition keeps the stored display and goals."""
        stored = behavior_metric_json(1)
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): _ok(stored),
                ("PATCH", f"{_METRICS_PATH}/1"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(
            1,
            UpdateMetricParams(
                definition=Metric("Login", math="unique"), verified=True
            ),
        )
        assert server.body(1) == {
            "definition": {
                "behavior": _LOGIN_BEHAVIOR,
                "measurement": {"math": "unique"},
                "display": stored["definition"]["display"],
                "goals": stored["definition"]["goals"],
            },
            "verified": True,
        }

    def test_kind_change_refused_after_the_read(self, temp_dir: Path) -> None:
        """A formula definition for a behavior metric raises SM3 and sends no PATCH."""
        server = _Server({("GET", f"{_METRICS_PATH}/1"): _ok(behavior_metric_json(1))})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.update_metric(
                1,
                UpdateMetricParams(
                    definition=RawMetricDefinition(
                        "formula", formula_metric_json()["definition"]
                    )
                ),
            )
        assert exc_info.value.code == "SM3_KIND_CHANGE"
        assert server.calls() == [("GET", f"{_METRICS_PATH}/1")]

    def test_failed_read_raises(self, temp_dir: Path) -> None:
        """A 404 on the read raises QueryError and sends no PATCH."""
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): httpx.Response(
                    404, json={"error": "Metric not found for id 1"}
                )
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(1, UpdateMetricParams(definition=Metric("Login")))
        assert exc_info.value.status_code == 404
        assert server.calls() == [("GET", f"{_METRICS_PATH}/1")]

    @pytest.mark.parametrize(
        ("params", "code"),
        [
            (UpdateMetricParams(name=""), "SM1_EMPTY_NAME"),
            (UpdateMetricParams(description="d" * 256), "SM2_NAME_TOO_LONG"),
            (
                UpdateMetricParams(
                    definition=RawMetricDefinition("metric", {"behavior": {"x": 1}})
                ),
                "SM4_SCHEMA",
            ),
            (
                UpdateMetricParams(
                    goals=[MetricGoal(label="L", checkpoints=[("2026-01-01", 1)])],
                    display=MetricDisplay(precision=9),
                ),
                "SM4_SCHEMA",
            ),
        ],
    )
    def test_refusals_send_nothing(
        self, temp_dir: Path, params: UpdateMetricParams, code: str
    ) -> None:
        """Each local refusal fires before the read and the PATCH.

        Args:
            temp_dir: Temporary directory fixture.
            params: Params that break one rule.
            code: The expected registry code.
        """
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.update_metric(1, params)
        assert exc_info.value.code == code
        assert server.requests == []

    def test_validate_false_skips_the_schema_check(self, temp_dir: Path) -> None:
        """validate=False sends a definition that the mirror would refuse."""
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): _ok(behavior_metric_json(1)),
                ("PATCH", f"{_METRICS_PATH}/1"): _ok(behavior_metric_json(1)),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(
            1,
            UpdateMetricParams(
                definition=RawMetricDefinition("metric", {"behavior": {"x": 1}})
            ),
            validate=False,
        )
        assert server.body(1)["definition"]["behavior"] == {"x": 1}


# =============================================================================
# bulk_update_metrics
# =============================================================================


class TestBulkUpdateMetrics:
    """Tests for Workspace.bulk_update_metrics()."""

    def test_bulk_verify(self, temp_dir: Path) -> None:
        """A bulk verify sends one PATCH with integer ids and reads nothing."""
        server = _Server(
            {
                ("PATCH", _METRICS_PATH): _ok(
                    behavior_metric_json(1, verified=True),
                    behavior_metric_json(2, verified=True),
                )
            }
        )
        ws = _make_workspace(temp_dir, server)
        metrics = ws.bulk_update_metrics(
            [
                BulkUpdateMetricEntry(id=1, verified=True),
                BulkUpdateMetricEntry(id=2, verified=True),
            ]
        )
        assert [m.id for m in metrics] == [1, 2]
        assert server.calls() == [("PATCH", _METRICS_PATH)]
        assert server.body(0) == {
            "metrics": [{"id": 1, "verified": True}, {"id": 2, "verified": True}]
        }

    def test_entry_with_definition_is_read_first(self, temp_dir: Path) -> None:
        """An entry with a definition reads its metric, then joins the one PATCH."""
        stored = behavior_metric_json(1)
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): _ok(stored),
                ("PATCH", _METRICS_PATH): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.bulk_update_metrics(
            [
                BulkUpdateMetricEntry(id=1, definition=Metric("Login"), owned_by=8),
                BulkUpdateMetricEntry(id=2, name="Renamed"),
            ]
        )
        assert server.calls() == [
            ("GET", f"{_METRICS_PATH}/1"),
            ("PATCH", _METRICS_PATH),
        ]
        entries = server.body(1)["metrics"]
        assert entries[0]["id"] == 1
        assert entries[0]["owned_by"] == {"id": 8}
        assert entries[0]["definition"]["measurement"] == {"math": "total"}
        assert entries[0]["definition"]["display"] == stored["definition"]["display"]
        assert entries[1] == {"id": 2, "name": "Renamed"}

    def test_one_bad_entry_stops_the_batch(self, temp_dir: Path) -> None:
        """A kind change in one entry raises SM3 and sends no PATCH."""
        server = _Server({("GET", f"{_METRICS_PATH}/1"): _ok(behavior_metric_json(1))})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.bulk_update_metrics(
                [
                    BulkUpdateMetricEntry(
                        id=1,
                        definition=RawMetricDefinition(
                            "formula", formula_metric_json()["definition"]
                        ),
                    )
                ]
            )
        assert exc_info.value.code == "SM3_KIND_CHANGE"
        assert server.calls() == [("GET", f"{_METRICS_PATH}/1")]

    def test_name_rule_checked_before_any_request(self, temp_dir: Path) -> None:
        """An empty name in any entry raises SM1 before any request."""
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.bulk_update_metrics(
                [
                    BulkUpdateMetricEntry(id=1, verified=True),
                    BulkUpdateMetricEntry(id=2, name=" "),
                ]
            )
        assert exc_info.value.code == "SM1_EMPTY_NAME"
        assert server.requests == []

    def test_empty_sends_nothing(self, temp_dir: Path) -> None:
        """No entries means no request and an empty result."""
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        assert ws.bulk_update_metrics([]) == []
        assert server.requests == []


# =============================================================================
# Saved behaviors
# =============================================================================


_FUNNEL_DEFINITION: dict[str, Any] = saved_behavior_json()["definition"]
"""A funnel behavior definition from the shared fixtures."""


class TestCreateBehavior:
    """Tests for Workspace.create_behavior()."""

    def test_post_body(self, temp_dir: Path) -> None:
        """The wire type comes from the definition; a None description stays out."""
        server = _Server({("POST", _BEHAVIORS_PATH): _ok(saved_behavior_json(5))})
        ws = _make_workspace(temp_dir, server)
        behavior = ws.create_behavior(
            CreateBehaviorParams(
                name=" Checkout ", behavior=RawBehaviorDefinition(_FUNNEL_DEFINITION)
            )
        )
        assert isinstance(behavior, SavedBehavior)
        assert behavior.id == 5
        assert server.body(0) == {
            "type": "funnel",
            "name": "Checkout",
            "definition": _FUNNEL_DEFINITION,
        }

    def test_description_sent_when_set(self, temp_dir: Path) -> None:
        """A description goes out as a string."""
        server = _Server({("POST", _BEHAVIORS_PATH): _ok(saved_behavior_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_behavior(
            CreateBehaviorParams(
                name="b",
                behavior=RawBehaviorDefinition(_FUNNEL_DEFINITION),
                description="Cart to purchase.",
            )
        )
        assert server.body(0)["description"] == "Cart to purchase."

    @pytest.mark.parametrize("validate", [True, False])
    def test_missing_type_refused(self, temp_dir: Path, validate: bool) -> None:
        """A behavior with no type cannot name its wire type, even with validate=False.

        Args:
            temp_dir: Temporary directory fixture.
            validate: The validate flag.
        """
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_behavior(
                CreateBehaviorParams(
                    name="b", behavior=RawBehaviorDefinition({"behavior": {}})
                ),
                validate=validate,
            )
        assert exc_info.value.code == "SM4_SCHEMA"
        assert exc_info.value.details["path"] == "definition.behavior.type"
        assert server.requests == []

    def test_schema_refusal_and_validate_false(self, temp_dir: Path) -> None:
        """An unknown key raises SM4; validate=False sends it."""
        bad = {"behavior": {"type": "simple", "bogus": 1}}
        server = _Server({("POST", _BEHAVIORS_PATH): _ok(saved_behavior_json())})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_behavior(
                CreateBehaviorParams(name="b", behavior=RawBehaviorDefinition(bad))
            )
        assert exc_info.value.code == "SM4_SCHEMA"
        assert server.requests == []
        ws.create_behavior(
            CreateBehaviorParams(name="b", behavior=RawBehaviorDefinition(bad)),
            validate=False,
        )
        assert server.body(0)["definition"] == bad

    def test_empty_name_refused(self, temp_dir: Path) -> None:
        """An empty name raises SM1_EMPTY_NAME before any request."""
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_behavior(
                CreateBehaviorParams(
                    name="", behavior=RawBehaviorDefinition(_FUNNEL_DEFINITION)
                )
            )
        assert exc_info.value.code == "SM1_EMPTY_NAME"
        assert server.requests == []


class TestUpdateBehavior:
    """Tests for Workspace.update_behavior()."""

    def test_metadata_only_needs_no_read(self, temp_dir: Path) -> None:
        """Name, description, and verified send one PATCH and no GET."""
        server = _Server(
            {("PATCH", f"{_BEHAVIORS_PATH}/3"): _ok(saved_behavior_json(3))}
        )
        ws = _make_workspace(temp_dir, server)
        behavior = ws.update_behavior(
            3, UpdateBehaviorParams(name="n", description="d", verified=True)
        )
        assert isinstance(behavior, SavedBehavior)
        assert server.calls() == [("PATCH", f"{_BEHAVIORS_PATH}/3")]
        assert server.body(0) == {"name": "n", "description": "d", "verified": True}

    def test_new_definition_is_read_first(self, temp_dir: Path) -> None:
        """A new definition of the same type reads the behavior, then PATCHes."""
        server = _Server(
            {
                ("GET", f"{_BEHAVIORS_PATH}/3"): _ok(saved_behavior_json(3)),
                ("PATCH", f"{_BEHAVIORS_PATH}/3"): _ok(saved_behavior_json(3)),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_behavior(
            3, UpdateBehaviorParams(behavior=RawBehaviorDefinition(_FUNNEL_DEFINITION))
        )
        assert server.calls() == [
            ("GET", f"{_BEHAVIORS_PATH}/3"),
            ("PATCH", f"{_BEHAVIORS_PATH}/3"),
        ]
        assert server.body(1) == {"definition": _FUNNEL_DEFINITION}

    def test_type_change_refused(self, temp_dir: Path) -> None:
        """A simple definition for a funnel behavior raises SM3 and sends no PATCH."""
        server = _Server({("GET", f"{_BEHAVIORS_PATH}/3"): _ok(saved_behavior_json(3))})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.update_behavior(
                3,
                UpdateBehaviorParams(
                    behavior=RawBehaviorDefinition(
                        {"behavior": {"type": "simple", "behaviors": []}}
                    )
                ),
            )
        assert exc_info.value.code == "SM3_KIND_CHANGE"
        assert server.calls() == [("GET", f"{_BEHAVIORS_PATH}/3")]

    def test_schema_refusal_before_the_read(self, temp_dir: Path) -> None:
        """A definition that fails the mirror raises SM4 before any request."""
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.update_behavior(
                3,
                UpdateBehaviorParams(
                    behavior=RawBehaviorDefinition(
                        {"behavior": {"type": "funnel", "x": 1}}
                    )
                ),
            )
        assert exc_info.value.code == "SM4_SCHEMA"
        assert server.requests == []


# =============================================================================
# The explanation of a refused edit (blank 403)
# =============================================================================


_BLANK_403 = {"error": "", "status": "error"}
"""The body of the server's per-entity edit refusal: a 403 with no text."""

_METRIC_RULE = (
    "Only the creator of a saved metric, the users and teams that it is shared "
    "with for editing, and project owners can edit it."
)
"""The edit rule that every explained metric refusal states."""

_ASK_ONE = "Ask the creator to share it with edit access."
"""The remedy when the message names one entity."""

_ASK_EACH = "Ask the creator of each saved metric to share it with edit access."
"""The remedy when the message is about several metrics."""

_METRIC_HINT = (
    "The can_update_basic flag in list_metrics() (CLI: mp metrics list) shows "
    "which saved metrics this account can edit."
)
"""The hint of a bulk refusal when the client did not check every target."""

_BEHAVIOR_REASON = (
    "The server gives one answer for two causes. First cause: the account lacks "
    "the write_behaviors permission in this project. A project admin can grant "
    "it. Second cause: the saved behavior is not shared with the account for "
    "editing. Only the creator of a saved behavior, the users and teams that it "
    "is shared with for editing, and project owners can edit it. Ask the creator "
    "to share it with edit access. Nothing was changed."
)
"""The text that follows the subject of every explained behavior refusal."""

_THEIRS_2 = "2 ('Theirs', created by ana@example.com)"
"""How a message names metric 2 of the fixtures below."""


def _blank_403() -> httpx.Response:
    """Build the server's edit refusal: HTTP 403 with a blank ``error``.

    Returns:
        The response.
    """
    return httpx.Response(403, json=dict(_BLANK_403))


def _not_found() -> httpx.Response:
    """Build the server's answer to a read of an absent or deleted metric.

    Returns:
        The response.
    """
    return httpx.Response(404, json={"status": "error", "error": "Metric not found"})


@pytest.fixture
def recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record every ``time.sleep`` call, and do not wait.

    Args:
        monkeypatch: pytest monkeypatch fixture (restores ``time.sleep``).

    Returns:
        A list that holds the seconds of each ``time.sleep`` call, in order.
    """
    calls: list[float] = []
    monkeypatch.setattr("time.sleep", calls.append)
    return calls


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace ``time.monotonic`` with a clock that the test moves by hand.

    Args:
        monkeypatch: pytest monkeypatch fixture (restores ``time.monotonic``).

    Returns:
        A one-item list that holds the current time of the clock.
    """
    now = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: now[0])
    return now


class TestEditRefusals:
    """A blank 403 on an update says why the server refused it.

    The server refuses an edit of a saved metric or behavior that the
    account did not create and that is not shared with it for editing,
    with a 403 whose ``error`` is blank. The client fell back to "Permission
    denied", and the CLI added a service-account hint even under OAuth.
    """

    def test_metric_refusal_names_the_metric_and_its_creator(
        self, temp_dir: Path
    ) -> None:
        """The update reads the metric after the 403 and names its creator."""
        stored = behavior_metric_json(4107, "Weekly signups", can_view=False)
        server = _Server(
            {
                ("PATCH", f"{_METRICS_PATH}/4107"): _blank_403(),
                ("GET", f"{_METRICS_PATH}/4107"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(4107, UpdateMetricParams(name="Weekly signups"))

        err = exc_info.value
        assert err.status_code == 403
        assert err.message == (
            "This account cannot edit saved metric 4107 ('Weekly signups', "
            f"created by ana@example.com). {_METRIC_RULE} {_ASK_ONE} Nothing was "
            "changed."
        )
        assert err.response_body == _BLANK_403
        assert isinstance(err.__cause__, QueryError)
        assert err.__cause__.message == "Permission denied"
        assert server.calls() == [
            ("PATCH", f"{_METRICS_PATH}/4107"),
            ("GET", f"{_METRICS_PATH}/4107"),
        ]

    def test_explained_error_keeps_the_request_context(self, temp_dir: Path) -> None:
        """The new error carries the method, URL, params, and body of the update."""
        server = _Server(
            {
                ("PATCH", f"{_METRICS_PATH}/7"): _blank_403(),
                ("GET", f"{_METRICS_PATH}/7"): _ok(
                    behavior_metric_json(7, can_view=False)
                ),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(7, UpdateMetricParams(name="New name"))
        err = exc_info.value
        cause = err.__cause__
        assert isinstance(cause, QueryError)
        assert err.request_method == "PATCH"
        assert err.request_url == f"https://mixpanel.com{_METRICS_PATH}/7"
        assert err.request_params is not None
        assert err.request_params == cause.request_params
        assert err.request_body == {"name": "New name"}

    def test_message_has_no_definition(self, temp_dir: Path) -> None:
        """The read after the 403 never puts the stored definition in the message."""
        stored = {**warehouse_metric_json(41), "can_update_basic": False}
        server = _Server(
            {
                ("PATCH", f"{_METRICS_PATH}/41"): _blank_403(),
                ("GET", f"{_METRICS_PATH}/41"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(41, UpdateMetricParams(description="d"))
        assert stored["definition"]["query"] not in str(exc_info.value)
        assert "cannot edit saved metric 41" in exc_info.value.message

    @pytest.mark.parametrize(
        "created_by",
        [None, {}, {"id": 7, "name": "Ana"}, "absent"],
        ids=["null", "empty", "no-email", "absent"],
    )
    def test_row_without_a_creator_email_names_no_creator(
        self, temp_dir: Path, created_by: Any
    ) -> None:
        """A row with no creator, or a creator with no email, names the metric only.

        Args:
            temp_dir: Temporary directory fixture.
            created_by: The ``created_by`` value of the row, or ``"absent"``
                for a row without the key.
        """
        stored = behavior_metric_json(5, "Orphan", can_view=False)
        if created_by == "absent":
            del stored["created_by"]
        else:
            stored["created_by"] = created_by
        server = _Server(
            {
                ("PATCH", f"{_METRICS_PATH}/5"): _blank_403(),
                ("GET", f"{_METRICS_PATH}/5"): _ok(stored),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(5, UpdateMetricParams(name="X"))
        assert exc_info.value.message.startswith(
            "This account cannot edit saved metric 5 ('Orphan'). Only the creator"
        )

    # ---- which answers count as the blank refusal --------------------------

    @pytest.mark.parametrize(
        "body",
        [
            {"error": ""},
            {"error": "  ", "status": "error"},
            {"error": "", "status": "error", "message": ""},
        ],
        ids=["empty", "whitespace", "empty-message"],
    )
    def test_blank_error_string_is_the_refusal(
        self, temp_dir: Path, body: dict[str, str]
    ) -> None:
        """A 403 whose ``error`` is a blank string, with no other text, is explained.

        Args:
            temp_dir: Temporary directory fixture.
            body: The body of the 403.
        """
        server = _Server(
            {
                ("PATCH", f"{_METRICS_PATH}/1"): httpx.Response(403, json=body),
                ("GET", f"{_METRICS_PATH}/1"): _ok(
                    behavior_metric_json(1, "Theirs", can_view=False)
                ),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(1, UpdateMetricParams(name="X"))
        assert exc_info.value.message.startswith(
            "This account cannot edit saved metric 1 ('Theirs', created by "
        )

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"status": "error"},
            {"error": None},
            {"detail": "Forbidden"},
            {"Message": "User is not authorized to access this resource"},
            {"error": "", "message": "Error ID: 7f73"},
            {"error": "", "message": ["Session expired"]},
            {"error": "", "detail": "Request blocked"},
            {"error": "", "status": "ok"},
        ],
        ids=[
            "empty",
            "no-error-key",
            "null",
            "detail",
            "gateway",
            "message",
            "message-list",
            "blank-error-with-detail",
            "status-ok",
        ],
    )
    def test_403_of_another_shape_propagates_without_a_read(
        self, temp_dir: Path, body: dict[str, Any]
    ) -> None:
        """Only the recorded shape is explained; each other JSON 403 stays as it is.

        The recorded shape is a blank ``error`` string, a ``status`` of
        ``"error"`` (or none), and no value under another key. A JSON 403 of
        another shape (for example from a gateway or a proxy) has a cause
        that the client does not know.

        Args:
            temp_dir: Temporary directory fixture.
            body: The body of the 403.
        """
        server = _Server(
            {("PATCH", f"{_METRICS_PATH}/1"): httpx.Response(403, json=body)}
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(1, UpdateMetricParams(name="X"))
        assert exc_info.value.status_code == 403
        assert "cannot edit" not in exc_info.value.message
        assert "Nothing was changed" not in exc_info.value.message
        assert exc_info.value.__cause__ is None
        assert server.calls() == [("PATCH", f"{_METRICS_PATH}/1")]

    @pytest.mark.parametrize("status", [400, 404, 409])
    def test_blank_error_on_another_status_propagates_without_a_read(
        self, temp_dir: Path, status: int
    ) -> None:
        """A blank ``error`` on a status other than 403 is not an edit refusal.

        Args:
            temp_dir: Temporary directory fixture.
            status: The HTTP status of the answer.
        """
        server = _Server(
            {
                ("PATCH", f"{_METRICS_PATH}/1"): httpx.Response(
                    status, json=dict(_BLANK_403)
                )
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(1, UpdateMetricParams(name="X"))
        assert exc_info.value.status_code == status
        assert "cannot edit" not in exc_info.value.message
        assert server.calls() == [("PATCH", f"{_METRICS_PATH}/1")]

    @pytest.mark.parametrize(
        ("status", "body"),
        [
            (403, {"error": "Cannot save metric with your current plan"}),
            (409, {"error": "A metric with that name already exists"}),
        ],
    )
    def test_other_errors_propagate_without_a_read(
        self, temp_dir: Path, status: int, body: dict[str, str]
    ) -> None:
        """A 403 with its own text, or another status, propagates as sent.

        Args:
            temp_dir: Temporary directory fixture.
            status: The HTTP status of the refusal.
            body: Its body, with a non-blank error.
        """
        server = _Server(
            {("PATCH", f"{_METRICS_PATH}/1"): httpx.Response(status, json=body)}
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(1, UpdateMetricParams(name="X"))
        assert exc_info.value.message == body["error"]
        assert exc_info.value.status_code == status
        assert server.calls() == [("PATCH", f"{_METRICS_PATH}/1")]

    def test_bulk_other_error_propagates_without_a_read(self, temp_dir: Path) -> None:
        """A bulk update passes an error that is not the blank 403 on as sent."""
        body = {"error": "A metric with that name already exists"}
        server = _Server({("PATCH", _METRICS_PATH): httpx.Response(409, json=body)})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.bulk_update_metrics([BulkUpdateMetricEntry(id=1, name="Taken")])
        assert exc_info.value.status_code == 409
        assert exc_info.value.message == body["error"]
        assert server.calls() == [("PATCH", _METRICS_PATH)]

    def test_behavior_other_error_propagates_without_a_read(
        self, temp_dir: Path
    ) -> None:
        """A behavior update passes an error that is not the blank 403 on as sent."""
        body = {"error": "A behavior with that name already exists"}
        server = _Server(
            {("PATCH", f"{_BEHAVIORS_PATH}/3001"): httpx.Response(409, json=body)}
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_behavior(3001, UpdateBehaviorParams(name="Taken"))
        assert exc_info.value.status_code == 409
        assert exc_info.value.message == body["error"]
        assert server.calls() == [("PATCH", f"{_BEHAVIORS_PATH}/3001")]

    def test_403_without_a_json_body_propagates_without_a_read(
        self, temp_dir: Path
    ) -> None:
        """A 403 with no JSON body (for example from a proxy) stays as it is."""
        server = _Server({("PATCH", f"{_METRICS_PATH}/1"): httpx.Response(403)})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(1, UpdateMetricParams(name="X"))
        assert exc_info.value.message == "Permission denied"
        assert server.calls() == [("PATCH", f"{_METRICS_PATH}/1")]

    # ---- bulk updates ------------------------------------------------------

    def _bulk_message(
        self, temp_dir: Path, reads: dict[int, httpx.Response]
    ) -> tuple[str, list[tuple[str, str]]]:
        """Refuse a bulk update of the given metrics and return the explanation.

        Args:
            temp_dir: Temporary directory fixture.
            reads: The answer to the read of each target, keyed by metric id.
                The bulk update sends one entry per key, in this order.

        Returns:
            The message of the raised ``QueryError`` and the request log.
        """
        routes: dict[tuple[str, str], httpx.Response] = {
            ("PATCH", _METRICS_PATH): _blank_403()
        }
        for metric_id, response in reads.items():
            routes[("GET", f"{_METRICS_PATH}/{metric_id}")] = response
        server = _Server(routes)
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.bulk_update_metrics(
                [BulkUpdateMetricEntry(id=i, verified=True) for i in reads]
            )
        assert isinstance(exc_info.value.__cause__, QueryError)
        return exc_info.value.message, server.calls()

    def test_bulk_refusal_names_each_refused_metric(self, temp_dir: Path) -> None:
        """A bulk update reads each target and names every refused metric.

        It reads the targets one by one, not the full metric list, which can
        take more than 30 seconds on a large project.
        """
        message, calls = self._bulk_message(
            temp_dir,
            {
                1: _ok(behavior_metric_json(1, "Mine")),
                2: _ok(behavior_metric_json(2, "Theirs", can_view=False)),
                3: _ok(behavior_metric_json(3, "Also theirs", can_view=False)),
            },
        )
        assert message == (
            f"This account cannot edit saved metrics {_THEIRS_2}, 3 ('Also "
            f"theirs', created by ana@example.com). {_METRIC_RULE} {_ASK_EACH} "
            "Nothing was changed."
        )
        assert calls == [
            ("PATCH", _METRICS_PATH),
            ("GET", f"{_METRICS_PATH}/1"),
            ("GET", f"{_METRICS_PATH}/2"),
            ("GET", f"{_METRICS_PATH}/3"),
        ]

    def test_bulk_refusal_with_one_refused_metric_names_it_alone(
        self, temp_dir: Path
    ) -> None:
        """One refused metric in a batch reads as one metric.

        A row that has no ``can_update_basic`` key is not named as refused.
        """
        no_flag = {
            k: v
            for k, v in behavior_metric_json(1, "No flag").items()
            if k != "can_update_basic"
        }
        message, _ = self._bulk_message(
            temp_dir,
            {
                1: _ok(no_flag),
                2: _ok(behavior_metric_json(2, "Theirs", can_view=False)),
            },
        )
        assert message == (
            f"This account cannot edit saved metric {_THEIRS_2}. {_METRIC_RULE} "
            f"{_ASK_ONE} Nothing was changed."
        )

    def test_bulk_refusal_without_a_refused_row_lists_the_targets(
        self, temp_dir: Path
    ) -> None:
        """When no read finds a refused target, the message names every target."""
        message, _ = self._bulk_message(
            temp_dir,
            {
                1: _ok(behavior_metric_json(1, "Mine")),
                2: _ok(behavior_metric_json(2, "Also mine")),
            },
        )
        assert message == (
            "This account cannot edit one or more of these saved metrics: 1, 2. "
            f"{_METRIC_RULE} {_ASK_EACH} {_METRIC_HINT} Nothing was changed."
        )

    def test_bulk_refusal_names_a_target_that_was_not_found(
        self, temp_dir: Path
    ) -> None:
        """A 404 on a read says that the metric may be deleted.

        The bulk route also refuses a deleted metric that is not shared with
        the account, and the read of a deleted metric answers 404. The
        metric list cannot show such a metric, so the message gives no hint
        to look there.
        """
        message, calls = self._bulk_message(
            temp_dir, {1: _ok(behavior_metric_json(1, "Mine")), 2: _not_found()}
        )
        assert message == (
            "This account cannot edit one or more of these saved metrics: 1, 2. "
            "Saved metric 2 was not found; it may be deleted. "
            f"{_METRIC_RULE} {_ASK_EACH} Nothing was changed."
        )
        assert calls == [
            ("PATCH", _METRICS_PATH),
            ("GET", f"{_METRICS_PATH}/1"),
            ("GET", f"{_METRICS_PATH}/2"),
        ]

    def test_bulk_refusal_names_several_targets_that_were_not_found(
        self, temp_dir: Path
    ) -> None:
        """Several 404s give one sentence in the plural, after the refused metric."""
        message, _ = self._bulk_message(
            temp_dir,
            {
                1: _not_found(),
                2: _ok(behavior_metric_json(2, "Theirs", can_view=False)),
                3: _not_found(),
            },
        )
        assert message == (
            f"This account cannot edit saved metric {_THEIRS_2}. Saved metrics "
            "1, 3 were not found; they may be deleted. "
            f"{_METRIC_RULE} {_ASK_ONE} Nothing was changed."
        )

    def test_bulk_refusal_names_a_target_that_the_client_could_not_read(
        self, temp_dir: Path
    ) -> None:
        """A 403 on one read skips that target, and the message says so.

        The message must not read as the full list of the refused metrics.
        """
        message, calls = self._bulk_message(
            temp_dir,
            {
                1: httpx.Response(403, json={"error": "No access to this metric"}),
                2: _ok(behavior_metric_json(2, "Theirs", can_view=False)),
            },
        )
        assert message == (
            f"This account cannot edit saved metric {_THEIRS_2}. The client "
            f"could not read saved metric 1 to check it. {_METRIC_RULE} "
            f"{_ASK_ONE} {_METRIC_HINT} Nothing was changed."
        )
        assert calls == [
            ("PATCH", _METRICS_PATH),
            ("GET", f"{_METRICS_PATH}/1"),
            ("GET", f"{_METRICS_PATH}/2"),
        ]

    def test_bulk_refusal_reads_exactly_the_read_limit(self, temp_dir: Path) -> None:
        """A batch of exactly 10 targets is read, one request per target."""
        message, calls = self._bulk_message(
            temp_dir,
            {
                i: _ok(behavior_metric_json(i, f"M{i}", can_view=(i != 10)))
                for i in range(1, 11)
            },
        )
        assert message.startswith(
            "This account cannot edit saved metric 10 ('M10', created by "
            "ana@example.com). Only the creator"
        )
        assert calls == [
            ("PATCH", _METRICS_PATH),
            *[("GET", f"{_METRICS_PATH}/{i}") for i in range(1, 11)],
        ]

    def test_bulk_refusal_over_the_read_limit_reads_nothing(
        self, temp_dir: Path
    ) -> None:
        """More than 10 targets get the explanation without any read."""
        server = _Server({("PATCH", _METRICS_PATH): _blank_403()})
        ws = _make_workspace(temp_dir, server)
        ids = list(range(1, 12))
        with pytest.raises(QueryError) as exc_info:
            ws.bulk_update_metrics(
                [BulkUpdateMetricEntry(id=i, verified=True) for i in ids]
            )
        assert exc_info.value.message == (
            "This account cannot edit one or more of these saved metrics: "
            f"1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11. {_METRIC_RULE} {_ASK_EACH} "
            f"{_METRIC_HINT} Nothing was changed."
        )
        assert server.calls() == [("PATCH", _METRICS_PATH)]

    def test_repeated_bulk_target_is_read_once(self, temp_dir: Path) -> None:
        """Two entries for one metric give one read and the single-metric text."""
        server = _Server(
            {
                ("PATCH", _METRICS_PATH): _blank_403(),
                ("GET", f"{_METRICS_PATH}/2"): _ok(
                    behavior_metric_json(2, "Theirs", can_view=False)
                ),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.bulk_update_metrics(
                [
                    BulkUpdateMetricEntry(id=2, verified=True),
                    BulkUpdateMetricEntry(id=2, name="Renamed"),
                ]
            )
        assert exc_info.value.message == (
            f"This account cannot edit saved metric {_THEIRS_2}. {_METRIC_RULE} "
            f"{_ASK_ONE} Nothing was changed."
        )
        assert server.calls() == [
            ("PATCH", _METRICS_PATH),
            ("GET", f"{_METRICS_PATH}/2"),
        ]

    # ---- the reads after the 403 -------------------------------------------

    def test_read_gets_half_of_the_time_budget_for_each_phase(
        self, temp_dir: Path, clock: list[float]
    ) -> None:
        """Each phase of the first read gets half of the 10 s budget.

        ``httpx`` applies a timeout to each phase of a request (the
        connection, then the wait for the answer), not to the request as a
        whole. Half for each phase keeps a normal read inside the budget.
        The update keeps its own timeout.
        """
        server = _Server(
            {
                ("PATCH", f"{_METRICS_PATH}/7"): _blank_403(),
                ("GET", f"{_METRICS_PATH}/7"): _ok(
                    behavior_metric_json(7, can_view=False)
                ),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError):
            ws.update_metric(7, UpdateMetricParams(name="X"))
        patch_request, get_request = server.requests
        read_timeout = get_request.extensions["timeout"]
        assert read_timeout["connect"] == 5.0
        assert read_timeout["read"] == 5.0
        assert patch_request.extensions["timeout"]["read"] == DEFAULT_APP_TIMEOUT_S

    def test_reads_share_one_time_budget(
        self,
        temp_dir: Path,
        clock: list[float],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """All the reads together get 10 s: each read gets the time that is left.

        Each read below takes 6 s on the test clock. So 4 s are left for the
        second read (2 s for each phase), and the third read does not start.
        The message names the target that the client did not read.
        """
        server = _Server(
            {
                ("PATCH", _METRICS_PATH): _blank_403(),
                ("GET", f"{_METRICS_PATH}/1"): _ok(behavior_metric_json(1, "Mine")),
                ("GET", f"{_METRICS_PATH}/2"): _ok(
                    behavior_metric_json(2, "Theirs", can_view=False)
                ),
            }
        )

        def slow_server(request: httpx.Request) -> httpx.Response:
            """Answer from the scripted server; a read takes 6 s on the test clock.

            Args:
                request: The outgoing request.

            Returns:
                The scripted response.
            """
            response = server(request)
            if request.method == "GET":
                clock[0] += 6.0
            return response

        ws = _make_workspace(temp_dir, slow_server)
        with (
            caplog.at_level(logging.WARNING, logger="mixpanel_headless.workspace"),
            pytest.raises(QueryError) as exc_info,
        ):
            ws.bulk_update_metrics(
                [BulkUpdateMetricEntry(id=i, verified=True) for i in (1, 2, 3)]
            )
        reads = [r for r in server.requests if r.method == "GET"]
        assert [r.url.path for r in reads] == [
            f"{_METRICS_PATH}/1",
            f"{_METRICS_PATH}/2",
        ]
        assert [r.extensions["timeout"]["read"] for r in reads] == [5.0, 2.0]
        assert [r.extensions["timeout"]["connect"] for r in reads] == [5.0, 2.0]
        assert exc_info.value.message == (
            f"This account cannot edit saved metric {_THEIRS_2}. The client "
            f"could not read saved metric 3 to check it. {_METRIC_RULE} "
            f"{_ASK_ONE} {_METRIC_HINT} Nothing was changed."
        )
        assert "time budget" in caplog.text

    def test_failed_read_still_explains_the_refusal(self, temp_dir: Path) -> None:
        """When the read is refused too, the message explains the refusal without a creator."""
        server = _Server(
            {
                ("PATCH", f"{_METRICS_PATH}/4107"): _blank_403(),
                ("GET", f"{_METRICS_PATH}/4107"): _blank_403(),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_metric(4107, UpdateMetricParams(name="X"))
        assert exc_info.value.message == (
            f"This account cannot edit saved metric 4107. {_METRIC_RULE} "
            f"{_ASK_ONE} Nothing was changed."
        )

    def test_rate_limit_on_a_read_stops_the_reads_at_once(
        self,
        temp_dir: Path,
        recorded_sleeps: list[float],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A 429 on a read costs one request and no wait, and the reads stop.

        The 403 is already known, so the error must not wait for retries.
        """
        server = _Server(
            {
                ("PATCH", _METRICS_PATH): _blank_403(),
                ("GET", f"{_METRICS_PATH}/1"): httpx.Response(
                    429, headers={"Retry-After": "60"}, json={"error": "rate limit"}
                ),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with (
            caplog.at_level(logging.WARNING, logger="mixpanel_headless.workspace"),
            pytest.raises(QueryError) as exc_info,
        ):
            ws.bulk_update_metrics(
                [BulkUpdateMetricEntry(id=i, verified=True) for i in (1, 2, 3)]
            )
        assert exc_info.value.message == (
            "This account cannot edit one or more of these saved metrics: 1, 2, 3. "
            f"{_METRIC_RULE} {_ASK_EACH} {_METRIC_HINT} Nothing was changed."
        )
        assert server.calls() == [
            ("PATCH", _METRICS_PATH),
            ("GET", f"{_METRICS_PATH}/1"),
        ]
        assert recorded_sleeps == []
        assert "to explain the refused edit" in caplog.text
        assert "saved metric 1" in caplog.text

    def test_server_error_on_a_read_stops_the_reads(
        self, temp_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A 5xx on a read stops the reads, and the message names the unread targets.

        The row that was read before the error stays in the message. The
        message must not read as the full list of the refused metrics,
        because the client did not check the other targets.
        """
        server = _Server(
            {
                ("PATCH", _METRICS_PATH): _blank_403(),
                ("GET", f"{_METRICS_PATH}/2"): _ok(
                    behavior_metric_json(2, "Theirs", can_view=False)
                ),
                ("GET", f"{_METRICS_PATH}/5"): httpx.Response(
                    500, json={"error": "Internal error"}
                ),
            }
        )
        ws = _make_workspace(temp_dir, server)
        with (
            caplog.at_level(logging.WARNING, logger="mixpanel_headless.workspace"),
            pytest.raises(QueryError) as exc_info,
        ):
            ws.bulk_update_metrics(
                [BulkUpdateMetricEntry(id=i, verified=True) for i in (2, 5, 6)]
            )
        assert exc_info.value.message == (
            f"This account cannot edit saved metric {_THEIRS_2}. The client "
            f"could not read saved metrics 5, 6 to check them. {_METRIC_RULE} "
            f"{_ASK_ONE} {_METRIC_HINT} Nothing was changed."
        )
        assert server.calls() == [
            ("PATCH", _METRICS_PATH),
            ("GET", f"{_METRICS_PATH}/2"),
            ("GET", f"{_METRICS_PATH}/5"),
        ]
        assert "saved metric 5" in caplog.text

    def test_unexpected_read_failure_raises_the_original_403(
        self, temp_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An error outside the library classes never replaces the server's 403.

        The 403 goes out as it is, with the read error chained to it, so
        the traceback shows both.
        """
        server = _Server({("PATCH", f"{_METRICS_PATH}/1"): _blank_403()})
        ws = _make_workspace(temp_dir, server)
        with (
            patch.object(
                MixpanelAPIClient, "get_metric", side_effect=RuntimeError("boom")
            ),
            caplog.at_level(logging.WARNING, logger="mixpanel_headless.workspace"),
            pytest.raises(QueryError) as exc_info,
        ):
            ws.update_metric(1, UpdateMetricParams(name="X"))
        err = exc_info.value
        assert err.message == "Permission denied"
        assert err.status_code == 403
        read_error = err.__cause__
        assert isinstance(read_error, RuntimeError)
        assert str(read_error) == "boom"
        assert err.__context__ is read_error
        assert read_error.__context__ is None  # no cycle back to the 403
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "boom" in caplog.text

    # ---- behaviors ----------------------------------------------------------

    @pytest.mark.parametrize(
        ("read", "subject"),
        [
            (
                _ok(
                    {**saved_behavior_json(3001, "Checkout"), "can_update_basic": False}
                ),
                "This account cannot edit saved behavior 3001 ('Checkout', created "
                "by ana@example.com).",
            ),
            (
                _ok(saved_behavior_json(3001, "Checkout")),
                "This account cannot edit saved behavior 3001 ('Checkout', created "
                "by ana@example.com).",
            ),
            (
                _ok(
                    {
                        k: v
                        for k, v in saved_behavior_json(3001, "Checkout").items()
                        if k != "can_update_basic"
                    }
                ),
                "This account cannot edit saved behavior 3001 ('Checkout', created "
                "by ana@example.com).",
            ),
            (
                httpx.Response(
                    500, json={"error": "Behavior matching query does not exist"}
                ),
                "This account cannot edit saved behavior 3001.",
            ),
        ],
        ids=["flag-false", "flag-true", "flag-missing", "read-fails"],
    )
    def test_behavior_refusal_names_both_causes(
        self, temp_dir: Path, read: httpx.Response, subject: str
    ) -> None:
        """A refused behavior update names both causes, whatever the read shows.

        The server answers a missing ``write_behaviors`` permission and a
        behavior that is not shared for editing with the same blank 403, and
        its ``can_update_basic`` flag is false for both. So the read gives the
        name and the creator, and the message never selects one cause.

        Args:
            temp_dir: Temporary directory fixture.
            read: The answer to the read of the behavior.
            subject: The first sentence that the message must have.
        """
        server = _Server(
            {
                ("PATCH", f"{_BEHAVIORS_PATH}/3001"): _blank_403(),
                ("GET", f"{_BEHAVIORS_PATH}/3001"): read,
            }
        )
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(QueryError) as exc_info:
            ws.update_behavior(3001, UpdateBehaviorParams(name="Checkout v2"))
        assert exc_info.value.message == f"{subject} {_BEHAVIOR_REASON}"
        assert exc_info.value.status_code == 403
        assert isinstance(exc_info.value.__cause__, QueryError)
        assert server.calls() == [
            ("PATCH", f"{_BEHAVIORS_PATH}/3001"),
            ("GET", f"{_BEHAVIORS_PATH}/3001"),
        ]


# =============================================================================
# Typed values through the definition compiler
# =============================================================================


class TestTypedWrites:
    """create and update with the typed metric, formula, and behavior values."""

    def test_create_formula_with_operands(self, temp_dir: Path) -> None:
        """A Formula with operands saves as kind formula; references keep their id."""
        formula = Formula(
            "A / B * 100",
            label="Conversion",
            metrics=[Metric("Purchase", math="unique"), MetricRef(104700)],
        )
        server = _Server({("POST", _METRICS_PATH): _ok(formula_metric_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_metric(CreateMetricParams(name="Conversion", definition=formula))
        body = server.body(0)
        assert body["type"] == "formula"
        assert body["definition"] == build_formula_definition(formula)
        assert body["definition"]["formula"]["referencedMetrics"][1] == {
            "type": "metric",
            "id": 104700,
        }

    def test_formula_without_operands_refused(self, temp_dir: Path) -> None:
        """A Formula without operands raises SM7 before any request."""
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_metric(CreateMetricParams(name="n", definition=Formula("B / A")))
        assert exc_info.value.code == "SM7_FORMULA_WITHOUT_OPERANDS"
        assert server.requests == []

    def test_create_funnel_metric(self, temp_dir: Path) -> None:
        """A FunnelMetric saves as a behavior metric over the funnel behavior."""
        metric = FunnelMetric(FunnelBehavior(["View Cart", "Purchase"]))
        server = _Server({("POST", _METRICS_PATH): _ok(behavior_metric_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_metric(CreateMetricParams(name="Checkout", definition=metric))
        body = server.body(0)
        assert body["type"] == "metric"
        assert body["definition"] == build_metric_definition(metric)

    def test_update_formula_kind_check(self, temp_dir: Path) -> None:
        """A formula update passes on a stored formula and refuses a behavior metric."""
        formula = Formula("A", metrics=[Metric("Login")])
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/2"): _ok(formula_metric_json(2)),
                ("PATCH", f"{_METRICS_PATH}/2"): _ok(formula_metric_json(2)),
                ("GET", f"{_METRICS_PATH}/1"): _ok(behavior_metric_json(1)),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_metric(2, UpdateMetricParams(definition=formula))
        assert server.body(1)["definition"]["formula"]["definition"] == "A"
        with pytest.raises(ParamValidationError) as exc_info:
            ws.update_metric(1, UpdateMetricParams(definition=formula))
        assert exc_info.value.code == "SM3_KIND_CHANGE"

    @pytest.mark.parametrize(
        ("behavior", "wire_type"),
        [
            (SimpleBehavior(["Purchase", "Subscribe"], name="Buyers"), "simple"),
            (FunnelBehavior(["View Cart", "Purchase"]), "funnel"),
            (RetentionBehavior("Signup", "Login"), "retention"),
        ],
    )
    def test_create_typed_behavior(
        self,
        temp_dir: Path,
        behavior: SimpleBehavior | FunnelBehavior | RetentionBehavior,
        wire_type: str,
    ) -> None:
        """A typed behavior saves with its wire type and no name in the definition.

        Args:
            temp_dir: Temporary directory fixture.
            behavior: A typed behavior value.
            wire_type: Its wire type.
        """
        server = _Server({("POST", _BEHAVIORS_PATH): _ok(saved_behavior_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_behavior(CreateBehaviorParams(name="b", behavior=behavior))
        body = server.body(0)
        assert body["type"] == wire_type
        assert body["definition"] == build_behavior_definition(behavior)
        assert "name" not in body["definition"]["behavior"]

    @pytest.mark.parametrize(
        "definition",
        [
            FunnelMetric(FunnelBehavior(["View Cart", "Purchase"])),
            RetentionMetric(RetentionBehavior("Signup", "Login")),
            Formula(
                "A / B",
                metrics=[
                    FunnelMetric(FunnelBehavior(["View Cart", "Purchase"])),
                    Metric("Login"),
                ],
            ),
        ],
    )
    def test_create_metric_sends_no_legacy_filter_key(
        self,
        temp_dir: Path,
        definition: FunnelMetric | RetentionMetric | Formula,
    ) -> None:
        """A funnel or retention behavior, also as a formula operand, saves without ``filter``.

        The server's create schema rejects the legacy behavior key
        ``filter`` with a 400.

        Args:
            temp_dir: Temporary directory fixture.
            definition: A typed value whose query clause holds the legacy key.
        """
        server = _Server({("POST", _METRICS_PATH): _ok(behavior_metric_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_metric(CreateMetricParams(name="n", definition=definition))
        assert '"filter"' not in json.dumps(server.body(0))

    @pytest.mark.parametrize(
        "behavior",
        [
            FunnelBehavior(["View Cart", "Purchase"]),
            RetentionBehavior("Signup", "Login"),
        ],
    )
    def test_create_behavior_sends_no_legacy_filter_key(
        self, temp_dir: Path, behavior: FunnelBehavior | RetentionBehavior
    ) -> None:
        """A funnel or retention behavior saves without the legacy key ``filter``.

        Args:
            temp_dir: Temporary directory fixture.
            behavior: A typed funnel or retention behavior.
        """
        server = _Server({("POST", _BEHAVIORS_PATH): _ok(saved_behavior_json())})
        ws = _make_workspace(temp_dir, server)
        ws.create_behavior(CreateBehaviorParams(name="b", behavior=behavior))
        assert '"filter"' not in json.dumps(server.body(0))

    def test_create_refuses_a_legacy_key_in_a_compiled_definition(
        self, temp_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A compiled definition with a legacy key fails SM4 before any request."""
        monkeypatch.setattr(
            saved_definitions,
            "build_metric_definition",
            lambda _metric: {
                "behavior": {"type": "funnel", "filter": []},
                "measurement": {},
            },
        )
        monkeypatch.setattr(
            saved_definitions,
            "build_behavior_definition",
            lambda _behavior: {"behavior": {"type": "funnel", "filter": []}},
        )
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        funnel = FunnelBehavior(["View Cart", "Purchase"])
        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_metric(
                CreateMetricParams(name="n", definition=FunnelMetric(funnel))
            )
        assert exc_info.value.code == "SM4_SCHEMA"
        assert exc_info.value.details["path"] == "definition.behavior.filter"
        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_behavior(CreateBehaviorParams(name="b", behavior=funnel))
        assert exc_info.value.code == "SM4_SCHEMA"
        assert exc_info.value.details["path"] == "definition.behavior.filter"
        assert server.requests == []

    def test_create_strips_a_raw_legacy_key_update_sends_it(
        self, temp_dir: Path
    ) -> None:
        """A raw legacy key is removed on create, also with validate=False; an update sends it."""
        raw = RawMetricDefinition(
            "metric",
            {
                "behavior": {"type": "event", "name": "Login", "filter": []},
                "measurement": {"math": "total"},
            },
        )
        server = _Server(
            {
                ("GET", f"{_METRICS_PATH}/1"): _ok(behavior_metric_json(1)),
                ("PATCH", f"{_METRICS_PATH}/1"): _ok(behavior_metric_json(1)),
                ("POST", _METRICS_PATH): _ok(behavior_metric_json(2)),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.create_metric(CreateMetricParams(name="n", definition=raw))
        assert server.body(0)["definition"]["behavior"] == {
            "type": "event",
            "name": "Login",
        }
        ws.create_metric(CreateMetricParams(name="n", definition=raw), validate=False)
        assert "filter" not in server.body(1)["definition"]["behavior"]
        ws.update_metric(1, UpdateMetricParams(definition=raw))
        assert server.body(3)["definition"]["behavior"]["filter"] == []

    @pytest.mark.parametrize(
        ("row", "kind"),
        [
            (legacy_funnel_metric_json(), "metric"),
            (legacy_formula_metric_json(), "formula"),
        ],
    )
    @pytest.mark.parametrize("validate", [True, False])
    def test_copy_of_a_stored_metric_with_legacy_keys(
        self, temp_dir: Path, row: dict[str, Any], kind: str, validate: bool
    ) -> None:
        """to_raw_definition then create_metric sends no legacy key.

        Args:
            temp_dir: Temporary directory fixture.
            row: A stored metric whose definition has legacy keys.
            kind: The metric kind of the row.
            validate: Whether the schema mirror runs.
        """
        server = _Server({("POST", _METRICS_PATH): _ok(behavior_metric_json(5))})
        ws = _make_workspace(temp_dir, server)
        source = SavedMetric.model_validate(row)
        ws.create_metric(
            CreateMetricParams(name="copy", definition=source.to_raw_definition()),
            validate=validate,
        )
        body = server.body(0)
        assert body["type"] == kind
        expected = copy.deepcopy(row["definition"])
        strip_server_skipped_keys(kind, expected)
        assert body["definition"] == expected
        assert find_server_skipped_keys(kind, body["definition"]) == []
        assert source.definition == row["definition"]

    @pytest.mark.parametrize("validate", [True, False])
    def test_copy_of_a_stored_behavior_with_legacy_keys(
        self, temp_dir: Path, validate: bool
    ) -> None:
        """A stored behavior copied through RawBehaviorDefinition sends no legacy key.

        Args:
            temp_dir: Temporary directory fixture.
            validate: Whether the schema mirror runs.
        """
        row = legacy_behavior_json()
        server = _Server({("POST", _BEHAVIORS_PATH): _ok(saved_behavior_json(6))})
        ws = _make_workspace(temp_dir, server)
        source = SavedBehavior.model_validate(row)
        ws.create_behavior(
            CreateBehaviorParams(
                name="copy", behavior=RawBehaviorDefinition(source.definition)
            ),
            validate=validate,
        )
        definition = server.body(0)["definition"]
        assert find_server_skipped_keys("behavior", definition) == []
        assert definition["behavior"]["exclusions"] == [
            {"event": "Refund", "steps": {"from": 0, "to": 1}}
        ]
        assert (
            definition["behavior"]["behaviors"]
            == (row["definition"]["behavior"]["behaviors"])
        )
        assert server.body(0)["type"] == "funnel"

    def test_update_behavior_sends_a_raw_legacy_key(self, temp_dir: Path) -> None:
        """An update of a behavior sends a raw definition with its legacy keys."""
        row = legacy_behavior_json(3)
        server = _Server(
            {
                ("GET", f"{_BEHAVIORS_PATH}/3"): _ok(saved_behavior_json(3)),
                ("PATCH", f"{_BEHAVIORS_PATH}/3"): _ok(saved_behavior_json(3)),
            }
        )
        ws = _make_workspace(temp_dir, server)
        ws.update_behavior(
            3,
            UpdateBehaviorParams(behavior=RawBehaviorDefinition(row["definition"])),
        )
        assert server.body(1)["definition"] == row["definition"]

    def test_update_behavior_type_change_refused(self, temp_dir: Path) -> None:
        """A retention behavior for a stored funnel behavior raises SM3."""
        server = _Server({("GET", f"{_BEHAVIORS_PATH}/3"): _ok(saved_behavior_json(3))})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.update_behavior(
                3, UpdateBehaviorParams(behavior=RetentionBehavior("Signup", "Login"))
            )
        assert exc_info.value.code == "SM3_KIND_CHANGE"


# =============================================================================
# MR3: a warehouse metric is not a query value
# =============================================================================


class TestWarehouseMetricInQuery:
    """Workspace.query and build_params refuse a WarehouseMetric (MR3)."""

    @pytest.mark.parametrize(
        "events",
        [
            WarehouseMetric(55, "SELECT 1", "numeric"),
            [Metric("Login"), WarehouseMetric(55, "SELECT 1", "numeric")],
        ],
    )
    def test_build_params_refuses(self, temp_dir: Path, events: Any) -> None:
        """build_params raises MR3_WAREHOUSE_INLINE and points to MetricRef.

        Args:
            temp_dir: Temporary directory fixture.
            events: A warehouse metric alone or in a list.
        """
        ws = _make_workspace(temp_dir, _Server({}))
        with pytest.raises(ParamValidationError) as exc_info:
            ws.build_params(events)
        exc = exc_info.value
        assert exc.code == "MR3_WAREHOUSE_INLINE"
        assert "MetricRef" in str(exc)
        assert "create_metric" in str(exc)

    def test_query_refuses_before_any_request(self, temp_dir: Path) -> None:
        """query raises MR3_WAREHOUSE_INLINE and sends nothing."""
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.query(WarehouseMetric(55, "SELECT 1", "numeric"))  # type: ignore[arg-type]
        assert exc_info.value.code == "MR3_WAREHOUSE_INLINE"
        assert server.requests == []
