"""Unit tests for the pure report-link module (045-report-links).

One parametrized case per row of contracts/url-grammar.md §5 (parse table)
and §6 (builders), plus ``is_slug``, ``web_host``, and ``generate_slug``.
"""

from __future__ import annotations

from typing import Any

import pytest

from mixpanel_headless._internal.report_links import (
    APP_TO_REPORT_TYPE,
    BOOKMARK_HASH_FOR_TYPE,
    SLUG_ALPHABET,
    SLUG_APP_FOR_TYPE,
    SLUG_LENGTH,
    WEB_HOSTS,
    ParsedReportLink,
    build_bookmark_url,
    build_slug_url,
    generate_slug,
    is_slug,
    parse_report_link,
    web_host,
)
from mixpanel_headless.exceptions import ParamValidationError, ReportLinkParseError

_SLUG = "EBrV5bW2u9Mw"


class TestConstants:
    """Constants match data-model.md §8."""

    def test_slug_alphabet_and_length(self) -> None:
        """The mint alphabet omits 0, I, O, l and the length is 12."""
        assert SLUG_LENGTH == 12
        assert SLUG_ALPHABET == (
            "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        )
        for banned in "0IOl":
            assert banned not in SLUG_ALPHABET

    def test_tables(self) -> None:
        """Host, app, and hash tables hold the documented rows."""
        assert WEB_HOSTS == {
            "us": "mixpanel.com",
            "eu": "eu.mixpanel.com",
            "in": "in.mixpanel.com",
        }
        assert SLUG_APP_FOR_TYPE == {
            "insights": "insights",
            "funnels": "insights",
            "retention": "insights",
            "flows": "flows",
        }
        assert BOOKMARK_HASH_FOR_TYPE == {
            "insights": "insights#report/{id}",
            "funnels": "funnels#view/{id}",
            "retention": "retention#report/{id}",
            "flows": "flows#report/{id}",
            "launch-analysis": "impact#report/{id}",
        }
        assert APP_TO_REPORT_TYPE == {
            "insights": "insights",
            "funnels": "funnels",
            "retention": "retention",
            "flows": "flows",
            "impact": "launch-analysis",
        }


class TestWebHost:
    """``web_host`` maps a region to its web host."""

    @pytest.mark.parametrize(
        ("region", "host"),
        [("us", "mixpanel.com"), ("eu", "eu.mixpanel.com"), ("in", "in.mixpanel.com")],
    )
    def test_known_regions(self, region: str, host: str) -> None:
        """Each of the three regions maps to its host."""
        assert web_host(region) == host

    def test_unknown_region_raises_rl3(self) -> None:
        """An unknown region raises RL3_UNKNOWN_REGION with the stable text."""
        with pytest.raises(ParamValidationError) as exc_info:
            web_host("jp")
        assert exc_info.value.code == "RL3_UNKNOWN_REGION"
        assert str(exc_info.value) == (
            "Unknown region 'jp'. Expected one of: us, eu, in."
        )
        assert exc_info.value.details == {"region": "jp"}


class TestIsSlug:
    """``is_slug`` applies the server regex ``^[0-9a-zA-Z_-]{12}$``."""

    @pytest.mark.parametrize(
        "value",
        [_SLUG, "aaaaaaaaaaaa", "000000000000", "ab_-CD12efGH", "____________"],
    )
    def test_positive(self, value: str) -> None:
        """Twelve characters from the server alphabet are a slug."""
        assert is_slug(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "tooShort",
            "thirteenchars",
            "EBrV5bW2u9M!",
            "EBrV5bW2u9M ",
            " EBrV5bW2u9M",
            "EBrV5bW2u9Mw\n",
            "report/12345",
            "ÉBrV5bW2u9Mw",
        ],
    )
    def test_negative(self, value: str) -> None:
        """Wrong length or a character outside the alphabet is not a slug."""
        assert is_slug(value) is False


