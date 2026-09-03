"""Unit tests for mixpanel_headless exception hierarchy."""

from __future__ import annotations

import json

import pytest

from mixpanel_headless.exceptions import (
    CODED_GUARD_REGISTRY,
    CODED_GUARD_TWIN_CODES,
    AccountExistsError,
    AccountNotFoundError,
    APIError,
    AuthenticationError,
    ConfigError,
    DateRangeTooLargeError,
    EventNotFoundError,
    MixpanelHeadlessError,
    ParamTypeError,
    ParamValidationError,
    QueryError,
    RateLimitError,
    ResponseValidationError,
    ServerError,
)


class TestMixpanelHeadlessError:
    """Tests for the base exception class."""

    def test_basic_initialization(self) -> None:
        """Test basic exception creation."""
        exc = MixpanelHeadlessError("Something went wrong")
        assert str(exc) == "Something went wrong"
        assert exc.message == "Something went wrong"
        assert exc.code == "UNKNOWN_ERROR"
        assert exc.details == {}

    def test_with_code_and_details(self) -> None:
        """Test exception with custom code and details."""
        exc = MixpanelHeadlessError(
            "Test error",
            code="TEST_ERROR",
            details={"key": "value", "count": 42},
        )
        assert exc.code == "TEST_ERROR"
        assert exc.details == {"key": "value", "count": 42}

    def test_to_dict_serializable(self) -> None:
        """Test that to_dict output is JSON serializable."""
        exc = MixpanelHeadlessError(
            "Test error",
            code="TEST_ERROR",
            details={"nested": {"data": [1, 2, 3]}},
        )
        result = exc.to_dict()

        # Verify structure
        assert result["code"] == "TEST_ERROR"
        assert result["message"] == "Test error"
        assert result["details"]["nested"]["data"] == [1, 2, 3]

        # Verify JSON serializable
        json_str = json.dumps(result)
        assert "TEST_ERROR" in json_str

    def test_repr(self) -> None:
        """Test string representation."""
        exc = MixpanelHeadlessError("Test error", code="TEST")
        assert "MixpanelHeadlessError" in repr(exc)
        assert "Test error" in repr(exc)
        assert "TEST" in repr(exc)


class TestConfigError:
    """Tests for configuration error classes."""

    def test_config_error_code(self) -> None:
        """ConfigError should have CONFIG_ERROR code."""
        exc = ConfigError("Config issue")
        assert exc.code == "CONFIG_ERROR"
        assert isinstance(exc, MixpanelHeadlessError)

    def test_account_not_found_with_available(self) -> None:
        """AccountNotFoundError should list available accounts."""
        exc = AccountNotFoundError("missing", available_accounts=["a", "b", "c"])

        assert exc.code == "ACCOUNT_NOT_FOUND"
        assert exc.account_name == "missing"
        assert exc.available_accounts == ["a", "b", "c"]
        assert "missing" in str(exc)
        assert "'a'" in str(exc)
        assert "'b'" in str(exc)

    def test_account_not_found_no_available(self) -> None:
        """AccountNotFoundError with no available accounts."""
        exc = AccountNotFoundError("missing")

        assert exc.available_accounts == []
        assert "No accounts configured" in str(exc)

    def test_account_not_found_details(self) -> None:
        """AccountNotFoundError includes available_accounts in details."""
        exc = AccountNotFoundError("x", available_accounts=["y", "z"])
        details = exc.details

        assert details["account_name"] == "x"
        assert details["available_accounts"] == ["y", "z"]

    def test_account_exists_error(self) -> None:
        """AccountExistsError should have correct code and message."""
        exc = AccountExistsError("duplicate")

        assert exc.code == "ACCOUNT_EXISTS"
        assert exc.account_name == "duplicate"
        assert "duplicate" in str(exc)
        assert "already exists" in str(exc)


