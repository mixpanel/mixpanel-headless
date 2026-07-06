"""Unit tests for query argument validation rules.

Tests validation rules V7-V11 (time range) for US1,
V1-V3 (aggregation) for US2, V13-V14 (per-Metric) for US2,
V4 (formula) for US5, V5-V6 (analysis mode) for US6.

Also tests reusable validation functions (US2 shared-infra):
- ``validate_time_args()`` — V7-V10, V15, V20
- ``validate_group_by_args()`` — V11-V12, V18, V24

Validation is tested via Workspace.query() which raises
BookmarkValidationError on invalid arguments.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from mixpanel_headless import Workspace
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless._internal.validation import (
    validate_group_by_args,
    validate_query_args,
    validate_time_args,
)
from mixpanel_headless.exceptions import BookmarkValidationError
from mixpanel_headless.query_models import (
    FlowQuery,
    FunnelQuery,
    InsightsQuery,
    RetentionQuery,
)
from mixpanel_headless.types import Formula, GroupBy, Metric

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

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def ws(mock_config_manager: MagicMock) -> Workspace:
    """Create Workspace with mocked dependencies for validation testing."""
    return Workspace(session=_TEST_SESSION)


# =============================================================================
# T007: Time range validation rules (V7-V11)
# =============================================================================


class TestTimeRangeValidation:
    """Tests for time range validation rules V7-V11."""

    def test_v7_last_must_be_positive(self, ws: Workspace) -> None:
        """V7: last must be a positive integer."""
        with pytest.raises(BookmarkValidationError, match="greater than or equal to 1"):
            ws.query(InsightsQuery(events=[Metric("Login")], last=0))

    def test_v7_last_negative(self, ws: Workspace) -> None:
        """V7: negative last returns validation error."""
        with pytest.raises(BookmarkValidationError, match="greater than or equal to 1"):
            ws.query(InsightsQuery(events=[Metric("Login")], last=-5))

    def test_v8_from_date_format(self, ws: Workspace) -> None:
        """V8: malformed from_date is rejected at build time (a lone
        from_date is accepted at model construction)."""
        with pytest.raises(
            BookmarkValidationError, match="from_date must be YYYY-MM-DD format"
        ):
            ws.query(InsightsQuery(events=[Metric("Login")], from_date="01/01/2024"))

    def test_lone_from_date_builds_between_today(self, ws: Workspace) -> None:
        """from_date alone builds a 'between [from_date, today]' range."""
        from datetime import date

        params = ws.build_params(
            InsightsQuery(events=[Metric("Login")], from_date="2025-01-01")
        )
        time_entry = params["sections"]["time"][0]
        assert time_entry["dateRangeType"] == "between"
        assert time_entry["value"] == ["2025-01-01", date.today().isoformat()]

    def test_v8_to_date_format(self, ws: Workspace) -> None:
        """V8: to_date must also be YYYY-MM-DD format."""
        with pytest.raises(
            BookmarkValidationError, match="to_date must be YYYY-MM-DD format"
        ):
            ws.query(
                InsightsQuery(
                    events=[Metric("Login")],
                    from_date="2024-01-01",
                    to_date="Jan 31 2024",
                )
            )

    def test_v9_to_date_requires_from_date(self, ws: Workspace) -> None:
        """V9: to_date without from_date returns validation error."""
        with pytest.raises(BookmarkValidationError, match="to_date requires from_date"):
            ws.query(InsightsQuery(events=[Metric("Login")], to_date="2024-01-31"))

    def test_v10_last_with_explicit_dates(self, ws: Workspace) -> None:
        """V10: Cannot combine non-default last with explicit dates."""
        with pytest.raises(
            BookmarkValidationError, match="Cannot combine last=.*with explicit dates"
        ):
            ws.query(
                InsightsQuery(
                    events=[Metric("Login")],
                    last=7,
                    from_date="2024-01-01",
                    to_date="2024-01-31",
                )
            )

    def test_v10_default_last_with_dates_ok(self) -> None:
        """V10: Default last (30) with explicit dates is OK (last is ignored)."""
        errors = validate_query_args(
            events=["Login"],
            math="total",
            math_property=None,
            per_user=None,
            from_date="2024-01-01",
            to_date="2024-01-31",
            last=30,
            has_formula=False,
            rolling=None,
            cumulative=False,
            group_by=None,
        )
        assert errors == []

    def test_valid_date_range_passes(self) -> None:
        """Valid from_date/to_date passes validation."""
        errors = validate_query_args(
            events=["Login"],
            math="total",
            math_property=None,
            per_user=None,
            from_date="2024-01-01",
            to_date="2024-01-31",
            last=30,
            has_formula=False,
            rolling=None,
            cumulative=False,
            group_by=None,
        )
        assert errors == []

    def test_valid_last_passes(self) -> None:
        """Valid positive last passes validation."""
        errors = validate_query_args(
            events=["Login"],
            math="total",
            math_property=None,
            per_user=None,
            from_date=None,
            to_date=None,
            last=7,
            has_formula=False,
            rolling=None,
            cumulative=False,
            group_by=None,
        )
        assert errors == []


# =============================================================================
# T016: Aggregation validation rules V1-V3 (US2)
# =============================================================================


class TestAggregationValidation:
    """Tests for aggregation validation rules V1-V3."""

    def test_v1_property_math_requires_property(self, ws: Workspace) -> None:
        """V1: Property-based math requires property (caught at Metric construction)."""
        with pytest.raises(ValueError, match="requires a property"):
            InsightsQuery(events=[Metric("Purchase", math="average")])

    def test_v1_all_property_math_types(self, ws: Workspace) -> None:
        """V1: All property math types require property (caught at Metric construction)."""
        for math_type in (
            "average",
            "median",
            "min",
            "max",
            "p25",
            "p75",
            "p90",
            "p99",
        ):
            with pytest.raises(ValueError, match="requires a property"):
                InsightsQuery(events=[Metric("Purchase", math=math_type)])

    def test_v2_non_property_math_rejects_property(self, ws: Workspace) -> None:
        """V2: Non-property math Metric with property returns validation error."""
        with pytest.raises(BookmarkValidationError, match="property is only valid"):
            ws.query(
                InsightsQuery(
                    events=[Metric("Login", math="unique", property="amount")]
                )
            )

    def test_v2_unique_rejects_property(self, ws: Workspace) -> None:
        """V2: 'unique' math Metric rejects property."""
        with pytest.raises(BookmarkValidationError, match="property is only valid"):
            ws.query(
                InsightsQuery(
                    events=[Metric("Login", math="unique", property="amount")]
                )
            )

    def test_v3_per_user_incompatible_with_dau(self, ws: Workspace) -> None:
        """V3: per_user is incompatible with DAU."""
        with pytest.raises(BookmarkValidationError, match="per_user is incompatible"):
            ws.query(
                InsightsQuery(events=[Metric("Login", math="dau", per_user="average")])
            )

    def test_v3_per_user_incompatible_with_wau(self, ws: Workspace) -> None:
        """V3: per_user is incompatible with WAU."""
        with pytest.raises(BookmarkValidationError, match="per_user is incompatible"):
            ws.query(
                InsightsQuery(events=[Metric("Login", math="wau", per_user="total")])
            )

    def test_v3_per_user_incompatible_with_mau(self, ws: Workspace) -> None:
        """V3: per_user is incompatible with MAU."""
        with pytest.raises(BookmarkValidationError, match="per_user is incompatible"):
            ws.query(
                InsightsQuery(events=[Metric("Login", math="mau", per_user="min")])
            )

    def test_valid_property_math_with_property(self) -> None:
        """Valid property math with math_property passes validation."""
        errors = validate_query_args(
            events=["Purchase"],
            math="average",
            math_property="amount",
            per_user=None,
            from_date=None,
            to_date=None,
            last=30,
            has_formula=False,
            rolling=None,
            cumulative=False,
            group_by=None,
        )
        assert errors == []

    def test_valid_per_user_with_property(self) -> None:
        """Valid per_user with property math passes validation."""
        errors = validate_query_args(
            events=["Purchase"],
            math="total",
            math_property="revenue",
            per_user="average",
            from_date=None,
            to_date=None,
            last=30,
            has_formula=False,
            rolling=None,
            cumulative=False,
            group_by=None,
        )
        assert errors == []

    def test_per_user_without_property_raises(self) -> None:
        """per_user without math_property returns validation error."""
        errors = validate_query_args(
            events=["Purchase"],
            math="total",
            math_property=None,
            per_user="average",
            from_date=None,
            to_date=None,
            last=30,
            has_formula=False,
            rolling=None,
            cumulative=False,
            group_by=None,
        )
        assert any("per_user requires math_property" in e.message for e in errors)

    def test_per_user_with_unique_raises(self) -> None:
        """per_user with math='unique' returns validation error."""
        errors = validate_query_args(
            events=["Login"],
            math="unique",
            math_property=None,
            per_user="average",
            from_date=None,
            to_date=None,
            last=30,
            has_formula=False,
            rolling=None,
            cumulative=False,
            group_by=None,
        )
        assert any("per_user is incompatible" in e.message for e in errors)


# =============================================================================
# T018: Per-Metric validation V13-V14 (US2)
# =============================================================================


class TestPerMetricValidation:
    """Tests for per-Metric validation rules V13-V14."""

    def test_v13_metric_property_math_requires_property(self) -> None:
        """V13: Metric with property math requires property (caught at construction)."""
        from mixpanel_headless import Metric

        with pytest.raises(ValueError, match="requires a property"):
            Metric("Purchase", math="average")

    def test_v14_metric_non_property_math_rejects_property(self, ws: Workspace) -> None:
        """V14: Metric with non-property math rejects property."""
        with pytest.raises(BookmarkValidationError, match="property is only valid"):
            ws.query(
                InsightsQuery(
                    events=[Metric("Login", math="unique", property="amount")]
                )
            )

    def test_v14_metric_total_with_property_allowed(self, ws: Workspace) -> None:
        """V14: Metric with math='total' + property is allowed (sum semantics)."""
        from unittest.mock import MagicMock

        mock_api_client = MagicMock()
        mock_api_client.insights_query.return_value = {
            "computed_at": "",
            "date_range": {"from_date": "", "to_date": ""},
            "headers": [],
            "series": {},
            "meta": {},
        }
        ws._api_client = mock_api_client

        # Should pass validation and reach the API
        ws.query(
            InsightsQuery(events=[Metric("Purchase", math="total", property="amount")])
        )
        mock_api_client.insights_query.assert_called_once()

    def test_metric_per_user_with_dau(self, ws: Workspace) -> None:
        """Per-Metric per_user incompatible with DAU."""
        with pytest.raises(BookmarkValidationError, match="per_user is incompatible"):
            ws.query(
                InsightsQuery(events=[Metric("Login", math="dau", per_user="average")])
            )

    def test_metric_per_user_requires_property(self, ws: Workspace) -> None:
        """Per-Metric per_user requires property to be set."""
        with pytest.raises(BookmarkValidationError, match="per_user requires property"):
            ws.query(
                InsightsQuery(
                    events=[Metric("Login", math="total", per_user="average")]
                )
            )


# =============================================================================
# T035: Formula validation V4 (US5)
# =============================================================================


class TestFormulaValidation:
    """Tests for formula validation rule V4."""

    def test_v4_formula_requires_two_events(self, ws: Workspace) -> None:
        """V4: Formula requires at least 2 events."""
        with pytest.raises(
            BookmarkValidationError, match="formula requires at least 2 events"
        ):
            ws.query(InsightsQuery(events=[Metric("Login")], formula="A * 100"))

    def test_v4_formula_with_two_events_ok(self) -> None:
        """V4: Formula with 2 events passes validation."""
        errors = validate_query_args(
            events=["Login", "Signup"],
            math="total",
            math_property=None,
            per_user=None,
            from_date=None,
            to_date=None,
            last=30,
            has_formula=True,
            rolling=None,
            cumulative=False,
            group_by=None,
        )
        assert errors == []


# =============================================================================
# T040: Analysis mode validation V5-V6 (US6)
# =============================================================================


class TestAnalysisModeValidation:
    """Tests for analysis mode validation rules V5-V6."""

    def test_v5_rolling_and_cumulative_exclusive(self, ws: Workspace) -> None:
        """V5: Rolling and cumulative are mutually exclusive."""
        with pytest.raises(BookmarkValidationError, match="mutually exclusive"):
            ws.query(
                InsightsQuery(events=[Metric("Login")], rolling=7, cumulative=True)
            )

    def test_v6_rolling_must_be_positive(self, ws: Workspace) -> None:
        """V6: Rolling must be a positive integer."""
        with pytest.raises(BookmarkValidationError, match="greater than 0"):
            ws.query(InsightsQuery(events=[Metric("Login")], rolling=0))

    def test_v6_rolling_negative(self, ws: Workspace) -> None:
        """V6: Negative rolling returns validation error."""
        with pytest.raises(BookmarkValidationError, match="greater than 0"):
            ws.query(InsightsQuery(events=[Metric("Login")], rolling=-3))


# =============================================================================
# GroupBy validation V11-V12 (US3)
# =============================================================================


class TestGroupByValidation:
    """Tests for GroupBy validation rules V11-V12."""

    def test_v11_bucket_min_requires_bucket_size(self, ws: Workspace) -> None:
        """V11: bucket_min requires bucket_size."""
        with pytest.raises(
            BookmarkValidationError, match="bucket_min/bucket_max require bucket_size"
        ):
            ws.query(
                InsightsQuery(
                    events=[Metric("Purchase")],
                    group_by=[GroupBy("amount", bucket_min=0)],
                )
            )

    def test_v11_bucket_max_requires_bucket_size(self, ws: Workspace) -> None:
        """V11: bucket_max requires bucket_size."""
        with pytest.raises(
            BookmarkValidationError, match="bucket_min/bucket_max require bucket_size"
        ):
            ws.query(
                InsightsQuery(
                    events=[Metric("Purchase")],
                    group_by=[GroupBy("amount", bucket_max=100)],
                )
            )

    def test_v12_bucket_size_must_be_positive(self) -> None:
        """V12: bucket_size must be positive (caught at construction)."""
        from mixpanel_headless import GroupBy

        with pytest.raises(ValueError, match="greater than 0"):
            GroupBy("amount", bucket_size=0)

    def test_v12_bucket_size_negative(self) -> None:
        """V12: Negative bucket_size is caught at construction."""
        from mixpanel_headless import GroupBy

        with pytest.raises(ValueError, match="greater than 0"):
            GroupBy("amount", bucket_size=-10)

    def test_bucket_size_requires_numeric_type(self, ws: Workspace) -> None:
        """bucket_size with default string property_type returns validation error."""
        with pytest.raises(
            BookmarkValidationError, match="bucket_size requires property_type='number'"
        ):
            ws.query(
                InsightsQuery(
                    events=[Metric("Purchase")],
                    group_by=[GroupBy("amount", bucket_size=10)],
                )
            )

    def test_bucket_size_with_numeric_type_ok(self, ws: Workspace) -> None:
        """bucket_size with property_type='number' passes validation."""
        from unittest.mock import MagicMock

        mock_api_client = MagicMock()
        mock_api_client.insights_query.return_value = {
            "computed_at": "",
            "date_range": {"from_date": "", "to_date": ""},
            "headers": [],
            "series": {},
            "meta": {},
        }
        ws._api_client = mock_api_client

        # Should not raise BookmarkValidationError — validation passes
        ws.query(
            InsightsQuery(
                events=[Metric("Purchase")],
                group_by=[
                    GroupBy(
                        "amount",
                        property_type="number",
                        bucket_size=10,
                        bucket_min=0,
                        bucket_max=100,
                    )
                ],
            )
        )
        mock_api_client.insights_query.assert_called_once()

    def test_bucket_size_requires_min_max(self, ws: Workspace) -> None:
        """bucket_size without bucket_min/bucket_max returns validation error."""
        with pytest.raises(BookmarkValidationError, match="bucket_size requires both"):
            ws.query(
                InsightsQuery(
                    events=[Metric("Purchase")],
                    group_by=[
                        GroupBy("amount", property_type="number", bucket_size=10)
                    ],
                )
            )


# =============================================================================
# V0: Empty events validation
# =============================================================================


class TestEmptyEventsValidation:
    """Tests for empty events list validation (V0)."""

    def test_v0_empty_list_raises(self, ws: Workspace) -> None:
        """V0: Empty events list returns BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError, match="at least 1 item"):
            InsightsQuery(events=[])

    def test_v0_non_empty_list_passes(self, ws: Workspace) -> None:
        """V0: Non-empty events list passes validation (may fail at API)."""
        # This should pass validation but may fail at API call
        # since we don't have a mock API client here.
        # We only test that validation doesn't raise.
        try:
            ws.query(InsightsQuery(events=[Metric("Login")]))
        except Exception as e:
            # Any error other than BookmarkValidationError about empty events is acceptable
            assert "At least one event is required" not in str(e)


