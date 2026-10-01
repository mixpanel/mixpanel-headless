"""Saved behavior management commands.

This module provides commands for the saved behaviors of a project
(simple, funnel, and retention behaviors) via the App API:

- list: List saved behaviors with optional local filters
- get: Get one saved behavior by ID
- create: Create a saved behavior from a wire definition file or stdin
- update: Update a saved behavior
- delete: Delete one or more saved behaviors
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from mixpanel_headless.cli.options import FormatOption, JqOption
from mixpanel_headless.cli.utils import (
    ExitCode,
    err_console,
    get_workspace,
    handle_errors,
    output_result,
    status_spinner,
)
from mixpanel_headless.cli.validators import read_json_object_file

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


_NoValidateOption = Annotated[
    bool,
    typer.Option(
        "--no-validate",
        help="Skip the client-side check of the definition against the server schema.",
    ),
]
"""The ``--no-validate`` option of ``create`` and ``update``."""


@behaviors_app.command("create")
@handle_errors(redact_request=True)
def create_behavior(
    ctx: typer.Context,
    name: Annotated[
        str,
        typer.Option("--name", help="Behavior name (required, unique in the project)."),
    ],
    definition_file: Annotated[
        Path,
        typer.Option(
            "--definition-file",
            help=(
                'File with the wire definition JSON ({"behavior": {...}}, the '
                "`definition` field of `mp behaviors get ID --format json`), or "
                "'-' to read stdin."
            ),
        ),
    ],
    description: Annotated[
        str | None,
        typer.Option("--description", help="Behavior description."),
    ] = None,
    no_validate: _NoValidateOption = False,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Create a saved behavior from a wire definition.

    The behavior type comes from the definition (`behavior.type`). In a
    project with sharing on, the new behavior is private to you.

    Args:
        ctx: Typer context with global options.
        name: Behavior name.
        definition_file: Definition JSON file, or ``-`` for stdin.
        description: Optional description.
        no_validate: Skip the client-side schema check.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter for JSON output.

    Example:
        ```bash
        mp behaviors get 3001 --jq .definition | mp behaviors create --name Copy --definition-file -
        ```
    """
    from mixpanel_headless.types import CreateBehaviorParams, RawBehaviorDefinition

    definition = read_json_object_file(definition_file, "--definition-file")
    params = CreateBehaviorParams(
        name=name,
        behavior=RawBehaviorDefinition(definition),
        description=description,
    )
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Creating saved behavior..."):
        behavior = workspace.create_behavior(params, validate=not no_validate)

    output_result(ctx, behavior.model_dump(), format=format, jq_filter=jq_filter)


@behaviors_app.command("update")
@handle_errors(redact_request=True)
def update_behavior(
    ctx: typer.Context,
    behavior_id: Annotated[
        int,
        typer.Argument(help="Saved behavior ID to update."),
    ],
    name: Annotated[
        str | None,
        typer.Option("--name", help="New behavior name."),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="New description ('' clears it)."),
    ] = None,
    definition_file: Annotated[
        Path | None,
        typer.Option(
            "--definition-file",
            help=(
                "File with the new wire definition JSON, or '-' to read stdin. It "
                "replaces the stored definition and must keep the behavior type."
            ),
        ),
    ] = None,
    verified: Annotated[
        bool | None,
        typer.Option(
            "--verified/--no-verified",
            help="Mark the behavior as verified, or clear the flag.",
        ),
    ] = None,
    no_validate: _NoValidateOption = False,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Update a saved behavior.

    Only the options you pass change. The server does not check an update,
    so the client checks a new definition before the request. A command
    with no option to change sends nothing.

    Args:
        ctx: Typer context with global options.
        behavior_id: The saved behavior identifier.
        name: Optional new name.
        description: Optional new description.
        definition_file: Optional new definition file, or ``-`` for stdin.
        verified: Optional new verified state.
        no_validate: Skip the client-side schema check.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter for JSON output.

    Raises:
        typer.Exit: With code 3, before any request, when no option to
            change is given.
    """
    from mixpanel_headless.types import RawBehaviorDefinition, UpdateBehaviorParams

    if all(value is None for value in (name, description, definition_file, verified)):
        err_console.print(
            "[red]Error:[/red] Nothing to update: pass --name, --description, "
            "--definition-file, or --verified/--no-verified."
        )
        raise typer.Exit(ExitCode.INVALID_ARGS)

    params = UpdateBehaviorParams(
        name=name,
        description=description,
        behavior=(
            RawBehaviorDefinition(
                read_json_object_file(definition_file, "--definition-file")
            )
            if definition_file is not None
            else None
        ),
        verified=verified,
    )
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Updating saved behavior..."):
        behavior = workspace.update_behavior(
            behavior_id, params, validate=not no_validate
        )

    output_result(ctx, behavior.model_dump(), format=format, jq_filter=jq_filter)


@behaviors_app.command("delete")
@handle_errors(redact_request=True)
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
