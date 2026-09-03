"""Report (bookmark) management commands.

This module provides commands for managing Mixpanel reports/bookmarks
via the App API:

- list: List bookmarks with optional type/ID filters
- create: Create a new bookmark
- get: Get a single bookmark by ID
- update: Update an existing bookmark
- delete: Delete a bookmark
- bulk-delete: Delete multiple bookmarks
- bulk-update: Update multiple bookmarks
- linked-dashboards: Get dashboard IDs linked to a bookmark
- dashboard-ids: Get dashboard IDs containing a bookmark
- history: Get bookmark change history
- link: Create a shareable link to an unsaved report from params (045)
- resolve: Turn a report link, slug, or shortlink back into its params (045)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, cast

import typer

from mixpanel_headless._internal.report_links import parse_report_link
from mixpanel_headless._literal_types import FlowChartType
from mixpanel_headless.cli.options import FormatOption, JqOption
from mixpanel_headless.cli.utils import (
    ExitCode,
    err_console,
    get_workspace,
    handle_errors,
    output_result,
    present_result,
    status_spinner,
)
from mixpanel_headless.cli.validators import validate_json_object, validate_literal
from mixpanel_headless.exceptions import ReportLinkParseError
from mixpanel_headless.types import ReportLinkType

reports_app = typer.Typer(
    name="reports",
    help="Manage Mixpanel reports (bookmarks).",
    no_args_is_help=True,
)


@reports_app.command("list")
@handle_errors
def list_reports(
    ctx: typer.Context,
    bookmark_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            "-t",
            help="Filter by bookmark type (e.g., insights, funnels, flows, retention).",
        ),
    ] = None,
    ids: Annotated[
        str | None,
        typer.Option(
            "--ids",
            help="Comma-separated list of bookmark IDs to retrieve.",
        ),
    ] = None,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List bookmarks/reports with optional filters.

    Retrieves bookmarks from the Mixpanel App API. Optionally filter by
    report type or specific IDs.

    Args:
        ctx: Typer context with global options.
        bookmark_type: Optional report type filter (e.g., ``"funnels"``).
        ids: Comma-separated bookmark IDs to filter by.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter expression for JSON output.

    Example:
        ```bash
        mp reports list --type funnels
        mp reports list --ids 1,2,3 --format table
        ```
    """
    workspace = get_workspace(ctx)
    parsed_ids: list[int] | None = None
    if ids:
        parsed_ids = [int(i.strip()) for i in ids.split(",")]
    from typing import get_args

    from mixpanel_headless.types import BookmarkType

    typed_bt: BookmarkType | None = None
    if bookmark_type:
        valid_types = get_args(BookmarkType)
        if bookmark_type not in valid_types:
            err_console.print(
                f"[red]Invalid --type:[/red] '{bookmark_type}'. "
                f"Valid types: {', '.join(valid_types)}"
            )
            raise typer.Exit(code=1)
        typed_bt = cast(BookmarkType, bookmark_type)
    with status_spinner(ctx, "Fetching bookmarks..."):
        bookmarks = workspace.list_bookmarks_v2(bookmark_type=typed_bt, ids=parsed_ids)
    output_result(
        ctx,
        [b.model_dump() for b in bookmarks],
        format=format,
        jq_filter=jq_filter,
    )