# =============================================================================
# Formula-in-list validation
# =============================================================================


class TestFormulaInListValidation:
    """Tests for Formula objects in the events list."""

    def test_formula_alone_raises(self, ws: Workspace) -> None:
        """A Formula as the sole argument returns validation error."""
        with pytest.raises(
            BookmarkValidationError, match="At least one event is required"
        ):
            ws.query(InsightsQuery(events=[Formula("A * 100")]))

    def test_formula_with_top_level_raises(self, ws: Workspace) -> None:
        """Mixing Formula in list with top-level formula returns validation error."""
        with pytest.raises(BookmarkValidationError, match="Cannot combine top-level"):
            ws.query(
                InsightsQuery(
                    events=[Metric("A"), Metric("B"), Formula("A + B")],
                    formula="A - B",
                )
            )

    def test_formula_in_list_requires_two_events(self, ws: Workspace) -> None:
        """Formula in list with only 1 event triggers V4."""
        with pytest.raises(
            BookmarkValidationError, match="formula requires at least 2 events"
        ):
            ws.query(InsightsQuery(events=[Metric("Login"), Formula("A * 100")]))


# =============================================================================
# T054c: build_params() validation parity
# =============================================================================


class TestBuildParamsValidation:
    """T054c: build_params() runs the same validation as query()."""

    def test_rejects_invalid_last(self, ws: Workspace) -> None:
        """build_params() raises BookmarkValidationError for last=0."""
        with pytest.raises(BookmarkValidationError, match="greater than or equal to 1"):
            ws.build_params(InsightsQuery(events=[Metric("Login")], last=0))

    def test_rejects_formula_without_events(self, ws: Workspace) -> None:
        """build_params() validates formula requires 2+ events."""
        with pytest.raises(
            BookmarkValidationError, match="formula requires at least 2 events"
        ):
            ws.build_params(InsightsQuery(events=[Metric("Login")], formula="A + B"))

    def test_rejects_invalid_date_format(self, ws: Workspace) -> None:
        """build_params() rejects a malformed lone from_date via V8."""
        with pytest.raises(
            BookmarkValidationError, match="from_date must be YYYY-MM-DD format"
        ):
            ws.build_params(
                InsightsQuery(events=[Metric("Login")], from_date="01/01/2024")
            )