class TestGenerateSlug:
    """``generate_slug`` draws 12 characters with the injected chooser."""

    def test_deterministic_with_injected_choice(self) -> None:
        """An injected ``choice`` makes the slug deterministic."""
        assert generate_slug(choice=lambda alphabet: alphabet[0]) == "1" * 12
        assert generate_slug(choice=lambda alphabet: alphabet[-1]) == "z" * 12

    def test_choice_receives_the_alphabet(self) -> None:
        """The chooser is called once per character with SLUG_ALPHABET."""
        seen: list[str] = []

        def choice(alphabet: str) -> str:
            """Record the alphabet and return a fixed character."""
            seen.append(alphabet)
            return "A"

        assert generate_slug(choice=choice) == "A" * 12
        assert seen == [SLUG_ALPHABET] * 12

    def test_default_is_a_valid_slug(self) -> None:
        """The default ``secrets.choice`` yields a valid slug."""
        slug = generate_slug()
        assert len(slug) == 12
        assert is_slug(slug)
        assert all(c in SLUG_ALPHABET for c in slug)


# --- url-grammar.md §5 parse table --------------------------------------------

_PARSE_ROWS: list[tuple[str, dict[str, Any]]] = [
    (
        _SLUG,
        {
            "kind": "slug",
            "slug": _SLUG,
            "host": None,
            "region": None,
            "project_id": None,
            "workspace_id": None,
        },
    ),
    (f"  {_SLUG}  ", {"kind": "slug", "slug": _SLUG, "raw": _SLUG}),
    (
        "https://mixpanel.com/s/AbC123",
        {
            "kind": "short_link",
            "short_code": "AbC123",
            "region": "us",
            "host": "mixpanel.com",
        },
    ),
    (
        "https://eu.mixpanel.com/s/AbC123",
        {"kind": "short_link", "short_code": "AbC123", "region": "eu"},
    ),
    (
        f"https://eu.mixpanel.com/project/3/view/75/app/insights#{_SLUG}",
        {
            "kind": "slug",
            "region": "eu",
            "project_id": 3,
            "workspace_id": 75,
            "app": "insights",
            "report_type_hint": "insights",
            "slug": _SLUG,
        },
    ),
    (
        f"https://mixpanel.com/project/3/app/insights/#{_SLUG}",
        {"kind": "slug", "project_id": 3, "workspace_id": None, "slug": _SLUG},
    ),
    (
        "https://mixpanel.com/project/3/app/insights#report/123",
        {
            "kind": "bookmark",
            "bookmark_id": 123,
            "report_type_hint": "insights",
            "title_segment": None,
            "overrides_jsurl": None,
        },
    ),
    (
        "https://mixpanel.com/project/3/app/insights#report/123/weekly-actives",
        {
            "kind": "bookmark",
            "bookmark_id": 123,
            "title_segment": "weekly-actives",
            "overrides_jsurl": None,
        },
    ),
    (
        "https://mixpanel.com/project/3/app/insights#report/123/weekly-actives/~(a~1)",
        {
            "kind": "bookmark",
            "bookmark_id": 123,
            "title_segment": "weekly-actives",
            "overrides_jsurl": "~(a~1)",
        },
    ),
    (
        "https://mixpanel.com/project/3/app/insights#report/123/~(a~1)",
        {
            "kind": "bookmark",
            "bookmark_id": 123,
            "title_segment": None,
            "overrides_jsurl": "~(a~1)",
        },
    ),
    (
        "https://mixpanel.com/project/3/app/funnels#view/456",
        {
            "kind": "bookmark",
            "bookmark_id": 456,
            "report_type_hint": "funnels",
            "app": "funnels",
        },
    ),
    (
        "https://mixpanel.com/project/3/app/retention#report/7",
        {"kind": "bookmark", "bookmark_id": 7, "report_type_hint": "retention"},
    ),
    (
        "https://mixpanel.com/project/3/app/flows#report/8",
        {"kind": "bookmark", "bookmark_id": 8, "report_type_hint": "flows"},
    ),
    (
        "https://mixpanel.com/project/3/app/insights#segmentation-report/9",
        {"kind": "bookmark", "bookmark_id": 9, "report_type_hint": "insights"},
    ),
    (
        "https://mixpanel.com/project/3/app/impact#report/10",
        {
            "kind": "bookmark",
            "bookmark_id": 10,
            "report_type_hint": "launch-analysis",
            "app": "impact",
        },
    ),
    (
        "https://mixpanel.com/report/3/insights#report/123",
        {
            "kind": "bookmark",
            "project_id": 3,
            "workspace_id": None,
            "bookmark_id": 123,
            "app": "insights",
        },
    ),
    (
        "https://mixpanel.com/report/3/view/75/insights#report/123",
        {"kind": "bookmark", "project_id": 3, "workspace_id": 75, "bookmark_id": 123},
    ),
    (
        f"in.mixpanel.com/project/3/app/insights#{_SLUG}",
        {"kind": "slug", "region": "in", "host": "in.mixpanel.com", "slug": _SLUG},
    ),
    (
        f"HTTPS://MIXPANEL.COM/project/3/app/insights#{_SLUG}",
        {"kind": "slug", "host": "mixpanel.com", "region": "us", "slug": _SLUG},
    ),
    (
        f"https://mixpanel.com:443/project/3/app/insights#{_SLUG}",
        {"kind": "slug", "host": "mixpanel.com", "project_id": 3, "slug": _SLUG},
    ),
    (
        f"https://mixpanel.com/project/3/app/insights?utm=x#{_SLUG}",
        {"kind": "slug", "project_id": 3, "slug": _SLUG},
    ),
    (
        f"https://mixpanel.com/project/3/app/insights%23{_SLUG}",
        {"kind": "slug", "project_id": 3, "slug": _SLUG},
    ),
    (
        f"https://mixpanel.org/project/3/app/insights#{_SLUG}",
        {"kind": "slug", "region": "us", "host": "mixpanel.org", "slug": _SLUG},
    ),
    (
        "https://mixpanel.com/project/3/app/boards#id=555",
        {
            "kind": "dashboard",
            "dashboard_id": 555,
            "host": "mixpanel.com",
            "region": "us",
            "project_id": 3,
            "workspace_id": None,
            "app": "boards",
            "report_type_hint": None,
            "slug": None,
        },
    ),
    (
        "https://eu.mixpanel.com/project/3/view/75/app/boards#id=555",
        {
            "kind": "dashboard",
            "dashboard_id": 555,
            "host": "eu.mixpanel.com",
            "region": "eu",
            "project_id": 3,
            "workspace_id": 75,
            "app": "boards",
        },
    ),
    (
        f"https://in.mixpanel.com/project/3/view/75/app/boards#id=555&edited-bookmark={_SLUG}",
        {
            "kind": "slug",
            "slug": _SLUG,
            "dashboard_id": 555,
            "host": "in.mixpanel.com",
            "region": "in",
            "project_id": 3,
            "workspace_id": 75,
            "app": "boards",
            "report_type_hint": None,
        },
    ),
    (
        "https://eu.mixpanel.com/project/3/view/75/app/funnels#~(x)",
        {
            "kind": "legacy_jsurl",
            "host": "eu.mixpanel.com",
            "region": "eu",
            "project_id": 3,
            "workspace_id": 75,
            "app": "funnels",
            "report_type_hint": "funnels",
            "slug": None,
            "bookmark_id": None,
            "dashboard_id": None,
        },
    ),
    (
        f"https://mixpanel.com/project/3/app/boards#id=555&edited-bookmark={_SLUG}",
        {"kind": "slug", "slug": _SLUG, "dashboard_id": 555},
    ),
    (
        "https://mixpanel.com/project/3/app/insights#~(sections~(...))",
        {
            "kind": "legacy_jsurl",
            "host": "mixpanel.com",
            "region": "us",
            "project_id": 3,
            "workspace_id": None,
            "app": "insights",
            "report_type_hint": "insights",
            "slug": None,
            "bookmark_id": None,
        },
    ),
]

