"""Validator tests for saved-entity references in insights bookmarks.

Covers Layer 1 (``validate_query_args`` with ``MetricRef`` events), Layer 2
(``validate_bookmark`` with reference clauses and formula operands), and
the Pydantic mirror of the server's ``WarehouseShowClause``
(``analytics/lib/common/mxpnl/report/bookmarks/insights/show.py``).
"""

from __future__ import annotations

from typing import Any

import pytest

from mixpanel_headless._internal.bookmark_schema import (
    InsightsBookmarkParams,
    validate_with_pydantic,
)
from mixpanel_headless._internal.validation import (
    validate_bookmark,
    validate_query_args,
)
from mixpanel_headless.exceptions import ValidationError
from mixpanel_headless.types import (
    CustomPropertyRef,
    Filter,
    Formula,
    GroupBy,
    Metric,
    MetricRef,
)

# =============================================================================
# Helpers
# =============================================================================


def _query_args(**overrides: Any) -> dict[str, Any]:
    """Return valid keyword arguments for ``validate_query_args``.

    Args:
        **overrides: Keys to replace.

    Returns:
        The argument dict.
    """
    args: dict[str, Any] = {
        "events": [MetricRef(1)],
        "math": "total",
        "math_property": None,
        "per_user": None,
        "from_date": None,
        "to_date": None,
        "last": 30,
        "has_formula": False,
        "rolling": None,
        "cumulative": False,
        "group_by": None,
    }
    args.update(overrides)
    return args


def _bookmark(*show: dict[str, Any]) -> dict[str, Any]:
    """Return insights bookmark params with the given show clauses.

    Args:
        *show: The show clauses.

    Returns:
        A bookmark params dict with a valid time section.
    """
    return {
        "sections": {
            "show": list(show),
            "time": [{"dateRangeType": "in the last", "unit": "day"}],
            "filter": [],
            "group": [],
        },
        "displayOptions": {"chartType": "line"},
    }


def _codes(errors: list[ValidationError]) -> list[str]:
    """Return the codes of a validation error list.

    Args:
        errors: The errors.

    Returns:
        The codes, in order.
    """
    return [e.code for e in errors]


_EVENT_CLAUSE: dict[str, Any] = {
    "type": "metric",
    "behavior": {
        "type": "event",
        "name": "Login",
        "resourceType": "events",
        "filtersDeterminer": "all",
        "filters": [],
    },
    "measurement": {"math": "total"},
}

# =============================================================================
# Layer 1 — validate_query_args
# =============================================================================


class TestQueryArgsWithReferences:
    """validate_query_args accepts MetricRef events."""

    def test_reference_is_a_valid_event(self) -> None:
        """A MetricRef passes the event type guard and needs no event name."""
        assert validate_query_args(**_query_args()) == []

    def test_mixed_events(self) -> None:
        """References mix with names and Metric objects."""
        errors = validate_query_args(
            **_query_args(events=[MetricRef(1), "Login", Metric("Signup")])
        )
        assert errors == []

    def test_formula_letters_count_references(self) -> None:
        """Each reference takes a formula letter."""
        errors = validate_query_args(
            **_query_args(
                events=[MetricRef(1), MetricRef(2)],
                has_formula=True,
                formulas=[Formula("A / B")],
            )
        )
        assert errors == []

    def test_query_defaults_do_not_apply_to_references(self) -> None:
        """Property math at query level needs no property when no bare name exists."""
        errors = validate_query_args(**_query_args(math="average"))
        assert "V1_MATH_REQUIRES_PROPERTY" not in _codes(errors)

    def test_custom_property_override_is_checked(self) -> None:
        """A custom property override goes through the CP rules."""
        errors = validate_query_args(
            **_query_args(events=[MetricRef(1, property=CustomPropertyRef(0))])
        )
        assert _codes(errors) == ["CP1_INVALID_ID"]
        assert errors[0].path == "events[0]"