class TestOperationExceptions:
    """Tests for operation-related exceptions."""

    def test_authentication_error(self) -> None:
        """AuthenticationError should have AUTH_FAILED code."""
        exc = AuthenticationError("Invalid credentials")

        assert exc.code == "AUTH_FAILED"
        assert isinstance(exc, MixpanelHeadlessError)
        assert "Invalid credentials" in str(exc)

    def test_authentication_error_default_message(self) -> None:
        """AuthenticationError default message."""
        exc = AuthenticationError()

        assert "Authentication failed" in str(exc)

    def test_rate_limit_error_with_retry(self) -> None:
        """RateLimitError should include retry_after."""
        exc = RateLimitError("Too many requests", retry_after=60)

        assert exc.code == "RATE_LIMITED"
        assert exc.retry_after == 60
        assert "60" in str(exc)
        assert exc.details["retry_after"] == 60

    def test_rate_limit_error_no_retry(self) -> None:
        """RateLimitError without retry_after."""
        exc = RateLimitError("Too many requests")

        assert exc.retry_after is None
        assert "retry_after" not in exc.details

    def test_rate_limit_error_carries_project_id(self) -> None:
        """RateLimitError should expose project_id and record it in details."""
        exc = RateLimitError("Too many requests", project_id="3018488")

        assert exc.project_id == "3018488"
        assert exc.details["project_id"] == "3018488"

    def test_rate_limit_error_no_project_id(self) -> None:
        """RateLimitError without project_id omits it from details."""
        exc = RateLimitError("Too many requests")

        assert exc.project_id is None
        assert "project_id" not in exc.details

    def test_rate_limit_form_url_prefilled_with_project_id(self) -> None:
        """rate_limit_form_url prefills the project_id into the long form URL."""
        exc = RateLimitError("Too many requests", project_id="3018488")

        url = exc.rate_limit_form_url
        assert url.startswith("https://docs.google.com/forms/d/e/")
        assert "viewform" in url
        assert "usp=pp_url" in url
        assert "entry.1636741534=3018488" in url

    def test_rate_limit_form_url_short_without_project_id(self) -> None:
        """rate_limit_form_url falls back to the short link without a project_id."""
        exc = RateLimitError("Too many requests")

        assert exc.rate_limit_form_url == "https://forms.gle/7Y9UcUHe69bh8EgC7"

    def test_query_error(self) -> None:
        """QueryError should have QUERY_FAILED code and inherit from APIError."""
        exc = QueryError(
            "Invalid SQL syntax",
            status_code=400,
            response_body={"error": "syntax error"},
            request_params={"query": "SELECT * FROM"},
        )

        assert exc.code == "QUERY_FAILED"
        assert exc.status_code == 400
        assert exc.request_params == {"query": "SELECT * FROM"}


class TestEventNotFoundError:
    """Tests for EventNotFoundError exception."""

    def test_basic_creation(self) -> None:
        """EventNotFoundError should have EVENT_NOT_FOUND code."""
        exc = EventNotFoundError("sign up")

        assert exc.code == "EVENT_NOT_FOUND"
        assert exc.event_name == "sign up"
        assert exc.similar_events == []
        assert "sign up" in str(exc)
        assert "not found" in str(exc).lower()

    def test_with_suggestions(self) -> None:
        """EventNotFoundError should include suggestions in message."""
        exc = EventNotFoundError(
            "sign up",
            similar_events=["Sign Up", "Sign Up Complete"],
        )

        assert exc.similar_events == ["Sign Up", "Sign Up Complete"]
        assert "Did you mean" in str(exc)
        assert "'Sign Up'" in str(exc)
        assert "'Sign Up Complete'" in str(exc)

    def test_limits_suggestions_to_five(self) -> None:
        """EventNotFoundError should show at most 5 suggestions."""
        many_events = [f"Event {i}" for i in range(10)]
        exc = EventNotFoundError("test", similar_events=many_events)

        # Message should only contain first 5
        message = str(exc)
        assert "'Event 0'" in message
        assert "'Event 4'" in message
        assert "'Event 5'" not in message

        # But all are stored in property
        assert len(exc.similar_events) == 10

    def test_inherits_from_base(self) -> None:
        """EventNotFoundError should inherit from MixpanelHeadlessError."""
        exc = EventNotFoundError("test")
        assert isinstance(exc, MixpanelHeadlessError)

    def test_to_dict_includes_event_info(self) -> None:
        """to_dict should include event name and suggestions."""
        exc = EventNotFoundError("signup", similar_events=["Sign Up"])

        result = exc.to_dict()

        assert result["code"] == "EVENT_NOT_FOUND"
        assert result["details"]["event_name"] == "signup"
        assert result["details"]["similar_events"] == ["Sign Up"]

        # Verify JSON serializable
        json_str = json.dumps(result)
        assert "EVENT_NOT_FOUND" in json_str
        assert "signup" in json_str