# =============================================================================
# T064: Percentile validation (V1 inherited + new V26)
# =============================================================================


class TestPercentileValidation:
    """T064: Percentile validation rules."""

    def test_v1_percentile_requires_math_property(self, ws: Workspace) -> None:
        """V1: math='percentile' requires property (caught at Metric construction)."""
        with pytest.raises(ValueError, match="requires a property"):
            InsightsQuery(
                events=[Metric("Login", math="percentile", percentile_value=95)]
            )

    def test_v26_percentile_requires_percentile_value(self, ws: Workspace) -> None:
        """V26: math='percentile' requires percentile_value (caught at Metric construction)."""
        with pytest.raises(ValueError, match="percentile_value"):
            InsightsQuery(
                events=[Metric("Login", math="percentile", property="duration")]
            )

    def test_v26_metric_percentile_requires_value(self) -> None:
        """V26: Metric with math='percentile' requires percentile_value (caught at construction)."""
        with pytest.raises(ValueError, match="percentile_value"):
            Metric("Login", math="percentile", property="duration")

    def test_valid_percentile_passes(self, ws: Workspace) -> None:
        """Percentile with property and value passes validation."""
        result = ws.build_params(
            InsightsQuery(
                events=[
                    Metric(
                        "Login",
                        math="percentile",
                        property="duration",
                        percentile_value=95,
                    )
                ],
            )
        )
        assert isinstance(result, dict)


