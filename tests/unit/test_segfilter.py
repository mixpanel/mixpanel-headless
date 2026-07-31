"""Unit tests for Filter-to-segfilter conversion.

Tests the ``build_segfilter_entry`` function which converts ``Filter``
objects into the legacy segfilter dict format used by flows step filters.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from mixpanel_headless._internal.segfilter import (
    RESOURCE_TYPE_MAP,
    _convert_date_format,
    build_segfilter_entry,
)
from mixpanel_headless.types import (
    EqualityFilter,
    Filter,
    FilterFactory,
    NumericComparisonFilter,
    NumericRangeFilter,
    PresenceFilter,
)

_INVALID_OPERATOR = (ValueError, PydanticValidationError)

_ADAPTER: TypeAdapter[Any] = TypeAdapter(Filter)
"""Routes a raw payload to its union member — the dict/LLM entry point."""

# =============================================================================
# String Operators
# =============================================================================


class TestSegfilterStringOperators:
    """Conversion of string-typed Filter operators to segfilter format."""

    def test_equals(self) -> None:
        """FilterFactory.equals produces operator '==' with list operand."""
        f = FilterFactory.equals("country", "US")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "=="
        assert result["filter"]["operand"] == ["US"]

    def test_equals_multi_value(self) -> None:
        """FilterFactory.equals with a list produces operator '==' with list operand."""
        f = FilterFactory.equals("country", ["US", "UK"])
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "=="
        assert result["filter"]["operand"] == ["US", "UK"]

    def test_not_equals(self) -> None:
        """FilterFactory.not_equals produces operator '!=' with list operand."""
        f = FilterFactory.not_equals("country", "US")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "!="
        assert result["filter"]["operand"] == ["US"]

    def test_contains(self) -> None:
        """FilterFactory.contains produces operator 'in' with string operand."""
        f = FilterFactory.contains("name", "john")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "in"
        assert result["filter"]["operand"] == "john"

    def test_not_contains(self) -> None:
        """FilterFactory.not_contains produces operator 'not in' with string operand."""
        f = FilterFactory.not_contains("name", "john")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "not in"
        assert result["filter"]["operand"] == "john"

    def test_is_set(self) -> None:
        """FilterFactory.is_set produces operator 'set' with empty string operand."""
        f = FilterFactory.is_set("email")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "set"
        assert result["filter"]["operand"] == ""

    def test_is_not_set(self) -> None:
        """FilterFactory.is_not_set produces operator 'not set' with empty string operand."""
        f = FilterFactory.is_not_set("email")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "not set"
        assert result["filter"]["operand"] == ""


# =============================================================================
# Number Operators
# =============================================================================


class TestSegfilterNumberOperators:
    """Conversion of number-typed Filter operators to segfilter format."""

    def test_greater_than(self) -> None:
        """FilterFactory.greater_than produces operator '>' with stringified operand."""
        f = FilterFactory.greater_than("amount", 50)
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == ">"
        assert result["filter"]["operand"] == "50"

    def test_less_than(self) -> None:
        """FilterFactory.less_than produces operator '<' with stringified operand."""
        f = FilterFactory.less_than("amount", 50)
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "<"
        assert result["filter"]["operand"] == "50"

    def test_operand_stringified_int(self) -> None:
        """Numeric integer values are stringified in segfilter output."""
        f = FilterFactory.greater_than("count", 100)
        result = build_segfilter_entry(f)

        assert result["filter"]["operand"] == "100"
        assert isinstance(result["filter"]["operand"], str)

    def test_operand_stringified_float(self) -> None:
        """Numeric float values are stringified in segfilter output."""
        f = FilterFactory.greater_than("price", 9.99)
        result = build_segfilter_entry(f)

        assert result["filter"]["operand"] == "9.99"
        assert isinstance(result["filter"]["operand"], str)

    def test_between(self) -> None:
        """FilterFactory.between produces operator '><' with stringified list operand."""
        f = FilterFactory.between("amount", 10, 100)
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "><"
        assert result["filter"]["operand"] == ["10", "100"]

    def test_number_is_set(self) -> None:
        """Number is_set uses 'is set' operator with empty string operand.

        Note: FilterFactory.is_set always creates a string-typed filter, so this
        test constructs a number-typed filter directly to verify the number
        operator mapping handles is_set correctly.
        """
        f = PresenceFilter(
            property="score",
            operator="is set",
            value=None,
            property_type="number",
            resource_type="events",
        )
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "is set"
        assert result["filter"]["operand"] == ""

    def test_number_is_not_set(self) -> None:
        """Number is_not_set uses 'is not set' operator with empty string operand."""
        f = PresenceFilter(
            property="score",
            operator="is not set",
            value=None,
            property_type="number",
            resource_type="events",
        )
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "is not set"
        assert result["filter"]["operand"] == ""

    def test_equals_number(self) -> None:
        """Number 'equals' maps to '==' with stringified operand."""
        f = EqualityFilter(
            property="count",
            operator="equals",
            value=42,
            property_type="number",
            resource_type="events",
        )
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "=="
        assert result["filter"]["operand"] == "42"

    def test_is_equal_to_number_rejected(self) -> None:
        """'is equal to' is not a valid FilterOperator and is rejected."""
        with pytest.raises(_INVALID_OPERATOR):
            _ADAPTER.validate_python(
                {
                    "property": "count",
                    "operator": "is equal to",
                    "value": 42,
                    "property_type": "number",
                }
            )

    def test_not_equals_number(self) -> None:
        """Number 'does not equal' maps to '!=' with stringified operand."""
        f = EqualityFilter(
            property="count",
            operator="does not equal",
            value=7,
            property_type="number",
            resource_type="events",
        )
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "!="
        assert result["filter"]["operand"] == "7"

    def test_is_at_least(self) -> None:
        """Number 'is at least' maps to '>=' with stringified operand."""
        f = NumericComparisonFilter(
            property="count",
            operator="is at least",
            value=5,
            property_type="number",
            resource_type="events",
        )
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == ">="
        assert result["filter"]["operand"] == "5"

    def test_is_at_most(self) -> None:
        """Number 'is at most' maps to '<=' with stringified operand."""
        f = NumericComparisonFilter(
            property="count",
            operator="is at most",
            value=10,
            property_type="number",
            resource_type="events",
        )
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "<="
        assert result["filter"]["operand"] == "10"

    def test_not_between(self) -> None:
        """Number 'not between' maps to '!><' with stringified list operand."""
        f = NumericRangeFilter(
            property="amount",
            operator="not between",
            value=[10, 100],
            property_type="number",
            resource_type="events",
        )
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "!><"
        assert result["filter"]["operand"] == ["10", "100"]


# =============================================================================
# Boolean Operators
# =============================================================================


class TestSegfilterBooleanOperators:
    """Conversion of boolean-typed Filter operators to segfilter format."""

    def test_is_true(self) -> None:
        """FilterFactory.is_true produces operand 'true' with NO 'operator' key."""
        f = FilterFactory.is_true("verified")
        result = build_segfilter_entry(f)

        assert result["filter"]["operand"] == "true"
        assert "operator" not in result["filter"]

    def test_is_false(self) -> None:
        """FilterFactory.is_false produces operand 'false' with NO 'operator' key."""
        f = FilterFactory.is_false("verified")
        result = build_segfilter_entry(f)

        assert result["filter"]["operand"] == "false"
        assert "operator" not in result["filter"]


# =============================================================================
# Datetime Operators
# =============================================================================


class TestSegfilterDatetimeOperators:
    """Conversion of datetime-typed Filter operators to segfilter format."""

    def test_on(self) -> None:
        """FilterFactory.on produces operator '==' with MM/DD/YYYY operand."""
        f = FilterFactory.on("$time", "2026-01-15")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "=="
        assert result["filter"]["operand"] == "01/15/2026"

    def test_not_on(self) -> None:
        """FilterFactory.not_on produces operator '!=' with MM/DD/YYYY operand."""
        f = FilterFactory.not_on("$time", "2026-01-15")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "!="
        assert result["filter"]["operand"] == "01/15/2026"

    def test_before(self) -> None:
        """FilterFactory.before produces operator '>' with MM/DD/YYYY operand."""
        f = FilterFactory.before("$time", "2026-01-15")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == ">"
        assert result["filter"]["operand"] == "01/15/2026"

    def test_since(self) -> None:
        """FilterFactory.since produces operator '<' with MM/DD/YYYY operand."""
        f = FilterFactory.since("$time", "2026-01-15")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "<"
        assert result["filter"]["operand"] == "01/15/2026"

    def test_in_the_last(self) -> None:
        """FilterFactory.in_the_last produces operator '>' with quantity and unit."""
        f = FilterFactory.in_the_last("$time", 7, "day")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == ">"
        assert result["filter"]["operand"] == 7
        assert result["filter"]["unit"] == "days"

    def test_not_in_the_last(self) -> None:
        """FilterFactory.not_in_the_last produces operator '>' with quantity and unit."""
        f = FilterFactory.not_in_the_last("$time", 3, "week")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == ">"
        assert result["filter"]["operand"] == 3
        assert result["filter"]["unit"] == "weeks"

    def test_date_between(self) -> None:
        """FilterFactory.date_between produces operator '><' with MM/DD/YYYY list."""
        f = FilterFactory.date_between("$time", "2026-01-01", "2026-01-31")
        result = build_segfilter_entry(f)

        assert result["filter"]["operator"] == "><"
        assert result["filter"]["operand"] == ["01/01/2026", "01/31/2026"]

    def test_date_format_conversion(self) -> None:
        """YYYY-MM-DD dates are converted to MM/DD/YYYY in output."""
        f = FilterFactory.on("$time", "2026-03-05")
        result = build_segfilter_entry(f)

        assert result["filter"]["operand"] == "03/05/2026"

    def test_no_unit_for_absolute_dates(self) -> None:
        """Absolute date filters do NOT have a 'unit' key in filter dict."""
        f = FilterFactory.on("$time", "2026-01-15")
        result = build_segfilter_entry(f)

        assert "unit" not in result["filter"]

    def test_in_the_last_hour_unit(self) -> None:
        """Relative date with hour unit pluralizes to 'hours'."""
        f = FilterFactory.in_the_last("$time", 24, "hour")
        result = build_segfilter_entry(f)

        assert result["filter"]["unit"] == "hours"

    def test_in_the_last_month_unit(self) -> None:
        """Relative date with month unit pluralizes to 'months'."""
        f = FilterFactory.in_the_last("$time", 3, "month")
        result = build_segfilter_entry(f)

        assert result["filter"]["unit"] == "months"


# =============================================================================
# Resource Type Mapping
# =============================================================================


class TestSegfilterResourceTypeMapping:
    """Mapping of Filter.resource_type to segfilter property.source."""

    def test_events_maps_to_properties(self) -> None:
        """resource_type 'events' maps to property.source 'properties'."""
        f = FilterFactory.equals("country", "US", resource_type="events")
        result = build_segfilter_entry(f)

        assert result["property"]["source"] == "properties"

    def test_people_maps_to_user(self) -> None:
        """resource_type 'people' maps to property.source 'user'."""
        f = FilterFactory.equals("plan", "premium", resource_type="people")
        result = build_segfilter_entry(f)

        assert result["property"]["source"] == "user"

    def test_resource_type_map_constant(self) -> None:
        """RESOURCE_TYPE_MAP contains expected entries."""
        assert RESOURCE_TYPE_MAP["events"] == "properties"
        assert RESOURCE_TYPE_MAP["people"] == "user"


# =============================================================================
# Output Structure
# =============================================================================


class TestSegfilterStructure:
    """Structural validation of segfilter output dicts."""

    def test_top_level_keys(self) -> None:
        """Output dict has 'property', 'type', 'selected_property_type', 'filter'."""
        f = FilterFactory.equals("country", "US")
        result = build_segfilter_entry(f)

        assert "property" in result
        assert "type" in result
        assert "selected_property_type" in result
        assert "filter" in result

    def test_property_structure(self) -> None:
        """property dict contains 'name', 'source', 'type'."""
        f = FilterFactory.equals("country", "US")
        result = build_segfilter_entry(f)

        prop = result["property"]
        assert prop["name"] == "country"
        assert prop["source"] == "properties"
        assert prop["type"] == "string"

    def test_type_consistency(self) -> None:
        """type, selected_property_type, and property.type are all the same."""
        f = FilterFactory.greater_than("amount", 50)
        result = build_segfilter_entry(f)

        assert result["type"] == "number"
        assert result["selected_property_type"] == "number"
        assert result["property"]["type"] == "number"

    def test_boolean_type_consistency(self) -> None:
        """Boolean filters have 'boolean' in all type fields."""
        f = FilterFactory.is_true("verified")
        result = build_segfilter_entry(f)

        assert result["type"] == "boolean"
        assert result["selected_property_type"] == "boolean"
        assert result["property"]["type"] == "boolean"

    def test_datetime_type_consistency(self) -> None:
        """Datetime filters have 'datetime' in all type fields."""
        f = FilterFactory.on("$time", "2026-01-15")
        result = build_segfilter_entry(f)

        assert result["type"] == "datetime"
        assert result["selected_property_type"] == "datetime"
        assert result["property"]["type"] == "datetime"

    def test_property_name_preserved(self) -> None:
        """The property name from the Filter is used as-is."""
        f = FilterFactory.equals("$browser", "Chrome")
        result = build_segfilter_entry(f)

        assert result["property"]["name"] == "$browser"


# =============================================================================
# Helper Functions
# =============================================================================


class TestConvertDateFormat:
    """Tests for _convert_date_format helper."""

    def test_standard_conversion(self) -> None:
        """YYYY-MM-DD converts to MM/DD/YYYY."""
        assert _convert_date_format("2026-01-15") == "01/15/2026"

    def test_leading_zeros_preserved(self) -> None:
        """Month and day leading zeros are preserved."""
        assert _convert_date_format("2026-03-05") == "03/05/2026"

    def test_december(self) -> None:
        """December date converts correctly."""
        assert _convert_date_format("2025-12-31") == "12/31/2025"


# =============================================================================
# Edge Cases
# =============================================================================


class TestSegfilterEdgeCases:
    """Edge-case coverage for segfilter conversion."""

    def test_unknown_operator_raises(self) -> None:
        """Unknown string operator is rejected."""
        with pytest.raises(_INVALID_OPERATOR):
            _ADAPTER.validate_python(
                {"property": "x", "operator": "magical_unicorn", "value": "y"}
            )

    def test_unknown_number_operator_raises(self) -> None:
        """Unknown number operator is rejected."""
        with pytest.raises(_INVALID_OPERATOR):
            _ADAPTER.validate_python(
                {
                    "property": "x",
                    "operator": "magical_unicorn",
                    "value": 1,
                    "property_type": "number",
                }
            )

    def test_unknown_datetime_operator_raises(self) -> None:
        """Unknown datetime operator is rejected."""
        with pytest.raises(_INVALID_OPERATOR):
            _ADAPTER.validate_python(
                {
                    "property": "x",
                    "operator": "magical_unicorn",
                    "value": "2026-01-01",
                    "property_type": "datetime",
                }
            )

    def test_unknown_property_type_raises(self) -> None:
        """Unknown property type raises ValueError."""
        f = EqualityFilter(
            property="x",
            operator="equals",
            value="y",
            property_type="list",
            resource_type="events",
        )
        with pytest.raises(ValueError, match="Unsupported property type"):
            build_segfilter_entry(f)
