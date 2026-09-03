"""Pure parse and build helpers for Mixpanel report links (045-report-links).

A **report link** is a Mixpanel web URL that opens a report in the browser.
This module turns such a URL into a :class:`ParsedReportLink`, builds the
canonical URL for an unsaved-report slug or a saved report (bookmark), and
mints slugs. It is stdlib-only, makes no network calls, and is total: for
any input string :func:`parse_report_link` either returns a
:class:`ParsedReportLink` or raises :class:`ReportLinkParseError`.

The grammar is specified in ``specs/045-report-links/contracts/url-grammar.md``.
The constants below are the single place to change when Mixpanel moves an
app path (see ``SLUG_APP_FOR_TYPE``).

This is a private implementation detail. Use :class:`~mixpanel_headless.Workspace`
methods (``create_report_link``, ``resolve_report_link``, ``saved_report_link``)
instead of importing this module directly.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal
from urllib.parse import urlsplit

from mixpanel_headless._internal.auth.account import Region
from mixpanel_headless.exceptions import ParamValidationError, ReportLinkParseError

# =============================================================================
# Constants (data-model.md §8)
# =============================================================================

SLUG_ALPHABET: Final[str] = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
"""Characters the web app draws from when it mints a slug (no 0, I, O, l)."""

SLUG_LENGTH: Final[int] = 12
"""Length of every unsaved-report slug."""

SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-zA-Z_-]{12}$")
"""The server-side slug regex. Wider than the mint alphabet on purpose."""

WEB_HOSTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "us": "mixpanel.com",
        "eu": "eu.mixpanel.com",
        "in": "in.mixpanel.com",
    }
)
"""Web host per region. Builders always emit these hosts. Read-only."""

SLUG_APP_FOR_TYPE: Final[Mapping[str, str]] = MappingProxyType(
    {
        "insights": "insights",
        "funnels": "insights",
        "retention": "insights",
        "flows": "flows",
    }
)
"""App path segment used when a created slug URL is built, per report type.

The keys are exactly the :data:`~mixpanel_headless.types.ReportLinkType`
members; ``tests/unit/test_report_links.py`` locks that agreement.

Follows the Mixpanel MCP server: the Insights app hosts insights, funnels,
and retention slugs and reads ``type`` from the slug record; the Flows app
hosts flows slugs. If live QA shows the Insights app does not switch type,
change the ``funnels`` and ``retention`` rows here — one line each.
"""

BOOKMARK_HASH_FOR_TYPE: Final[Mapping[str, str]] = MappingProxyType(
    {
        "insights": "insights#report/{id}",
        "funnels": "funnels#view/{id}",
        "retention": "retention#report/{id}",
        "flows": "flows#report/{id}",
        "launch-analysis": "impact#report/{id}",
    }
)
"""``{app}#{hash}`` template per saved-report (bookmark) type.

The keys are exactly the :data:`~mixpanel_headless.types.BookmarkType` members.
"""

APP_TO_REPORT_TYPE: Final[Mapping[str, str]] = MappingProxyType(
    {
        "insights": "insights",
        "funnels": "funnels",
        "retention": "retention",
        "flows": "flows",
        "impact": "launch-analysis",
    }
)
"""Report type hinted by an app path segment. ``boards`` has no hint."""

ReportLinkKind = Literal["slug", "bookmark", "short_link", "dashboard", "legacy_jsurl"]
"""What a parsed link points at."""

_HOST_TO_REGION: Final[Mapping[str, Region]] = MappingProxyType(
    {
        "mixpanel.com": "us",
        "eu.mixpanel.com": "eu",
        "in.mixpanel.com": "in",
        "mixpanel.org": "us",
    }
)
"""Recognized web hosts. ``mixpanel.org`` parses as US; builders never emit it."""

_KNOWN_APPS: Final[frozenset[str]] = frozenset(
    {"insights", "funnels", "retention", "flows", "impact", "boards"}
)
"""App path segments the parser accepts."""

_ASCII_DIGITS_RE: Final[re.Pattern[str]] = re.compile(r"[0-9]+")
"""ASCII-only digit run. ``str.isdigit`` accepts Unicode digits; we do not."""

_SCHEME_RE: Final[re.Pattern[str]] = re.compile(r"https?://", re.IGNORECASE)
"""Leading URL scheme. Only ``http`` and ``https`` are accepted, any case."""

_PERCENT_HASH_RE: Final[re.Pattern[str]] = re.compile("%23", re.IGNORECASE)
"""A percent-encoded ``#``. The only escape the parser decodes."""

