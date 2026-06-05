"""Session-replay CLI commands (044-session-replay, Phase 1).

Implements ``mp replays {list,events,sign,fetch}``. Phase 2 adds
``analyze`` and ``for-user`` once the vendored analyzer ships.

Security: ``sign`` masks ``query_string`` by default. The
``--reveal-signed-urls`` opt-in emits a stderr warning on every
invocation per contracts/cli-commands.md §4.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from mixpanel_headless.cli.options import FormatOption, JqOption
from mixpanel_headless.cli.utils import (
    get_workspace,
    handle_errors,
    output_result,
    status_spinner,
)

replays_app = typer.Typer(
    name="replays",
    help="Session replay commands.",
    no_args_is_help=True,
)


# Stderr warning emitted every time --reveal-signed-urls is used.
_BEARER_WARNING = (
    "warning: signed URLs are bearer credentials valid for ~5 minutes. "
    "Treat them like session tokens — do not paste into chat, logs, "
    "or version control."
)


# =============================================================================
# mp replays list
# =============================================================================


@replays_app.command("list")
@handle_errors
def replays_list(
    ctx: typer.Context,
    user: Annotated[
        str | None,
        typer.Option(
            "--user",
            help="Mixpanel distinct_id. Mutually exclusive with --replay-id.",
        ),
    ] = None,
    replay_id: Annotated[
        list[str] | None,
        typer.Option(
            "--replay-id",
            help="Explicit replay ID to hydrate; repeatable. "
            "Mutually exclusive with --user.",
        ),
    ] = None,
    from_date: Annotated[
        str | None,
        typer.Option("--from", help="ISO date (YYYY-MM-DD). Required with --user."),
    ] = None,
    to_date: Annotated[
        str | None,
        typer.Option("--to", help="ISO date (YYYY-MM-DD). Required with --user."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum summaries to return. Default 100."),
    ] = 100,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Discover replays for a user, or hydrate explicit IDs.

    Issues a single Insights query against ``$mp_session_record`` grouped on
    ``$mp_replay_id`` and ``$mp_replay_retention_period``. Empty result is
    success (exit 0), not an error.

    Args:
        ctx: Typer context with global options.
        user: distinct_id; mutually exclusive with --replay-id.
        replay_id: Explicit replay IDs; mutually exclusive with --user.
        from_date: ISO date window start (required with --user).
        to_date: ISO date window end (required with --user).
        limit: Maximum summaries to return.
        format: Output format.
        jq_filter: Optional jq expression for JSON output.
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Listing replays..."):
        summaries = workspace.list_replays(
            distinct_id=user,
            replay_ids=replay_id,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
    output_result(
        ctx,
        [s.to_dict() for s in summaries],
        format=format,
        jq_filter=jq_filter,
    )


# =============================================================================
# mp replays events
# =============================================================================


@replays_app.command("events")
@handle_errors
def replays_events(
    ctx: typer.Context,
    replay_id: Annotated[
        str,
        typer.Argument(help="The replay ID to fetch Mixpanel events for."),
    ],
    properties: Annotated[
        str | None,
        typer.Option(
            "--properties",
            help="Comma-separated event properties as group keys. Max 5.",
        ),
    ] = None,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Mixpanel events that occurred during a replay's time window.

    The optional ``--properties`` flag accepts up to 5 event-property names
    that become group keys; more than 5 exits with code 3 per the Insights
    API cap.

    Args:
        ctx: Typer context with global options.
        replay_id: The replay to query.
        properties: Comma-separated property names (up to 5).
        format: Output format.
        jq_filter: Optional jq expression.
    """
    workspace = get_workspace(ctx)
    prop_list = (
        [p.strip() for p in properties.split(",") if p.strip()] if properties else None
    )
    with status_spinner(ctx, "Fetching replay events..."):
        events = workspace.events_for_replay(replay_id, event_properties=prop_list)
    output_result(
        ctx,
        [e.to_dict() for e in events],
        format=format,
        jq_filter=jq_filter,
    )


# =============================================================================
# mp replays sign
# =============================================================================


