"""Tests for inline metrics in the query validators and the Workspace builders.

Covers funnel and retention metrics, metrics over more than one event, and
formulas with their own operands in ``validate_query_args`` (Layer 1),
``validate_bookmark`` (Layer 2), ``Workspace.build_params``, and the
refusal of more than one event per step in ``query_funnel`` and
``query_retention``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from mixpanel_headless import Workspace
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless._internal.query.metric_builders import (
    build_funnel_metric_clause,
    build_metric_clause,
    build_retention_metric_clause,
)
from mixpanel_headless._internal.validation import (
    validate_bookmark,
    validate_query_args,
)
from mixpanel_headless.exceptions import BookmarkValidationError, ValidationError
from mixpanel_headless.types import (
    CohortCriteria,
    CohortDefinition,
    CohortMetric,
    CustomEventRef,
    Exclusion,
    Filter,
    Formula,
    FormulaOperand,
    FunnelBehavior,
    FunnelMetric,
    FunnelStep,
    InlineCustomProperty,
    Metric,
    RetentionBehavior,
    RetentionMetric,
    SimpleBehavior,
)

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
"""Fake session for ``Workspace(session=...)``."""

FUNNEL = FunnelBehavior(["Signup", "Purchase"])
"""A valid two-step funnel behavior."""

RETENTION = RetentionBehavior("Signup", "Login")
"""A valid retention behavior."""


@pytest.fixture
def ws(mock_config_manager: MagicMock) -> Workspace:
    """Create Workspace with mocked dependencies for params testing."""
    return Workspace(session=_TEST_SESSION)


def _args(
    events: list[str | Metric | CohortMetric | FunnelMetric | RetentionMetric],
    formulas: list[Formula] | None = None,
) -> list[ValidationError]:
    """Run ``validate_query_args`` with neutral query-level arguments."""
    resolved = formulas or []
    return validate_query_args(
        events=events,
        math="total",
        math_property=None,
        per_user=None,
        from_date=None,
        to_date=None,
        last=30,
        has_formula=any(f.metrics is None for f in resolved),
        rolling=None,
        cumulative=False,
        group_by=None,
        formulas=resolved,
    )


def _inline_cohort_metric() -> CohortMetric:
    """Return a CohortMetric that holds an inline definition.

    Construction refuses an inline definition, because the server returns
    500 for it. The query validator checks it again, so this helper skips
    the constructor checks to reach that check.
    """
    definition = CohortDefinition(
        CohortCriteria.did_event("Purchase", at_least=1, within_days=30)
    )
    metric = object.__new__(CohortMetric)
    object.__setattr__(metric, "cohort", definition)
    object.__setattr__(metric, "name", None)
    return metric


def _codes(errors: list[ValidationError]) -> list[str]:
    """Return the codes of the errors, in order."""
    return [e.code for e in errors]


# =============================================================================
# Layer 1: validate_query_args
# =============================================================================


class TestQueryArgsAcceptNewKinds:
    """Valid funnel, retention, and multi-event metrics pass Layer 1."""

    def test_all_kinds_pass(self) -> None:
        """Every new kind passes with no error."""
        events: list[str | Metric | CohortMetric | FunnelMetric | RetentionMetric] = [
            Metric(["Login", CustomEventRef(4)], math="unique"),
            Metric(SimpleBehavior(["A", "B"])),
            FunnelMetric(FUNNEL),
            RetentionMetric(RETENTION),
        ]
        assert _args(events) == []

    def test_unknown_item_type_keeps_v21(self) -> None:
        """An item of an unknown type is still refused with V21."""
        errors = _args([3])  # type: ignore[list-item]
        assert _codes(errors) == ["V21_INVALID_EVENT_TYPE"]
        assert "FunnelMetric" in errors[0].message


class TestFunnelMetricRules:
    """The ``query_funnel`` rules run on a funnel metric, with their codes."""

    @pytest.mark.parametrize(
        ("metric", "code", "path"),
        [
            (
                FunnelMetric(FunnelBehavior(["A", "B"], conversion_window=0)),
                "F3_CONVERSION_WINDOW_POSITIVE",
                "events[0].conversion_window",
            ),
            (
                FunnelMetric(FunnelBehavior(["A", "B"], conversion_window=400)),
                "F3_CONVERSION_WINDOW_MAX",
                "events[0].conversion_window",
            ),
            (
                FunnelMetric(FUNNEL, math="conversion_rate_session"),
                "F9_SESSION_MATH_REQUIRES_SESSION_WINDOW",
                "events[0].math",
            ),
            (
                FunnelMetric(
                    FunnelBehavior(["A", "B"], exclusions=[Exclusion("X", 0, 5)])
                ),
                "F4_EXCLUSION_STEP_BOUNDS",
                "events[0].exclusions[0]",
            ),
            (
                FunnelMetric(FunnelBehavior(["A", "B"], reentry_mode="bogus")),  # type: ignore[arg-type]
                "F12_INVALID_REENTRY_MODE",
                "events[0].reentry_mode",
            ),
        ],
    )
    def test_rule(self, metric: FunnelMetric, code: str, path: str) -> None:
        """Each funnel rule gives its current code under the metric's path."""
        errors = _args([metric])
        assert code in _codes(errors)
        assert path in [e.path for e in errors]

    def test_several_events_in_one_step_point_to_custom_events(self) -> None:
        """A list as a step keeps F2 and names custom events as the fix."""
        behavior = FunnelBehavior(["A", ["B", "C"]])  # type: ignore[list-item]
        errors = _args([FunnelMetric(behavior)])
        assert _codes(errors) == ["F2_EMPTY_STEP_EVENT"]
        assert errors[0].path == "events[0].steps[1]"
        assert "$custom_event:<id>" in errors[0].message

    def test_custom_property_is_scanned(self) -> None:
        """An invalid inline custom property on a funnel metric is refused."""
        prop = InlineCustomProperty(formula="", inputs={})
        errors = _args([FunnelMetric(FUNNEL, math="average", property=prop)])
        assert "CP2_EMPTY_FORMULA" in _codes(errors)


