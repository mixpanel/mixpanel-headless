"""Saved behavior management commands.

This module provides commands for the saved behaviors of a project
(simple, funnel, and retention behaviors) via the App API:

- list: List saved behaviors with optional local filters
- get: Get one saved behavior by ID
- delete: Delete one or more saved behaviors
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

behaviors_app = typer.Typer(
    name="behaviors",
    help="Manage Mixpanel saved behaviors.",
    no_args_is_help=True,
)

_LIST_COLUMNS = ["id", "name", "type", "verified", "can_view", "modified"]
"""Columns of the ``--format table`` view; the definition stays out of the table."""


@behaviors_app.command("list")
@handle_errors
def list_behaviors(
    ctx: typer.Context,
    behavior_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help="Keep one type: simple, funnel, or retention.",
        ),
    ] = None,
    name_contains: Annotated[
        str | None,
        typer.Option(
            "--name-contains",
            help="Keep behaviors whose name contains this text (ignores case).",
        ),
    ] = None,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List the saved behaviors of the project.

    The server has no pagination or filters, so one request fetches all
    rows and the options filter them locally.

    Args:
        ctx: Typer context with global options.
        behavior_type: Optional behavior type to keep.
        name_contains: Optional case-insensitive name substring.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter for JSON output.
    """
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Listing saved behaviors..."):
        behaviors = workspace.list_behaviors(
            behavior_type=behavior_type,
            name_contains=name_contains,
        )

    output_result(
        ctx,
        [b.model_dump() for b in behaviors],
        columns=_LIST_COLUMNS,
        format=format,
        jq_filter=jq_filter,
    )


@behaviors_app.command("get")
@handle_errors
def get_behavior(
    ctx: typer.Context,
    behavior_id: Annotated[
        int,
        typer.Argument(help="Saved behavior ID to retrieve."),
    ],
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Get one saved behavior by ID.

    Prints the full behavior: metadata, verified state, permission flags,
    and the stored definition. The server answers an unknown ID with a 500.

    Args:
        ctx: Typer context with global options.
        behavior_id: The saved behavior identifier.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter for JSON output.
    """
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Fetching saved behavior..."):
        behavior = workspace.get_behavior(behavior_id)

    output_result(
        ctx,
        behavior.model_dump(),
        format=format,
        jq_filter=jq_filter,
    )


@behaviors_app.command("delete")
@handle_errors
def delete_behaviors(
    ctx: typer.Context,
    behavior_ids: Annotated[
        list[int],
        typer.Argument(help="One or more saved behavior IDs to delete."),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help=(
                "Delete behaviors that your account cannot edit (can_update_basic "
                "false). A superadmin account can delete behaviors that other "
                "users created."
            ),
        ),
    ] = False,
) -> None:
    """Delete one or more saved behaviors.

    One ID is read first, so an unknown ID fails (the server answers the
    read with a 500) and nothing is deleted. Several IDs go in one bulk
    request, and the server skips the IDs that do not name a behavior,
    with no error.

    The server lets a project superadmin delete behaviors that other users
    created. So the command refuses, before any delete, a behavior whose
    can_update_basic flag is false for your account. Pass --force to
    delete it anyway.

    Args:
        ctx: Typer context with global options.
        behavior_ids: The saved behavior identifiers.
        force: Delete behaviors that your account cannot edit.
    """
    workspace = get_workspace(ctx)

    if len(behavior_ids) == 1:
        with status_spinner(ctx, "Deleting saved behavior..."):
            workspace.delete_behavior(behavior_ids[0], force=force)
        err_console.print(f"[green]Deleted saved behavior {behavior_ids[0]}.[/green]")
        return

    with status_spinner(ctx, "Deleting saved behaviors..."):
        workspace.delete_behaviors(behavior_ids, force=force)
    joined = ", ".join(str(i) for i in behavior_ids)
    err_console.print(
        f"[green]Sent one delete for {len(behavior_ids)} saved behaviors: "
        f"{joined}.[/green] The server skips IDs that do not name a behavior."
    )
