"""Unit tests for filter-to-selector translation (user_builders).

Tests for ``filter_to_selector()``, ``filters_to_selector()``, and
``extract_cohort_filter()`` which translate ``Filter`` objects to engage
API selector strings.

Task ID: T004
"""

from __future__ import annotations

import pytest

from mixpanel_headless._internal.query.user_builders import (
    extract_cohort_filter,
    filter_to_selector,
    filters_to_selector,
)
from mixpanel_headless._literal_types import FilterOperatorInput
from mixpanel_headless.exceptions import ParamValidationError
from mixpanel_headless.types import CohortCriteria, CohortDefinition, Filter
from tests.conftest import make_unchecked_filter

# =============================================================================
# filter_to_selector — individual operator mapping
# =============================================================================


class TestFilterToSelectorEquals:
    """Tests for equals operator translation."""

    def test_single_string_value(self) -> None:
        """Equals with a single string produces ``properties["p"] == "v"``."""
        f = Filter.equals("plan", "premium")
        result = filter_to_selector(f)
        assert result == 'properties["plan"] == "premium"'

    def test_multi_value_produces_or_chain(self) -> None:
        """Equals with multiple values produces OR-chained equality checks."""
        f = Filter.equals("country", ["US", "CA", "UK"])
        result = filter_to_selector(f)
        assert result == (
            '(properties["country"] == "US"'
            " or "
            'properties["country"] == "CA"'
            " or "
            'properties["country"] == "UK")'
        )

    def test_two_values_or(self) -> None:
        """Equals with exactly two values produces a single OR."""
        f = Filter.equals("status", ["active", "trial"])
        result = filter_to_selector(f)
        assert result == (
            '(properties["status"] == "active" or properties["status"] == "trial")'
        )

    def test_single_value_in_list(self) -> None:
        """Equals with a one-element list produces simple equality (no OR)."""
        f = Filter.equals("plan", ["premium"])
        result = filter_to_selector(f)
        assert result == 'properties["plan"] == "premium"'


class TestFilterToSelectorNotEquals:
    """Tests for does-not-equal operator translation."""

    def test_single_value(self) -> None:
        """Not-equals with a single value produces ``!=``."""
        f = Filter.not_equals("plan", "free")
        result = filter_to_selector(f)
        assert result == 'properties["plan"] != "free"'

    def test_multi_value(self) -> None:
        """Not-equals with multiple values produces AND-chained inequalities."""
        f = Filter.not_equals("status", ["banned", "deleted"])
        result = filter_to_selector(f)
        # Each value must not match -- AND semantics for not-equals
        assert 'properties["status"] != "banned"' in result
        assert 'properties["status"] != "deleted"' in result


class TestFilterToSelectorContains:
    """Tests for contains operator translation."""

    def test_contains_string(self) -> None:
        """Contains produces ``"v" in properties["p"]``."""
        f = Filter.contains("email", "gmail")
        result = filter_to_selector(f)
        assert result == '"gmail" in properties["email"]'


class TestFilterToSelectorNotContains:
    """Tests for does-not-contain operator translation."""

    def test_not_contains_string(self) -> None:
        """Not-contains produces ``not "v" in properties["p"]``."""
        f = Filter.not_contains("email", "spam")
        result = filter_to_selector(f)
        assert result == 'not "spam" in properties["email"]'


class TestFilterToSelectorGreaterThan:
    """Tests for greater-than operator translation."""

    def test_integer_value(self) -> None:
        """Greater-than with int produces ``properties["p"] > n``."""
        f = Filter.greater_than("age", 18)
        result = filter_to_selector(f)
        assert result == 'properties["age"] > 18'

    def test_float_value(self) -> None:
        """Greater-than with float produces ``properties["p"] > n.n``."""
        f = Filter.greater_than("score", 9.5)
        result = filter_to_selector(f)
        assert result == 'properties["score"] > 9.5'


class TestFilterToSelectorLessThan:
    """Tests for less-than operator translation."""

    def test_integer_value(self) -> None:
        """Less-than with int produces ``properties["p"] < n``."""
        f = Filter.less_than("age", 65)
        result = filter_to_selector(f)
        assert result == 'properties["age"] < 65'

    def test_float_value(self) -> None:
        """Less-than with float produces ``properties["p"] < n.n``."""
        f = Filter.less_than("price", 19.99)
        result = filter_to_selector(f)
        assert result == 'properties["price"] < 19.99'


class TestFilterToSelectorBetween:
    """Tests for between (inclusive range) operator translation."""

    def test_integer_range(self) -> None:
        """Between with ints produces ``>= a and <= b``."""
        f = Filter.between("age", 18, 65)
        result = filter_to_selector(f)
        assert result == 'properties["age"] >= 18 and properties["age"] <= 65'

    def test_float_range(self) -> None:
        """Between with floats produces ``>= a and <= b``."""
        f = Filter.between("score", 1.5, 9.5)
        result = filter_to_selector(f)
        assert result == 'properties["score"] >= 1.5 and properties["score"] <= 9.5'

    def test_mixed_int_float(self) -> None:
        """Between with mixed int/float values."""
        f = Filter.between("amount", 0, 99.99)
        result = filter_to_selector(f)
        assert result == 'properties["amount"] >= 0 and properties["amount"] <= 99.99'


