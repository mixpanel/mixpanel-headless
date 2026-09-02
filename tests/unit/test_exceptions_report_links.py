"""Unit tests for the report-link exception family (045-report-links).

Covers the hierarchy, default codes (data-model.md §7), ``to_dict()`` shape,
``details`` carrying parsed fields plus ``hint``, the stable message texts in
contracts/error-messages.md §1 to §6, and the ``RL*`` guard-code registration.
"""

from __future__ import annotations

import json

import pytest

from mixpanel_headless.exceptions import (
    CODED_GUARD_REGISTRY,
    APIError,
    MixpanelHeadlessError,
    ParamValidationError,
    ReportLinkError,
    ReportLinkNotFoundError,
    ReportLinkParseError,
    ReportLinkScopeMismatchError,
    ShortLinkResolutionError,
    UnsupportedReportLinkError,
)

_LEAF_CLASSES: list[type[ReportLinkError]] = [
    ReportLinkParseError,
    UnsupportedReportLinkError,
    ReportLinkNotFoundError,
    ReportLinkScopeMismatchError,
    ShortLinkResolutionError,
]


class TestReportLinkHierarchy:
    """Every report-link exception subclasses MixpanelHeadlessError, not APIError."""

    def test_base_subclasses_mixpanel_headless_error(self) -> None:
        """ReportLinkError is a MixpanelHeadlessError and not an APIError."""
        assert issubclass(ReportLinkError, MixpanelHeadlessError)
        assert not issubclass(ReportLinkError, APIError)

    @pytest.mark.parametrize("exc_cls", _LEAF_CLASSES)
    def test_leaf_subclasses_report_link_error(
        self, exc_cls: type[ReportLinkError]
    ) -> None:
        """Each leaf class is a ReportLinkError and a MixpanelHeadlessError."""
        assert issubclass(exc_cls, ReportLinkError)
        assert issubclass(exc_cls, MixpanelHeadlessError)

    def test_catchable_as_base(self) -> None:
        """A leaf raise is caught by ``except ReportLinkError``."""
        with pytest.raises(ReportLinkError):
            raise ReportLinkParseError("boom")


class TestDefaultCodes:
    """Default codes match data-model.md §7."""

    @pytest.mark.parametrize(
        ("exc_cls", "expected"),
        [
            (ReportLinkError, "REPORT_LINK_ERROR"),
            (ReportLinkParseError, "REPORT_LINK_UNPARSEABLE"),
            (UnsupportedReportLinkError, "UNSUPPORTED_REPORT_LINK"),
            (ReportLinkNotFoundError, "REPORT_LINK_NOT_FOUND"),
            (ReportLinkScopeMismatchError, "REPORT_LINK_SCOPE_MISMATCH"),
            (ShortLinkResolutionError, "SHORT_LINK_RESOLUTION_ERROR"),
        ],
    )
    def test_default_code(self, exc_cls: type[ReportLinkError], expected: str) -> None:
        """Constructing with a message only yields the class default code."""
        exc = exc_cls("msg")
        assert exc.code == expected
        assert exc.message == "msg"
        assert str(exc) == "msg"

    @pytest.mark.parametrize(
        ("exc_cls", "code"),
        [
            (ReportLinkParseError, "REPORT_LINK_NOT_MIXPANEL_HOST"),
            (ReportLinkParseError, "REPORT_LINK_UNRECOGNIZED_PATH"),
            (ReportLinkParseError, "REPORT_LINK_UNRECOGNIZED_HASH"),
            (ReportLinkParseError, "REPORT_LINK_EMPTY_HASH"),
            (UnsupportedReportLinkError, "UNSUPPORTED_LEGACY_HASH"),
            (UnsupportedReportLinkError, "UNSUPPORTED_DASHBOARD_LINK"),
            (UnsupportedReportLinkError, "UNSUPPORTED_REPORT_TYPE"),
            (ReportLinkNotFoundError, "REPORT_LINK_SLUG_NOT_FOUND"),
            (ReportLinkNotFoundError, "REPORT_LINK_BOOKMARK_NOT_FOUND"),
            (ReportLinkNotFoundError, "SHORT_LINK_NOT_FOUND"),
            (ReportLinkScopeMismatchError, "REPORT_LINK_PROJECT_MISMATCH"),
            (ReportLinkScopeMismatchError, "REPORT_LINK_REGION_MISMATCH"),
            (ShortLinkResolutionError, "SHORT_LINK_NO_LOCATION"),
            (ShortLinkResolutionError, "SHORT_LINK_UNEXPECTED_RESPONSE"),
            (ShortLinkResolutionError, "SHORT_LINK_CHAIN"),
        ],
    )
    def test_explicit_code_override(
        self, exc_cls: type[ReportLinkError], code: str
    ) -> None:
        """An explicit ``code`` keyword replaces the default."""
        exc = exc_cls("msg", code=code)
        assert exc.code == code


