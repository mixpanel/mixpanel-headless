"""Saved metric management commands.

This module provides commands for the saved metrics of a project (behavior
metrics, formulas, and warehouse metrics) via the App API:

- list: List saved metrics with optional local filters
- get: Get one saved metric by ID
- create: Create a saved metric from a wire definition file or stdin
- update: Update a saved metric
- verify: Verify or unverify saved metrics in one request
- query: Run a saved metric by reference
- delete: Delete one or more saved metrics
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

import typer

from mixpanel_headless._literal_types import QueryTimeUnit
from mixpanel_headless.cli.options import FormatOption, JqOption
from mixpanel_headless.cli.utils import (
    err_console,
    get_workspace,
    handle_errors,
    output_result,
    present_result,
    status_spinner,
)
from mixpanel_headless.cli.validators import read_json_object_file, validate_literal

if TYPE_CHECKING:
    from mixpanel_headless.types import RawMetricDefinition

_MetricKind = Literal["metric", "formula", "warehouse"]
"""Wire kinds that ``--kind`` accepts."""

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


def _infer_kind(definition: dict[str, Any], warehouse_source_id: int | None) -> str:
    """Guess the metric kind of a wire definition.

    Args:
        definition: The wire definition dict.
        warehouse_source_id: The ``--warehouse-source-id`` value.

    Returns:
        ``"formula"`` when the definition has a ``formula`` block,
        ``"warehouse"`` when it has a ``query`` or a warehouse source is
        given, otherwise ``"metric"``.
    """
    if "formula" in definition:
        return "formula"
    if "query" in definition or warehouse_source_id is not None:
        return "warehouse"
    return "metric"


def _raw_definition(
    definition_file: Path,
    kind: str | None,
    warehouse_source_id: int | None,
) -> RawMetricDefinition:
    """Read a definition file into a ``RawMetricDefinition``.

    Args:
        definition_file: The file path, or ``-`` for stdin.
        kind: The ``--kind`` value, or ``None`` to infer it.
        warehouse_source_id: The ``--warehouse-source-id`` value.

    Returns:
        The raw definition value.

    Raises:
        typer.Exit: With code 3 when the file is unreadable, not a JSON
            object, or ``--kind`` is not a metric kind.
    """
    from mixpanel_headless.types import RawMetricDefinition

    definition = read_json_object_file(definition_file, "--definition-file")
    chosen = (
        cast(_MetricKind, validate_literal(kind, _MetricKind, "--kind"))
        if kind is not None
        else cast(_MetricKind, _infer_kind(definition, warehouse_source_id))
    )
    return RawMetricDefinition(chosen, definition, warehouse_source_id)


_DefinitionFileOption = Annotated[
    Path,
    typer.Option(
        "--definition-file",
        help=(
            "File with the wire definition JSON (the `definition` field of "
            "`mp metrics get ID --format json`), or '-' to read stdin."
        ),
    ),
]
"""The ``--definition-file`` option of ``create``."""

_KindOption = Annotated[
    str | None,
    typer.Option(
        "--kind",
        help=(
            "Metric kind: metric, formula, or warehouse. Default: formula when "
            "the definition has a formula block, warehouse when it has a query, "
            "otherwise metric."
        ),
    ),
]
"""The ``--kind`` option of ``create`` and ``update``."""

_WarehouseSourceOption = Annotated[
    int | None,
    typer.Option(
        "--warehouse-source-id",
        help="Warehouse source of a warehouse metric.",
    ),
]
"""The ``--warehouse-source-id`` option of ``create`` and ``update``."""

_NoValidateOption = Annotated[
    bool,
    typer.Option(
        "--no-validate",
        help="Skip the client-side check of the definition against the server schema.",
    ),
]
"""The ``--no-validate`` option of ``create`` and ``update``."""


@metrics_app.command("create")
@handle_errors(redact_request=True)
def create_metric(
    ctx: typer.Context,
    name: Annotated[
        str,
        typer.Option("--name", help="Metric name (required, unique in the project)."),
    ],
    definition_file: _DefinitionFileOption,
    kind: _KindOption = None,
    warehouse_source_id: _WarehouseSourceOption = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="Metric description."),
    ] = None,
    owner_id: Annotated[
        int | None,
        typer.Option("--owner-id", help="User ID of the owner."),
    ] = None,
    verified: Annotated[
        bool,
        typer.Option("--verified", help="Mark the new metric as verified."),
    ] = False,
    no_validate: _NoValidateOption = False,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Create a saved metric from a wire definition.

    The definition file holds the `definition` object of a saved metric, the
    same shape that `mp metrics get` prints, so a metric can be copied or
    restored. The owner and the verified flag go in a second request,
    because the server drops them from a create. In a project with sharing
    on, the new metric is private to you.

    Args:
        ctx: Typer context with global options.
        name: Metric name.
        definition_file: Definition JSON file, or ``-`` for stdin.
        kind: Metric kind, or ``None`` to infer it.
        warehouse_source_id: Warehouse source of a warehouse metric.
        description: Optional description.
        owner_id: Optional owner user ID.
        verified: Mark the metric as verified.
        no_validate: Skip the client-side schema check.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter for JSON output.

    Example:
        ```bash
        mp metrics get 104700 --jq .definition > definition.json
        mp metrics create --name "Signups (copy)" --definition-file definition.json
        ```
    """
    from mixpanel_headless.types import CreateMetricParams

    params = CreateMetricParams(
        name=name,
        definition=_raw_definition(definition_file, kind, warehouse_source_id),
        description=description,
        owned_by=owner_id,
        verified=True if verified else None,
    )
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Creating saved metric..."):
        metric = workspace.create_metric(params, validate=not no_validate)

    output_result(ctx, metric.model_dump(), format=format, jq_filter=jq_filter)