class TestFilterToSelectorIsSet:
    """Tests for is-set (property existence) operator translation."""

    def test_is_set(self) -> None:
        """Is-set produces ``defined(properties["p"])``."""
        f = Filter.is_set("email")
        result = filter_to_selector(f)
        assert result == 'defined(properties["email"])'


class TestFilterToSelectorIsNotSet:
    """Tests for is-not-set (property non-existence) operator translation."""

    def test_is_not_set(self) -> None:
        """Is-not-set produces ``not defined(properties["p"])``."""
        f = Filter.is_not_set("phone")
        result = filter_to_selector(f)
        assert result == 'not defined(properties["phone"])'


class TestFilterToSelectorBooleans:
    """Tests for boolean (true/false) operator translation."""

    def test_is_true(self) -> None:
        """True operator produces ``properties["p"] == true`` (no quotes)."""
        f = Filter.is_true("verified")
        result = filter_to_selector(f)
        assert result == 'properties["verified"] == true'

    def test_is_false(self) -> None:
        """False operator produces ``properties["p"] == false`` (no quotes)."""
        f = Filter.is_false("opted_out")
        result = filter_to_selector(f)
        assert result == 'properties["opted_out"] == false'


class TestFilterToSelectorInclusiveNumbers:
    """Tests for at-least, at-most, and not-between number translation."""

    def test_at_least(self) -> None:
        """At-least produces an inclusive ``>=`` comparison."""
        f = Filter.at_least("score", 80, resource_type="people")
        assert filter_to_selector(f) == 'properties["score"] >= 80'

    def test_at_most(self) -> None:
        """At-most produces an inclusive ``<=`` comparison."""
        f = Filter.at_most("errors", 5.5, resource_type="people")
        assert filter_to_selector(f) == 'properties["errors"] <= 5.5'

    def test_not_between(self) -> None:
        """Not-between matches values outside the range, in parentheses."""
        f = Filter.not_between("age", 18, 65, resource_type="people")
        assert filter_to_selector(f) == (
            '(properties["age"] < 18 or properties["age"] > 65)'
        )

    def test_not_between_keeps_and_precedence(self) -> None:
        """The parenthesized OR stays one term when AND-combined with others."""
        result = filters_to_selector(
            [Filter.is_set("age"), Filter.not_between("age", 18, 65)]
        )
        assert result == (
            'defined(properties["age"]) and '
            '(properties["age"] < 18 or properties["age"] > 65)'
        )


#: The cast ``datetime()`` wrapper every date translation applies to the property.
_LAST_SEEN = 'datetime(properties["$last_seen"])'


class TestFilterToSelectorAbsoluteDates:
    """Tests for absolute date operators (project-time day boundaries)."""

    def test_since(self) -> None:
        """Since is inclusive of the start of the given day."""
        f = Filter.since("$last_seen", "2026-09-01", resource_type="people")
        assert filter_to_selector(f) == (
            f'{_LAST_SEEN} >= datetime("2026-09-01T00:00:00")'
        )

    def test_before(self) -> None:
        """Before excludes the given day."""
        f = Filter.before("$last_seen", "2026-09-01", resource_type="people")
        assert filter_to_selector(f) == (
            f'{_LAST_SEEN} < datetime("2026-09-01T00:00:00")'
        )

    def test_on(self) -> None:
        """On covers the whole day, from 00:00:00 to 23:59:59 inclusive."""
        f = Filter.on("$last_seen", "2026-09-01", resource_type="people")
        assert filter_to_selector(f) == (
            f'{_LAST_SEEN} >= datetime("2026-09-01T00:00:00") and '
            f'{_LAST_SEEN} <= datetime("2026-09-01T23:59:59")'
        )

    def test_not_on(self) -> None:
        """Not-on matches a set value outside the day, in parentheses."""
        f = Filter.not_on("$last_seen", "2026-09-01", resource_type="people")
        assert filter_to_selector(f) == (
            f'({_LAST_SEEN} < datetime("2026-09-01T00:00:00") or '
            f'{_LAST_SEEN} > datetime("2026-09-01T23:59:59"))'
        )

    def test_date_between(self) -> None:
        """Date-between includes both the first and the last day."""
        f = Filter.date_between(
            "$last_seen", "2026-09-01", "2026-09-30", resource_type="people"
        )
        assert filter_to_selector(f) == (
            f'{_LAST_SEEN} >= datetime("2026-09-01T00:00:00") and '
            f'{_LAST_SEEN} <= datetime("2026-09-30T23:59:59")'
        )

    def test_date_between_single_day_matches_on(self) -> None:
        """A one-day date-between range produces the same selector as on."""
        between = Filter.date_between("d", "2026-09-01", "2026-09-01")
        assert filter_to_selector(between) == filter_to_selector(
            Filter.on("d", "2026-09-01")
        )

    def test_date_not_between(self) -> None:
        """Date-not-between matches a set value outside the range."""
        f = Filter.date_not_between(
            "$last_seen", "2026-09-01", "2026-09-30", resource_type="people"
        )
        assert filter_to_selector(f) == (
            f'({_LAST_SEEN} < datetime("2026-09-01T00:00:00") or '
            f'{_LAST_SEEN} > datetime("2026-09-30T23:59:59"))'
        )

    def test_last_calendar_day_needs_no_next_day(self) -> None:
        """The last representable date translates without date arithmetic."""
        f = Filter.on("d", "9999-12-31")
        assert filter_to_selector(f).endswith('<= datetime("9999-12-31T23:59:59")')

    def test_property_name_is_escaped(self) -> None:
        """Quotes in the property name stay escaped inside the cast."""
        f = Filter.since('we"ird', "2026-09-01")
        assert filter_to_selector(f) == (
            'datetime(properties["we\\"ird"]) >= datetime("2026-09-01T00:00:00")'
        )