_SHORT_CODE_RE: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-z_\-]+")
"""Shortlink code after ``/s/``."""

_BOOKMARK_HASH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:report|segmentation-report|view)/([0-9]+)(?:/(?!~)([^/]+))?(?:/(~.*))?",
    re.DOTALL,
)
"""``report/{id}[/{title}][/~(...)]``, ``segmentation-report/{id}``, ``view/{id}``."""

_UNPARSEABLE_HINT: Final[str] = (
    "Pass a full Mixpanel report URL, a shortlink (https://mixpanel.com/s/...), "
    "or a 12-character slug."
)
_HOST_HINT: Final[str] = "Expected mixpanel.com, eu.mixpanel.com, or in.mixpanel.com."
_PATH_HINT: Final[str] = (
    "Expected /project/{id}/app/{app}#..., "
    "/project/{id}/view/{wid}/app/{app}#..., or /s/{code}."
)
_HASH_HINT: Final[str] = (
    "Expected a 12-character slug, report/{id}, view/{id}, or id={dashboard_id}."
)
_EMPTY_HASH_HINT: Final[str] = (
    "Open the report in the browser and copy the full URL including the part after '#'."
)


# =============================================================================
# Parsed link
# =============================================================================


@dataclass(frozen=True)
class ParsedReportLink:
    """The structured parts of a report link string. Pure data.

    Attributes:
        kind: What the link points at.
        raw: The input after ``strip()``.
        host: Lower-case host without port. ``None`` for a bare slug.
        region: Region derived from the host. ``mixpanel.org`` maps to ``us``.
        project_id: From ``/project/{pid}/`` or legacy ``/report/{pid}/``.
        workspace_id: From ``/view/{wid}/``.
        app: The app path segment (``insights``, ``funnels``, ``retention``,
            ``flows``, ``impact``, ``boards``).
        report_type_hint: ``APP_TO_REPORT_TYPE[app]``. The server-stored type
            is authoritative; this is a hint only.
        slug: Set when ``kind == "slug"``.
        bookmark_id: Set when ``kind == "bookmark"``.
        dashboard_id: Set for ``boards#id=`` links, kept when an
            ``edited-bookmark`` slug is also present.
        short_code: Set when ``kind == "short_link"``.
        title_segment: The kebab title after ``#report/{id}/``.
        overrides_jsurl: The raw ``~(...)`` tail after a bookmark hash. Never
            decoded.
    """

    kind: ReportLinkKind
    raw: str
    host: str | None = None
    region: Region | None = None
    project_id: int | None = None
    workspace_id: int | None = None
    app: str | None = None
    report_type_hint: str | None = None
    slug: str | None = None
    bookmark_id: int | None = None
    dashboard_id: int | None = None
    short_code: str | None = None
    title_segment: str | None = None
    overrides_jsurl: str | None = None


# =============================================================================
# Small pure helpers
# =============================================================================


def web_host(region: str) -> str:
    """Return the Mixpanel web host for a region.

    Args:
        region: One of ``us``, ``eu``, ``in``.

    Returns:
        The host, for example ``eu.mixpanel.com``.

    Raises:
        ParamValidationError: ``RL3_UNKNOWN_REGION`` when the region is not
            in :data:`WEB_HOSTS`.
    """
    host = WEB_HOSTS.get(region)
    if host is None:
        raise ParamValidationError(
            f"Unknown region {region!r}. Expected one of: us, eu, in.",
            code="RL3_UNKNOWN_REGION",
            details={"region": region},
        )
    return host