class TestQueryMeasurementIgnoredByReferences:
    """V29_QUERY_MEASUREMENT_IGNORED: no event uses a query-level measurement."""

    @pytest.mark.parametrize(
        ("argument", "value"),
        [
            ("math", "unique"),
            ("math_property", "amount"),
            ("per_user", "total"),
            ("percentile_value", 95),
        ],
    )
    def test_argument_with_only_references_is_refused(
        self, argument: str, value: object
    ) -> None:
        """A non-default query-level argument with only references is refused."""
        errors = validate_query_args(**_query_args(**{argument: value}))
        assert "V29_QUERY_MEASUREMENT_IGNORED" in _codes(errors)
        refused = [e for e in errors if e.code == "V29_QUERY_MEASUREMENT_IGNORED"]
        assert [e.path for e in refused] == [argument]
        assert "MetricRef" in refused[0].message

    def test_every_ignored_argument_is_named(self) -> None:
        """Each ignored argument gets its own error, in argument order."""
        errors = validate_query_args(
            **_query_args(math="average", math_property="amount", per_user="total")
        )
        refused = [e.path for e in errors if e.code == "V29_QUERY_MEASUREMENT_IGNORED"]
        assert refused == ["math", "math_property", "per_user"]

    def test_references_with_metrics_only_are_refused(self) -> None:
        """A Metric does not use the query-level math either."""
        errors = validate_query_args(
            **_query_args(events=[MetricRef(1), Metric("Login")], math="unique")
        )
        assert _codes(errors) == ["V29_QUERY_MEASUREMENT_IGNORED"]

    def test_bare_event_name_uses_the_argument(self) -> None:
        """With a bare event name the argument is used, so nothing is refused."""
        errors = validate_query_args(
            **_query_args(events=[MetricRef(1), "Login"], math="unique")
        )
        assert errors == []

    def test_default_arguments_pass(self) -> None:
        """The default query-level measurement is not a conflict."""
        assert validate_query_args(**_query_args()) == []

    def test_metrics_without_references_keep_todays_behavior(self) -> None:
        """Without a reference, a Metric still ignores the argument silently."""
        errors = validate_query_args(
            **_query_args(events=[Metric("Login")], math="unique")
        )
        assert errors == []


class TestWarehouseBreakdownWarning:
    """V28_WAREHOUSE_BREAKDOWN: a warehouse reference ignores group_by and where."""

    def test_group_by_warns(self) -> None:
        """A breakdown with a warehouse reference gives a warning, not an error."""
        errors = validate_query_args(
            **_query_args(events=[MetricRef(7, type="warehouse")], group_by="$os")
        )
        assert _codes(errors) == ["V28_WAREHOUSE_BREAKDOWN"]
        assert errors[0].severity == "warning"
        assert errors[0].path == "events[0]"
        assert "group_by" in errors[0].message

    def test_where_warns(self) -> None:
        """A filter with a warehouse reference gives a warning."""
        errors = validate_query_args(
            **_query_args(
                events=[MetricRef(7, type="warehouse")],
                where=Filter.equals("country", "US"),
            )
        )
        assert _codes(errors) == ["V28_WAREHOUSE_BREAKDOWN"]
        assert "where" in errors[0].message

    def test_one_warning_per_warehouse_reference(self) -> None:
        """Each warehouse reference gets its own warning."""
        errors = validate_query_args(
            **_query_args(
                events=[
                    MetricRef(7, type="warehouse"),
                    MetricRef(8),
                    MetricRef(9, type="warehouse"),
                ],
                group_by=[GroupBy("$os")],
            )
        )
        assert [e.path for e in errors] == ["events[0]", "events[2]"]

    @pytest.mark.parametrize("group_by", [None, []])
    def test_no_breakdown_no_warning(self, group_by: Any) -> None:
        """No breakdown and no filter give no warning."""
        errors = validate_query_args(
            **_query_args(
                events=[MetricRef(7, type="warehouse")], group_by=group_by, where=[]
            )
        )
        assert errors == []

    def test_behavior_metric_reference_does_not_warn(self) -> None:
        """A behavior-metric reference takes breakdowns normally."""
        errors = validate_query_args(**_query_args(group_by="$os"))
        assert errors == []


# =============================================================================
# Layer 2 — validate_bookmark
# =============================================================================