class TestFilterToSelectorRelativeDates:
    """Tests for relative date operators (server clock via the NOW macro)."""

    def test_in_the_last_days(self) -> None:
        """In-the-last spans N days back from the server's current time."""
        f = Filter.in_the_last("$last_seen", 7, "day", resource_type="people")
        assert filter_to_selector(f) == (
            f"{_LAST_SEEN} >= datetime(NOW - 604800) and {_LAST_SEEN} < datetime(NOW)"
        )

    def test_not_in_the_last_days(self) -> None:
        """Not-in-the-last matches a set value before the window or in the future."""
        f = Filter.not_in_the_last("$last_seen", 7, "day", resource_type="people")
        assert filter_to_selector(f) == (
            f"({_LAST_SEEN} < datetime(NOW - 604800) or {_LAST_SEEN} >= datetime(NOW))"
        )

    def test_in_the_next_days(self) -> None:
        """In-the-next spans N days forward from the server's current time."""
        f = Filter.in_the_next("renews_at", 7, "day", resource_type="people")
        assert filter_to_selector(f) == (
            'datetime(properties["renews_at"]) >= datetime(NOW) and '
            'datetime(properties["renews_at"]) < datetime(NOW + 604800)'
        )

    @pytest.mark.parametrize(
        ("quantity", "unit", "seconds"),
        [
            (24, "hour", 86400),
            (1, "day", 86400),
            (2, "week", 1209600),
            (1, "month", 2592000),
            (3, "month", 7776000),
        ],
    )
    def test_unit_seconds(self, quantity: int, unit: str, seconds: int) -> None:
        """Units convert to seconds with 7-day weeks and 30-day months."""
        f = Filter.in_the_last("d", quantity, unit)  # type: ignore[arg-type]
        assert f"datetime(NOW - {seconds})" in filter_to_selector(f)

    def test_now_macro_has_spaces_around_minus(self) -> None:
        """``NOW - n`` keeps its spaces: ``NOW -n`` is a syntax error server-side."""
        result = filter_to_selector(Filter.in_the_last("d", 1, "hour"))
        assert "NOW - 3600" in result
        assert "NOW -3600" not in result

    def test_fifty_year_window_is_allowed(self) -> None:
        """A window of exactly 50 years (18250 days) translates."""
        f = Filter.in_the_last("d", 18250, "day")
        assert "datetime(NOW - 1576800000)" in filter_to_selector(f)


# =============================================================================
# filter_to_selector — value formatting
# =============================================================================


class TestFilterToSelectorValueFormatting:
    """Tests for correct value formatting in selectors."""

    def test_string_value_quoted(self) -> None:
        """String values are wrapped in double quotes."""
        f = Filter.equals("city", "New York")
        result = filter_to_selector(f)
        assert result == 'properties["city"] == "New York"'

    def test_integer_value_unquoted(self) -> None:
        """Integer values appear without quotes."""
        f = Filter.greater_than("count", 100)
        result = filter_to_selector(f)
        assert "100" in result
        assert '"100"' not in result

    def test_float_value_unquoted(self) -> None:
        """Float values appear without quotes."""
        f = Filter.less_than("ratio", 0.5)
        result = filter_to_selector(f)
        assert "0.5" in result
        assert '"0.5"' not in result

    def test_boolean_true_unquoted(self) -> None:
        """Boolean true is lowercase and unquoted."""
        f = Filter.is_true("active")
        result = filter_to_selector(f)
        assert "true" in result
        assert '"true"' not in result

    def test_boolean_false_unquoted(self) -> None:
        """Boolean false is lowercase and unquoted."""
        f = Filter.is_false("disabled")
        result = filter_to_selector(f)
        assert "false" in result
        assert '"false"' not in result

    def test_zero_integer(self) -> None:
        """Zero integer is formatted correctly."""
        f = Filter.greater_than("balance", 0)
        result = filter_to_selector(f)
        assert result == 'properties["balance"] > 0'

    def test_negative_integer(self) -> None:
        """Negative integer is formatted correctly."""
        f = Filter.greater_than("offset", -10)
        result = filter_to_selector(f)
        assert result == 'properties["offset"] > -10'