@replays_app.command("sign")
@handle_errors
def replays_sign(
    ctx: typer.Context,
    replay_ids: Annotated[
        list[str],
        typer.Argument(help="One or more replay IDs to sign."),
    ],
    env: Annotated[
        str,
        typer.Option(
            "--env",
            help="Replay environment ('prod' or 'dev'). Default 'prod'.",
        ),
    ] = "prod",
    reveal_signed_urls: Annotated[
        bool,
        typer.Option(
            "--reveal-signed-urls",
            help=(
                "Opt into full bearer-credential disclosure. Emits a stderr "
                "warning on every invocation."
            ),
        ),
    ] = False,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Sign one or more replay IDs for CDN access.

    Default output masks ``query_string`` as ``<redacted N chars>`` so the
    bearer credential never ends up in default logs. ``--reveal-signed-urls``
    opts into the full credential AND prints a stderr warning every
    invocation — meant for explicit "I am about to fetch this in a script"
    use cases, not exploratory CLI work.

    Args:
        ctx: Typer context.
        replay_ids: Replay IDs to sign.
        env: 'prod' or 'dev'.
        reveal_signed_urls: When True, output the raw bearer credential
            AND warn on stderr.
        format: Output format.
        jq_filter: Optional jq expression.
    """
    if env not in ("prod", "dev"):
        raise typer.BadParameter(f"env must be 'prod' or 'dev'; got {env!r}")

    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Signing replays..."):
        signed = workspace.sign_replays(replay_ids, env=env)  # type: ignore[arg-type]

    if reveal_signed_urls:
        # Emit the warning EVERY invocation — even when stdout is piped to a
        # file; the credential is sensitive regardless of pipeline shape.
        print(_BEARER_WARNING, file=sys.stderr)
        # to_dict() includes the full credential plus the documented _warning
        # key so downstream serializers can surface the risk.
        payload = [s.to_dict() for s in signed]
    else:
        # Default: use the masking that SignedReplay.__repr__ provides,
        # serialized to a flat dict with redacted query_string + expires_at.
        payload = [
            {
                "replay_id": s.replay_id,
                "url": s.url,
                "query_string": f"<redacted {len(s.query_string)} chars>",
                "env": s.env,
                "signed_at": s.signed_at,
                "expires_at": s.expires_at,
            }
            for s in signed
        ]

    output_result(ctx, payload, format=format, jq_filter=jq_filter)


# =============================================================================
# mp replays fetch
# =============================================================================


@replays_app.command("fetch")
@handle_errors
def replays_fetch(
    ctx: typer.Context,
    replay_id: Annotated[
        str,
        typer.Argument(help="The replay ID to fetch."),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--output",
            help=(
                "Write rrweb events as a JSON array to this file. When "
                "omitted, prints a one-line summary to stdout."
            ),
        ),
    ] = None,
    env: Annotated[
        str,
        typer.Option("--env", help="Replay environment ('prod' or 'dev')."),
    ] = "prod",
    include_events: Annotated[
        bool,
        typer.Option(
            "--include-events",
            help="Trigger the Mixpanel-events join (populates mixpanel_events).",
        ),
    ] = False,
    max_files: Annotated[
        int,
        typer.Option("--max-files", help="Hard upper bound on CDN walk."),
    ] = 500,
) -> None:
    """Pull raw rrweb bytes for a single replay.

    With ``-o file.json`` the output is a timestamp-sorted JSON array
    directly compatible with the rrweb JS player. Without ``-o`` the
    command prints a one-line summary (event count, duration, retention)
    to stdout.

    Args:
        ctx: Typer context.
        replay_id: The replay to fetch.
        output: Optional path to write the rrweb JSON array.
        env: 'prod' or 'dev'.
        include_events: Whether to fire the Mixpanel-events join.
        max_files: Upper bound on the CDN walk.
    """
    if env not in ("prod", "dev"):
        raise typer.BadParameter(f"env must be 'prod' or 'dev'; got {env!r}")

    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching replay..."):
        replay = workspace.fetch_replay(
            replay_id,
            env=env,  # type: ignore[arg-type]
            max_files=max_files,
            include_mixpanel_events=include_events,
        )

    if output is not None:
        # Player-compatible: timestamp-sorted array of raw rrweb events.
        output.write_text(json.dumps(replay.to_rrweb_player_json()))
        return

    duration_minutes = int(replay.duration_seconds // 60)
    duration_seconds = int(replay.duration_seconds % 60)
    print(
        f"fetched {replay.replay_id} — {len(replay.rrweb_events)} events, "
        f"{duration_minutes}m {duration_seconds:02d}s, "
        f"{replay.retention_days}-day retention"
    )


# =============================================================================
# mp replays analyze (Phase 2)
# =============================================================================


@replays_app.command("analyze")
@handle_errors
def replays_analyze(
    ctx: typer.Context,
    replay_id: Annotated[
        str,
        typer.Argument(help="The replay ID to analyze."),
    ],
    format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format. 'plain' = markdown timeline; 'json' = action list.",
        ),
    ] = "plain",
) -> None:
    """Render an analyzer-produced markdown timeline for a single replay.

    Default output is the markdown timeline (suitable for stdout or LLM
    consumption). With ``--format json`` the command emits the normalized
    action list as a JSON array.

    Args:
        ctx: Typer context.
        replay_id: The replay to analyze.
        format: 'plain' (default markdown) or 'json' (action list).
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Analyzing replay..."):
        replay = workspace.fetch_replay(replay_id)
    if format == "json":
        print(json.dumps([a.to_dict() for a in replay.actions], indent=2))
    else:
        print(replay.summary_markdown)


# =============================================================================
# mp replays for-user (Phase 2)
# =============================================================================


@replays_app.command("for-user")
@handle_errors
def replays_for_user(
    ctx: typer.Context,
    user: Annotated[
        str,
        typer.Argument(help="Mixpanel distinct_id to fetch replays for."),
    ],
    from_date: Annotated[
        str,
        typer.Option("--from", help="ISO date (YYYY-MM-DD)."),
    ],
    to_date: Annotated[
        str,
        typer.Option("--to", help="ISO date (YYYY-MM-DD)."),
    ],
    include: Annotated[
        list[str] | None,
        typer.Option(
            "--include",
            help="Extras to fetch; repeatable. Accepts 'analyze'.",
        ),
    ] = None,
    mixpanel_events: Annotated[
        bool,
        typer.Option(
            "--mixpanel-events/--no-mixpanel-events",
            help="Include the Mixpanel event stream alongside actions. Default on.",
        ),
    ] = True,
    out_dir: Annotated[
        Path | None,
        typer.Option(
            "--out-dir",
            help=(
                "Directory to write per-replay markdown + index.json. "
                "When omitted, markdown summaries are concatenated to stdout."
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum replays. Default 100."),
    ] = 100,
) -> None:
    """Discovery + fetch + analyze in one command.

    Args:
        ctx: Typer context.
        user: Mixpanel distinct_id.
        from_date: ISO date window start.
        to_date: ISO date window end.
        include: Repeatable 'analyze' opt-in (emit per-replay markdown).
        mixpanel_events: Include the Mixpanel event stream alongside actions.
            Defaults to True, matching Workspace.replays_for_user.
        out_dir: Directory to write per-replay outputs (+ index.json).
        limit: Maximum replays.
    """
    include_set = set(include or [])
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching replay bundle..."):
        bundle = workspace.replays_for_user(
            user,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            include_mixpanel_events=mixpanel_events,
        )
    if not bundle.replays:
        print(f"no replays found for {user} in {from_date}..{to_date}")
        return

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        if "analyze" in include_set:
            for replay in bundle.replays:
                (out_dir / f"{replay.replay_id}-summary.md").write_text(
                    replay.summary_markdown
                )
        # index.json mirrors bundle.sessions_df for downstream consumers.
        index_path = out_dir / "index.json"
        index_path.write_text(bundle.sessions_df.to_json(orient="records"))
        df = bundle.sessions_df
        total_actions = int(df["n_actions"].sum()) if not df.empty else 0
        total_clicks = int(df["n_clicks"].sum()) if not df.empty else 0
        total_errors = int(df["n_errors"].sum()) if not df.empty else 0
        print(
            f"wrote {len(bundle.replays)} replays to {out_dir}/\n"
            f"total: {total_actions} actions, {total_clicks} clicks, "
            f"{total_errors} errors"
        )
        return

    # Stdout fall-through: concatenated markdown summaries.
    if "analyze" in include_set:
        for replay in bundle.replays:
            print(replay.summary_markdown)
            print("\n---\n")
    else:
        print(bundle.summary_markdown)