@reports_app.command("create")
@handle_errors
def create_report(
    ctx: typer.Context,
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Name for the new report."),
    ],
    bookmark_type: Annotated[
        str,
        typer.Option("--type", "-t", help="Report type (e.g., insights, funnels)."),
    ],
    params: Annotated[
        str,
        typer.Option(
            "--params",
            "-p",
            help="Report parameters as a JSON string.",
        ),
    ],
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Optional description."),
    ] = None,
    dashboard_id: Annotated[
        int | None,
        typer.Option("--dashboard-id", help="Dashboard ID to add the report to."),
    ] = None,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Create a new bookmark (saved report).

    Creates a bookmark in the Mixpanel App API with the given name,
    type, and query parameters.

    Args:
        ctx: Typer context with global options.
        name: Name for the new report.
        bookmark_type: Report type (e.g., ``"insights"``, ``"funnels"``).
        params: Report parameters as a JSON string.
        description: Optional description for the report.
        dashboard_id: Optional dashboard ID to add the report to.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter expression for JSON output.

    Example:
        ```bash
        mp reports create --name "Signup Funnel" --type funnels \\
            --params '{"events": [{"event": "Signup"}]}'
        ```
    """
    from mixpanel_headless.types import CreateBookmarkParams

    workspace = get_workspace(ctx)
    try:
        parsed_params = json.loads(params)
    except json.JSONDecodeError as exc:
        err_console.print(f"[red]Invalid JSON for --params:[/red] {exc.msg}")
        raise typer.Exit(code=1) from None
    create_params = CreateBookmarkParams(
        name=name,
        bookmark_type=bookmark_type,
        params=parsed_params,
        description=description,
        dashboard_id=dashboard_id,
    )
    with status_spinner(ctx, "Creating bookmark..."):
        bookmark = workspace.create_bookmark(create_params)
    output_result(
        ctx,
        bookmark.model_dump(),
        format=format,
        jq_filter=jq_filter,
    )


@reports_app.command("get")
@handle_errors
def get_report(
    ctx: typer.Context,
    bookmark_id: Annotated[
        int,
        typer.Argument(help="Bookmark ID to retrieve."),
    ],
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Get a single bookmark by ID.

    Retrieves the full bookmark object from the Mixpanel App API.

    Args:
        ctx: Typer context with global options.
        bookmark_id: The bookmark identifier.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter expression for JSON output.

    Example:
        ```bash
        mp reports get 12345
        mp reports get 12345 --format table
        ```
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching bookmark..."):
        bookmark = workspace.get_bookmark(bookmark_id)
    output_result(
        ctx,
        bookmark.model_dump(),
        format=format,
        jq_filter=jq_filter,
    )


@reports_app.command("update")
@handle_errors
def update_report(
    ctx: typer.Context,
    bookmark_id: Annotated[
        int,
        typer.Argument(help="Bookmark ID to update."),
    ],
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="New name for the report."),
    ] = None,
    params: Annotated[
        str | None,
        typer.Option(
            "--params",
            "-p",
            help="Updated report parameters as a JSON string.",
        ),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Updated description."),
    ] = None,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Update an existing bookmark.

    Patches the specified bookmark with the provided fields. Only
    supplied fields are updated; omitted fields remain unchanged.

    Args:
        ctx: Typer context with global options.
        bookmark_id: The bookmark identifier.
        name: New name for the report.
        params: Updated report parameters as a JSON string.
        description: Updated description.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter expression for JSON output.

    Example:
        ```bash
        mp reports update 12345 --name "Renamed Report"
        mp reports update 12345 --params '{"events": [{"event": "Login"}]}'
        ```
    """
    from mixpanel_headless.types import UpdateBookmarkParams

    workspace = get_workspace(ctx)
    if params:
        try:
            parsed_params = json.loads(params)
        except json.JSONDecodeError as exc:
            err_console.print(f"[red]Invalid JSON for --params:[/red] {exc.msg}")
            raise typer.Exit(code=1) from None
    else:
        parsed_params = None
    update_params = UpdateBookmarkParams(
        name=name,
        params=parsed_params,
        description=description,
    )
    with status_spinner(ctx, "Updating bookmark..."):
        bookmark = workspace.update_bookmark(bookmark_id, update_params)
    output_result(
        ctx,
        bookmark.model_dump(),
        format=format,
        jq_filter=jq_filter,
    )


