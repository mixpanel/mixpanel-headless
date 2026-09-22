"""``mp help`` Typer command.

Offline reference help for the library. The command wraps
:func:`mixpanel_headless.reference.describe` /
:func:`mixpanel_headless.reference.search` and prints the rendered text with
``typer.echo`` only, so literal tags such as ``[property]`` survive.

Unlike the entity commands, the default output format is ``text``,
because the command is documentation, not data. The command never calls
``get_workspace`` or ``get_config``, ignores the global ``-a/-p/-w/-t``
flags, and touches no file.

Exit codes:
    0: entry found and printed, or a search with at least one hit.
    2: an option value the parser rejects (``-f table``); Click prints the
       usage error.
    3: flag misuse, reported on stderr with nothing on stdout: ``--jq``
       without ``-f json``, ``search`` with no term, or a ``--domain`` that is
       unknown, ambiguous, or paired with a query other than ``Workspace``
       (``HelpDomainError``; the valid titles follow on one ``Domains:``
       line).
    4: not found. A describe miss prints the message and suggestions on
       stdout (a JSON error object under ``-f json``); a search with no
       hits prints its normal view first (``{"term": ..., "hits": []}``
       under ``-f json``). A name miss exits 4 even when ``--domain`` was
       passed.
"""

from __future__ import annotations

import json
from typing import Annotated, cast

import click
import typer

from mixpanel_headless._internal.help.models import HELP_FORMATS
from mixpanel_headless.cli.utils import ExitCode, _apply_jq_filter, handle_errors
from mixpanel_headless.exceptions import HelpDomainError, HelpLookupError
from mixpanel_headless.reference import (
    HelpFormat,
    describe,
    render,
    render_miss,
    search,
)

HelpFormatOption = Annotated[
    str,
    typer.Option(
        "--format",
        "-f",
        help="Output format (default text).",
        click_type=click.Choice(list(HELP_FORMATS)),
    ),
]
"""``-f/--format`` restricted to the library's help formats."""

_SEARCH_USAGE = "search needs a term. Usage: mp help search <term>"
"""Error line for a bare ``search`` query (printed on stderr by ``_fail``)."""


def _emit(text: str) -> None:
    """Write ``text`` to stdout without Rich markup processing.

    Args:
        text: Rendered help text.
    """
    typer.echo(text)


def _fail(message: str, code: ExitCode) -> None:
    """Print ``message`` to stderr and exit with ``code``.

    Args:
        message: Human-readable error line.
        code: Exit code to raise.

    Raises:
        typer.Exit: Always, with ``code``.
    """
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code)


def _domain_error_text(exc: HelpDomainError) -> str:
    """Build the stderr text for a rejected ``--domain``.

    Args:
        exc: The domain error raised by :func:`describe`.

    Returns:
        The error message, followed by one ``Domains: ...`` line when the
        error carries titles to offer (unknown or ambiguous domain).
    """
    if not exc.domains:
        return exc.message
    return f"{exc.message}\nDomains: {', '.join(exc.domains)}"


def _apply_jq(text: str, expr: str) -> str:
    """Apply a jq expression to a JSON document and re-serialize the results.

    Args:
        text: JSON text produced by the ``json`` renderer.
        expr: jq filter expression.

    Returns:
        One JSON document per line when the filter yields several values, the
        single value otherwise.

    Raises:
        typer.Exit: When the filter is invalid (exit 3, from the shared helper).
    """
    values = _apply_jq_filter(text, expr)
    if len(values) == 1:
        return json.dumps(values[0], indent=2)
    return "\n".join(json.dumps(v) for v in values)


@handle_errors
def help_command(
    query: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Query tokens, e.g. Workspace.query, Filter, MathType, types, "
                "exceptions, or 'search cohort'. Omit for the overview."
            ),
            show_default=False,
        ),
    ] = None,
    format: HelpFormatOption = "text",
    jq: Annotated[
        str | None,
        typer.Option("--jq", help="Apply a jq filter (requires -f json)."),
    ] = None,
    domain: Annotated[
        str | None,
        typer.Option(
            "--domain",
            help="Restrict the Workspace listing to one domain (unique prefix ok).",
        ),
    ] = None,
    no_hints: Annotated[
        bool,
        typer.Option("--no-hints", help="Suppress the hosted-docs Tip block."),
    ] = False,
) -> None:
    """Built-in API reference for mixpanel_headless (offline, no auth).

    Args:
        query: Query tokens joined with spaces; ``None`` prints the overview.
        format: ``text`` (default), ``markdown``, or ``json``.
        jq: Optional jq expression, applied to the ``json`` output only.
        domain: Optional domain filter for the ``Workspace`` listing.
        no_hints: When set, omit the ``Tip:`` block.

    Raises:
        typer.Exit: Exit 3 for flag misuse (``--jq`` without ``-f json``, a
            bare ``search``, a rejected ``--domain``); exit 4 for a lookup
            miss or a search with no hits.

    Example:
        ```bash
        mp help                              # overview
        mp help Workspace --domain "funnel query"
        mp help Workspace.query.events       # one parameter
        mp help Filter -f json --jq '.construction[].name'
        mp help search cohort
        python3 -m mixpanel_headless help types   # when mp is not on PATH
        ```
    """
    from mixpanel_headless._internal.help.resolve import parse_query

    if jq is not None and format != "json":
        _fail("--jq requires --format json", ExitCode.INVALID_ARGS)

    fmt = cast(HelpFormat, format)
    text = " ".join(query or ())
    mode, payload = parse_query(text)

    exit_code = 0
    if mode == "search":
        if not payload:
            _fail(_SEARCH_USAGE, ExitCode.INVALID_ARGS)
        result = search(payload)
        rendered = render(result, fmt)
        if not result.hits:
            exit_code = ExitCode.NOT_FOUND
    else:
        target = None if mode == "overview" else payload
        try:
            entry = describe(target, hints=not no_hints, domain=domain)
        except HelpDomainError as exc:
            # The query resolved; the flag is wrong. Caught before the
            # plain miss because it is a subclass of HelpLookupError.
            _fail(_domain_error_text(exc), ExitCode.INVALID_ARGS)
        except HelpLookupError as exc:
            _emit(render_miss(exc, fmt))
            raise typer.Exit(ExitCode.NOT_FOUND) from None
        rendered = render(entry, fmt)

    if jq is not None:
        rendered = _apply_jq(rendered, jq)
    _emit(rendered)
    if exit_code:
        raise typer.Exit(exit_code)