class TestRetentionMetricRules:
    """The ``query_retention`` rules run on a retention metric, with their codes."""

    @pytest.mark.parametrize(
        ("metric", "code"),
        [
            (
                RetentionMetric(RetentionBehavior("A", "B", bucket_sizes=[7, 1])),
                "R6_BUCKET_SIZES_ASCENDING",
            ),
            (
                RetentionMetric(RetentionBehavior("A", "B", retention_unit="hour")),  # type: ignore[arg-type]
                "R7_INVALID_RETENTION_UNIT",
            ),
            (
                RetentionMetric(RetentionBehavior("A", "B", alignment="x")),  # type: ignore[arg-type]
                "R8_INVALID_ALIGNMENT",
            ),
        ],
    )
    def test_rule(self, metric: RetentionMetric, code: str) -> None:
        """Each retention rule gives its current code under the metric's path."""
        errors = _args([metric])
        assert code in _codes(errors)
        assert all(e.path.startswith("events[0].") for e in errors)

    def test_several_events_point_to_custom_events(self) -> None:
        """A list as the born event gives R1 and names custom events."""
        behavior = RetentionBehavior(["A", "B"], "C")  # type: ignore[arg-type]
        errors = _args([RetentionMetric(behavior)])
        assert _codes(errors) == ["R1_EMPTY_BORN_EVENT"]
        assert errors[0].path == "events[0].born_event"
        assert "$custom_event:<id>" in errors[0].message