class TestDateRangeTooLargeError:
    """Tests for DateRangeTooLargeError exception."""

    def test_basic_creation(self) -> None:
        """DateRangeTooLargeError should have correct code and message."""
        exc = DateRangeTooLargeError(
            from_date="2024-01-01",
            to_date="2024-06-30",
            days_requested=182,
        )

        assert exc.code == "DATE_RANGE_TOO_LARGE"
        assert exc.from_date == "2024-01-01"
        assert exc.to_date == "2024-06-30"
        assert exc.days_requested == 182
        assert exc.max_days == 100  # default
        assert "182 days" in str(exc)
        assert "100 days" in str(exc)
        assert "Split" in str(exc)

    def test_custom_max_days(self) -> None:
        """DateRangeTooLargeError should support custom max_days."""
        exc = DateRangeTooLargeError(
            from_date="2024-01-01",
            to_date="2024-02-15",
            days_requested=45,
            max_days=30,
        )

        assert exc.max_days == 30
        assert "30 days" in str(exc)

    def test_inherits_from_base(self) -> None:
        """DateRangeTooLargeError should inherit from MixpanelHeadlessError."""
        exc = DateRangeTooLargeError("2024-01-01", "2024-06-30", 182)
        assert isinstance(exc, MixpanelHeadlessError)

    def test_to_dict_includes_date_info(self) -> None:
        """to_dict should include all date range information."""
        exc = DateRangeTooLargeError(
            from_date="2024-01-01",
            to_date="2024-06-30",
            days_requested=182,
            max_days=100,
        )

        result = exc.to_dict()

        assert result["code"] == "DATE_RANGE_TOO_LARGE"
        assert result["details"]["from_date"] == "2024-01-01"
        assert result["details"]["to_date"] == "2024-06-30"
        assert result["details"]["days_requested"] == 182
        assert result["details"]["max_days"] == 100

        # Verify JSON serializable
        json_str = json.dumps(result)
        assert "DATE_RANGE_TOO_LARGE" in json_str


class TestExceptionHierarchy:
    """Tests for exception inheritance."""

    def test_all_inherit_from_base(self) -> None:
        """All exceptions should inherit from MixpanelHeadlessError."""
        exceptions: list[MixpanelHeadlessError] = [
            ConfigError("test"),
            AccountNotFoundError("test"),
            AccountExistsError("test"),
            AuthenticationError("test"),
            RateLimitError("test"),
            QueryError("test"),
            EventNotFoundError("test"),
            DateRangeTooLargeError("2024-01-01", "2024-06-30", 182),
        ]

        for exc in exceptions:
            assert isinstance(exc, MixpanelHeadlessError), (
                f"{exc.__class__.__name__} should inherit from MixpanelHeadlessError"
            )
            assert isinstance(exc, Exception)

    def test_config_exceptions_inherit_from_config_error(self) -> None:
        """Config-related exceptions should inherit from ConfigError."""
        assert isinstance(AccountNotFoundError("x"), ConfigError)
        assert isinstance(AccountExistsError("x"), ConfigError)

    def test_catch_all_works(self) -> None:
        """Catch all library errors with single except clause."""
        exceptions_to_raise = [
            ConfigError("test"),
            AccountNotFoundError("test"),
            AuthenticationError("test"),
            RateLimitError("test"),
        ]

        for exc in exceptions_to_raise:
            with pytest.raises(MixpanelHeadlessError) as caught:
                raise exc

            assert caught.value.code is not None
            assert caught.value.to_dict() is not None

    def test_error_codes_match_expected(self) -> None:
        """Verify all error codes match expected values."""
        expected_codes = {
            ConfigError: "CONFIG_ERROR",
            AccountNotFoundError: "ACCOUNT_NOT_FOUND",
            AccountExistsError: "ACCOUNT_EXISTS",
            AuthenticationError: "AUTH_FAILED",
            RateLimitError: "RATE_LIMITED",
            QueryError: "QUERY_FAILED",
            EventNotFoundError: "EVENT_NOT_FOUND",
            DateRangeTooLargeError: "DATE_RANGE_TOO_LARGE",
        }

        for exc_class, expected_code in expected_codes.items():
            exc: MixpanelHeadlessError
            if exc_class in (AccountNotFoundError, AccountExistsError):
                exc = exc_class("test")
            elif exc_class is EventNotFoundError:
                exc = exc_class("test_event")
            elif exc_class is DateRangeTooLargeError:
                exc = exc_class("2024-01-01", "2024-06-30", 182)
            else:
                exc = exc_class("test message")

            assert exc.code == expected_code, (
                f"{exc_class.__name__} should have code {expected_code}, got {exc.code}"
            )