class TestReferenceShowClauses:
    """validate_bookmark accepts reference clauses with an id and no behavior."""

    @pytest.mark.parametrize(
        "clause",
        [
            {"type": "metric", "id": 42},
            {"type": "metric", "id": 42, "overrides": {"name": "x"}},
            {"type": "metric", "id": 42, "isHidden": True},
            {"type": "warehouse", "id": 7},
            {"type": "formula", "id": 9},
        ],
    )
    def test_accepted(self, clause: dict[str, Any]) -> None:
        """Each reference shape validates cleanly."""
        assert validate_bookmark(_bookmark(clause)) == []

    @pytest.mark.parametrize("bad_id", [0, -5, "42", True, 1.5])
    def test_bad_reference_id(self, bad_id: Any) -> None:
        """B27_INVALID_REFERENCE_ID: a reference id is a positive integer."""
        errors = validate_bookmark(_bookmark({"type": "metric", "id": bad_id}))
        assert _codes(errors) == ["B27_INVALID_REFERENCE_ID"]
        assert errors[0].path == "sections.show[0].id"

    def test_warehouse_needs_an_id(self) -> None:
        """B28_WAREHOUSE_MISSING_ID: the server runs a warehouse metric by id only."""
        errors = validate_bookmark(
            _bookmark(
                {"type": "warehouse", "query": "select 1", "metricType": "numeric"}
            )
        )
        assert _codes(errors) == ["B28_WAREHOUSE_MISSING_ID"]

    def test_no_id_and_no_behavior_is_still_refused(self) -> None:
        """A metric clause with neither an id nor a behavior keeps B6."""
        errors = validate_bookmark(_bookmark({"type": "metric"}))
        assert _codes(errors) == ["B6_MISSING_BEHAVIOR"]

    def test_inline_clause_with_id_is_checked_as_inline(self) -> None:
        """A clause with an id and a behavior is validated as an inline clause."""
        clause = {**_EVENT_CLAUSE, "id": 42, "measurement": {"math": "bogus"}}
        errors = validate_bookmark(_bookmark(clause))
        assert "B9_INVALID_MATH" in _codes(errors)


class TestFormulaOperands:
    """validate_bookmark checks each entry of a formula's referencedMetrics."""

    def _formula(self, *operands: Any) -> dict[str, Any]:
        """Return a formula clause with the given operands.

        Args:
            *operands: The referencedMetrics entries.

        Returns:
            The formula clause.
        """
        return {
            "type": "formula",
            "definition": "A / B",
            "measurement": {},
            "referencedMetrics": list(operands),
        }

    def test_reference_operands(self) -> None:
        """Operands that refer to saved metrics by id and type are accepted."""
        clause = self._formula(
            {"type": "metric", "id": 104700}, {"type": "metric", "id": 118228}
        )
        assert validate_bookmark(_bookmark(clause)) == []

    def test_inline_operand(self) -> None:
        """An inline operand is accepted when it is a valid metric clause."""
        assert validate_bookmark(_bookmark(self._formula(_EVENT_CLAUSE))) == []

    def test_operand_without_type(self) -> None:
        """B29_OPERAND_MISSING_TYPE: the server needs the type of an operand."""
        errors = validate_bookmark(_bookmark(self._formula({"id": 5})))
        assert _codes(errors) == ["B29_OPERAND_MISSING_TYPE"]
        assert errors[0].path == "sections.show[0].referencedMetrics[0]"

    @pytest.mark.parametrize("bad_id", [0, -3, "7", True])
    def test_saved_formula_reference_bad_id(self, bad_id: object) -> None:
        """A saved-formula reference clause gets the positive-id check too."""
        errors = validate_bookmark(_bookmark({"type": "formula", "id": bad_id}))
        assert _codes(errors) == ["B27_INVALID_REFERENCE_ID"]
        assert errors[0].path == "sections.show[0].id"

    def test_saved_formula_reference_good_id(self) -> None:
        """A saved-formula reference with a positive id passes."""
        assert validate_bookmark(_bookmark({"type": "formula", "id": 42})) == []

    def test_operand_bad_id(self) -> None:
        """An operand id is a positive integer."""
        errors = validate_bookmark(
            _bookmark(self._formula({"type": "metric", "id": 0}))
        )
        assert _codes(errors) == ["B27_INVALID_REFERENCE_ID"]
        assert errors[0].path == "sections.show[0].referencedMetrics[0].id"

    def test_inline_operand_errors_carry_the_operand_path(self) -> None:
        """Errors inside an inline operand name the operand path."""
        operand = {**_EVENT_CLAUSE, "measurement": {"math": "bogus"}}
        errors = validate_bookmark(_bookmark(self._formula(operand)))
        assert [e.path for e in errors if e.code == "B9_INVALID_MATH"] == [
            "sections.show[0].referencedMetrics[0].measurement.math"
        ]

    def test_operand_without_id_or_behavior(self) -> None:
        """An operand with neither an id nor a behavior is refused."""
        errors = validate_bookmark(_bookmark(self._formula({"type": "metric"})))
        assert _codes(errors) == ["B6_MISSING_BEHAVIOR"]
        assert errors[0].path == "sections.show[0].referencedMetrics[0]"

    def test_non_dict_operand(self) -> None:
        """An operand that is not a dict is refused."""
        errors = validate_bookmark(_bookmark(self._formula("A")))
        assert _codes(errors) == ["B6_MISSING_BEHAVIOR"]

    def test_empty_operand_list(self) -> None:
        """A formula with an empty operand list stays valid."""
        assert validate_bookmark(_bookmark(self._formula())) == []

    def test_legacy_formula_shape_is_untouched(self) -> None:
        """The legacy nested formula shape still validates."""
        clause = {"formula": {"definition": "(A/B)*100", "name": "Rate"}}
        assert validate_bookmark(_bookmark(_EVENT_CLAUSE, clause)) == []