class TestFormulaRules:
    """Formula rules by form: the letter form keeps V16/V19 first, then FM4."""

    def test_operand_formula_alone_passes(self) -> None:
        """A formula with operands needs no other event (no V0, no V4)."""
        formula = Formula("A / B", metrics=[Metric("A"), Metric("B")])
        assert _args([], [formula]) == []

    def test_operand_formula_with_one_event_passes(self) -> None:
        """A formula with operands does not count the query's events (no V4)."""
        formula = Formula("A", metrics=[Metric("A")])
        assert _args(["Login"], [formula]) == []

    def test_no_events_and_no_operand_formula_keeps_v0(self) -> None:
        """Without events and without an operand formula V0 stays."""
        assert "V0_NO_EVENTS" in _codes(_args([]))

    def test_letter_formula_without_letters_keeps_v16(self) -> None:
        """No letters still gives V16 alone."""
        errors = _args(["A", "B"], [Formula("1 + 2")])
        assert _codes(errors) == ["V16_FORMULA_SYNTAX"]

    def test_letter_formula_out_of_bounds_keeps_v19(self) -> None:
        """A letter past the events still gives V19 alone, even with bad syntax."""
        errors = _args(["A", "B"], [Formula("C +")])
        assert _codes(errors) == ["V19_FORMULA_BOUNDS"]

    @pytest.mark.parametrize("expression", ["A +", "A $ B", "A ^ -B", "(A"])
    def test_letter_formula_bad_syntax_gives_fm4(self, expression: str) -> None:
        """Bad syntax that passes V16 and V19 gives FM4_SYNTAX."""
        errors = _args(["A", "B"], [Formula(expression)])
        assert _codes(errors) == ["FM4_SYNTAX"]
        assert errors[0].path == "formula"

    def test_letter_formula_valid_syntax_passes(self) -> None:
        """A valid letter formula has no error."""
        assert _args(["A", "B"], [Formula("(B / A) * 1e2")]) == []

    def test_letter_scan_of_v19_is_unchanged(self) -> None:
        """V19 still reads the E of ``1E2`` as a letter, as in every release."""
        errors = _args(["A", "B"], [Formula("(B / A) * 1E2")])
        assert _codes(errors) == ["V19_FORMULA_BOUNDS"]

    def test_operands_are_validated_under_their_path(self) -> None:
        """Operand rules run with the path of the operand."""
        operands: list[FormulaOperand] = [
            Metric("A", math="unique", property="amount"),
            FunnelMetric(FunnelBehavior(["A", "B"], conversion_window=0)),
        ]
        errors = _args([], [Formula("A + B", metrics=operands)])
        by_code = {e.code: e.path for e in errors}
        assert by_code["V14_METRIC_REJECTS_PROPERTY"] == "formula.metrics[0]"
        assert by_code["F3_CONVERSION_WINDOW_POSITIVE"] == (
            "formula.metrics[1].conversion_window"
        )

    def test_inline_cohort_operand_is_refused(self) -> None:
        """An operand CohortMetric with an inline definition gets CM5, as at top level."""
        operand = _inline_cohort_metric()
        errors = _args([], [Formula("A", metrics=[operand])])
        assert _codes(errors) == ["CM5_INLINE_COHORT_METRIC"]
        assert errors[0].path == "formula.metrics[0]"

    def test_operand_step_filters_are_scanned(self) -> None:
        """A custom property in an operand's simple-behavior step filter is checked."""
        bad = Filter.equals(InlineCustomProperty(formula="", inputs={}), "x")
        behavior = SimpleBehavior([FunnelStep("Buy", filters=[bad]), "Login"])
        errors = _args([], [Formula("A", metrics=[Metric(behavior)])])
        assert "CP2_EMPTY_FORMULA" in _codes(errors)
        assert errors[0].path == "formula.metrics[0].event[0].filters[0]"

    def test_top_level_step_filters_keep_their_path(self) -> None:
        """The top-level scan of simple-behavior step filters keeps its path."""
        bad = Filter.equals(InlineCustomProperty(formula="", inputs={}), "x")
        behavior = SimpleBehavior([FunnelStep("Buy", filters=[bad]), "Login"])
        errors = _args([Metric(behavior)])
        assert "CP2_EMPTY_FORMULA" in _codes(errors)
        assert errors[0].path == "events[0].event[0].filters[0]"


