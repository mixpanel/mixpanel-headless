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
    0: entry found and printed.
    3: ``--jq`` without ``-f json``, ``search`` with no term, or an unknown or
       ambiguous ``--domain``.
    4: the query names nothing (suggestions are printed on stdout).
"""

from __future__ import annotations

import json
from typing import Annotated, cast

import click
import typer

from mixpanel_headless.cli.utils import ExitCode, _apply_jq_filter, handle_errors
from mixpanel_headless.exceptions import HelpLookupError
from mixpanel_headless.reference import HelpFormat, describe, render, search

HelpFormatOption = Annotated[
    str,
    typer.Option(
        "--format",
        "-f",
        help="Output format (default text).",
        click_type=click.Choice(["text", "markdown", "json"]),
    ),
]
"""``-f/--format`` restricted to the three help formats."""

_SEARCH_USAGE = "Usage: mp help search <term>"
"""Line printed for a bare ``search`` query."""


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


def _miss_text(exc: HelpLookupError, fmt: HelpFormat) -> str:
    """Render a lookup miss for stdout in the requested format.

    Args:
        exc: The error raised by :func:`describe`, with suggestions and hits.
        fmt: ``text``, ``markdown``, or ``json``.

    Returns:
        A JSON error object for ``json``; otherwise the message, the
        ``Did you mean?`` block, and the first search hits.
    """
    from mixpanel_headless._internal.help.models import SearchResult

    message = f"No help entry for '{exc.query}'."
    hits = exc.hits[:5]
    if fmt == "json":
        return json.dumps(
            {
                "error": message,
                "query": exc.query,
                "suggestions": list(exc.suggestions),
                "hits": [hit.to_dict() for hit in hits],
            },
            indent=2,
        )
    blocks = [message]
    if exc.suggestions:
        blocks.append(
            "\n".join(["Did you mean?", *(f"  {s}" for s in exc.suggestions)])
        )
    if hits:
        blocks.append(render(SearchResult(term=exc.query, hits=hits), fmt))
    return "\n\n".join(blocks)


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
        typer.Exit: Exit 3 for flag misuse or an unknown domain, exit 4 for
            a lookup miss.

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

    if mode == "search":
        if not payload:
            _emit(_SEARCH_USAGE)
            raise typer.Exit(ExitCode.INVALID_ARGS)
        rendered = render(search(payload), fmt)
    else:
        target = None if mode == "overview" else payload
        try:
            entry = describe(target, hints=not no_hints, domain=domain)
        except HelpLookupError as exc:
            if domain is not None:
                # ``describe`` raises for an unknown / ambiguous domain and for
                # ``domain=`` on a non-Workspace query; both are flag misuse.
                titles = ", ".join(exc.suggestions)
                _emit(exc.message + (f"\nDomains: {titles}" if titles else ""))
                raise typer.Exit(ExitCode.INVALID_ARGS) from None
            _emit(_miss_text(exc, fmt))
            raise typer.Exit(ExitCode.NOT_FOUND) from None
        rendered = render(entry, fmt)

    if jq is not None:
        rendered = _apply_jq(rendered, jq)
    _emit(rendered)