@reports_app.command("delete")
@handle_errors
def delete_report(
    ctx: typer.Context,
    bookmark_id: Annotated[
        int,
        typer.Argument(help="Bookmark ID to delete."),
    ],
) -> None:
    """Delete a bookmark.

    Permanently removes the specified bookmark from the project.

    Args:
        ctx: Typer context with global options.
        bookmark_id: The bookmark identifier.

    Example:
        ```bash
        mp reports delete 12345
        ```
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Deleting bookmark..."):
        workspace.delete_bookmark(bookmark_id)
    err_console.print(f"[green]Deleted bookmark {bookmark_id}.[/green]")


@reports_app.command("bulk-delete")
@handle_errors
def bulk_delete_reports(
    ctx: typer.Context,
    ids: Annotated[
        str,
        typer.Option(
            "--ids",
            help="Comma-separated list of bookmark IDs to delete.",
        ),
    ],
) -> None:
    """Delete multiple bookmarks at once.

    Permanently removes all specified bookmarks from the project.

    Args:
        ctx: Typer context with global options.
        ids: Comma-separated bookmark IDs to delete.

    Example:
        ```bash
        mp reports bulk-delete --ids 1,2,3
        ```
    """
    workspace = get_workspace(ctx)
    parsed_ids = [int(i.strip()) for i in ids.split(",")]
    with status_spinner(ctx, f"Deleting {len(parsed_ids)} bookmarks..."):
        workspace.bulk_delete_bookmarks(parsed_ids)
    err_console.print(f"[green]Deleted {len(parsed_ids)} bookmark(s).[/green]")


@reports_app.command("bulk-update")
@handle_errors
def bulk_update_reports(
    ctx: typer.Context,
    entries: Annotated[
        str,
        typer.Option(
            "--entries",
            "-e",
            help='JSON string: list of objects with "id" and fields to update.',
        ),
    ],
) -> None:
    """Update multiple bookmarks at once.

    Accepts a JSON array of update entries. Each entry must include
    an ``id`` field and any fields to update (e.g., ``name``).

    Args:
        ctx: Typer context with global options.
        entries: JSON string containing a list of update entries.

    Example:
        ```bash
        mp reports bulk-update --entries '[{"id": 1, "name": "Renamed"}]'
        ```
    """
    from mixpanel_headless.types import BulkUpdateBookmarkEntry

    workspace = get_workspace(ctx)
    try:
        parsed_entries = json.loads(entries)
    except json.JSONDecodeError as exc:
        err_console.print(f"[red]Invalid JSON for --entries:[/red] {exc.msg}")
        raise typer.Exit(code=1) from None
    entry_objs = [BulkUpdateBookmarkEntry.model_validate(e) for e in parsed_entries]
    with status_spinner(ctx, f"Updating {len(entry_objs)} bookmarks..."):
        workspace.bulk_update_bookmarks(entry_objs)
    err_console.print(f"[green]Updated {len(entry_objs)} bookmark(s).[/green]")


@reports_app.command("linked-dashboards")
@handle_errors
def linked_dashboards(
    ctx: typer.Context,
    bookmark_id: Annotated[
        int,
        typer.Argument(help="Bookmark ID to look up."),
    ],
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Get dashboard IDs linked to a bookmark.

    Returns a list of dashboard IDs that reference the specified
    bookmark via the ``bookmark_linked_dashboard_ids`` API.

    Args:
        ctx: Typer context with global options.
        bookmark_id: The bookmark identifier.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter expression for JSON output.

    Example:
        ```bash
        mp reports linked-dashboards 12345
        ```
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching linked dashboards..."):
        dash_ids = workspace.bookmark_linked_dashboard_ids(bookmark_id)
    output_result(
        ctx,
        dash_ids,
        format=format,
        jq_filter=jq_filter,
    )


@reports_app.command("dashboard-ids")
@handle_errors
def dashboard_ids(
    ctx: typer.Context,
    bookmark_id: Annotated[
        int,
        typer.Argument(help="Bookmark ID to look up."),
    ],
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Get dashboard IDs containing a bookmark.

    Returns a list of dashboard IDs that contain the specified
    bookmark. Uses the ``get_bookmark_dashboard_ids`` workspace method.

    Args:
        ctx: Typer context with global options.
        bookmark_id: The bookmark identifier.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter expression for JSON output.

    Example:
        ```bash
        mp reports dashboard-ids 12345
        ```
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching dashboard IDs..."):
        dash_ids = workspace.get_bookmark_dashboard_ids(bookmark_id)
    output_result(
        ctx,
        dash_ids,
        format=format,
        jq_filter=jq_filter,
    )


@reports_app.command("history")
@handle_errors
def report_history(
    ctx: typer.Context,
    bookmark_id: Annotated[
        int,
        typer.Argument(help="Bookmark ID to get history for."),
    ],
    cursor: Annotated[
        str | None,
        typer.Option("--cursor", help="Pagination cursor for next page."),
    ] = None,
    page_size: Annotated[
        int | None,
        typer.Option("--page-size", help="Maximum entries per page."),
    ] = None,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Get change history for a bookmark.

    Returns a paginated list of changes made to the specified bookmark,
    including who made the change and when.

    Args:
        ctx: Typer context with global options.
        bookmark_id: The bookmark identifier.
        cursor: Opaque pagination cursor for fetching subsequent pages.
        page_size: Maximum number of entries per page.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter expression for JSON output.

    Example:
        ```bash
        mp reports history 12345
        mp reports history 12345 --page-size 10
        mp reports history 12345 --cursor "abc123"
        ```
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching bookmark history..."):
        history = workspace.get_bookmark_history(
            bookmark_id, cursor=cursor, page_size=page_size
        )
    output_result(
        ctx,
        history.model_dump(),
        format=format,
        jq_filter=jq_filter,
    )


# =============================================================================
# Report links (045-report-links)
# =============================================================================


def _stdin_is_tty() -> bool:
    """Return whether stdin is an interactive terminal.

    A seam for tests: ``CliRunner`` swaps ``sys.stdin``, so the check is
    read through this function rather than at import time.

    Returns:
        ``True`` when stdin is a terminal.
    """
    return sys.stdin.isatty()


def _read_params_source(
    source: str | None,
    params: str | None,
    params_file: Path | None,
) -> str:
    """Pick exactly one params source and return its raw text.

    Stdin is read when nothing is given, when the positional is ``-``, when
    ``--params -`` is given, or when ``--params-file -`` is given. In every
    one of those forms an interactive terminal is refused, so the command
    never blocks and waits for typed input.

    Args:
        source: The optional positional argument; only ``-`` (stdin) is valid.
        params: The ``--params`` inline JSON text (``-`` means stdin).
        params_file: The ``--params-file`` path (``-`` means stdin).

    Returns:
        The raw JSON text to parse.

    Raises:
        typer.Exit: With code 3 (INVALID_ARGS) when more than one source is
            given, the positional is not ``-``, the file cannot be read, or
            stdin would be read from a terminal.
    """
    given = [x for x in (source, params, params_file) if x is not None]
    if len(given) > 1:
        err_console.print(
            "[red]Error:[/red] Pass only one of --params, --params-file, or '-'."
        )
        raise typer.Exit(ExitCode.INVALID_ARGS)
    if source is not None and source != "-":
        err_console.print(
            "[red]Error:[/red] Only '-' (read stdin) is accepted as a positional "
            "argument. Use --params JSON or --params-file PATH."
        )
        raise typer.Exit(ExitCode.INVALID_ARGS)
    if params is not None and params != "-":
        return params
    if params_file is not None and str(params_file) != "-":
        try:
            return params_file.read_text(encoding="utf-8")
        except OSError as exc:
            err_console.print(f"[red]Error:[/red] Cannot read --params-file: {exc}")
            raise typer.Exit(ExitCode.INVALID_ARGS) from exc
    if _stdin_is_tty():
        err_console.print(
            "[red]Error:[/red] stdin is a terminal. Provide --params JSON, "
            "--params-file PATH, or pipe a JSON object on stdin."
        )
        raise typer.Exit(ExitCode.INVALID_ARGS)
    return sys.stdin.read()


@reports_app.command("link")
@handle_errors
def link_report(
    ctx: typer.Context,
    source: Annotated[
        str | None,
        typer.Argument(
            metavar="[-]",
            help="Pass '-' to read the params JSON object from stdin.",
        ),
    ] = None,
    params: Annotated[
        str | None,
        typer.Option(
            "--params",
            help="Report params as an inline JSON object, or '-' to read stdin.",
        ),
    ] = None,
    params_file: Annotated[
        Path | None,
        typer.Option(
            "--params-file",
            help="Path to a file that holds the params JSON object.",
        ),
    ] = None,
    report_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            "-t",
            help="Report type: insights, funnels, retention, flows. Default: insights.",
        ),
    ] = None,
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Name stored with the unsaved report."),
    ] = "",
    description: Annotated[
        str,
        typer.Option("--description", "-d", help="Description stored with it."),
    ] = "",
    workspace_id: Annotated[
        int | None,
        typer.Option(
            "--workspace-id",
            help=(
                "Workspace for the /view/{wid} URL segment. Default: the session "
                "workspace, then auto-resolve, then a project-only URL."
            ),
        ),
    ] = None,
    bookmark_id: Annotated[
        int | None,
        typer.Option(
            "--bookmark-id",
            help="Saved report ID to reference from the unsaved report.",
        ),
    ] = None,
    no_validate: Annotated[
        bool,
        typer.Option(
            "--no-validate",
            help="Skip the client-side params schema check before the upload.",
        ),
    ] = False,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Create a shareable link to an unsaved report from query params.

    Stores the params on the Mixpanel server under a 12-character slug and
    prints the URL that opens them in the report editor. Params come from
    --params, --params-file, or stdin. With --format plain only the URL is
    printed, so a shell can capture it.

    Args:
        ctx: Typer context with global options.
        source: ``-`` to read stdin.
        params: Inline JSON object, or ``-`` to read stdin.
        params_file: File that holds the JSON object, or ``-`` to read stdin.
        report_type: insights, funnels, retention, or flows.
        name: Name stored with the record.
        description: Description stored with the record.
        workspace_id: Workspace for the URL segment.
        bookmark_id: Saved report reference.
        no_validate: Skip schema validation.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter expression for JSON output.

    Example:
        ```bash
        mp reports link --params '{"sections": {...}}' --name "Logins"
        cat params.json | mp reports link -f plain
        mp reports link --params-file params.json --type funnels --jq .url
        ```
    """
    raw_text = _read_params_source(source, params, params_file)
    params_dict = validate_json_object(raw_text, "--params")
    validated_type: ReportLinkType | None = None
    if report_type is not None:
        validated_type = cast(
            ReportLinkType, validate_literal(report_type, ReportLinkType, "--type")
        )

    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Creating report link..."):
        link = workspace.create_report_link(
            params_dict,
            report_type=validated_type,
            name=name,
            description=description,
            workspace_id=workspace_id,
            bookmark_id=bookmark_id,
            validate=not no_validate,
        )

    if format == "plain":
        typer.echo(link.url)
        return
    output_result(ctx, link.to_dict(), format=format, jq_filter=jq_filter)