_ERROR_ROWS: list[tuple[str, str]] = [
    ("https://mixpanel.com/project/3/app/insights", "REPORT_LINK_EMPTY_HASH"),
    ("https://mixpanel.com/project/3/app/insights#", "REPORT_LINK_EMPTY_HASH"),
    (
        f"https://example.com/project/3/app/insights#{_SLUG}",
        "REPORT_LINK_NOT_MIXPANEL_HOST",
    ),
    (
        "https://api.mixpanel.com/project/3/app/insights#x",
        "REPORT_LINK_NOT_MIXPANEL_HOST",
    ),
    ("https://mixpanel.com/settings/project/3", "REPORT_LINK_UNRECOGNIZED_PATH"),
    (
        f"https://mixpanel.com/project/abc/app/insights#{_SLUG}",
        "REPORT_LINK_UNRECOGNIZED_PATH",
    ),
    (
        "https://mixpanel.com/project/3/app/insights#foo/bar",
        "REPORT_LINK_UNRECOGNIZED_HASH",
    ),
    (
        "https://mixpanel.com/project/3/app/insights#tooShort",
        "REPORT_LINK_UNRECOGNIZED_HASH",
    ),
    ("", "REPORT_LINK_UNPARSEABLE"),
    ("not a url at all", "REPORT_LINK_UNPARSEABLE"),
]