@metrics_app.command("update")
@handle_errors(redact_request=True)
def update_metric(
    ctx: typer.Context,
    metric_id: Annotated[
        int,
        typer.Argument(help="Saved metric ID to update."),
    ],
    name: Annotated[
        str | None,
        typer.Option("--name", help="New metric name."),
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
                "File with the new wire definition JSON, or '-' to read stdin. "
                "It replaces the stored definition; the stored display and goals "
                "stay unless the file sets them."
            ),
        ),
    ] = None,
    kind: _KindOption = None,
    warehouse_source_id: _WarehouseSourceOption = None,
    owner_id: Annotated[
        int | None,
        typer.Option("--owner-id", help="User ID of the new owner."),
    ] = None,
    verified: Annotated[
        bool | None,
        typer.Option(
            "--verified/--no-verified",
            help="Mark the metric as verified, or clear the flag.",
        ),
    ] = None,
    no_validate: _NoValidateOption = False,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Update a saved metric.

    Only the options you pass change. A new definition must have the kind of
    the stored metric. The server does not check an update, so the client
    checks the definition before the request.

    Args:
        ctx: Typer context with global options.
        metric_id: The saved metric identifier.
        name: Optional new name.
        description: Optional new description.
        definition_file: Optional new definition file, or ``-`` for stdin.
        kind: Metric kind of the file, or ``None`` to infer it.
        warehouse_source_id: Warehouse source of a warehouse definition.
        owner_id: Optional new owner user ID.
        verified: Optional new verified state.
        no_validate: Skip the client-side schema check.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter for JSON output.

    Example:
        ```bash
        mp metrics get 104700 --jq .definition > definition.json
        # edit definition.json
        mp metrics update 104700 --definition-file definition.json
        ```
    """
    from mixpanel_headless.types import UpdateMetricParams

    params = UpdateMetricParams(
        name=name,
        description=description,
        definition=(
            _raw_definition(definition_file, kind, warehouse_source_id)
            if definition_file is not None
            else None
        ),
        owned_by=owner_id,
        verified=verified,
    )
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Updating saved metric..."):
        metric = workspace.update_metric(metric_id, params, validate=not no_validate)

    output_result(ctx, metric.model_dump(), format=format, jq_filter=jq_filter)


@metrics_app.command("verify")
@handle_errors(redact_request=True)
def verify_metrics(
    ctx: typer.Context,
    metric_ids: Annotated[
        list[int],
        typer.Argument(help="One or more saved metric IDs."),
    ],
    unverify: Annotated[
        bool,
        typer.Option("--unverify", help="Clear the verified flag instead."),
    ] = False,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Verify (or unverify) saved metrics in one request.

    Prints the updated metrics. The server skips IDs that do not name a
    metric of the project; the command names them on stderr.

    Args:
        ctx: Typer context with global options.
        metric_ids: The saved metric identifiers.
        unverify: Clear the flag instead of setting it.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter for JSON output.
    """
    from mixpanel_headless.types import BulkUpdateMetricEntry

    entries = [
        BulkUpdateMetricEntry(id=metric_id, verified=not unverify)
        for metric_id in metric_ids
    ]
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Updating saved metrics..."):
        metrics = workspace.bulk_update_metrics(entries)

    updated = {m.id for m in metrics}
    skipped = [metric_id for metric_id in metric_ids if metric_id not in updated]
    if skipped:
        joined = ", ".join(str(i) for i in skipped)
        err_console.print(
            f"[yellow]Warning:[/yellow] The server skipped these IDs: {joined}."
        )
    output_result(
        ctx,
        [m.model_dump() for m in metrics],
        columns=_LIST_COLUMNS,
        format=format,
        jq_filter=jq_filter,
    )