def is_slug(value: str) -> bool:
    """Return whether ``value`` matches the server slug regex.

    Args:
        value: Any string.

    Returns:
        ``True`` for exactly 12 characters from ``[0-9A-Za-z_-]``.
    """
    return SLUG_RE.fullmatch(value) is not None


def generate_slug(*, choice: Callable[[str], str] = secrets.choice) -> str:
    """Mint a new 12-character slug from :data:`SLUG_ALPHABET`.

    Args:
        choice: Function that picks one character from the alphabet. Defaults
            to :func:`secrets.choice`. Tests inject a deterministic chooser.

    Returns:
        A slug for which :func:`is_slug` is true.

    Example:
        ```python
        generate_slug(choice=lambda alphabet: alphabet[0])
        # "111111111111"
        ```
    """
    return "".join(choice(SLUG_ALPHABET) for _ in range(SLUG_LENGTH))


def _require_positive_id(field: str, value: int) -> None:
    """Reject an id that the parser could never read back.

    The path and hash grammars accept ASCII digit runs only, so a zero or
    negative id would build a URL that :func:`parse_report_link` rejects.
    Checking here keeps the build-then-parse round trip total.

    Args:
        field: The parameter name, for the message and ``details``.
        value: The id to check.

    Raises:
        ParamValidationError: ``RL6_INVALID_ID`` when ``value`` is not a
            positive integer.
    """
    if value <= 0:
        raise ParamValidationError(
            f"Invalid {field} {value}. An id is a positive integer.",
            code="RL6_INVALID_ID",
            details={"field": field, "value": value},
        )


def _project_path(project_id: int, workspace_id: int | None) -> str:
    """Return ``/project/{pid}`` with an optional ``/view/{wid}`` segment.

    Args:
        project_id: Project id.
        workspace_id: Optional workspace id.

    Returns:
        The path prefix without the ``/app/...`` tail.

    Raises:
        ParamValidationError: ``RL6_INVALID_ID`` when either id is not a
            positive integer.
    """
    _require_positive_id("project_id", project_id)
    if workspace_id is None:
        return f"/project/{project_id}"
    _require_positive_id("workspace_id", workspace_id)
    return f"/project/{project_id}/view/{workspace_id}"


def _lookup_type(table: Mapping[str, str], report_type: str) -> str:
    """Look up a report type in a builder table.

    Args:
        table: :data:`SLUG_APP_FOR_TYPE` or :data:`BOOKMARK_HASH_FOR_TYPE`.
        report_type: The type to look up.

    Returns:
        The table value.

    Raises:
        ParamValidationError: ``RL1_UNKNOWN_REPORT_TYPE`` when the type is
            not a key of ``table``.
    """
    value = table.get(report_type)
    if value is None:
        allowed = ", ".join(sorted(table))
        raise ParamValidationError(
            f"Unknown report type {report_type!r}. Expected one of: {allowed}.",
            code="RL1_UNKNOWN_REPORT_TYPE",
            details={"report_type": report_type, "allowed": sorted(table)},
        )
    return value


# =============================================================================
# Builders
# =============================================================================