# =============================================================================
# T068: Histogram validation
# =============================================================================


class TestHistogramValidation:
    """T068: Histogram validation."""

    def test_v1_histogram_requires_property(self, ws: Workspace) -> None:
        """V1: math='histogram' requires property (caught at Metric construction)."""
        with pytest.raises(ValueError, match="requires a property"):
            InsightsQuery(events=[Metric("Login", math="histogram")])

    def test_v27_histogram_requires_per_user(self, ws: Workspace) -> None:
        """V27: math='histogram' requires per_user."""
        with pytest.raises(BookmarkValidationError, match="requires per_user"):
            ws.build_params(
                InsightsQuery(
                    events=[Metric("Purchase", math="histogram", property="amount")]
                )
            )

    def test_v27_metric_histogram_requires_per_user(self, ws: Workspace) -> None:
        """V27: Metric(math='histogram') requires per_user."""
        with pytest.raises(BookmarkValidationError, match="requires per_user"):
            ws.build_params(
                InsightsQuery(
                    events=[Metric("Purchase", math="histogram", property="amount")]
                )
            )

    def test_histogram_with_property_and_per_user_passes(self, ws: Workspace) -> None:
        """Histogram with property and per_user passes validation."""
        result = ws.build_params(
            InsightsQuery(
                events=[
                    Metric(
                        "Purchase",
                        math="histogram",
                        property="amount",
                        per_user="total",
                    )
                ],
            )
        )
        assert isinstance(result, dict)