class TestParseTable:
    """Every row of url-grammar.md §5 parses to the documented kind and fields."""

    @pytest.mark.parametrize(("value", "expected"), _PARSE_ROWS)
    def test_row(self, value: str, expected: dict[str, Any]) -> None:
        """The parsed link carries the expected kind and fields."""
        parsed = parse_report_link(value)
        assert isinstance(parsed, ParsedReportLink)
        for name, want in expected.items():
            assert getattr(parsed, name) == want, name
        if "raw" not in expected:
            assert parsed.raw == value.strip()

    @pytest.mark.parametrize(("value", "code"), _ERROR_ROWS)
    def test_error_row(self, value: str, code: str) -> None:
        """Unrecognizable input raises ReportLinkParseError with the row's code."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link(value)
        assert exc_info.value.code == code
        assert "hint" in exc_info.value.details

    def test_unparseable_message(self) -> None:
        """§1 REPORT_LINK_UNPARSEABLE names the raw input."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("not a url at all")
        assert str(exc_info.value) == (
            "Could not parse report link: 'not a url at all'"
        )
        assert exc_info.value.details["hint"] == (
            "Pass a full Mixpanel report URL, a shortlink "
            "(https://mixpanel.com/s/...), or a 12-character slug."
        )

    def test_not_mixpanel_host_message(self) -> None:
        """§1 REPORT_LINK_NOT_MIXPANEL_HOST names the host."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("https://example.com/project/3/app/insights#x")
        assert str(exc_info.value) == (
            "Report link host 'example.com' is not a Mixpanel web host."
        )
        assert exc_info.value.details["host"] == "example.com"
        assert exc_info.value.details["hint"] == (
            "Expected mixpanel.com, eu.mixpanel.com, or in.mixpanel.com."
        )

    def test_unrecognized_path_message(self) -> None:
        """§1 REPORT_LINK_UNRECOGNIZED_PATH names the path."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("https://mixpanel.com/settings/project/3")
        assert str(exc_info.value) == (
            "Report link path '/settings/project/3' is not a report, "
            "dashboard, or shortlink path."
        )
        assert exc_info.value.details["path"] == "/settings/project/3"
        assert "/s/{code}" in exc_info.value.details["hint"]

    def test_unrecognized_hash_message(self) -> None:
        """§1 REPORT_LINK_UNRECOGNIZED_HASH names the hash."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("https://mixpanel.com/project/3/app/insights#foo/bar")
        assert str(exc_info.value) == (
            "Report link hash 'foo/bar' is not a slug, a saved report, "
            "or a dashboard reference."
        )
        assert exc_info.value.details["hash"] == "foo/bar"
        assert "12-character slug" in exc_info.value.details["hint"]

    def test_empty_hash_message(self) -> None:
        """§1 REPORT_LINK_EMPTY_HASH names the app."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("https://mixpanel.com/project/3/app/funnels#")
        assert str(exc_info.value) == (
            "Report link has no fragment after '#'. It points at the funnels "
            "app but not at a report."
        )
        assert exc_info.value.details["app"] == "funnels"
        assert exc_info.value.details["project_id"] == 3

    def test_parse_error_details_carry_parsed_fields(self) -> None:
        """A hash error still reports region and project from the path."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("https://eu.mixpanel.com/project/9/view/2/app/flows#x")
        details = exc_info.value.details
        assert details["region"] == "eu"
        assert details["project_id"] == 9
        assert details["workspace_id"] == 2

    def test_frozen(self) -> None:
        """ParsedReportLink rejects attribute assignment."""
        parsed = parse_report_link(_SLUG)
        with pytest.raises(AttributeError):
            parsed.slug = "x"  # type: ignore[misc]

    def test_boards_id_outside_boards_app_is_unrecognized(self) -> None:
        """``id=`` hashes are only dashboard references under the boards app."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("https://mixpanel.com/project/3/app/insights#id=555")
        assert exc_info.value.code == "REPORT_LINK_UNRECOGNIZED_HASH"

    def test_boards_with_invalid_edited_bookmark_is_dashboard(self) -> None:
        """A non-slug ``edited-bookmark`` value falls back to the dashboard kind."""
        parsed = parse_report_link(
            "https://mixpanel.com/project/3/app/boards#id=555&edited-bookmark=short"
        )
        assert parsed.kind == "dashboard"
        assert parsed.dashboard_id == 555
        assert parsed.slug is None

    def test_short_link_without_code_is_unrecognized_path(self) -> None:
        """``/s/`` with no code is not a shortlink."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("https://mixpanel.com/s/")
        assert exc_info.value.code == "REPORT_LINK_UNRECOGNIZED_PATH"

    def test_unknown_app_is_unrecognized_path(self) -> None:
        """An app segment outside the known set is a path error."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("https://mixpanel.com/project/3/app/users#abc")
        assert exc_info.value.code == "REPORT_LINK_UNRECOGNIZED_PATH"

    def test_non_ascii_digits_are_not_ids(self) -> None:
        """Unicode digits do not parse as a project id."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link(f"https://mixpanel.com/project/٣/app/insights#{_SLUG}")
        assert exc_info.value.code == "REPORT_LINK_UNRECOGNIZED_PATH"

    def test_bare_known_host_is_unrecognized_path(self) -> None:
        """A bare host with no path parses as a Mixpanel URL with no report path."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("mixpanel.com")
        assert exc_info.value.code == "REPORT_LINK_UNRECOGNIZED_PATH"

    def test_host_prefix_lookalike_is_unparseable(self) -> None:
        """``mixpanel.comx`` is not a known host, so no scheme is prepended."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link(f"mixpanel.comx/project/3/app/insights#{_SLUG}")
        assert exc_info.value.code == "REPORT_LINK_UNPARSEABLE"
        assert exc_info.value.details["raw"] == (
            f"mixpanel.comx/project/3/app/insights#{_SLUG}"
        )

    def test_boards_hash_without_id_is_unrecognized(self) -> None:
        """A boards fragment without ``id=`` is a hash error, never a crash."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("https://mixpanel.com/project/3/app/boards#foo=bar")
        assert exc_info.value.code == "REPORT_LINK_UNRECOGNIZED_HASH"

    def test_malformed_netloc_is_unparseable(self) -> None:
        """A netloc urlsplit rejects becomes REPORT_LINK_UNPARSEABLE."""
        with pytest.raises(ReportLinkParseError) as exc_info:
            parse_report_link("https://[::1/project/3/app/insights#x")
        assert exc_info.value.code == "REPORT_LINK_UNPARSEABLE"