class TestDetailsAndToDict:
    """``details`` carries parsed fields and ``hint``; ``to_dict`` is JSON-safe."""

    def test_details_default_empty(self) -> None:
        """No details yields an empty dict, never None."""
        assert ReportLinkError("msg").details == {}

    def test_details_carry_parsed_fields_and_hint(self) -> None:
        """Parsed link fields and the hint are readable from ``details``."""
        exc = ReportLinkScopeMismatchError(
            "mismatch",
            code="REPORT_LINK_PROJECT_MISMATCH",
            details={
                "kind": "slug",
                "region": "us",
                "project_id": 3,
                "workspace_id": 75,
                "slug": "EBrV5bW2u9Mw",
                "hint": "switch project",
            },
        )
        assert exc.details["kind"] == "slug"
        assert exc.details["region"] == "us"
        assert exc.details["project_id"] == 3
        assert exc.details["workspace_id"] == 75
        assert exc.details["slug"] == "EBrV5bW2u9Mw"
        assert exc.details["hint"] == "switch project"

    def test_to_dict_shape(self) -> None:
        """``to_dict`` returns code, message, details and is JSON-serializable."""
        exc = ReportLinkNotFoundError(
            "gone",
            code="SHORT_LINK_NOT_FOUND",
            details={"short_code": "AbC123", "host": "mixpanel.com"},
        )
        d = exc.to_dict()
        assert d == {
            "code": "SHORT_LINK_NOT_FOUND",
            "message": "gone",
            "details": {"short_code": "AbC123", "host": "mixpanel.com"},
        }
        json.dumps(d)

    def test_repr_names_class_and_code(self) -> None:
        """``repr`` follows the MixpanelHeadlessError convention."""
        exc = ShortLinkResolutionError("x", code="SHORT_LINK_CHAIN")
        assert repr(exc) == (
            "ShortLinkResolutionError(message='x', code='SHORT_LINK_CHAIN')"
        )