class TestAPIError:
    """Tests for APIError base class."""

    def test_basic_creation(self) -> None:
        """APIError should capture HTTP context."""
        exc = APIError(
            "Test error",
            status_code=500,
            response_body={"error": "Internal error"},
            request_method="GET",
            request_url="https://api.example.com/test",
            request_params={"param1": "value1"},
        )

        assert exc.status_code == 500
        assert exc.response_body == {"error": "Internal error"}
        assert exc.request_method == "GET"
        assert exc.request_url == "https://api.example.com/test"
        assert exc.request_params == {"param1": "value1"}
        assert exc.code == "API_ERROR"

    def test_inherits_from_base(self) -> None:
        """APIError should inherit from MixpanelHeadlessError."""
        exc = APIError("Test", status_code=400)
        assert isinstance(exc, MixpanelHeadlessError)

    def test_to_dict_includes_http_context(self) -> None:
        """to_dict should include all HTTP context."""
        exc = APIError(
            "Test error",
            status_code=400,
            response_body="Bad request",
            request_method="POST",
            request_url="https://api.example.com/query",
            request_params={"project_id": "123"},
            request_body={"data": "test"},
        )

        result = exc.to_dict()

        assert result["details"]["status_code"] == 400
        assert result["details"]["response_body"] == "Bad request"
        assert result["details"]["request_method"] == "POST"
        assert result["details"]["request_url"] == "https://api.example.com/query"
        assert result["details"]["request_params"] == {"project_id": "123"}
        assert result["details"]["request_body"] == {"data": "test"}

        # Verify JSON serializable
        json_str = json.dumps(result)
        assert "400" in json_str

    def test_optional_fields(self) -> None:
        """Optional fields should not appear in details if not provided."""
        exc = APIError("Test", status_code=500)

        assert exc.response_body is None
        assert exc.request_method is None
        assert "response_body" not in exc.details
        assert "request_method" not in exc.details

    def test_catchable_as_base(self) -> None:
        """APIError should be catchable as MixpanelHeadlessError."""
        with pytest.raises(MixpanelHeadlessError):
            raise APIError("Test", status_code=500)


class TestServerError:
    """Tests for ServerError (5xx errors)."""

    def test_basic_creation(self) -> None:
        """ServerError should have SERVER_ERROR code."""
        exc = ServerError("Internal server error", status_code=500)

        assert exc.code == "SERVER_ERROR"
        assert exc.status_code == 500
        assert isinstance(exc, APIError)
        assert isinstance(exc, MixpanelHeadlessError)

    def test_with_full_context(self) -> None:
        """ServerError should include request/response context."""
        exc = ServerError(
            "Server error: unit and interval both specified",
            status_code=500,
            response_body={"error": "unit and interval both specified"},
            request_method="GET",
            request_url="https://mixpanel.com/api/query/retention",
            request_params={"unit": "day", "interval": 7},
        )

        assert "unit and interval" in str(exc)
        assert exc.response_body == {"error": "unit and interval both specified"}
        assert exc.request_params == {"unit": "day", "interval": 7}

    def test_to_dict_serializable(self) -> None:
        """ServerError to_dict should be JSON serializable."""
        exc = ServerError(
            "Test",
            status_code=503,
            response_body={"retry_after": 60},
        )

        result = exc.to_dict()
        json_str = json.dumps(result)
        assert "503" in json_str
        assert "SERVER_ERROR" in json_str


class TestAPIErrorHierarchy:
    """Tests for API error inheritance."""

    def test_authentication_error_inherits_from_api_error(self) -> None:
        """AuthenticationError should inherit from APIError."""
        exc = AuthenticationError(
            "Invalid credentials",
            status_code=401,
            request_url="https://api.example.com",
        )

        assert isinstance(exc, APIError)
        assert exc.status_code == 401
        assert exc.request_url == "https://api.example.com"

    def test_authentication_error_carries_request_body(self) -> None:
        """AuthenticationError accepts request_body like its sibling errors.

        A 401 on a POST should expose the payload that was rejected, matching
        the QueryError / ServerError branches.
        """
        exc = AuthenticationError(
            "Invalid credentials",
            request_method="POST",
            request_url="https://api.example.com",
            request_body={"name": "dash"},
        )

        assert exc.request_body == {"name": "dash"}
        assert exc.to_dict()["details"]["request_body"] == {"name": "dash"}

    def test_rate_limit_error_inherits_from_api_error(self) -> None:
        """RateLimitError should inherit from APIError."""
        exc = RateLimitError(
            "Too many requests",
            retry_after=60,
            status_code=429,
            request_method="GET",
            request_url="https://api.example.com/query",
        )

        assert isinstance(exc, APIError)
        assert exc.status_code == 429
        assert exc.retry_after == 60
        assert exc.request_method == "GET"

    def test_query_error_inherits_from_api_error(self) -> None:
        """QueryError should inherit from APIError."""
        exc = QueryError(
            "Invalid query",
            status_code=400,
            response_body={"error": "syntax error"},
            request_params={"event": "signup"},
        )

        assert isinstance(exc, APIError)
        assert exc.status_code == 400
        assert exc.response_body == {"error": "syntax error"}

    def test_server_error_inherits_from_api_error(self) -> None:
        """ServerError should inherit from APIError."""
        exc = ServerError("Internal error", status_code=500)

        assert isinstance(exc, APIError)
        assert exc.status_code == 500

    def test_catch_all_api_errors(self) -> None:
        """All API errors should be catchable with APIError."""
        errors = [
            AuthenticationError("test"),
            RateLimitError("test"),
            QueryError("test"),
            ServerError("test", status_code=500),
        ]

        for error in errors:
            with pytest.raises(APIError):
                raise error


