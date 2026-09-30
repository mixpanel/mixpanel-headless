"""Workspace tests for querying saved metrics and saved behaviors by reference.

Covers ``MetricRef`` in ``build_params`` / ``query``, ``BehaviorRef`` in the
funnel and retention builders, the warehouse breakdown warning, and the
report and report-link round trip of reference params. Fixtures copy
``tests/unit/test_workspace_report_links.py``.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

import mixpanel_headless as mp
from mixpanel_headless import Workspace
from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless.exceptions import BookmarkValidationError
from mixpanel_headless.types import (
    BehaviorRef,
    CreateBookmarkParams,
    FunnelQueryResult,
    MetricRef,
    QueryResult,
    RetentionQueryResult,
    SavedBehavior,
    SavedMetric,
)
from tests.unit._saved_metric_fixtures import (
    behavior_metric_json,
    formula_metric_json,
    saved_behavior_json,
    warehouse_metric_json,
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


@pytest.fixture
def mock_api_client() -> MagicMock:
    """Create a spec'd mock API client whose slug POST echoes a record."""
    client = MagicMock(spec=MixpanelAPIClient)
    client.close = MagicMock()
    client.create_bookmark_url.side_effect = lambda body: {
        **body,
        "project_id": 12345,
        "created_at": "2026-09-30T10:00:00",
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
    """A Workspace on the default US session."""
    return workspace_factory()


@pytest.fixture
def mock_live_query(ws: Workspace) -> MagicMock:
    """Install a spec'd LiveQueryService mock on the workspace."""
    from mixpanel_headless._internal.services.live_query import LiveQueryService

    svc = MagicMock(spec=LiveQueryService)
    ws._live_query = svc
    return svc


def _codes(exc: BookmarkValidationError) -> list[str]:
    """Return the codes of a BookmarkValidationError.

    Args:
        exc: The raised error.

    Returns:
        The error codes, in order.
    """
    return [e.code for e in exc.errors]


# =============================================================================
# Insights: MetricRef
# =============================================================================


class TestBuildParamsWithMetricRef:
    """build_params accepts MetricRef anywhere it accepts a Metric."""

    def test_single_reference(self, ws: Workspace) -> None:
        """A reference alone gives one reference clause."""
        params = ws.build_params(MetricRef(42), last=7)
        assert params["sections"]["show"] == [{"type": "metric", "id": 42}]
        assert params["displayOptions"]["chartType"] == "line"

    def test_reference_with_overrides(self, ws: Workspace) -> None:
        """Typed fields reach the clause overrides."""
        params = ws.build_params(MetricRef(42, segment_method="first", label="First"))
        assert params["sections"]["show"] == [
            {
                "type": "metric",
                "id": 42,
                "overrides": {
                    "name": "First",
                    "measurement": {"segmentMethod": "first"},
                },
            }
        ]

    def test_references_with_top_level_formula(self, ws: Workspace) -> None:
        """A formula over references hides them and follows them."""
        params = ws.build_params(
            [MetricRef(1), MetricRef(2)], formula="A / B", formula_label="Rate"
        )
        show = params["sections"]["show"]
        assert show[0] == {"type": "metric", "id": 1, "isHidden": True}
        assert show[1] == {"type": "metric", "id": 2, "isHidden": True}
        assert show[2]["type"] == "formula"
        assert show[2]["definition"] == "A / B"

    def test_mixed_with_inline_metrics_and_tuple(self, ws: Workspace) -> None:
        """References mix with names and Metric objects in a tuple."""
        params = ws.build_params(
            (MetricRef(1), "Login", mp.Metric("Signup", math="unique"))
        )
        show = params["sections"]["show"]
        assert show[0] == {"type": "metric", "id": 1}
        assert show[1]["behavior"]["name"] == "Login"
        assert show[2]["measurement"] == {"math": "unique"}

    def test_warehouse_reference_with_group_by_logs_a_warning(
        self, ws: Workspace, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A warehouse reference with a breakdown builds and logs V28."""
        with caplog.at_level(logging.WARNING, logger="mixpanel_headless.workspace"):
            params = ws.build_params(MetricRef(7, type="warehouse"), group_by="$os")
        assert params["sections"]["show"] == [{"type": "warehouse", "id": 7}]
        assert "V28_WAREHOUSE_BREAKDOWN" in caplog.text

    def test_warehouse_reference_alone_logs_nothing(
        self, ws: Workspace, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A warehouse reference without breakdown or filter logs no warning."""
        with caplog.at_level(logging.WARNING, logger="mixpanel_headless.workspace"):
            ws.build_params(MetricRef(7, type="warehouse"))
        assert "V28_WAREHOUSE_BREAKDOWN" not in caplog.text

    def test_bad_custom_property_override_is_refused(self, ws: Workspace) -> None:
        """A custom property override goes through the CP rules."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_params(MetricRef(1, property=mp.CustomPropertyRef(0)))
        assert _codes(exc_info.value) == ["CP1_INVALID_ID"]


_REFERENCE_RESPONSE: dict[str, Any] = {
    "computed_at": "2026-09-30T08:31:15.232311+00:00",
    "date_range": {
        "from_date": "2024-09-01T00:00:00-07:00",
        "to_date": "2024-09-03T23:59:59.999000-07:00",
    },
    "headers": ["$event"],
    "meta": {
        "is_segmentation_limit_hit": False,
        "min_sampling_factor": 1.0,
        "report_sections": {"group": [], "show": [{"metric_key": "Docs created"}]},
        "sub_query_count": 1,
    },
    "series": {
        "Docs created": {
            "2024-09-01T00:00:00-07:00": 962,
            "2024-09-02T00:00:00-07:00": 952,
            "2024-09-03T00:00:00-07:00": 981,
        }
    },
}
"""Shape of a live insights response for a saved-metric reference.

The series key is the saved metric name with no math suffix, and the
header is ``$event`` (an inline event metric gives ``$metric``).
"""


class TestQueryWithMetricRef:
    """query() sends the reference params to the insights endpoint."""

    def test_reference_response_labels(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A reference response parses, and the saved name labels the series."""
        mock_api_client.insights_query.return_value = _REFERENCE_RESPONSE

        result = ws.query(MetricRef(42), from_date="2024-09-01", to_date="2024-09-03")

        assert result.headers == ["$event"]
        df = result.df
        assert list(df.columns) == ["date", "event", "count"]
        assert df["event"].unique().tolist() == ["Docs created"]
        assert df["count"].tolist() == [962, 952, 981]

    def test_query_sends_reference(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """The live query receives the reference clause unchanged."""
        sentinel = QueryResult(computed_at="t", from_date="d", to_date="d")
        mock_live_query.query.return_value = sentinel

        result = ws.query(MetricRef(42, math="unique"), last=7)

        assert result is sentinel
        params = mock_live_query.query.call_args.kwargs["bookmark_params"]
        assert params["sections"]["show"] == [
            {
                "type": "metric",
                "id": 42,
                "overrides": {"measurement": {"math": "unique"}},
            }
        ]


# =============================================================================
# Funnels: BehaviorRef
# =============================================================================


class TestFunnelWithBehaviorRef:
    """build_funnel_params accepts a BehaviorRef in place of the step list."""

    def test_reference_behavior(self, ws: Workspace) -> None:
        """The behavior block is the reference, and the measurement is built."""
        params = ws.build_funnel_params(BehaviorRef(5, "funnel"), last=30)
        assert params["sections"]["show"] == [
            {
                "type": "metric",
                "behavior": {"type": "funnel", "id": 5},
                "measurement": {
                    "math": "conversion_rate_unique",
                    "property": None,
                    "stepIndex": None,
                },
            }
        ]
        assert params["displayOptions"] == {"chartType": "funnel-steps"}
        assert params["sections"]["formula"] == []

    def test_matches_inline_sections(self, ws: Workspace) -> None:
        """Everything except the behavior block matches the inline builder."""
        inline = ws.build_funnel_params(
            ["Signup", "Purchase"],
            math="average",
            math_property="amount",
            mode="trends",
        )
        ref = ws.build_funnel_params(
            BehaviorRef(5, "funnel"),
            math="average",
            math_property="amount",
            mode="trends",
        )
        assert ref["displayOptions"] == inline["displayOptions"]
        assert ref["sections"]["time"] == inline["sections"]["time"]
        assert (
            ref["sections"]["show"][0]["measurement"]
            == inline["sections"]["show"][0]["measurement"]
        )

    @pytest.mark.parametrize("kind", ["retention", "simple"])
    def test_wrong_type(self, ws: Workspace, kind: Any) -> None:
        """F13_BEHAVIOR_REF_TYPE: a funnel query needs a funnel behavior."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_funnel_params(BehaviorRef(5, kind))
        assert _codes(exc_info.value) == ["F13_BEHAVIOR_REF_TYPE"]
        assert exc_info.value.errors[0].path == "steps"

    @pytest.mark.parametrize(
        ("kwargs", "name"),
        [
            ({"conversion_window": 7}, "conversion_window"),
            ({"conversion_window_unit": "week"}, "conversion_window_unit"),
            ({"order": "any"}, "order"),
            ({"exclusions": ["Logout"]}, "exclusions"),
            ({"holding_constant": "plan"}, "holding_constant"),
            ({"reentry_mode": "basic"}, "reentry_mode"),
        ],
    )
    def test_behavior_settings_are_refused(
        self, ws: Workspace, kwargs: dict[str, Any], name: str
    ) -> None:
        """F14_BEHAVIOR_REF_SETTINGS: the saved behavior owns these settings."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_funnel_params(BehaviorRef(5, "funnel"), **kwargs)
        assert _codes(exc_info.value) == ["F14_BEHAVIOR_REF_SETTINGS"]
        assert name in exc_info.value.errors[0].message

    def test_default_settings_are_allowed(self, ws: Workspace) -> None:
        """Default values of the behavior settings are not a change."""
        params = ws.build_funnel_params(
            BehaviorRef(5, "funnel"),
            conversion_window=14,
            conversion_window_unit="day",
            order="loose",
            exclusions=[],
            holding_constant=[],
        )
        assert params["sections"]["show"][0]["behavior"] == {"type": "funnel", "id": 5}

    def test_query_level_rules_still_apply(self, ws: Workspace) -> None:
        """Measurement and time rules apply to a reference too."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_funnel_params(
                BehaviorRef(5, "funnel"), math_property="amount", last=0
            )
        codes = _codes(exc_info.value)
        assert "F11_MATH_REJECTS_PROPERTY" in codes
        assert "V7_LAST_POSITIVE" in codes

    def test_signature_defaults_match_the_refusal_rule(self) -> None:
        """The refusal rule compares with the real signature defaults."""
        for method in (Workspace.query_funnel, Workspace.build_funnel_params):
            params = inspect.signature(method).parameters
            assert params["conversion_window"].default == 14
            assert params["conversion_window_unit"].default == "day"
            assert params["order"].default == "loose"

    def test_query_funnel_sends_reference(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """query_funnel runs the reference params."""
        sentinel = FunnelQueryResult(computed_at="t", from_date="d", to_date="d")
        mock_live_query.query_funnel.return_value = sentinel

        result = ws.query_funnel(BehaviorRef(5, "funnel"))

        assert result is sentinel
        params = mock_live_query.query_funnel.call_args.kwargs["bookmark_params"]
        assert params["sections"]["show"][0]["behavior"] == {"type": "funnel", "id": 5}


# =============================================================================
# Retention: BehaviorRef
# =============================================================================


class TestRetentionWithBehaviorRef:
    """build_retention_params accepts a BehaviorRef in place of the events."""

    def test_reference_behavior(self, ws: Workspace) -> None:
        """The behavior block is the reference, and the measurement is built."""
        params = ws.build_retention_params(BehaviorRef(6, "retention"))
        assert params["sections"]["show"] == [
            {
                "type": "metric",
                "behavior": {"type": "retention", "id": 6},
                "measurement": {"math": "retention_rate"},
            }
        ]
        assert params["displayOptions"] == {"chartType": "retention-curve"}
        assert "sorting" in params

    def test_matches_inline_params(self, ws: Workspace) -> None:
        """Everything except the behavior block matches the inline builder."""
        inline = ws.build_retention_params(
            "Signup", "Login", math="unique", retention_cumulative=True, mode="table"
        )
        ref = ws.build_retention_params(
            BehaviorRef(6, "retention"),
            math="unique",
            retention_cumulative=True,
            mode="table",
        )
        ref["sections"]["show"][0]["behavior"] = inline["sections"]["show"][0][
            "behavior"
        ]
        assert ref == inline

    @pytest.mark.parametrize("kind", ["funnel", "simple"])
    def test_wrong_type(self, ws: Workspace, kind: Any) -> None:
        """R14_BEHAVIOR_REF_TYPE: a retention query needs a retention behavior."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_retention_params(BehaviorRef(6, kind))
        assert _codes(exc_info.value) == ["R14_BEHAVIOR_REF_TYPE"]
        assert exc_info.value.errors[0].path == "born_event"

    @pytest.mark.parametrize(
        ("kwargs", "name"),
        [
            ({"return_event": "Login"}, "return_event"),
            ({"retention_unit": "day"}, "retention_unit"),
            ({"alignment": "interval_start"}, "alignment"),
            ({"bucket_sizes": [1, 7]}, "bucket_sizes"),
            ({"unbounded_mode": "carry_forward"}, "unbounded_mode"),
        ],
    )
    def test_behavior_settings_are_refused(
        self, ws: Workspace, kwargs: dict[str, Any], name: str
    ) -> None:
        """R15_BEHAVIOR_REF_SETTINGS: the saved behavior owns these settings."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_retention_params(BehaviorRef(6, "retention"), **kwargs)
        assert _codes(exc_info.value) == ["R15_BEHAVIOR_REF_SETTINGS"]
        assert name in exc_info.value.errors[0].message

    def test_query_level_rules_still_apply(self, ws: Workspace) -> None:
        """Math, mode, and unit rules apply to a reference too."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_retention_params(
                BehaviorRef(6, "retention"),
                math="median",  # type: ignore[arg-type]
                unit="hour",
            )
        codes = _codes(exc_info.value)
        assert "R9_INVALID_MATH" in codes
        assert "R11_INVALID_UNIT" in codes

    def test_missing_return_event_without_reference(self, ws: Workspace) -> None:
        """R2_EMPTY_RETURN_EVENT: event retention still needs a return event."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_retention_params("Signup")
        assert _codes(exc_info.value) == ["R2_EMPTY_RETURN_EVENT"]

    def test_signature_defaults_match_the_refusal_rule(self) -> None:
        """The refusal rule compares with the real signature defaults."""
        for method in (Workspace.query_retention, Workspace.build_retention_params):
            params = inspect.signature(method).parameters
            assert params["return_event"].default is None
            assert params["retention_unit"].default == "week"
            assert params["alignment"].default == "birth"

    def test_query_retention_sends_reference(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """query_retention runs the reference params."""
        sentinel = RetentionQueryResult(computed_at="t", from_date="d", to_date="d")
        mock_live_query.query_retention.return_value = sentinel

        result = ws.query_retention(BehaviorRef(6, "retention"))

        assert result is sentinel
        params = mock_live_query.query_retention.call_args.kwargs["bookmark_params"]
        assert params["sections"]["show"][0]["behavior"] == {
            "type": "retention",
            "id": 6,
        }


# =============================================================================
# Saved entities as query inputs
# =============================================================================


class TestSavedEntitiesAsQueryInputs:
    """SavedMetric and SavedBehavior work wherever their references do."""

    def test_saved_metric_alone(self, ws: Workspace) -> None:
        """A SavedMetric becomes a reference of its own kind."""
        metric = SavedMetric.model_validate(formula_metric_json(metric_id=118228))
        params = ws.build_params(metric)
        assert params["sections"]["show"] == [{"type": "formula", "id": 118228}]

    def test_list_of_saved_metrics(self, ws: Workspace) -> None:
        """A list of saved metrics, as list_metrics returns it, is a valid query."""
        metrics = [
            SavedMetric.model_validate(behavior_metric_json(metric_id=1)),
            SavedMetric.model_validate(warehouse_metric_json(metric_id=2)),
        ]
        params = ws.build_params(metrics, formula="A + B")
        show = params["sections"]["show"]
        assert show[0] == {"type": "metric", "id": 1, "isHidden": True}
        assert show[1] == {"type": "warehouse", "id": 2, "isHidden": True}
        assert show[2]["definition"] == "A + B"

    def test_saved_metric_mixed_with_inline(self, ws: Workspace) -> None:
        """Saved metrics, references, names, and Metrics mix in one list."""
        metric = SavedMetric.model_validate(behavior_metric_json(metric_id=5))
        params = ws.build_params(
            [metric, MetricRef(6, math="unique"), "Login", mp.Metric("Signup")]
        )
        show = params["sections"]["show"]
        assert show[0] == {"type": "metric", "id": 5}
        assert show[1]["overrides"] == {"measurement": {"math": "unique"}}
        assert show[2]["behavior"]["name"] == "Login"
        assert show[3]["behavior"]["name"] == "Signup"

    def test_query_with_saved_metric(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """query() runs a SavedMetric by reference."""
        mock_live_query.query.return_value = QueryResult(
            computed_at="t", from_date="d", to_date="d"
        )
        ws.query(SavedMetric.model_validate(behavior_metric_json(metric_id=9)))
        params = mock_live_query.query.call_args.kwargs["bookmark_params"]
        assert params["sections"]["show"] == [{"type": "metric", "id": 9}]

    def test_legacy_saved_metric_is_refused(self, ws: Workspace) -> None:
        """A legacy behavior row cannot run by reference."""
        metric = SavedMetric.model_validate(
            {**behavior_metric_json(), "type": "behavior"}
        )
        with pytest.raises(mp.ParamValidationError) as exc_info:
            ws.build_params(metric)
        assert exc_info.value.code == "MR5_INVALID_TYPE"

    def test_saved_funnel_behavior(self, ws: Workspace) -> None:
        """A SavedBehavior of type funnel replaces the step list."""
        behavior = SavedBehavior.model_validate(saved_behavior_json(behavior_id=3001))
        params = ws.build_funnel_params(behavior)
        assert params["sections"]["show"][0]["behavior"] == {
            "type": "funnel",
            "id": 3001,
        }

    def test_saved_retention_behavior(self, ws: Workspace) -> None:
        """A SavedBehavior of type retention replaces both events."""
        behavior = SavedBehavior.model_validate(
            saved_behavior_json(behavior_id=4410, behavior_type="retention")
        )
        params = ws.build_retention_params(behavior)
        assert params["sections"]["show"][0]["behavior"] == {
            "type": "retention",
            "id": 4410,
        }

    def test_saved_behavior_of_wrong_type(self, ws: Workspace) -> None:
        """The engines check the type of a SavedBehavior too."""
        behavior = SavedBehavior.model_validate(
            saved_behavior_json(behavior_type="retention")
        )
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_funnel_params(behavior)
        assert _codes(exc_info.value) == ["F13_BEHAVIOR_REF_TYPE"]

    def test_query_funnel_with_saved_behavior(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """query_funnel runs a SavedBehavior by reference."""
        mock_live_query.query_funnel.return_value = FunnelQueryResult(
            computed_at="t", from_date="d", to_date="d"
        )
        ws.query_funnel(
            SavedBehavior.model_validate(saved_behavior_json(behavior_id=7))
        )
        params = mock_live_query.query_funnel.call_args.kwargs["bookmark_params"]
        assert params["sections"]["show"][0]["behavior"] == {"type": "funnel", "id": 7}

    def test_query_retention_with_saved_behavior(
        self, ws: Workspace, mock_live_query: MagicMock
    ) -> None:
        """query_retention runs a SavedBehavior by reference."""
        mock_live_query.query_retention.return_value = RetentionQueryResult(
            computed_at="t", from_date="d", to_date="d"
        )
        ws.query_retention(
            SavedBehavior.model_validate(
                saved_behavior_json(behavior_id=8, behavior_type="retention")
            )
        )
        params = mock_live_query.query_retention.call_args.kwargs["bookmark_params"]
        assert params["sections"]["show"][0]["behavior"] == {
            "type": "retention",
            "id": 8,
        }


# =============================================================================
# Reports and report links keep the reference
# =============================================================================


class TestReferencesInReportsAndLinks:
    """A report or report link built from reference params keeps the reference."""

    def test_report_link_round_trip(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """create_report_link posts the reference, and resolve returns it."""
        params = ws.build_params(
            [MetricRef(42, segment_method="first"), MetricRef(43, type="formula")]
        )

        link = ws.create_report_link(params)

        body = mock_api_client.create_bookmark_url.call_args.args[0]
        assert body["params"]["sections"]["show"] == [
            {
                "type": "metric",
                "id": 42,
                "overrides": {"measurement": {"segmentMethod": "first"}},
            },
            {"type": "formula", "id": 43},
        ]
        mock_api_client.get_bookmark_url.return_value = {
            "slug": link.slug,
            "type": "insights",
            "params": body["params"],
            "project_id": 12345,
            "created_at": "2026-09-30T10:00:00",
        }

        resolved = ws.resolve_report_link(link.slug)

        assert resolved.params == params

    def test_report_link_with_warehouse_reference(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A warehouse reference passes the client-side schema check."""
        params = ws.build_params(MetricRef(7, type="warehouse"))
        ws.create_report_link(params)
        body = mock_api_client.create_bookmark_url.call_args.args[0]
        assert body["params"]["sections"]["show"] == [{"type": "warehouse", "id": 7}]

    def test_report_link_with_behavior_reference(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """A funnel over a saved behavior passes the client-side schema check."""
        params = ws.build_funnel_params(BehaviorRef(5, "funnel"))
        ws.create_report_link(params, report_type="funnels")
        body = mock_api_client.create_bookmark_url.call_args.args[0]
        assert body["params"]["sections"]["show"][0]["behavior"] == {
            "type": "funnel",
            "id": 5,
        }

    def test_saved_report_keeps_the_reference(
        self, ws: Workspace, mock_api_client: MagicMock
    ) -> None:
        """create_bookmark sends the reference clause as built."""
        mock_api_client.create_bookmark.return_value = {
            "id": 1,
            "name": "Buyers",
            "type": "insights",
            "params": {},
        }
        mock_api_client.add_report_to_dashboard.return_value = {
            "id": 10,
            "title": "Board",
            "is_private": False,
            "is_restricted": False,
            "is_favorited": False,
            "can_update_basic": True,
            "can_share": True,
            "can_view": True,
            "can_update_restricted": False,
            "can_update_visibility": False,
            "is_superadmin": False,
            "allow_staff_override": False,
            "can_pin": True,
            "is_shared_with_project": True,
            "ancestors": [],
        }
        params = ws.build_params(MetricRef(42, label="Buyers"))

        ws.create_bookmark(
            CreateBookmarkParams(
                name="Buyers",
                bookmark_type="insights",
                params=params,
                dashboard_id=10,
            )
        )

        sent = mock_api_client.create_bookmark.call_args.args[0]
        assert sent["params"]["sections"]["show"] == [
            {"type": "metric", "id": 42, "overrides": {"name": "Buyers"}}
        ]