def build_slug_url(
    *,
    region: str,
    project_id: int,
    slug: str,
    report_type: str,
    workspace_id: int | None = None,
) -> str:
    """Build the web URL for an unsaved-report slug.

    Args:
        region: Session region (``us``, ``eu``, ``in``).
        project_id: Project the slug record lives in.
        slug: The 12-character slug.
        report_type: One of the :data:`SLUG_APP_FOR_TYPE` keys.
        workspace_id: Optional workspace for the ``/view/{wid}`` segment.

    Returns:
        ``https://{host}/project/{pid}[/view/{wid}]/app/{app}#{slug}``.

    Raises:
        ParamValidationError: ``RL3_UNKNOWN_REGION``, ``RL1_UNKNOWN_REPORT_TYPE``,
            ``RL2_INVALID_SLUG``, or ``RL6_INVALID_ID`` (a zero or negative
            project or workspace id).

    Example:
        ```python
        build_slug_url(
            region="us", project_id=3, slug="EBrV5bW2u9Mw",
            report_type="insights", workspace_id=75,
        )
        # "https://mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw"
        ```
    """
    host = web_host(region)
    app = _lookup_type(SLUG_APP_FOR_TYPE, report_type)
    if not is_slug(slug):
        raise ParamValidationError(
            f"Invalid slug {slug!r}. A slug is exactly 12 characters from "
            f"[0-9A-Za-z_-].",
            code="RL2_INVALID_SLUG",
            details={"slug": slug},
        )
    return f"https://{host}{_project_path(project_id, workspace_id)}/app/{app}#{slug}"


def build_bookmark_url(
    *,
    region: str,
    project_id: int,
    bookmark_id: int,
    report_type: str,
    workspace_id: int | None = None,
) -> str:
    """Build the web URL for a saved report (bookmark).

    Args:
        region: Session region (``us``, ``eu``, ``in``).
        project_id: Project the bookmark lives in.
        bookmark_id: Numeric saved-report id.
        report_type: One of the :data:`BOOKMARK_HASH_FOR_TYPE` keys.
        workspace_id: Optional workspace for the ``/view/{wid}`` segment.

    Returns:
        ``https://{host}/project/{pid}[/view/{wid}]/app/{app}#{hash}``.

    Raises:
        ParamValidationError: ``RL3_UNKNOWN_REGION``, ``RL1_UNKNOWN_REPORT_TYPE``,
            or ``RL6_INVALID_ID`` (a zero or negative project, workspace, or
            bookmark id).

    Example:
        ```python
        build_bookmark_url(
            region="us", project_id=3, bookmark_id=123, report_type="funnels"
        )
        # "https://mixpanel.com/project/3/app/funnels#view/123"
        ```
    """
    host = web_host(region)
    _require_positive_id("bookmark_id", bookmark_id)
    tail = _lookup_type(BOOKMARK_HASH_FOR_TYPE, report_type).format(id=bookmark_id)
    return f"https://{host}{_project_path(project_id, workspace_id)}/app/{tail}"


# =============================================================================
# Parser
# =============================================================================


def _unparseable(raw: str) -> ReportLinkParseError:
    """Build the ``REPORT_LINK_UNPARSEABLE`` error.

    Args:
        raw: The stripped input.

    Returns:
        The error, ready to raise.
    """
    return ReportLinkParseError(
        f"Could not parse report link: {raw!r}",
        code="REPORT_LINK_UNPARSEABLE",
        details={"raw": raw, "hint": _UNPARSEABLE_HINT},
    )


def _starts_with_known_host(value: str) -> bool:
    """Return whether a scheme-less string starts with a Mixpanel web host.

    Args:
        value: The input without a leading scheme.

    Returns:
        ``True`` when the string starts with a known host followed by the end
        of the string, ``/``, ``:``, ``#``, or ``?``.
    """
    lowered = value.lower()
    for host in _HOST_TO_REGION:
        if lowered.startswith(host):
            rest = lowered[len(host) :]
            if rest == "" or rest[0] in "/:#?":
                return True
    return False