# =============================================================================
# filter_to_selector — edge cases
# =============================================================================


class TestFilterToSelectorEdgeCases:
    """Tests for edge cases in filter-to-selector translation."""

    def test_property_name_with_dollar_prefix(self) -> None:
        """Dollar-prefixed properties (Mixpanel builtins) are handled."""
        f = Filter.equals("$city", "London")
        result = filter_to_selector(f)
        assert result == 'properties["$city"] == "London"'

    def test_property_name_with_spaces(self) -> None:
        """Property names containing spaces are handled."""
        f = Filter.equals("first name", "Alice")
        result = filter_to_selector(f)
        assert result == 'properties["first name"] == "Alice"'

    def test_value_with_double_quotes(self) -> None:
        """String values containing double quotes are escaped."""
        f = Filter.contains("description", 'say "hello"')
        result = filter_to_selector(f)
        # The value must be present in the selector without breaking syntax
        assert "say" in result
        assert "hello" in result

    def test_value_with_backslash(self) -> None:
        """String values containing backslashes are handled."""
        f = Filter.contains("path", "C:\\Users")
        result = filter_to_selector(f)
        assert "C:\\" in result or "C:\\\\Users" in result

    def test_empty_string_value(self) -> None:
        """Empty string value is represented as empty quoted string."""
        f = Filter.equals("tag", "")
        result = filter_to_selector(f)
        assert '""' in result


# =============================================================================
# filters_to_selector — AND combination
# =============================================================================


class TestFiltersToSelector:
    """Tests for combining multiple filters with AND."""

    def test_empty_list_returns_empty_string(self) -> None:
        """Empty filter list produces empty string."""
        result = filters_to_selector([])
        assert result == ""

    def test_single_filter(self) -> None:
        """Single filter produces its selector without AND."""
        result = filters_to_selector([Filter.equals("plan", "premium")])
        assert result == 'properties["plan"] == "premium"'

    def test_two_filters_and_combined(self) -> None:
        """Two filters are combined with `` and ``."""
        result = filters_to_selector(
            [
                Filter.equals("plan", "premium"),
                Filter.is_set("email"),
            ]
        )
        assert result == (
            'properties["plan"] == "premium" and defined(properties["email"])'
        )

    def test_three_filters_and_combined(self) -> None:
        """Three filters produce two AND operators."""
        result = filters_to_selector(
            [
                Filter.equals("plan", "premium"),
                Filter.greater_than("age", 18),
                Filter.is_set("email"),
            ]
        )
        assert " and " in result
        assert result.count(" and ") == 2
        assert 'properties["plan"] == "premium"' in result
        assert 'properties["age"] > 18' in result
        assert 'defined(properties["email"])' in result

    def test_preserves_filter_order(self) -> None:
        """Filters appear in the selector in the order they were provided."""
        result = filters_to_selector(
            [
                Filter.is_set("a"),
                Filter.is_set("b"),
                Filter.is_set("c"),
            ]
        )
        parts = result.split(" and ")
        assert parts[0] == 'defined(properties["a"])'
        assert parts[1] == 'defined(properties["b"])'
        assert parts[2] == 'defined(properties["c"])'

    def test_mixed_operator_types(self) -> None:
        """Different operator types combine correctly."""
        result = filters_to_selector(
            [
                Filter.equals("country", "US"),
                Filter.greater_than("age", 21),
                Filter.is_true("verified"),
                Filter.is_not_set("banned_at"),
            ]
        )
        parts = result.split(" and ")
        assert len(parts) == 4


# =============================================================================
# extract_cohort_filter
# =============================================================================