# =============================================================================
# Coded-guard classes (E2 coding pass) — ParamValidationError / ParamTypeError /
# ResponseValidationError + CODED_GUARD_REGISTRY uniqueness guard.
# =============================================================================

#: Snapshot of the pre-existing error-code universe at the start of the E2
#: coding pass (recon `codes` from context/phase1/recon/validation-errors.json
#: at 852d718 UNION a fresh literal scan of src/mixpanel_headless/** for
#: `code="…"` / `code: str = "…"` / `self._code = "…"` assignments plus the
#: two dynamic `FL_TYPE_{name}` expansions). Newly minted coded-guard codes
#: must never collide with this set (design §1, RR-2).
PRE_EXISTING_CODE_UNIVERSE: frozenset[str] = frozenset(
    {
        "ACCOUNT_EXISTS",
        "ACCOUNT_IN_USE",
        "ACCOUNT_NOT_FOUND",
        "API_ERROR",
        "AUTH_FAILED",
        "B0_INVALID_LITERAL",
        "B10_MATH_MISSING_PROPERTY",
        "B11_INVALID_PER_USER",
        "B12_INVALID_TIME_UNIT",
        "B13_INVALID_DATE_RANGE_TYPE",
        "B14_INVALID_FILTER_TYPE",
        "B15_INVALID_FILTER_OPERATOR",
        "B16_INVALID_RESOURCE_TYPE",
        "B17_INVALID_PROPERTY_TYPE",
        "B18B_INVALID_CP_ID",
        "B18_MISSING_FILTER_PROPERTY",
        "B19_INVALID_FILTERS_DETERMINER",
        "B1_MISSING_SECTIONS",
        "B20B_FILTER_VALUE_NOT_FINITE",
        "B20_EMPTY_FILTER_VALUE",
        "B21_FILTER_VALUE_TOO_MANY",
        "B22_COHORT_BEHAVIOR_ID",
        "B22_COHORT_MISSING_IDENTIFIER",
        "B23_COHORT_RESOURCE_TYPE",
        "B24_COHORT_MATH",
        "B25_COHORT_FILTER_VALUE",
        "B26_EMPTY_COHORTS",
        "B2_MISSING_DISPLAY_OPTIONS",
        "B3_MISSING_SHOW",
        "B4_SHOW_EMPTY",
        "B5_INVALID_CHART_TYPE",
        "B6_MISSING_BEHAVIOR",
        "B7_INVALID_BEHAVIOR_TYPE",
        "B8_MISSING_EVENT_NAME",
        "B9_INVALID_MATH",
        "BOOKMARK_VALIDATION_ERROR",
        "BUSINESS_CONTEXT_TOO_LONG",
        "CB3_RETENTION_MIXED_BREAKDOWN",
        "CDN_FETCH_ERROR",
        "CDN_INVALID_RESPONSE",
        "CDN_UNEXPECTED_STATUS",
        "CM5_INLINE_COHORT_METRIC",
        "CONFIG_ERROR",
        "CP1_INVALID_ID",
        "CP2_EMPTY_FORMULA",
        "CP3_EMPTY_INPUTS",
        "CP4_INVALID_INPUT_KEY",
        "CP5_FORMULA_TOO_LONG",
        "CP6_EMPTY_INPUT_NAME",
        "DATE_RANGE_TOO_LARGE",
        "DG1_INVALID_DATA_GROUP_ID",
        "EVENT_NOT_FOUND",
        "F10_MATH_MISSING_PROPERTY",
        "F11_MATH_REJECTS_PROPERTY",
        "F12_INVALID_REENTRY_MODE",
        "F1_MAX_STEPS",
        "F1_MIN_STEPS",
        "F2_CONTROL_CHAR_STEP_EVENT",
        "F2_EMPTY_STEP_EVENT",
        "F2_INVISIBLE_STEP_EVENT",
        "F3_CONVERSION_WINDOW_MAX",
        "F3_CONVERSION_WINDOW_POSITIVE",
        "F3_CONVERSION_WINDOW_TYPE",
        "F4_CONTROL_CHAR_EXCLUSION",
        "F4_EMPTY_EXCLUSION_EVENT",
        "F4_EXCLUSION_NEGATIVE_STEP",
        "F4_EXCLUSION_STEP_BOUNDS",
        "F4_EXCLUSION_STEP_ORDER",
        "F7_INVALID_WINDOW_UNIT",
        "F7_SECOND_MIN_WINDOW",
        "F8_EMPTY_HOLDING_CONSTANT_PROPERTY",
        "F8_MAX_HOLDING_CONSTANT",
        "F9_SESSION_MATH_REQUIRES_SESSION_WINDOW",
        "F9_SESSION_WINDOW_REQUIRES_ONE",
        "FL10_SESSION_WINDOW_REQUIRES_ONE",
        "FL1_EMPTY_STEPS",
        "FL2_CONTROL_CHAR_STEP_EVENT",
        "FL2_EMPTY_STEP_EVENT",
        "FL2_INVISIBLE_STEP_EVENT",
        "FL3_FORWARD_RANGE",
        "FL4_REVERSE_RANGE",
        "FL5_NO_DIRECTION",
        "FL6_CARDINALITY_RANGE",
        "FL7_CONVERSION_WINDOW_MAX",
        "FL7_CONVERSION_WINDOW_POSITIVE",
        "FL9_SESSION_REQUIRES_SESSION_WINDOW",
        "FLB1_EMPTY_STEPS",
        "FLB2_EMPTY_STEP_EVENT",
        "FLB3_INVALID_COUNT_TYPE",
        "FLB4_INVALID_CHART_TYPE",
        "FLB5_MISSING_DATE_RANGE",
        "FLB6_INVALID_VERSION",
        "FL_FILTER_CONTROL_CHAR",
        "FL_INVALID_COUNT_TYPE",
        "FL_INVALID_FILTERS_COMBINATOR",
        "FL_INVALID_HIDDEN_EVENT_TYPE",
        "FL_INVALID_MODE",
        "FL_INVALID_WINDOW_UNIT",
        "FL_TIME_COMPARISON_NOT_SUPPORTED",
        "FL_TYPE_FORWARD",
        "FL_TYPE_REVERSE",
        "HTTP_ERROR",
        "INVALID_ARGUMENT",
        "INVALID_MATH_TYPE",
        "INVALID_RESPONSE",
        "MISSING_FIELD",
        "MISSING_URL",
        "NETWORK_ERROR",
        "NO_WORKSPACES",
        "OAUTH_AUTH_DENIED",
        "OAUTH_BROWSER_ERROR",
        "OAUTH_CONFIG_ERROR",
        "OAUTH_NETWORK_UNREACHABLE",
        "OAUTH_PASTE_ERROR",
        "OAUTH_PORT_ERROR",
        "OAUTH_REFRESH_ERROR",
        "OAUTH_REFRESH_REVOKED",
        "OAUTH_REGION_PROBE_FAILED",
        "OAUTH_REGISTRATION_ERROR",
        "OAUTH_STATE_MISMATCH",
        "OAUTH_TIMEOUT",
        "OAUTH_TOKEN_ERROR",
        "ORGANIZATION_AMBIGUOUS",
        "PAGINATION_LIMIT",
        "PROJECT_NOT_FOUND",
        "QUERY_FAILED",
        "R10_INVALID_MODE",
        "R11_INVALID_UNIT",
        "R12_EMPTY_GROUP_BY",
        "R13_INVALID_UNBOUNDED_MODE",
        "R1_CONTROL_CHAR_BORN_EVENT",
        "R1_EMPTY_BORN_EVENT",
        "R1_INVISIBLE_BORN_EVENT",
        "R2_CONTROL_CHAR_RETURN_EVENT",
        "R2_EMPTY_RETURN_EVENT",
        "R2_INVISIBLE_RETURN_EVENT",
        "R5_BUCKET_SIZES_INTEGER",
        "R5_BUCKET_SIZES_POSITIVE",
        "R5_BUCKET_SIZES_TOO_MANY",
        "R6_BUCKET_SIZES_ASCENDING",
        "R7_INVALID_RETENTION_UNIT",
        "R8_INVALID_ALIGNMENT",
        "R9_INVALID_MATH",
        "RATE_LIMITED",
        "S1_INVALID_SORT_BY",
        "S2_MISSING_COL_SORT_ATTRS",
        "S3_UNKNOWN_FIELD",
        "S4_UNKNOWN_CHART_TYPE",
        "S5_NOT_A_DICT",
        "S6_INVALID_SORT_ORDER",
        "S7_NOT_A_LIST",
        "S8_MISSING_SORT_BY",
        "S9_MISSING_SORT_ORDER",
        "SERVER_ERROR",
        "U0",
        "U1",
        "U10",
        "U11",
        "U12",
        "U13",
        "U14",
        "U15",
        "U16",
        "U17",
        "U18",
        "U19",
        "U2",
        "U20",
        "U21",
        "U22",
        "U23",
        "U24",
        "U25",
        "U26",
        "U27",
        "U28",
        "U29",
        "U3",
        "U30",
        "U4",
        "U5",
        "U6",
        "U7",
        "U8",
        "U9",
        "UNKNOWN_ERROR",
        "UP1",
        "UP2",
        "UP3",
        "UP4",
        "UPDATE_TARGET_MISMATCH",
        "UPLOAD_ERROR",
        "UPLOAD_FAILED",
        "UPLOAD_NOT_FOUND",
        "UPLOAD_TIMEOUT",
        "U_COHORT",
        "U_FILTER",
        "V0_NO_EVENTS",
        "V10_DATE_LAST_EXCLUSIVE",
        "V11_BUCKET_REQUIRES_SIZE",
        "V12B_BUCKET_REQUIRES_NUMBER",
        "V12C_BUCKET_REQUIRES_BOUNDS",
        "V12_BUCKET_SIZE_POSITIVE",
        "V13_METRIC_MATH_PROPERTY",
        "V14_METRIC_REJECTS_PROPERTY",
        "V15_DATE_ORDER",
        "V16_FORMULA_SYNTAX",
        "V17_EMPTY_EVENT",
        "V18_BUCKET_ORDER",
        "V19_FORMULA_BOUNDS",
        "V1_MATH_REQUIRES_PROPERTY",
        "V20_LAST_TOO_LARGE",
        "V21_INVALID_EVENT_TYPE",
        "V22_CONTROL_CHAR_EVENT",
        "V22_INVISIBLE_EVENT",
        "V23_ROLLING_TOO_LARGE",
        "V24_BUCKET_NOT_FINITE",
        "V25_INVALID_FILTER_TYPE",
        "V26_PERCENTILE_REQUIRES_VALUE",
        "V27_HISTOGRAM_REQUIRES_PER_USER",
        "V2_MATH_REJECTS_PROPERTY",
        "V3B_PER_USER_REQUIRES_PROPERTY",
        "V3_PER_USER_INCOMPATIBLE",
        "V4_FORMULA_CONFLICT",
        "V4_FORMULA_MIN_EVENTS",
        "V5_ROLLING_CUMULATIVE_EXCLUSIVE",
        "V6_ROLLING_POSITIVE",
        "V7_LAST_POSITIVE",
        "V8_DATE_FORMAT",
        "V8_DATE_INVALID",
        "V9_TO_REQUIRES_FROM",
        "VALIDATION_ERROR",
    }
)