# --- url-grammar.md §6 builders -----------------------------------------------


class TestBuilders:
    """Every row of url-grammar.md §6 builds the documented URL or raises."""

    def test_slug_us_with_workspace(self) -> None:
        """US, insights, workspace 75."""
        assert (
            build_slug_url(
                region="us",
                project_id=3,
                slug=_SLUG,
                report_type="insights",
                workspace_id=75,
            )
            == f"https://mixpanel.com/project/3/view/75/app/insights#{_SLUG}"
        )

    def test_slug_eu_funnels_uses_insights_app(self) -> None:
        """EU, funnels, no workspace: the Insights app hosts funnel slugs."""
        assert (
            build_slug_url(
                region="eu",
                project_id=3,
                slug=_SLUG,
                report_type="funnels",
            )
            == f"https://eu.mixpanel.com/project/3/app/insights#{_SLUG}"
        )

    def test_slug_in_flows(self) -> None:
        """IN, flows: the Flows app hosts flow slugs."""
        assert (
            build_slug_url(
                region="in",
                project_id=3,
                slug=_SLUG,
                report_type="flows",
            )
            == f"https://in.mixpanel.com/project/3/app/flows#{_SLUG}"
        )

    def test_slug_retention_uses_insights_app(self) -> None:
        """Retention slugs also live under the Insights app."""
        assert (
            build_slug_url(
                region="us",
                project_id=3,
                slug=_SLUG,
                report_type="retention",
            )
            == f"https://mixpanel.com/project/3/app/insights#{_SLUG}"
        )

    def test_bookmark_insights(self) -> None:
        """Insights saved report."""
        assert (
            build_bookmark_url(
                region="us",
                project_id=3,
                bookmark_id=123,
                report_type="insights",
            )
            == "https://mixpanel.com/project/3/app/insights#report/123"
        )

    def test_bookmark_funnels_with_workspace(self) -> None:
        """Funnels saved report uses the ``view/`` hash form."""
        assert (
            build_bookmark_url(
                region="us",
                project_id=3,
                bookmark_id=123,
                report_type="funnels",
                workspace_id=75,
            )
            == "https://mixpanel.com/project/3/view/75/app/funnels#view/123"
        )

    @pytest.mark.parametrize(
        ("report_type", "tail"),
        [
            ("retention", "retention#report/123"),
            ("flows", "flows#report/123"),
            ("launch-analysis", "impact#report/123"),
        ],
    )
    def test_bookmark_other_types(self, report_type: str, tail: str) -> None:
        """Retention, flows, and launch-analysis hash forms."""
        assert (
            build_bookmark_url(
                region="us",
                project_id=3,
                bookmark_id=123,
                report_type=report_type,
            )
            == f"https://mixpanel.com/project/3/app/{tail}"
        )

    def test_slug_unknown_type_raises_rl1(self) -> None:
        """``boards`` is not a slug report type."""
        with pytest.raises(ParamValidationError) as exc_info:
            build_slug_url(region="us", project_id=3, slug=_SLUG, report_type="boards")
        assert exc_info.value.code == "RL1_UNKNOWN_REPORT_TYPE"
        assert str(exc_info.value) == (
            "Unknown report type 'boards'. Expected one of: "
            "flows, funnels, insights, retention."
        )
        assert exc_info.value.details == {
            "report_type": "boards",
            "allowed": ["flows", "funnels", "insights", "retention"],
        }

    def test_bookmark_unknown_type_raises_rl1(self) -> None:
        """``boards`` is not a bookmark report type either."""
        with pytest.raises(ParamValidationError) as exc_info:
            build_bookmark_url(
                region="us", project_id=3, bookmark_id=1, report_type="boards"
            )
        assert exc_info.value.code == "RL1_UNKNOWN_REPORT_TYPE"
        assert "launch-analysis" in str(exc_info.value)

    def test_slug_invalid_slug_raises_rl2(self) -> None:
        """A short slug is rejected before the URL is built."""
        with pytest.raises(ParamValidationError) as exc_info:
            build_slug_url(
                region="us", project_id=3, slug="short", report_type="insights"
            )
        assert exc_info.value.code == "RL2_INVALID_SLUG"
        assert str(exc_info.value) == (
            "Invalid slug 'short'. A slug is exactly 12 characters from [0-9A-Za-z_-]."
        )
        assert exc_info.value.details == {"slug": "short"}

    @pytest.mark.parametrize("builder", ["slug", "bookmark"])
    def test_unknown_region_raises_rl3(self, builder: str) -> None:
        """Both builders reject an unknown region."""
        with pytest.raises(ParamValidationError) as exc_info:
            if builder == "slug":
                build_slug_url(
                    region="jp", project_id=3, slug=_SLUG, report_type="insights"
                )
            else:
                build_bookmark_url(
                    region="jp", project_id=3, bookmark_id=1, report_type="insights"
                )
        assert exc_info.value.code == "RL3_UNKNOWN_REGION"