class TestExtractCohortFilter:
    """Tests for separating cohort filters from property filters."""

    def test_no_cohort_filter(self) -> None:
        """List without cohort filter returns all filters and None."""
        filters = [
            Filter.equals("plan", "premium"),
            Filter.is_set("email"),
        ]
        remaining, cohort = extract_cohort_filter(filters)
        assert len(remaining) == 2
        assert cohort is None

    def test_empty_list(self) -> None:
        """Empty list returns empty list and None."""
        remaining, cohort = extract_cohort_filter([])
        assert remaining == []
        assert cohort is None

    def test_only_cohort_filter(self) -> None:
        """List with only a cohort filter returns empty remaining and the filter."""
        filters = [Filter.in_cohort(123, "Power Users")]
        remaining, cohort = extract_cohort_filter(filters)
        assert remaining == []
        assert cohort is not None

    def test_cohort_filter_with_saved_id(self) -> None:
        """Cohort filter with saved ID is correctly extracted."""
        filters = [
            Filter.equals("plan", "premium"),
            Filter.in_cohort(456, "VIPs"),
            Filter.is_set("email"),
        ]
        remaining, cohort = extract_cohort_filter(filters)
        assert len(remaining) == 2
        assert cohort is not None
        # Remaining should not contain the cohort filter
        for f in remaining:
            assert f._property != "$cohorts"

    def test_cohort_filter_with_inline_definition(self) -> None:
        """Cohort filter with inline CohortDefinition is extracted."""
        cohort_def = CohortDefinition.all_of(
            CohortCriteria.did_event("Purchase", at_least=1, within_days=30),
        )
        filters = [
            Filter.equals("plan", "premium"),
            Filter.in_cohort(cohort_def, name="Buyers"),
        ]
        remaining, cohort = extract_cohort_filter(filters)
        assert len(remaining) == 1
        assert cohort is not None

    def test_not_in_cohort_extracted(self) -> None:
        """Not-in-cohort filter is also extracted as a cohort filter."""
        filters = [
            Filter.equals("plan", "free"),
            Filter.not_in_cohort(789, "Bots"),
        ]
        remaining, cohort = extract_cohort_filter(filters)
        assert len(remaining) == 1
        assert cohort is not None

    def test_remaining_filters_preserve_order(self) -> None:
        """Non-cohort filters maintain their original order."""
        f1 = Filter.equals("plan", "premium")
        f2 = Filter.greater_than("age", 18)
        f3 = Filter.is_set("email")
        filters = [f1, Filter.in_cohort(123), f2, f3]
        remaining, _ = extract_cohort_filter(filters)
        assert remaining == [f1, f2, f3]

    def test_cohort_filter_identity_preserved(self) -> None:
        """Extracted cohort filter is the same object from the input list."""
        cohort_filter = Filter.in_cohort(123, "Power Users")
        filters = [Filter.equals("plan", "free"), cohort_filter]
        _, cohort = extract_cohort_filter(filters)
        assert cohort is cohort_filter

    def test_original_list_not_mutated(self) -> None:
        """Input filter list is not modified by extraction."""
        filters = [
            Filter.equals("plan", "premium"),
            Filter.in_cohort(123),
            Filter.is_set("email"),
        ]
        original_len = len(filters)
        extract_cohort_filter(filters)
        assert len(filters) == original_len


# =============================================================================
# PR #118 review fixes — property escaping and between bounds
# =============================================================================


class TestFilterToSelectorPropertyEscaping:
    """Tests for property name escaping in selectors."""

    def test_property_with_double_quote(self) -> None:
        """Property name containing double quote is escaped."""
        f = Filter.equals('weird"prop', "val")
        result = filter_to_selector(f)
        assert result == 'properties["weird\\"prop"] == "val"'

    def test_property_with_backslash(self) -> None:
        """Property name containing backslash is escaped."""
        f = Filter.equals("back\\slash", "val")
        result = filter_to_selector(f)
        assert result == 'properties["back\\\\slash"] == "val"'


class TestFilterToSelectorBetweenBoundsValidation:
    """Tests for between operator bound type validation."""

    def test_string_lower_bound_rejected(self) -> None:
        """String lower bound raises ValueError."""
        f = Filter("prop", "is between", ["low", 10])  # type: ignore[arg-type]
        import pytest

        with pytest.raises(ValueError, match="int or float for lower bound"):
            filter_to_selector(f)

    def test_string_upper_bound_rejected(self) -> None:
        """String upper bound raises ValueError."""
        f = Filter("prop", "is between", [0, "high"])  # type: ignore[arg-type]
        import pytest

        with pytest.raises(ValueError, match="int or float for upper bound"):
            filter_to_selector(f)


class TestNotEqualsErrorMessage:
    """Tests for not_equals error message correctness."""

    def test_error_references_correct_method_name(self) -> None:
        """Error message references Filter.not_equals(), not does_not_equal()."""
        f = Filter("prop", "does not equal", [{"nested": True}])
        import pytest

        with pytest.raises(ValueError, match="Filter.not_equals"):
            filter_to_selector(f)


# =============================================================================
# Coded guard errors — ES* family (E2 coding pass, design §1.6)
# =============================================================================