class TestParamValidationError:
    """Tests for the ParamValidationError dual-inheritance guard error."""

    def test_dual_inheritance(self) -> None:
        """ParamValidationError is both a domain error and a ValueError."""
        exc = ParamValidationError("bad value", code="FD1_QUANTITY_NOT_POSITIVE")
        assert isinstance(exc, MixpanelHeadlessError)
        assert isinstance(exc, ValueError)
        assert issubclass(ParamValidationError, ValueError)

    def test_code_and_message(self) -> None:
        """The code kwarg and message are carried unchanged."""
        exc = ParamValidationError("bad value", code="FD1_QUANTITY_NOT_POSITIVE")
        assert exc.code == "FD1_QUANTITY_NOT_POSITIVE"
        assert exc.message == "bad value"
        assert str(exc) == "bad value"

    def test_default_code_is_generic_validation_error(self) -> None:
        """Without an explicit code the R5.5 generic VALIDATION_ERROR applies."""
        exc = ParamValidationError("bad value")
        assert exc.code == "VALIDATION_ERROR"

    def test_catchable_as_value_error(self) -> None:
        """Existing except ValueError handlers keep catching converted guards."""
        with pytest.raises(ValueError):
            raise ParamValidationError("bad value", code="FD1_QUANTITY_NOT_POSITIVE")

    def test_to_dict_round_trip(self) -> None:
        """to_dict() serializes code, message, and details."""
        exc = ParamValidationError(
            "bad value",
            code="FD1_QUANTITY_NOT_POSITIVE",
            details={"quantity": 0},
        )
        result = exc.to_dict()
        assert result == {
            "code": "FD1_QUANTITY_NOT_POSITIVE",
            "message": "bad value",
            "details": {"quantity": 0},
        }
        json.dumps(result)