class TestEventNamesInsideMetrics:
    """The event-name checks run on each name inside a multi-event Metric."""

    @pytest.mark.parametrize("invisible", ["\u200b", "\u200b\ufeff", "\u2060"])
    def test_invisible_name_in_a_list_gives_v22(self, invisible: str) -> None:
        """An invisible-only name in a list gives V22_INVISIBLE_EVENT with its path."""
        errors = _args([Metric(["Login", invisible])])
        assert _codes(errors) == ["V22_INVISIBLE_EVENT"]
        assert errors[0].path == "events[0].event[1]"

    def test_invisible_name_in_a_simple_behavior_gives_v22(self) -> None:
        """Names in a SimpleBehavior, plain and in a FunnelStep, are checked."""
        behavior = SimpleBehavior(["\u200b", FunnelStep("\ufeff"), "Login"])
        errors = _args([Metric(behavior)])
        assert _codes(errors) == ["V22_INVISIBLE_EVENT", "V22_INVISIBLE_EVENT"]
        assert [e.path for e in errors] == ["events[0].event[0]", "events[0].event[1]"]

    def test_invisible_name_in_an_operand_gives_v22(self) -> None:
        """Operand names are checked under the operand's path."""
        operands: list[FormulaOperand] = [Metric("\u200b"), Metric(["A", "\u2060"])]
        errors = _args([], [Formula("A + B", metrics=operands)])
        assert [(e.code, e.path) for e in errors] == [
            ("V22_INVISIBLE_EVENT", "formula.metrics[0]"),
            ("V22_INVISIBLE_EVENT", "formula.metrics[1].event[1]"),
        ]

    def test_visible_names_pass(self) -> None:
        """Ordinary names in lists and behaviors pass."""
        behavior = SimpleBehavior(["Login", FunnelStep("Buy")])
        assert _args([Metric(["Login", CustomEventRef(3)]), Metric(behavior)]) == []

    def test_single_event_name_keeps_todays_error(self) -> None:
        """A single invisible event name keeps the top-level V22 path."""
        errors = _args([Metric("\u200b")])
        assert [(e.code, e.path) for e in errors] == [
            ("V22_INVISIBLE_EVENT", "events[0]")
        ]


class TestEventTypesInsideMetrics:
    """Layer 1 refuses the list items that the Metric constructor refuses (MT5)."""

    def test_step_put_in_the_list_later_gives_mt5(self) -> None:
        """A FunnelStep put into the caller's list after construction is refused."""
        events: list[Any] = ["Login", "Signup"]
        metric = Metric(events, filters=[Filter.equals("country", "US")])
        events[1] = FunnelStep("Signup")
        errors = _args([metric])
        assert [(e.code, e.path) for e in errors] == [
            ("MT5_INVALID_EVENT_TYPE", "events[0].event[1]")
        ]
        assert "got FunnelStep" in errors[0].message
        assert "SimpleBehavior" in errors[0].message

    @pytest.mark.parametrize("item", [123, True, None], ids=["int", "bool", "none"])
    def test_other_item_put_in_the_list_later_gives_mt5(self, item: object) -> None:
        """A number, a bool, or None put into the list later is refused."""
        events: list[Any] = ["Login"]
        metric = Metric(events)
        events.append(item)
        errors = _args([metric])
        assert [(e.code, e.path) for e in errors] == [
            ("MT5_INVALID_EVENT_TYPE", "events[0].event[1]")
        ]

    def test_operand_item_gives_mt5_under_its_path(self) -> None:
        """A formula operand's list items are checked under the operand's path."""
        events: list[Any] = ["A", "B"]
        formula = Formula("A", metrics=[Metric(events)])
        events[0] = FunnelStep("A")
        errors = _args([], [formula])
        assert [(e.code, e.path) for e in errors] == [
            ("MT5_INVALID_EVENT_TYPE", "formula.metrics[0].event[0]")
        ]

    def test_event_of_another_type_gives_mt5(self) -> None:
        """A Metric whose event is no supported kind is refused.

        Construction refuses it first, so the test sets the field after
        construction to reach the query check.
        """
        metric = Metric("Login")
        object.__setattr__(metric, "event", FunnelStep("Login"))
        errors = _args([metric])
        assert [(e.code, e.path) for e in errors] == [
            ("MT5_INVALID_EVENT_TYPE", "events[0].event")
        ]

    def test_names_custom_events_and_behavior_steps_pass(self) -> None:
        """Names, custom events, and steps inside a SimpleBehavior pass."""
        behavior = SimpleBehavior([FunnelStep("a", filters=[Filter.equals("c", "US")])])
        assert _args([Metric(["Login", CustomEventRef(3)]), Metric(behavior)]) == []

    def test_build_params_refuses_a_step_put_in_the_list_later(
        self, ws: Workspace
    ) -> None:
        """``build_params`` raises instead of writing unfiltered entries."""
        events: list[Any] = ["Login", "Signup"]
        metric = Metric(events, filters=[Filter.equals("country", "US")])
        events[0] = FunnelStep("Login")
        with pytest.raises(BookmarkValidationError) as excinfo:
            ws.build_params(metric)
        assert [e.code for e in excinfo.value.errors] == ["MT5_INVALID_EVENT_TYPE"]