def _parse_path(
    segments: list[str],
) -> tuple[str | None, int | None, int | None, str | None]:
    """Match the path segments against the recognized path forms.

    Args:
        segments: Non-empty path segments.

    Returns:
        ``(short_code, project_id, workspace_id, app)``. Exactly one of
        ``short_code`` or the ``(project_id, app)`` pair is set on success.
        All four are ``None`` when nothing matched.
    """
    n = len(segments)
    if n == 2 and segments[0] == "s" and _SHORT_CODE_RE.fullmatch(segments[1]):
        return segments[1], None, None, None

    pid_s: str | None = None
    wid_s: str | None = None
    app: str | None = None
    if n == 4 and segments[0] == "project" and segments[2] == "app":
        pid_s, app = segments[1], segments[3]
    elif (
        n == 6
        and segments[0] == "project"
        and segments[2] == "view"
        and segments[4] == "app"
    ):
        pid_s, wid_s, app = segments[1], segments[3], segments[5]
    elif n == 3 and segments[0] == "report":
        pid_s, app = segments[1], segments[2]
    elif n == 5 and segments[0] == "report" and segments[2] == "view":
        pid_s, wid_s, app = segments[1], segments[3], segments[4]
    else:
        return None, None, None, None

    if pid_s is None or not _ASCII_DIGITS_RE.fullmatch(pid_s):
        return None, None, None, None
    if wid_s is not None and not _ASCII_DIGITS_RE.fullmatch(wid_s):
        return None, None, None, None
    if app not in _KNOWN_APPS:
        return None, None, None, None
    return None, int(pid_s), (int(wid_s) if wid_s is not None else None), app


def _fragment_fields(fragment: str) -> dict[str, str]:
    """Split a ``k=v&k2=v2`` fragment into a dict. Keeps the first of dupes.

    Args:
        fragment: The URL fragment.

    Returns:
        Mapping of key to value for every ``k=v`` pair.
    """
    fields: dict[str, str] = {}
    for pair in fragment.split("&"):
        key, sep, value = pair.partition("=")
        if sep and key not in fields:
            fields[key] = value
    return fields


def _trim_fragment(fragment: str) -> str:
    """Drop a query tail and trailing slashes from a hash that has no JSURL.

    A browser or a link builder can append ``?utm=x`` or a ``/`` after the
    slug or the ``report/{id}`` hash. A hash that contains ``~`` carries a
    JSURL override or legacy body, which may hold ``?`` and ``/`` itself, so
    it is returned unchanged.

    Args:
        fragment: The raw URL fragment.

    Returns:
        The fragment to match against the hash grammar.
    """
    if "~" in fragment:
        return fragment
    head, _, _ = fragment.partition("?")
    return head.rstrip("/")