def _warn_ignored_overrides(link: str) -> None:
    """Warn when a saved-report link carries a ``~(...)`` override tail.

    Specified in ``specs/045-report-links/contracts/cli-commands.md`` §7. The
    parse is pure and cheap. A parse failure is ignored here so the
    ``Workspace`` call raises the canonical error with the right exit code.

    Args:
        link: The raw link string the user passed, or the expanded target of
            a shortlink.
    """
    try:
        parsed = parse_report_link(link)
    except ReportLinkParseError:
        return
    if parsed.kind == "bookmark" and parsed.overrides_jsurl is not None:
        err_console.print(
            f"[yellow]warning:[/yellow] ignoring URL overrides "
            f"{parsed.overrides_jsurl!r}; running the saved report's base params"
        )


@reports_app.command("resolve")
@handle_errors
def resolve_report(
    ctx: typer.Context,
    link: Annotated[
        str,
        typer.Argument(
            help=(
                "A full report URL, a shortlink (https://mixpanel.com/s/...), or a "
                "bare 12-character slug. Quote URLs so the shell does not "
                "interpret '#'."
            ),
        ),
    ],
    run: Annotated[
        bool,
        typer.Option(
            "--run",
            help="Run the resolved report and print the query result instead.",
        ),
    ] = False,
    mode: Annotated[
        str | None,
        typer.Option(
            "--mode",
            help="Flows chart mode for --run: sankey, paths, or tree.",
        ),
    ] = None,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Resolve a report link to its query params, and optionally run it.

    Without --run, prints the resolved report: type, params, project,
    workspace, canonical URL, and the saved report when there is one. With
    --run, runs the params through the matching query engine and prints the
    typed result. Region and project mismatches fail before any network call.

    Args:
        ctx: Typer context with global options.
        link: The link string.
        run: Run the report instead of printing its params.
        mode: Flows chart mode, used with --run.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter expression for JSON output.

    Example:
        ```bash
        mp reports resolve 'https://mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw'
        mp reports resolve EBrV5bW2u9Mw --jq .params
        mp reports resolve 'https://mixpanel.com/s/AbC123' --run -f csv
        mp reports resolve 'https://mixpanel.com/project/3/app/insights#report/123' --run
        ```
    """
    _warn_ignored_overrides(link)
    workspace = get_workspace(ctx)

    if run:
        validated_mode: FlowChartType | None = None
        if mode is not None:
            validated_mode = cast(
                FlowChartType, validate_literal(mode, FlowChartType, "--mode")
            )
        with status_spinner(ctx, "Resolving and running report link..."):
            result = workspace.query_report_link(link, mode=validated_mode)
        present_result(ctx, result, format, jq_filter=jq_filter)
        return

    with status_spinner(ctx, "Resolving report link..."):
        resolved = workspace.resolve_report_link(link)
    if resolved.expanded_url is not None:
        _warn_ignored_overrides(resolved.expanded_url)
    output_result(ctx, resolved.to_dict(), format=format, jq_filter=jq_filter)