# =============================================================================
# Reusable validate_time_args() (US2 shared-infra)
# =============================================================================


class TestValidateTimeArgs:
    """Tests for the reusable validate_time_args() function.

    Calls validate_time_args() directly (not through Workspace)
    to verify time-related validation rules V7-V10, V15, V20.
    """

    def test_v7_last_zero(self) -> None:
        """V7: last=0 returns error with code V7_LAST_POSITIVE."""
        errors = validate_time_args(from_date=None, to_date=None, last=0)
        assert len(errors) == 1
        assert errors[0].code == "V7_LAST_POSITIVE"

    def test_v7_last_negative(self) -> None:
        """V7: last=-5 returns error with code V7_LAST_POSITIVE."""
        errors = validate_time_args(from_date=None, to_date=None, last=-5)
        assert len(errors) == 1
        assert errors[0].code == "V7_LAST_POSITIVE"

    def test_v8_from_date_bad_format(self) -> None:
        """V8: from_date='01/01/2024' returns error with code V8_DATE_FORMAT."""
        errors = validate_time_args(from_date="01/01/2024", to_date=None, last=30)
        assert any(e.code == "V8_DATE_FORMAT" for e in errors)

    def test_v8_to_date_bad_format(self) -> None:
        """V8: to_date='Jan 31 2024' returns error with code V8_DATE_FORMAT."""
        errors = validate_time_args(
            from_date="2024-01-01", to_date="Jan 31 2024", last=30
        )
        assert any(e.code == "V8_DATE_FORMAT" for e in errors)

    def test_v8_invalid_calendar_date(self) -> None:
        """V8: from_date='2024-02-30' returns error with code V8_DATE_INVALID."""
        errors = validate_time_args(from_date="2024-02-30", to_date=None, last=30)
        assert any(e.code == "V8_DATE_INVALID" for e in errors)

    def test_v9_to_date_without_from_date(self) -> None:
        """V9: to_date without from_date returns error with code V9_TO_REQUIRES_FROM."""
        errors = validate_time_args(from_date=None, to_date="2024-01-31", last=30)
        assert any(e.code == "V9_TO_REQUIRES_FROM" for e in errors)

    def test_v10_from_date_with_non_default_last(self) -> None:
        """V10: from_date + last=7 (non-default) returns error V10_DATE_LAST_EXCLUSIVE."""
        errors = validate_time_args(
            from_date="2024-01-01", to_date="2024-01-31", last=7
        )
        assert any(e.code == "V10_DATE_LAST_EXCLUSIVE" for e in errors)

    def test_v10_from_date_with_default_last_ok(self) -> None:
        """V10: from_date + last=30 (default) produces NO error."""
        errors = validate_time_args(
            from_date="2024-01-01", to_date="2024-01-31", last=30
        )
        assert not any(e.code == "V10_DATE_LAST_EXCLUSIVE" for e in errors)

    def test_v15_from_date_after_to_date(self) -> None:
        """V15: from_date > to_date returns error with code V15_DATE_ORDER."""
        errors = validate_time_args(
            from_date="2024-02-01", to_date="2024-01-01", last=30
        )
        assert any(e.code == "V15_DATE_ORDER" for e in errors)

    def test_v20_last_too_large(self) -> None:
        """V20: last=5000 returns error with code V20_LAST_TOO_LARGE."""
        errors = validate_time_args(from_date=None, to_date=None, last=5000)
        assert any(e.code == "V20_LAST_TOO_LARGE" for e in errors)

    def test_valid_date_range(self) -> None:
        """Valid from_date+to_date with default last returns empty errors list."""
        errors = validate_time_args(
            from_date="2024-01-01", to_date="2024-01-31", last=30
        )
        assert errors == []

    def test_valid_last_only(self) -> None:
        """Valid: no dates, last=30 returns empty errors list."""
        errors = validate_time_args(from_date=None, to_date=None, last=30)
        assert errors == []