# =============================================================================
# Layer 2: validate_bookmark
# =============================================================================


class TestBookmarkWithNewKinds:
    """Layer 2 checks funnel and retention maths by behavior type."""

    def _bookmark(self, show: list[dict[str, Any]]) -> dict[str, Any]:
        """Wrap show clauses in a minimal insights bookmark."""
        return {"sections": {"show": show}, "displayOptions": {"chartType": "line"}}

    def test_funnel_and_retention_maths_pass_in_insights(self) -> None:
        """A funnel and a retention clause in insights have valid maths."""
        show = [
            build_funnel_metric_clause(FunnelMetric(FUNNEL)),
            build_retention_metric_clause(RetentionMetric(RETENTION)),
            build_metric_clause(Metric(["A", CustomEventRef(3)])),
        ]
        assert validate_bookmark(self._bookmark(show)) == []

    def test_bad_math_in_a_funnel_clause_is_refused(self) -> None:
        """A funnel clause with a non-funnel math gives B9."""
        clause = build_funnel_metric_clause(FunnelMetric(FUNNEL))
        clause["measurement"]["math"] = "dau"
        codes = _codes(validate_bookmark(self._bookmark([clause])))
        assert codes == ["B9_INVALID_MATH"]

    def test_formula_operands_are_validated(self) -> None:
        """Each ``referencedMetrics`` entry is checked as a show clause."""
        operand = build_metric_clause(Metric("A"))
        operand["measurement"]["math"] = "bogus"
        formula = {
            "type": "formula",
            "definition": "A",
            "measurement": {},
            "referencedMetrics": [operand],
        }
        errors = validate_bookmark(self._bookmark([formula]))
        assert _codes(errors) == ["B9_INVALID_MATH"]
        assert errors[0].path == (
            "sections.show[0].referencedMetrics[0].measurement.math"
        )


# =============================================================================
# Workspace.build_params
# =============================================================================


