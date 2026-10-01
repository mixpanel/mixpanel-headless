# ruff: noqa: ARG001, ARG005
"""Unit tests for the Workspace saved metric and saved behavior write methods.

Tests for:
- ``create_metric``: the exact POST body per definition kind, the follow-up
  PATCH for owner and verified, and the checks that run before any request
- ``update_metric``: the reads it needs, the full definition it sends, and
  the kind-change refusal
- ``bulk_update_metrics``, ``create_behavior``, ``update_behavior``

Every refusal test also checks that no request left the client.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr

from mixpanel_headless._internal import saved_definitions
from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless._internal.query.metric_builders import (
    build_behavior_definition,
    build_formula_definition,
    build_metric_definition,
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
            "definition": {**stored["definition"], "display": {"prefix": "#"}}
        }

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

    def test_create_refuses_a_raw_legacy_key_update_sends_it(
        self, temp_dir: Path
    ) -> None:
        """A raw legacy key fails SM4 on create; an update sends it as given.

        A create with ``validate=False`` also sends it, and leaves the
        refusal to the server.
        """
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
        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_metric(CreateMetricParams(name="n", definition=raw))
        assert exc_info.value.details["path"] == "definition.behavior.filter"
        assert server.requests == []
        ws.update_metric(1, UpdateMetricParams(definition=raw))
        assert server.body(1)["definition"]["behavior"]["filter"] == []
        ws.create_metric(CreateMetricParams(name="n", definition=raw), validate=False)
        assert server.body(2)["definition"]["behavior"]["filter"] == []

    def test_create_behavior_refuses_a_raw_legacy_key(self, temp_dir: Path) -> None:
        """A raw behavior definition with a legacy key fails SM4 on create."""
        server = _Server({})
        ws = _make_workspace(temp_dir, server)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.create_behavior(
                CreateBehaviorParams(
                    name="b",
                    behavior=RawBehaviorDefinition(
                        {"behavior": {"type": "funnel", "filter": []}}
                    ),
                )
            )
        assert exc_info.value.code == "SM4_SCHEMA"
        assert server.requests == []

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