class TestParamTypeError:
    """Tests for the ParamTypeError dual-inheritance guard error."""

    def test_dual_inheritance(self) -> None:
        """ParamTypeError is both a domain error and a TypeError."""
        exc = ParamTypeError("bad type", code="LC6_KWARG_VALUE_TYPE")
        assert isinstance(exc, MixpanelHeadlessError)
        assert isinstance(exc, TypeError)
        assert issubclass(ParamTypeError, TypeError)

    def test_code_and_message(self) -> None:
        """The code kwarg and message are carried unchanged."""
        exc = ParamTypeError("bad type", code="LC6_KWARG_VALUE_TYPE")
        assert exc.code == "LC6_KWARG_VALUE_TYPE"
        assert exc.message == "bad type"
        assert str(exc) == "bad type"

    def test_default_code_is_generic_validation_error(self) -> None:
        """Without an explicit code the R5.5 generic VALIDATION_ERROR applies."""
        exc = ParamTypeError("bad type")
        assert exc.code == "VALIDATION_ERROR"

    def test_catchable_as_type_error(self) -> None:
        """Existing except TypeError handlers keep catching converted guards."""
        with pytest.raises(TypeError):
            raise ParamTypeError("bad type", code="LC6_KWARG_VALUE_TYPE")

    def test_to_dict_round_trip(self) -> None:
        """to_dict() serializes code, message, and details."""
        exc = ParamTypeError("bad type", code="LC6_KWARG_VALUE_TYPE")
        result = exc.to_dict()
        assert result["code"] == "LC6_KWARG_VALUE_TYPE"
        assert result["message"] == "bad type"
        json.dumps(result)