# =============================================================================
# Reusable validate_group_by_args() (US2 shared-infra)
# =============================================================================


class TestValidateGroupByArgs:
    """Tests for the reusable validate_group_by_args() function.

    Calls validate_group_by_args() directly (not through Workspace)
    to verify group-by validation rules V11-V12, V18, V24.
    """

    def test_v11_bucket_min_without_bucket_size(self) -> None:
        """V11: bucket_min without bucket_size returns V11_BUCKET_REQUIRES_SIZE."""
        errors = validate_group_by_args(
            group_by=GroupBy("amount", bucket_min=0),
        )
        assert any(e.code == "V11_BUCKET_REQUIRES_SIZE" for e in errors)

    def test_v12_bucket_size_zero(self) -> None:
        """V12: bucket_size=0 is rejected at construction."""
        with pytest.raises(ValueError, match="greater than 0"):
            GroupBy("amount", bucket_size=0)

    def test_v12_bucket_size_negative(self) -> None:
        """V12: bucket_size=-5 is rejected at construction."""
        with pytest.raises(ValueError, match="greater than 0"):
            GroupBy("amount", bucket_size=-5)

    def test_v12b_bucket_size_wrong_property_type(self) -> None:
        """V12B: bucket_size with property_type='string' returns V12B_BUCKET_REQUIRES_NUMBER."""
        errors = validate_group_by_args(
            group_by=GroupBy("amount", property_type="string", bucket_size=10),
        )
        assert any(e.code == "V12B_BUCKET_REQUIRES_NUMBER" for e in errors)

    def test_v12c_bucket_size_without_bounds(self) -> None:
        """V12C: bucket_size without bucket_min/bucket_max returns V12C_BUCKET_REQUIRES_BOUNDS."""
        errors = validate_group_by_args(
            group_by=GroupBy("amount", property_type="number", bucket_size=10),
        )
        assert any(e.code == "V12C_BUCKET_REQUIRES_BOUNDS" for e in errors)

    def test_v18_bucket_min_gte_bucket_max(self) -> None:
        """V18: bucket_min >= bucket_max is rejected by GroupBy.__post_init__."""
        with pytest.raises(ValueError, match="bucket_min.*must be less than"):
            GroupBy(
                "amount",
                property_type="number",
                bucket_size=10,
                bucket_min=100,
                bucket_max=50,
            )

    def test_v24_bucket_size_nan(self) -> None:
        """V24: bucket_size=float('nan') is rejected at construction."""
        with pytest.raises(ValueError, match="greater than 0"):
            GroupBy("amount", bucket_size=float("nan"))

    def test_v24_bucket_min_inf(self) -> None:
        """V24: bucket_min=float('inf') returns V24_BUCKET_NOT_FINITE."""
        errors = validate_group_by_args(
            group_by=GroupBy("amount", bucket_min=float("inf")),
        )
        assert any(e.code == "V24_BUCKET_NOT_FINITE" for e in errors)

    def test_valid_none_group_by(self) -> None:
        """Valid: None group_by returns empty errors list."""
        errors = validate_group_by_args(group_by=None)
        assert errors == []

    def test_valid_string_group_by(self) -> None:
        """Valid: string group_by returns empty errors list."""
        errors = validate_group_by_args(group_by="country")
        assert errors == []

    def test_valid_group_by_with_buckets(self) -> None:
        """Valid: GroupBy with valid bucket config returns empty errors list."""
        errors = validate_group_by_args(
            group_by=GroupBy(
                "revenue",
                property_type="number",
                bucket_size=50,
                bucket_min=0,
                bucket_max=500,
            ),
        )
        assert errors == []


