"""Property-based tests for the pure report-link module (045-report-links).

Covers the seven invariants in contracts/url-grammar.md §7. Hypothesis
profiles come from ``tests/conftest.py`` (``default``, ``dev``, ``ci``).
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.report_links import (
    BOOKMARK_HASH_FOR_TYPE,
    SLUG_ALPHABET,
    SLUG_APP_FOR_TYPE,
    ParsedReportLink,
    build_bookmark_url,
    build_slug_url,
    generate_slug,
    is_slug,
    parse_report_link,
)
from mixpanel_headless.exceptions import ParamValidationError, ReportLinkParseError

_SERVER_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-"
_SERVER_RE = re.compile(r"^[0-9a-zA-Z_-]{12}$")

regions = st.sampled_from(["us", "eu", "in"])
project_ids = st.integers(min_value=1, max_value=10**9)
workspace_ids = st.none() | st.integers(min_value=1, max_value=10**9)
slugs = st.text(alphabet=_SERVER_ALPHABET, min_size=12, max_size=12)
slug_types = st.sampled_from(sorted(SLUG_APP_FOR_TYPE))
bookmark_types = st.sampled_from(sorted(BOOKMARK_HASH_FOR_TYPE))
bookmark_ids = st.integers(min_value=1, max_value=10**9)


def _decorate(url: str, variant: str) -> str:
    """Apply one decoration variant to a built URL.

    Args:
        url: A URL produced by ``build_slug_url`` or ``build_bookmark_url``.
        variant: One of ``trailing_slash``, ``query``, ``upper_host``,
            ``no_scheme``, ``percent_hash``.

    Returns:
        The decorated URL string.
    """
    head, _, fragment = url.partition("#")
    if variant == "trailing_slash":
        return f"{head}/#{fragment}"
    if variant == "query":
        return f"{head}?utm=x#{fragment}"
    if variant == "upper_host":
        scheme, _, rest = url.partition("://")
        host, _, tail = rest.partition("/")
        return f"{scheme}://{host.upper()}/{tail}"
    if variant == "no_scheme":
        return url.split("://", 1)[1]
    if variant == "percent_hash":
        return f"{head}%23{fragment}"
    raise AssertionError(variant)  # pragma: no cover


class TestSlugInvariants:
    """§7.1 and §7.7: generated slugs and non-slugs."""

    @given(st.integers())
    def test_generate_slug_shape(self, _seed: int) -> None:
        """Every generated slug has length 12, alphabet chars, and is a slug."""
        slug = generate_slug()
        assert len(slug) == 12
        assert all(c in SLUG_ALPHABET for c in slug)
        assert is_slug(slug)

    @given(st.text())
    def test_is_slug_matches_server_regex(self, value: str) -> None:
        """``is_slug`` agrees with the server regex for any text."""
        assert is_slug(value) is bool(_SERVER_RE.fullmatch(value))

    @given(
        st.text().filter(
            lambda s: len(s) != 12 or any(c not in _SERVER_ALPHABET for c in s)
        )
    )
    def test_non_slugs_are_never_slugs(self, value: str) -> None:
        """Wrong length or a char outside the server alphabet is never a slug."""
        assert is_slug(value) is False


class TestRoundTrips:
    """§7.2 and §7.3: build then parse recovers the inputs."""

    @given(regions, project_ids, workspace_ids, slugs, slug_types)
    def test_slug_url_round_trip(
        self, region: str, pid: int, wid: int | None, slug: str, report_type: str
    ) -> None:
        """A built slug URL parses back to the same region, ids, and slug."""
        url = build_slug_url(
            region=region,
            project_id=pid,
            slug=slug,
            report_type=report_type,
            workspace_id=wid,
        )
        parsed = parse_report_link(url)
        assert parsed.kind == "slug"
        assert parsed.region == region
        assert parsed.project_id == pid
        assert parsed.workspace_id == wid
        assert parsed.slug == slug
        assert parsed.app == SLUG_APP_FOR_TYPE[report_type]

    @given(regions, project_ids, workspace_ids, bookmark_ids, bookmark_types)
    def test_bookmark_url_round_trip(
        self, region: str, pid: int, wid: int | None, bid: int, report_type: str
    ) -> None:
        """A built bookmark URL parses back with the type as the hint."""
        url = build_bookmark_url(
            region=region,
            project_id=pid,
            bookmark_id=bid,
            report_type=report_type,
            workspace_id=wid,
        )
        parsed = parse_report_link(url)
        assert parsed.kind == "bookmark"
        assert parsed.region == region
        assert parsed.project_id == pid
        assert parsed.workspace_id == wid
        assert parsed.bookmark_id == bid
        assert parsed.report_type_hint == report_type


class TestNonPositiveIds:
    """§7.8 (review follow-up): a built URL always parses, so bad ids never build."""

    @given(regions, st.integers(max_value=0), slugs, slug_types)
    def test_slug_builder_rejects_non_positive_project(
        self, region: str, pid: int, slug: str, report_type: str
    ) -> None:
        """Any project id at or below zero raises RL6 before a URL exists."""
        with pytest.raises(ParamValidationError) as exc_info:
            build_slug_url(
                region=region, project_id=pid, slug=slug, report_type=report_type
            )
        assert exc_info.value.code == "RL6_INVALID_ID"

    @given(regions, project_ids, st.integers(max_value=0), bookmark_ids, bookmark_types)
    def test_bookmark_builder_rejects_non_positive_workspace(
        self, region: str, pid: int, wid: int, bid: int, report_type: str
    ) -> None:
        """Any workspace id at or below zero raises RL6 before a URL exists."""
        with pytest.raises(ParamValidationError) as exc_info:
            build_bookmark_url(
                region=region,
                project_id=pid,
                bookmark_id=bid,
                report_type=report_type,
                workspace_id=wid,
            )
        assert exc_info.value.code == "RL6_INVALID_ID"

    @given(regions, project_ids, st.integers(max_value=0), bookmark_types)
    def test_bookmark_builder_rejects_non_positive_bookmark(
        self, region: str, pid: int, bid: int, report_type: str
    ) -> None:
        """Any bookmark id at or below zero raises RL6 before a URL exists."""
        with pytest.raises(ParamValidationError) as exc_info:
            build_bookmark_url(
                region=region, project_id=pid, bookmark_id=bid, report_type=report_type
            )
        assert exc_info.value.code == "RL6_INVALID_ID"


class TestDecorationInvariance:
    """§7.4: decorations change ``raw`` only."""

    @given(
        regions,
        project_ids,
        workspace_ids,
        slugs,
        slug_types,
        st.sampled_from(
            ["trailing_slash", "query", "upper_host", "no_scheme", "percent_hash"]
        ),
    )
    def test_slug_url_decorations(
        self,
        region: str,
        pid: int,
        wid: int | None,
        slug: str,
        report_type: str,
        variant: str,
    ) -> None:
        """Each decoration of a slug URL parses to an equal result modulo raw."""
        url = build_slug_url(
            region=region,
            project_id=pid,
            slug=slug,
            report_type=report_type,
            workspace_id=wid,
        )
        base = parse_report_link(url)
        decorated = _decorate(url, variant)
        got = parse_report_link(decorated)
        assert replace(got, raw=base.raw) == base

    @given(
        regions,
        project_ids,
        workspace_ids,
        bookmark_ids,
        bookmark_types,
        st.sampled_from(
            ["trailing_slash", "query", "upper_host", "no_scheme", "percent_hash"]
        ),
    )
    def test_bookmark_url_decorations(
        self,
        region: str,
        pid: int,
        wid: int | None,
        bid: int,
        report_type: str,
        variant: str,
    ) -> None:
        """Each decoration of a bookmark URL parses to an equal result modulo raw."""
        url = build_bookmark_url(
            region=region,
            project_id=pid,
            bookmark_id=bid,
            report_type=report_type,
            workspace_id=wid,
        )
        base = parse_report_link(url)
        got = parse_report_link(_decorate(url, variant))
        assert replace(got, raw=base.raw) == base


def _assert_kind_fields(parsed: ParsedReportLink) -> None:
    """Assert the per-kind id field invariants of url-grammar.md §7.6.

    Args:
        parsed: Any parse result.
    """
    if parsed.kind == "slug":
        assert parsed.slug is not None
        assert is_slug(parsed.slug)
    elif parsed.kind == "bookmark":
        assert parsed.bookmark_id is not None
    elif parsed.kind == "short_link":
        assert parsed.short_code is not None
        assert parsed.region is not None
    elif parsed.kind == "dashboard":
        assert parsed.dashboard_id is not None
    else:
        assert parsed.kind == "legacy_jsurl"


class TestTotality:
    """§7.5 and §7.6: the parser never raises anything but a parse error."""

    @given(st.text())
    def test_any_text(self, value: str) -> None:
        """Any text returns a ParsedReportLink or raises ReportLinkParseError."""
        try:
            parsed = parse_report_link(value)
        except ReportLinkParseError:
            return
        assert isinstance(parsed, ParsedReportLink)
        _assert_kind_fields(parsed)

    @given(
        st.sampled_from(["mixpanel.com", "eu.mixpanel.com", "in.mixpanel.com"]),
        st.text(max_size=60),
        st.text(max_size=40),
    )
    def test_mixpanel_host_with_random_path_and_hash(
        self, host: str, path: str, fragment: str
    ) -> None:
        """Random paths and hashes under a Mixpanel host are total too."""
        value = f"https://{host}/{path}#{fragment}"
        try:
            parsed = parse_report_link(value)
        except ReportLinkParseError as exc:
            assert exc.code.startswith("REPORT_LINK_")
            return
        _assert_kind_fields(parsed)

    @given(regions, project_ids, workspace_ids, slugs, slug_types)
    def test_bare_slug_has_no_scope(
        self, region: str, pid: int, wid: int | None, slug: str, report_type: str
    ) -> None:
        """A bare slug parses with host, region, project, and workspace unset."""
        parsed = parse_report_link(slug)
        assert parsed.kind == "slug"
        assert parsed.slug == slug
        assert (parsed.host, parsed.region, parsed.project_id, parsed.workspace_id) == (
            None,
            None,
            None,
            None,
        )


@pytest.mark.parametrize(
    "variant", ["trailing_slash", "query", "upper_host", "no_scheme", "percent_hash"]
)
def test_decorate_helper_changes_the_string(variant: str) -> None:
    """The test helper produces a string different from its input."""
    url = "https://mixpanel.com/project/3/app/insights#EBrV5bW2u9Mw"
    assert _decorate(url, variant) != url