class TestResponseValidationError:
    """Tests for the ResponseValidationError response-seam error."""

    def test_inherits_from_base_only(self) -> None:
        """ResponseValidationError is a domain error but NOT a ValueError.

        It deliberately does not impersonate pydantic.ValidationError
        (which subclasses ValueError) — the wrap is a sanctioned behavior
        change recorded by E2.
        """
        exc = ResponseValidationError("response failed validation")
        assert isinstance(exc, MixpanelHeadlessError)
        assert not isinstance(exc, ValueError)
        assert not isinstance(exc, TypeError)

    def test_default_code(self) -> None:
        """The class defaults to the RESPONSE_VALIDATION_ERROR generic code."""
        exc = ResponseValidationError("response failed validation")
        assert exc.code == "RESPONSE_VALIDATION_ERROR"

    def test_details_carried(self) -> None:
        """Structured details (model name, pydantic errors) are carried."""
        exc = ResponseValidationError(
            "response failed validation",
            details={"model": "Dashboard", "errors": []},
        )
        assert exc.details == {"model": "Dashboard", "errors": []}
        json.dumps(exc.to_dict())


class TestCodedGuardRegistry:
    """Uniqueness guard for the codes minted by the E2 coding pass."""

    def test_minted_codes_do_not_collide_with_pre_existing_universe(self) -> None:
        """No minted full code collides with the pre-existing code universe.

        The universe is the recon 175-code set UNION the fresh literal scan
        (232 codes total — a superset of the design's 227-code universe,
        per RR-2 the binding basis for this check).
        """
        assert len(PRE_EXISTING_CODE_UNIVERSE) == 232
        collisions = CODED_GUARD_REGISTRY & PRE_EXISTING_CODE_UNIVERSE
        assert collisions == frozenset()

    def test_minted_registry_size(self) -> None:
        """The registry lists all 126 minted full codes, no duplicates.

        The E2 coding pass minted 120 (the design's nominal 123 minus the
        three AT codes for ``AccountTestResult`` — that validator is
        pydantic-internal, so those sites stay builtin under the design's
        P3 policy). 045-report-links added the six ``RL*`` guards: ``RL1``
        to ``RL4`` in the first cut, ``RL5`` (``ResolvedReport`` consistency)
        and ``RL6`` (positive ids in the URL builders) from PR review.
        """
        assert len(CODED_GUARD_REGISTRY) == 126

    def test_twin_codes_all_pre_exist(self) -> None:
        """Every reused twin code already exists in the code universe."""
        assert len(CODED_GUARD_TWIN_CODES) == 9
        assert CODED_GUARD_TWIN_CODES <= PRE_EXISTING_CODE_UNIVERSE

    def test_twins_disjoint_from_minted(self) -> None:
        """Twin (reused) codes are not double-listed as minted codes."""
        assert frozenset() == CODED_GUARD_TWIN_CODES & CODED_GUARD_REGISTRY

    def test_generic_codes(self) -> None:
        """VALIDATION_ERROR pre-exists; RESPONSE_VALIDATION_ERROR is minted."""
        assert "VALIDATION_ERROR" in PRE_EXISTING_CODE_UNIVERSE
        assert "RESPONSE_VALIDATION_ERROR" in CODED_GUARD_REGISTRY


class TestCodedGuardPublicExports:
    """The three coded-guard classes are part of the public API surface."""

    def test_exported_from_package_root(self) -> None:
        """ParamValidationError/ParamTypeError/ResponseValidationError export."""
        import mixpanel_headless as mp

        assert mp.ParamValidationError is ParamValidationError
        assert mp.ParamTypeError is ParamTypeError
        assert mp.ResponseValidationError is ResponseValidationError

    def test_listed_in_all(self) -> None:
        """The new classes are listed in the package __all__."""
        import mixpanel_headless as mp

        assert "ParamValidationError" in mp.__all__
        assert "ParamTypeError" in mp.__all__
        assert "ResponseValidationError" in mp.__all__