# =============================================================================
# Normalization error contract: build methods raise BookmarkValidationError
# =============================================================================


class TestNormalizationErrorContract:
    """Schema-valid model inputs never leak raw pydantic errors from build.

    The bare-``str`` union arms on the query models carry no length or
    range constraints (that is what the published JSON schema advertises),
    so empty strings and out-of-range top-level values reach the build
    methods. The documented contract is ``BookmarkValidationError`` with
    the Layer-1 code — not ``pydantic.ValidationError`` from the str →
    component normalization.
    """

    def test_funnel_empty_step_string(self, ws: Workspace) -> None:
        """F2: empty step string surfaces as BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_funnel_params(FunnelQuery(steps=["", "Login"]))
        err = next(e for e in exc_info.value.errors if e.code == "F2_EMPTY_STEP_EVENT")
        assert err.path == "steps[0]"

    def test_funnel_empty_exclusion_string(self, ws: Workspace) -> None:
        """F4: empty exclusion string surfaces as BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_funnel_params(
                FunnelQuery(steps=["Signup", "Login"], exclusions=[""])
            )
        err = next(
            e for e in exc_info.value.errors if e.code == "F4_EMPTY_EXCLUSION_EVENT"
        )
        assert err.path == "exclusions[0]"

    def test_funnel_empty_holding_constant_string(self, ws: Workspace) -> None:
        """F8b: empty holding_constant string surfaces as BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_funnel_params(
                FunnelQuery(steps=["Signup", "Login"], holding_constant=[""])
            )
        err = next(
            e
            for e in exc_info.value.errors
            if e.code == "F8_EMPTY_HOLDING_CONSTANT_PROPERTY"
        )
        assert err.path == "holding_constant[0]"

    def test_funnel_aggregates_multiple_normalization_errors(
        self, ws: Workspace
    ) -> None:
        """Empty step and empty exclusion are reported in a single pass."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_funnel_params(FunnelQuery(steps=["", "Login"], exclusions=[""]))
        codes = {e.code for e in exc_info.value.errors}
        assert "F2_EMPTY_STEP_EVENT" in codes
        assert "F4_EMPTY_EXCLUSION_EVENT" in codes

    def test_insights_empty_formula(self, ws: Workspace) -> None:
        """Empty top-level formula surfaces as BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_params(InsightsQuery(events=["Signup", "Login"], formula=""))
        assert any(e.path.startswith("formula") for e in exc_info.value.errors)

    def test_retention_empty_born_event(self, ws: Workspace) -> None:
        """R1: empty born_event surfaces as BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_retention_params(
                RetentionQuery(born_event="", return_event="Login")
            )
        assert any(e.code == "R1_EMPTY_BORN_EVENT" for e in exc_info.value.errors)

    def test_retention_empty_return_event(self, ws: Workspace) -> None:
        """R2: empty return_event surfaces as BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_retention_params(
                RetentionQuery(born_event="Signup", return_event="")
            )
        assert any(e.code == "R2_EMPTY_RETURN_EVENT" for e in exc_info.value.errors)

    def test_flow_empty_event_string(self, ws: Workspace) -> None:
        """FL2: empty flow event string surfaces as BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_flow_params(FlowQuery(event=""))
        err = next(e for e in exc_info.value.errors if e.code == "FL2_EMPTY_STEP_EVENT")
        assert err.path == "steps[0]"

    def test_flow_forward_out_of_range(self, ws: Workspace) -> None:
        """FL3: top-level forward beyond FlowStep's 0-5 range is structured."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_flow_params(FlowQuery(event="Login", forward=7))
        assert any(e.code == "FL3_FORWARD_RANGE" for e in exc_info.value.errors)

    def test_flow_reverse_out_of_range(self, ws: Workspace) -> None:
        """FL4: top-level reverse beyond FlowStep's 0-5 range is structured."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            ws.build_flow_params(FlowQuery(event="Login", reverse=9))
        assert any(e.code == "FL4_REVERSE_RANGE" for e in exc_info.value.errors)

    def test_exception_type_independent_of_input_spelling(self, ws: Workspace) -> None:
        """Dict-spelled and bare-str-spelled bad input raise the same type."""
        with pytest.raises(BookmarkValidationError):
            FunnelQuery.model_validate({"steps": [{"event": ""}, {"event": "L"}]})
        with pytest.raises(BookmarkValidationError):
            ws.build_funnel_params(FunnelQuery(steps=["", "L"]))