# =============================================================================
# Pydantic mirror — WarehouseShowClause
# =============================================================================


class TestWarehouseShowClauseMirror:
    """The mirror routes type "warehouse" to WarehouseShowClause.

    Mirrors ``show.py`` ``WarehouseShowClause`` and its definition base. The
    server model requires ``query``, ``metricType``, and
    ``warehouseSourceId``; the web app stores a saved warehouse metric in a
    report as ``{id, type, overrides}`` and the server fills the rest from
    the saved metric, so the mirror requires them only without an id.
    """

    def _validate(self, clause: dict[str, Any]) -> list[ValidationError]:
        """Validate insights params that hold one show clause.

        Args:
            clause: The show clause.

        Returns:
            The translated validation errors.
        """
        return validate_with_pydantic(InsightsBookmarkParams, _bookmark(clause))

    @pytest.mark.parametrize(
        "clause",
        [
            {"type": "warehouse", "id": 7},
            {"type": "warehouse", "id": 7, "overrides": {"name": "ARR"}},
            {
                "type": "warehouse",
                "id": 7,
                "name": "ARR",
                "query": "select day, value from arr",
                "metricType": "timeseries",
                "warehouseSourceId": 3,
                "timeColumn": "day",
                "valueColumn": "value",
                "aggregation": "last_value",
                "syncInterval": "daily",
                "isHidden": False,
            },
            {
                "type": "warehouse",
                "query": "select 1",
                "metricType": "numeric",
                "warehouseSourceId": 3,
            },
        ],
    )
    def test_accepted(self, clause: dict[str, Any]) -> None:
        """References and full inline clauses validate."""
        assert self._validate(clause) == []

    def test_inline_without_id_needs_the_definition(self) -> None:
        """Without an id, query, metricType, and warehouseSourceId are required."""
        errors = self._validate({"type": "warehouse", "query": "select 1"})
        assert _codes(errors) == ["B0_VALIDATOR_ERROR"]
        assert errors[0].path == "sections.show[0]"
        assert "metricType" in errors[0].message
        assert "warehouseSourceId" in errors[0].message

    def test_unknown_key(self) -> None:
        """An unknown key is refused, as on the server."""
        errors = self._validate({"type": "warehouse", "id": 7, "behavior": {}})
        assert _codes(errors) == ["S3_UNKNOWN_FIELD"]
        assert errors[0].path == "sections.show[0].behavior"

    def test_bad_metric_type(self) -> None:
        """metricType is numeric or timeseries."""
        errors = self._validate({"type": "warehouse", "id": 7, "metricType": "table"})
        assert _codes(errors) == ["B0_INVALID_LITERAL"]
        assert errors[0].path == "sections.show[0].metricType"

    def test_operand_metric_id_is_tolerated(self) -> None:
        """A stored operand may carry the server's string metric_id.

        The server adds ``metric_id`` to saved formula operands in its
        responses, and clients send it back; its ``BehaviorShowClause``
        ignores the key.
        """
        clause = {
            "type": "formula",
            "definition": "A / B",
            "referencedMetrics": [
                {"type": "metric", "id": 5, "metric_id": "5"},
                {"type": "metric", "id": 6, "metric_id": "6"},
            ],
        }
        assert self._validate(clause) == []

    def test_metric_and_formula_references_pass(self) -> None:
        """Behavior-metric and formula references pass their own models."""
        assert self._validate({"type": "metric", "id": 42, "overrides": {}}) == []
        assert self._validate({"type": "formula", "id": 9}) == []