class TestCodedEngageSelectorCodes:
    """Coded-guard tests for the engage-selector ES* family (design §1.6).

    Each converted raise site gets a direct ``filter_to_selector`` test and
    a seam test through the registered ``filters_to_selector`` entry point.
    Assertions are class + ``.code`` only — never message text (R5.4).
    """

    def test_es1_direct_raises_coded_error(self) -> None:
        """_prop_ref rejects a non-string property with ES1."""
        f = Filter(123, "is set", None)  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES1_PROPERTY_NOT_STRING"

    def test_es1_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES1 for non-string properties."""
        f = Filter(("tup",), "is set", None)  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES1_PROPERTY_NOT_STRING"

    def test_es2_direct_raises_coded_error(self) -> None:
        """Non-list value for 'equals' raises ES2."""
        f = Filter("p", "equals", "notalist")
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES2_EQUALS_EXPECTS_LIST"

    def test_es2_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES2 for non-list equals values."""
        f = Filter("p", "equals", 7)
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES2_EQUALS_EXPECTS_LIST"

    def test_es3_direct_raises_coded_error(self) -> None:
        """All-non-scalar equals values raise ES3."""
        f = Filter("p", "equals", [None])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES3_EQUALS_NO_TERMS"

    def test_es3_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES3 when no valid equals terms remain."""
        f = Filter("p", "equals", [[1, 2]])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES3_EQUALS_NO_TERMS"

    def test_es4_direct_raises_coded_error(self) -> None:
        """Non-list value for 'does not equal' raises ES4."""
        f = Filter("p", "does not equal", "notalist")
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES4_NOT_EQUALS_EXPECTS_LIST"

    def test_es4_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES4 for non-list not-equals values."""
        f = Filter("p", "does not equal", 3.5)
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES4_NOT_EQUALS_EXPECTS_LIST"

    def test_es5_direct_raises_coded_error(self) -> None:
        """All-non-scalar not-equals values raise ES5."""
        f = Filter("p", "does not equal", [None])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES5_NOT_EQUALS_NO_TERMS"

    def test_es5_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES5 when no valid not-equals terms remain."""
        f = Filter("p", "does not equal", [[1]])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES5_NOT_EQUALS_NO_TERMS"

    def test_es6_direct_raises_coded_error(self) -> None:
        """Non-str value for 'contains' raises ES6."""
        f = Filter("p", "contains", 5)
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES6_CONTAINS_EXPECTS_STR"

    def test_es6_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES6 for non-str contains values."""
        f = Filter("p", "contains", ["list"])
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES6_CONTAINS_EXPECTS_STR"

    def test_es7_direct_raises_coded_error(self) -> None:
        """Non-str value for 'does not contain' raises ES7."""
        f = Filter("p", "does not contain", 5)
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES7_NOT_CONTAINS_EXPECTS_STR"

    def test_es7_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES7 for non-str not-contains values."""
        f = Filter("p", "does not contain", 0.5)
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES7_NOT_CONTAINS_EXPECTS_STR"

    def test_es8_direct_raises_coded_error(self) -> None:
        """Non-number value for 'is greater than' raises ES8."""
        f = Filter("p", "is greater than", "x")
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES8_GT_EXPECTS_NUMBER"

    def test_es8_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES8 for non-number greater-than values."""
        f = Filter("p", "is greater than", [1])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES8_GT_EXPECTS_NUMBER"

    def test_es9_direct_raises_coded_error(self) -> None:
        """Non-number value for 'is less than' raises ES9."""
        f = Filter("p", "is less than", "x")
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES9_LT_EXPECTS_NUMBER"

    def test_es9_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES9 for non-number less-than values."""
        f = Filter("p", "is less than", None)
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES9_LT_EXPECTS_NUMBER"

    def test_es10_direct_raises_coded_error(self) -> None:
        """Wrong-length list for 'is between' raises ES10."""
        f = Filter("p", "is between", [1])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES10_BETWEEN_EXPECTS_PAIR"

    def test_es10_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES10 for non-list between values."""
        f = Filter("p", "is between", "nope")
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES10_BETWEEN_EXPECTS_PAIR"

    def test_es11_direct_raises_coded_error(self) -> None:
        """Non-number lower bound raises ES11."""
        f = Filter("p", "is between", ["low", 10])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES11_BETWEEN_LOWER_NOT_NUMBER"

    def test_es11_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES11 for non-number lower bounds."""
        f = Filter("p", "is between", [None, 10])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES11_BETWEEN_LOWER_NOT_NUMBER"

    def test_es12_direct_raises_coded_error(self) -> None:
        """Non-number upper bound raises ES12."""
        f = Filter("p", "is between", [0, "high"])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES12_BETWEEN_UPPER_NOT_NUMBER"

    def test_es12_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES12 for non-number upper bounds."""
        f = Filter("p", "is between", [0, None])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES12_BETWEEN_UPPER_NOT_NUMBER"

    def test_es13_direct_raises_coded_error(self) -> None:
        """Unsupported operator raises ES13."""
        f = make_unchecked_filter("p", "was frobnicated", None)
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES13_UNSUPPORTED_OPERATOR"

    def test_es13_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES13 for unsupported operators."""
        f = make_unchecked_filter("p", "is within", None)
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES13_UNSUPPORTED_OPERATOR"

    def test_es_guards_stay_catchable_as_value_error(self) -> None:
        """Converted ES* guards remain catchable via bare ValueError."""
        f = make_unchecked_filter("p", "was frobnicated", None)
        with pytest.raises(ValueError) as excinfo:
            filter_to_selector(f)
        assert isinstance(excinfo.value, ParamValidationError)
        assert excinfo.value.code == "ES13_UNSUPPORTED_OPERATOR"

    @pytest.mark.parametrize(
        "f",
        [
            Filter.starts_with("url", "https://", resource_type="people"),
            Filter.ends_with("email", "@example.com", resource_type="people"),
            Filter.list_contains("cart", Brand="nike", resource_type="people"),
        ],
        ids=["starts_with", "ends_with", "list_contains"],
    )
    def test_es14_direct_raises_coded_error(self, f: Filter) -> None:
        """Constructors with no Engage selector form raise ES14."""
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES14_NO_SELECTOR_EQUIVALENT"

    def test_es14_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES14 for a starts-with filter."""
        f = Filter.starts_with("url", "https://", resource_type="people")
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([Filter.is_set("url"), f])
        assert excinfo.value.code == "ES14_NO_SELECTOR_EQUIVALENT"

    @pytest.mark.parametrize("operator", ["since", "before", "on", "not_on"])
    def test_es15_direct_raises_coded_error(self, operator: str) -> None:
        """A non-string value for a single-date operator raises ES15."""
        f = Filter("d", operator, 20260901)  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES15_DATE_EXPECTS_STR"

    def test_es15_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES15 for a non-string date."""
        f = Filter("d", "was since", None)
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES15_DATE_EXPECTS_STR"

    @pytest.mark.parametrize(
        ("value", "code"),
        [
            ("09/01/2026", "V8_DATE_FORMAT"),
            ('2026-09-01") or true or ("', "V8_DATE_FORMAT"),
            ("2026-02-30", "V8_DATE_INVALID"),
        ],
    )
    def test_v8_twin_rejects_bad_date_string(self, value: str, code: str) -> None:
        """A malformed date string is rejected with the factory's V8 code."""
        f = Filter("d", "was on", value)
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == code

    @pytest.mark.parametrize(
        "value",
        ["2026-09-01", ["2026-09-01"], ["2026-09-01", 5], ("2026-09-01", "2026-09-02")],
        ids=["str", "one-item", "non-str-item", "tuple"],
    )
    def test_es16_direct_raises_coded_error(self, value: object) -> None:
        """A date range that is not a list of two strings raises ES16."""
        f = Filter("d", "was between", value)  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES16_DATE_RANGE_EXPECTS_PAIR"

    def test_es16_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES16 for a bad date-not-between range."""
        f = Filter("d", "was not between", None)
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES16_DATE_RANGE_EXPECTS_PAIR"

    def test_v8_twin_rejects_bad_range_bound(self) -> None:
        """A malformed bound in a date range raises the factory's V8 code."""
        f = Filter("d", "was between", ["2026-09-01", "2026-13-01"])
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "V8_DATE_INVALID"

    @pytest.mark.parametrize(
        "value",
        ["7", 0, -3, True, 7.0],
        ids=["str", "zero", "negative", "bool", "float"],
    )
    def test_es17_direct_raises_coded_error(self, value: object) -> None:
        """A relative quantity that is not a positive int raises ES17."""
        f = Filter("d", "was in the", value, _date_unit="day")  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES17_RELATIVE_QUANTITY_INVALID"

    @pytest.mark.parametrize(
        "f",
        [
            Filter.in_the_last("d", 18251, "day"),
            Filter.not_in_the_last("d", 609, "month"),
            Filter.in_the_next("d", 2608, "week"),
            Filter.in_the_last("d", 438001, "hour"),
        ],
        ids=["days", "months", "weeks", "hours"],
    )
    def test_es17_rejects_window_over_fifty_years(self, f: Filter) -> None:
        """A relative window longer than 50 years raises ES17."""
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES17_RELATIVE_QUANTITY_INVALID"

    def test_es17_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES17 for a bad in-the-next quantity."""
        f = Filter("d", "was in the next", None, _date_unit="day")
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES17_RELATIVE_QUANTITY_INVALID"

    @pytest.mark.parametrize("unit", [None, "year", "days"])
    def test_es18_direct_raises_coded_error(self, unit: object) -> None:
        """A missing or unknown relative date unit raises ES18."""
        f = Filter("d", "was in the", 7, _date_unit=unit)  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES18_RELATIVE_UNIT_INVALID"

    def test_es18_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES18 for a not-in-the-last filter."""
        f = Filter("d", "was not in the", 7)
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES18_RELATIVE_UNIT_INVALID"

    def test_es19_direct_raises_coded_error(self) -> None:
        """Non-number value for 'is at least' raises ES19."""
        f = Filter("p", "is at least", "x")
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES19_AT_LEAST_EXPECTS_NUMBER"

    def test_es19_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES19 for non-number at-least values."""
        f = Filter("p", "at_least", [1])  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES19_AT_LEAST_EXPECTS_NUMBER"

    def test_es20_direct_raises_coded_error(self) -> None:
        """Non-number value for 'is at most' raises ES20."""
        f = Filter("p", "is at most", None)
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "ES20_AT_MOST_EXPECTS_NUMBER"

    def test_es20_seam_raises_coded_error(self) -> None:
        """filters_to_selector surfaces ES20 for non-number at-most values."""
        f = Filter("p", "at_most", "5")
        with pytest.raises(ParamValidationError) as excinfo:
            filters_to_selector([f])
        assert excinfo.value.code == "ES20_AT_MOST_EXPECTS_NUMBER"

    @pytest.mark.parametrize(
        ("value", "code"),
        [
            ([1], "ES10_BETWEEN_EXPECTS_PAIR"),
            ("nope", "ES10_BETWEEN_EXPECTS_PAIR"),
            (["low", 10], "ES11_BETWEEN_LOWER_NOT_NUMBER"),
            ([0, None], "ES12_BETWEEN_UPPER_NOT_NUMBER"),
        ],
    )
    def test_not_between_reuses_between_codes(self, value: object, code: str) -> None:
        """Not-between shares the between shape rules and their codes."""
        f = Filter("p", "not between", value)  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == code

    @pytest.mark.parametrize(
        ("op", "value", "code"),
        [
            ("is greater than", True, "ES8_GT_EXPECTS_NUMBER"),
            ("is less than", False, "ES9_LT_EXPECTS_NUMBER"),
            ("is at least", True, "ES19_AT_LEAST_EXPECTS_NUMBER"),
            ("is at most", False, "ES20_AT_MOST_EXPECTS_NUMBER"),
            ("is between", [True, 10], "ES11_BETWEEN_LOWER_NOT_NUMBER"),
            ("not between", [0, False], "ES12_BETWEEN_UPPER_NOT_NUMBER"),
        ],
    )
    def test_number_operators_reject_bool(
        self, op: FilterOperatorInput, value: object, code: str
    ) -> None:
        """A bool is not a number bound, although bool subclasses int."""
        f = Filter("p", op, value)  # type: ignore[arg-type]
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == code

    @pytest.mark.parametrize("op", ["was between", "was not between"])
    def test_reversed_date_range_raises_factory_order_code(
        self, op: FilterOperatorInput
    ) -> None:
        """A direct date range with its days reversed raises FD2_DATE_ORDER.

        ``Filter.date_between()`` and ``Filter.date_not_between()`` reject a
        reversed range; a directly constructed Filter gets the same check.
        """
        f = Filter("d", op, ["2026-09-30", "2026-09-01"])
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        assert excinfo.value.code == "FD2_DATE_ORDER"

    def test_same_day_date_range_is_accepted(self) -> None:
        """A direct date range whose first and last day match is valid."""
        f = Filter("d", "was between", ["2026-09-01", "2026-09-01"])
        assert filter_to_selector(f) == (
            'datetime(properties["d"]) >= datetime("2026-09-01T00:00:00") '
            'and datetime(properties["d"]) <= datetime("2026-09-01T23:59:59")'
        )


class TestUnsupportedFilterMessages:
    """Unsupported constructors name the Filter method and give a workaround."""

    @pytest.mark.parametrize(
        ("f", "constructor"),
        [
            (Filter.starts_with("url", "https://"), "Filter.starts_with()"),
            (Filter.ends_with("email", "@example.com"), "Filter.ends_with()"),
            (Filter.list_contains("cart", Brand="nike"), "Filter.list_contains()"),
        ],
    )
    def test_message_names_constructor(self, f: Filter, constructor: str) -> None:
        """The ES14 message names the public constructor, not the wire operator."""
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(f)
        message = str(excinfo.value)
        assert message.startswith(constructor)
        assert "query_user(where=...)" in message

    def test_starts_with_suggests_contains_then_dataframe(self) -> None:
        """The starts-with message suggests contains plus a result.df check."""
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(Filter.starts_with("url", "https://"))
        message = str(excinfo.value)
        assert "Filter.contains('url', 'https://')" in message
        assert "result.df" in message

    def test_list_contains_suggests_contains_for_string_lists(self) -> None:
        """The list-contains message points at contains for a list of strings."""
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(Filter.list_contains("cart", Brand="nike"))
        assert "Filter.contains('cart', " in str(excinfo.value)

    def test_unknown_operator_shows_raw_selector_workaround(self) -> None:
        """The ES13 message shows a raw selector string as the way out."""
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(make_unchecked_filter("p", "was frobnicated", None))
        message = str(excinfo.value)
        assert "'was frobnicated'" in message
        assert 'where=\'properties["plan"] == "premium"\'' in message

    def test_relative_window_message_names_constructor(self) -> None:
        """The over-long window message names the constructor and the fix."""
        with pytest.raises(ParamValidationError) as excinfo:
            filter_to_selector(Filter.in_the_next("d", 609, "month"))
        message = str(excinfo.value)
        assert message.startswith("Filter.in_the_next()")
        assert "Filter.since()" in message