class TestBuildParamsWithNewKinds:
    """``build_params`` takes the new kinds wherever it takes a Metric."""

    def test_funnel_metric_alone(self, ws: Workspace) -> None:
        """A funnel metric alone writes its clause."""
        params = ws.build_params(FunnelMetric(FUNNEL))
        assert params["sections"]["show"] == [
            build_funnel_metric_clause(FunnelMetric(FUNNEL))
        ]

    def test_retention_metric_alone(self, ws: Workspace) -> None:
        """A retention metric alone writes its clause."""
        params = ws.build_params(RetentionMetric(RETENTION))
        assert params["sections"]["show"] == [
            build_retention_metric_clause(RetentionMetric(RETENTION))
        ]

    def test_metric_over_several_events(self, ws: Workspace) -> None:
        """A metric over a list writes a simple behavior."""
        params = ws.build_params(Metric(["Login", "Signup"], math="unique"))
        assert params["sections"]["show"][0]["behavior"]["type"] == "simple"

    def test_simple_behavior_of_filtered_steps(self, ws: Workspace) -> None:
        """Per-step filters in a SimpleBehavior reach each event entry."""
        us = Filter.equals("country", "US")
        behavior = SimpleBehavior(
            [
                FunnelStep("a", filters=[us]),
                FunnelStep("b", filters=[us], filters_combinator="any"),
            ]
        )
        us_entry = {
            "resourceType": "events",
            "filterType": "string",
            "defaultType": "string",
            "filterValue": ["US"],
            "filterOperator": "equals",
            "value": "country",
        }
        params = ws.build_params(Metric(behavior, math="unique"))
        assert params["sections"]["show"] == [
            {
                "type": "metric",
                "behavior": {
                    "type": "simple",
                    "name": "a or b",
                    "resourceType": "events",
                    "filtersDeterminer": "all",
                    "filters": [],
                    "behaviors": [
                        {
                            "type": "event",
                            "id": None,
                            "name": "a",
                            "filters": [us_entry],
                            "filtersDeterminer": "all",
                        },
                        {
                            "type": "event",
                            "id": None,
                            "name": "b",
                            "filters": [us_entry],
                            "filtersDeterminer": "any",
                        },
                    ],
                },
                "measurement": {"math": "unique"},
            }
        ]

    def test_operand_formula_alone(self, ws: Workspace) -> None:
        """A formula with operands can be the whole query."""
        formula = Formula("A / B", metrics=[Metric("A"), FunnelMetric(FUNNEL)])
        show = ws.build_params(formula)["sections"]["show"]
        assert [c["type"] for c in show] == ["formula"]
        assert len(show[0]["referencedMetrics"]) == 2

    def test_operand_formula_leaves_metrics_visible(self, ws: Workspace) -> None:
        """Metrics next to an operand formula are not hidden."""
        show = ws.build_params(["Login", Formula("A", metrics=[Metric("Signup")])])[
            "sections"
        ]["show"]
        assert "isHidden" not in show[0]

    def test_letter_formula_without_events_keeps_v0(self, ws: Workspace) -> None:
        """A formula without operands alone is still refused with V0."""
        with pytest.raises(BookmarkValidationError) as excinfo:
            ws.build_params(Formula("A / B"))
        assert excinfo.value.errors[0].code == "V0_NO_EVENTS"

    def test_letter_formula_bytes_are_unchanged(self, ws: Workspace) -> None:
        """A letter formula writes the clauses of every release."""
        params = ws.build_params(["A", "B"], formula="B / A", formula_label="R")
        assert params["sections"]["show"][2] == {
            "type": "formula",
            "definition": "B / A",
            "measurement": {},
            "referencedMetrics": [],
            "name": "R",
        }
        assert params["sections"]["show"][0]["isHidden"] is True


# =============================================================================
# query_funnel and query_retention: one event per step
# =============================================================================


class TestOneEventPerStep:
    """Funnel steps and retention events take one event, and say so."""

    def test_funnel_step_list_points_to_custom_events(self, ws: Workspace) -> None:
        """A list as a funnel step keeps F2 and names custom events."""
        with pytest.raises(BookmarkValidationError) as excinfo:
            ws.build_funnel_params(["A", ["B", "C"]])  # type: ignore[list-item]
        error = excinfo.value.errors[0]
        assert error.code == "F2_EMPTY_STEP_EVENT"
        assert "$custom_event:<id>" in error.message

    def test_funnel_step_simple_behavior_points_to_custom_events(
        self, ws: Workspace
    ) -> None:
        """A simple behavior as a funnel step is refused the same way."""
        with pytest.raises(BookmarkValidationError) as excinfo:
            ws.build_funnel_params(["A", SimpleBehavior(["B", "C"])])  # type: ignore[list-item]
        assert "$custom_event:<id>" in excinfo.value.errors[0].message

    @pytest.mark.parametrize(
        ("born", "back", "code"),
        [
            (["A", "B"], "C", "R1_EMPTY_BORN_EVENT"),
            ("A", SimpleBehavior(["B", "C"]), "R2_EMPTY_RETURN_EVENT"),
        ],
    )
    def test_retention_event_list_points_to_custom_events(
        self, ws: Workspace, born: object, back: object, code: str
    ) -> None:
        """A list or simple behavior as a retention event names custom events."""
        with pytest.raises(BookmarkValidationError) as excinfo:
            ws.build_retention_params(born, back)  # type: ignore[arg-type]
        error = excinfo.value.errors[0]
        assert error.code == code
        assert "$custom_event:<id>" in error.message