@metrics_app.command("query")
@handle_errors
def query_metric(
    ctx: typer.Context,
    metric_id: Annotated[
        int,
        typer.Argument(help="Saved metric ID to run."),
    ],
    from_date: Annotated[
        str | None,
        typer.Option("--from", help="Start date (YYYY-MM-DD)."),
    ] = None,
    to_date: Annotated[
        str | None,
        typer.Option("--to", help="End date (YYYY-MM-DD)."),
    ] = None,
    last: Annotated[
        int,
        typer.Option("--last", help="Days back from today when --from/--to are unset."),
    ] = 30,
    unit: Annotated[
        str,
        typer.Option(
            "--unit", "-u", help="Time unit: hour, day, week, month, quarter."
        ),
    ] = "day",
    group_by: Annotated[
        str | None,
        typer.Option("--group-by", help="Property to break the result down by."),
    ] = None,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Run a saved metric by reference, as a report that uses it does.

    Reads the metric to learn its kind, then runs an insights query whose
    only metric is a reference to it. The server expands the saved
    definition at query time, so the result follows the stored metric.

    Args:
        ctx: Typer context with global options.
        metric_id: The saved metric identifier.
        from_date: Optional start date.
        to_date: Optional end date.
        last: Days back from today when no dates are given.
        unit: Time unit of the series.
        group_by: Optional breakdown property.
        format: Output format (json, jsonl, table, csv, plain).
        jq_filter: Optional jq filter for JSON output.

    Example:
        ```bash
        mp metrics query 104700 --from 2024-09-01 --to 2024-09-30 --unit week
        ```
    """
    validated_unit = cast(
        QueryTimeUnit, validate_literal(unit, QueryTimeUnit, "--unit")
    )
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Running saved metric..."):
        metric = workspace.get_metric(metric_id)
        result = workspace.query(
            metric.to_ref(),
            from_date=from_date,
            to_date=to_date,
            last=last,
            unit=validated_unit,
            group_by=group_by,
        )

    present_result(ctx, result, format, jq_filter=jq_filter)


@metrics_app.command("delete")
@handle_errors(redact_request=True)
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