class TestCanonicalMessages:
    """Stable message texts from contracts/error-messages.md §1 to §5."""

    def test_parse_unparseable(self) -> None:
        """§1 REPORT_LINK_UNPARSEABLE wording."""
        raw = "not a url at all"
        exc = ReportLinkParseError(
            f"Could not parse report link: {raw!r}",
            details={
                "raw": raw,
                "hint": (
                    "Pass a full Mixpanel report URL, a shortlink "
                    "(https://mixpanel.com/s/...), or a 12-character slug."
                ),
            },
        )
        assert "Could not parse report link: 'not a url at all'" in str(exc)
        assert exc.details["hint"].startswith("Pass a full Mixpanel report URL")

    def test_parse_not_mixpanel_host(self) -> None:
        """§1 REPORT_LINK_NOT_MIXPANEL_HOST wording."""
        exc = ReportLinkParseError(
            "Report link host 'example.com' is not a Mixpanel web host.",
            code="REPORT_LINK_NOT_MIXPANEL_HOST",
            details={
                "host": "example.com",
                "hint": "Expected mixpanel.com, eu.mixpanel.com, or in.mixpanel.com.",
            },
        )
        assert "is not a Mixpanel web host" in str(exc)
        assert exc.details["host"] == "example.com"

    def test_unsupported_legacy_hash(self) -> None:
        """§2 UNSUPPORTED_LEGACY_HASH wording."""
        exc = UnsupportedReportLinkError(
            "This link uses the legacy JSURL hash format, which "
            "mixpanel-headless cannot decode.",
            code="UNSUPPORTED_LEGACY_HASH",
            details={
                "kind": "legacy_jsurl",
                "hint": (
                    "Open it in a browser (the app re-mints a shareable link "
                    "on load) and copy the new URL."
                ),
            },
        )
        assert "legacy JSURL hash format" in str(exc)
        assert "Open it in a browser" in exc.details["hint"]

    def test_not_found_slug(self) -> None:
        """§3 REPORT_LINK_SLUG_NOT_FOUND wording."""
        exc = ReportLinkNotFoundError(
            "No unsaved report found for slug EBrV5bW2u9Mw in project 3 (us). "
            "A slug is only readable in the project and region that created it.",
            code="REPORT_LINK_SLUG_NOT_FOUND",
            details={"slug": "EBrV5bW2u9Mw", "project_id": 3, "region": "us"},
        )
        assert "No unsaved report found for slug EBrV5bW2u9Mw" in str(exc)
        assert "only readable in the project and region" in str(exc)

    def test_scope_project_mismatch(self) -> None:
        """§4 REPORT_LINK_PROJECT_MISMATCH wording names both projects."""
        exc = ReportLinkScopeMismatchError(
            "Report link belongs to project 3 but the active session is "
            'project 12345. Switch with ws.use(project="3") '
            "(CLI: mp --project 3 ...) and retry.",
            code="REPORT_LINK_PROJECT_MISMATCH",
            details={"link_project_id": 3, "session_project_id": 12345},
        )
        assert "belongs to project 3" in str(exc)
        assert "active session is project 12345" in str(exc)
        assert 'ws.use(project="3")' in str(exc)

    def test_short_link_chain(self) -> None:
        """§5 SHORT_LINK_CHAIN wording."""
        exc = ShortLinkResolutionError(
            "Shortlink /s/AbC redirects to another shortlink "
            "(https://mixpanel.com/s/XyZ). mixpanel-headless follows one "
            "redirect only.",
            code="SHORT_LINK_CHAIN",
            details={
                "short_code": "AbC",
                "target": "https://mixpanel.com/s/XyZ",
                "hint": "Resolve the target shortlink directly.",
            },
        )
        assert "follows one redirect only" in str(exc)
        assert exc.details["hint"] == "Resolve the target shortlink directly."


class TestBuilderGuardCodes:
    """§6 builder guards are ParamValidationError codes in the registry."""

    @pytest.mark.parametrize(
        "code",
        [
            "RL1_UNKNOWN_REPORT_TYPE",
            "RL2_INVALID_SLUG",
            "RL3_UNKNOWN_REGION",
            "RL4_REPORT_TYPE_CONFLICT",
        ],
    )
    def test_registered(self, code: str) -> None:
        """Each RL code is present in CODED_GUARD_REGISTRY."""
        assert code in CODED_GUARD_REGISTRY

    def test_param_validation_error_carries_rl_code(self) -> None:
        """A guard raised with an RL code is a ValueError with that code."""
        exc = ParamValidationError(
            "Unknown region 'jp'. Expected one of: us, eu, in.",
            code="RL3_UNKNOWN_REGION",
        )
        assert isinstance(exc, ValueError)
        assert exc.code == "RL3_UNKNOWN_REGION"