def parse_report_link(value: str) -> ParsedReportLink:
    """Parse a Mixpanel report link, shortlink, or bare slug.

    Normalization (url-grammar.md §1): strip, decode ``%23`` to ``#`` when
    there is no ``#`` (no other escape is decoded), prepend ``https://`` for
    a scheme-less known host, lower-case the host, drop the port, ignore the
    query string, drop empty path segments, and drop a ``?`` tail or trailing
    ``/`` from a hash that carries no ``~`` JSURL body. A scheme other than
    ``http`` or ``https`` is not a report link.

    The parser is total. It returns a :class:`ParsedReportLink` for every
    recognizable Mixpanel URL, including dashboards and legacy JSURL hashes,
    and raises :class:`ReportLinkParseError` for everything else.

    Args:
        value: A full URL, a ``https://mixpanel.com/s/{code}`` shortlink, or
            a bare 12-character slug.

    Returns:
        The parsed link.

    Raises:
        ReportLinkParseError: With code ``REPORT_LINK_UNPARSEABLE``,
            ``REPORT_LINK_NOT_MIXPANEL_HOST``, ``REPORT_LINK_UNRECOGNIZED_PATH``,
            ``REPORT_LINK_UNRECOGNIZED_HASH``, or ``REPORT_LINK_EMPTY_HASH``.

    Example:
        ```python
        parsed = parse_report_link(
            "https://mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw"
        )
        parsed.kind        # "slug"
        parsed.project_id  # 3
        parsed.slug        # "EBrV5bW2u9Mw"
        ```
    """
    raw = value.strip()
    if not raw:
        raise _unparseable(raw)
    if is_slug(raw):
        return ParsedReportLink(kind="slug", raw=raw, slug=raw)

    normalized = raw
    if "#" not in normalized:
        normalized = _PERCENT_HASH_RE.sub("#", normalized)
    if not _SCHEME_RE.match(normalized):
        if not _starts_with_known_host(normalized):
            raise _unparseable(raw)
        normalized = f"https://{normalized}"

    try:
        parts = urlsplit(normalized)
        host = parts.hostname
    except ValueError:
        raise _unparseable(raw) from None
    if not host:
        raise _unparseable(raw)

    region = _HOST_TO_REGION.get(host)
    if region is None:
        raise ReportLinkParseError(
            f"Report link host {host!r} is not a Mixpanel web host.",
            code="REPORT_LINK_NOT_MIXPANEL_HOST",
            details={"raw": raw, "host": host, "hint": _HOST_HINT},
        )

    segments = [s for s in parts.path.split("/") if s]
    short_code, project_id, workspace_id, app = _parse_path(segments)
    if short_code is not None:
        return ParsedReportLink(
            kind="short_link",
            raw=raw,
            host=host,
            region=region,
            short_code=short_code,
        )
    if project_id is None or app is None:
        raise ReportLinkParseError(
            f"Report link path {parts.path!r} is not a report, dashboard, "
            f"or shortlink path.",
            code="REPORT_LINK_UNRECOGNIZED_PATH",
            details={
                "raw": raw,
                "host": host,
                "region": region,
                "path": parts.path,
                "hint": _PATH_HINT,
            },
        )

    base: dict[str, object] = {
        "raw": raw,
        "host": host,
        "region": region,
        "project_id": project_id,
        "workspace_id": workspace_id,
        "app": app,
    }
    hint = APP_TO_REPORT_TYPE.get(app)
    fragment = _trim_fragment(parts.fragment)
    if not fragment:
        raise ReportLinkParseError(
            f"Report link has no fragment after '#'. It points at the {app} app "
            f"but not at a report.",
            code="REPORT_LINK_EMPTY_HASH",
            details={**base, "hint": _EMPTY_HASH_HINT},
        )

    bookmark_match = _BOOKMARK_HASH_RE.fullmatch(fragment)
    if bookmark_match is not None:
        return ParsedReportLink(
            kind="bookmark",
            raw=raw,
            host=host,
            region=region,
            project_id=project_id,
            workspace_id=workspace_id,
            app=app,
            report_type_hint=hint,
            bookmark_id=int(bookmark_match.group(1)),
            title_segment=bookmark_match.group(2),
            overrides_jsurl=bookmark_match.group(3),
        )

    if app == "boards":
        fields = _fragment_fields(fragment)
        dashboard_s = fields.get("id")
        if dashboard_s is not None and _ASCII_DIGITS_RE.fullmatch(dashboard_s):
            dashboard_id = int(dashboard_s)
            edited = fields.get("edited-bookmark")
            if edited is not None and is_slug(edited):
                return ParsedReportLink(
                    kind="slug",
                    raw=raw,
                    host=host,
                    region=region,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    app=app,
                    report_type_hint=hint,
                    slug=edited,
                    dashboard_id=dashboard_id,
                )
            return ParsedReportLink(
                kind="dashboard",
                raw=raw,
                host=host,
                region=region,
                project_id=project_id,
                workspace_id=workspace_id,
                app=app,
                report_type_hint=hint,
                dashboard_id=dashboard_id,
            )

    if is_slug(fragment):
        return ParsedReportLink(
            kind="slug",
            raw=raw,
            host=host,
            region=region,
            project_id=project_id,
            workspace_id=workspace_id,
            app=app,
            report_type_hint=hint,
            slug=fragment,
        )

    if fragment.startswith("~"):
        return ParsedReportLink(
            kind="legacy_jsurl",
            raw=raw,
            host=host,
            region=region,
            project_id=project_id,
            workspace_id=workspace_id,
            app=app,
            report_type_hint=hint,
        )

    raise ReportLinkParseError(
        f"Report link hash {fragment!r} is not a slug, a saved report, "
        f"or a dashboard reference.",
        code="REPORT_LINK_UNRECOGNIZED_HASH",
        details={**base, "hash": fragment, "hint": _HASH_HINT},
    )
