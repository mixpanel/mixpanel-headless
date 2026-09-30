"""Saved metric management commands.

This module provides commands for the saved metrics of a project (behavior
metrics, formulas, and warehouse metrics) via the App API:

- list: List saved metrics with optional local filters
- get: Get one saved metric by ID
- delete: Delete one or more saved metrics
"""

from __future__ import annotations

from typing import Annotated

import typer

from mixpanel_headless.cli.options import FormatOption, JqOption
from mixpanel_headless.cli.utils import (
    err_console,
    get_workspace,
    handle_errors,
    output_result,
    status_spinner,
)

metrics_app = typer.Typer(
    name="metrics",
    help="Manage Mixpanel saved metrics.",
    no_args_is_help=True,
)

_LIST_COLUMNS = ["id", "name", "type", "verified", "can_view", "modified"]
"""Columns of the ``--format table`` view; the definition stays out of the table."""


@metrics_app.command("list")
@handle_errors
def list_metrics(
    ctx: typer.Context,
    metric_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help="Keep one kind: metric, formula, or warehouse.",
        ),
    ] = None,
    verified: Annotated[
        bool | None,
        typer.Option(
            "--verified/--no-verified",
            help="Keep only verified (--verified) or unverified (--no-verified) metrics.",
        ),
    ] = None,
    name_contains: Annotated[
        str | None,
        typer.Option(
            "--name-contains",
            help="Keep metrics whose name contains this text (ignores case).",
        ),
    ] = None,
    viewable_only: Annotated[
        bool,
        typer.Option(
            "--viewable-only",
            help="Drop the metrics that you cannot view (can_view false).",
        ),
    ] = False,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List the saved metrics of the project.

    Returns every kind (behavior metric, formula, warehouse metric) with
    its full definition, including the metrics that you cannot view. The
    server has no pagination or filters, so one request fetches all rows
    and the options filter them locally. On a large project the request
    can take more than 30 seconds.

    Args:
        ctx: Typer context with global options.
        metric_type: Optional kind to keep.
        verified: Optional verified state to keep.
        name_contains: Optional case-insensitive name substring.
        viewable_only: Drop the rows with ``can_view`` false.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter for JSON output.
    """
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Listing saved metrics..."):
        metrics = workspace.list_metrics(
            metric_type=metric_type,
            verified=verified,
            name_contains=name_contains,
            viewable_only=viewable_only,
        )

    output_result(
        ctx,
        [m.model_dump() for m in metrics],
        columns=_LIST_COLUMNS,
        format=format,
        jq_filter=jq_filter,
    )


@metrics_app.command("get")
@handle_errors
def get_metric(
    ctx: typer.Context,
    metric_id: Annotated[
        int,
        typer.Argument(help="Saved metric ID to retrieve."),
    ],
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Get one saved metric by ID.

    Prints the full metric: metadata, owner, verified state, permission
    flags, and the stored definition.

    Args:
        ctx: Typer context with global options.
        metric_id: The saved metric identifier.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter for JSON output.
    """
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Fetching saved metric..."):
        metric = workspace.get_metric(metric_id)

    output_result(
        ctx,
        metric.model_dump(),
        format=format,
        jq_filter=jq_filter,
    )


@metrics_app.command("delete")
@handle_errors
def delete_metrics(
    ctx: typer.Context,
    metric_ids: Annotated[
        list[int],
        typer.Argument(help="One or more saved metric IDs to delete."),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help=(
                "Delete metrics that your account cannot edit (can_update_basic "
                "false). A superadmin account can delete metrics that other "
                "users own."
            ),
        ),
    ] = False,
) -> None:
    """Delete one or more saved metrics.

    One ID is read first, so an unknown ID fails and nothing is deleted.
    Several IDs go in one bulk request, and the server skips the IDs that
    do not name an active metric, with no error.

    The server lets a project superadmin delete metrics that other users
    own. So the command refuses, before any delete, a metric whose
    can_update_basic flag is false for your account. Pass --force to
    delete it anyway.

    Args:
        ctx: Typer context with global options.
        metric_ids: The saved metric identifiers.
        force: Delete metrics that your account cannot edit.
    """
    workspace = get_workspace(ctx)

    if len(metric_ids) == 1:
        with status_spinner(ctx, "Deleting saved metric..."):
            workspace.delete_metric(metric_ids[0], force=force)
        err_console.print(f"[green]Deleted saved metric {metric_ids[0]}.[/green]")
        return

    with status_spinner(ctx, "Deleting saved metrics..."):
        workspace.delete_metrics(metric_ids, force=force)
    joined = ", ".join(str(i) for i in metric_ids)
    err_console.print(
        f"[green]Sent one delete for {len(metric_ids)} saved metrics: {joined}.[/green] "
        "The server skips IDs that do not name an active metric."
    )
