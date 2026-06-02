"""Schema discovery commands.

This module provides commands for inspecting Mixpanel project data:

Live (calls Mixpanel API):
- events: List event names from Mixpanel
- properties: List properties for an event
- values: List values for a property
- subproperties: Discover subproperties of a list-of-object property
- funnels: List saved funnels
- cohorts: List saved cohorts
- top-events: List today's top events
- bookmarks: List saved reports (bookmarks)
- lexicon-schemas: List Lexicon schemas
- lexicon-schema: Get a single Lexicon schema
"""

from __future__ import annotations

from typing import Annotated

import typer

from mixpanel_headless.cli.options import FormatOption, JqOption
from mixpanel_headless.cli.utils import (
    get_workspace,
    handle_errors,
    output_result,
    status_spinner,
)
from mixpanel_headless.cli.validators import (
    validate_count_type,
    validate_entity_type,
)

inspect_app = typer.Typer(
    name="inspect",
    help="Inspect Mixpanel project schema.",
    epilog="""Live (calls Mixpanel API):
  events, properties, values, subproperties, funnels, cohorts, top-events,
  bookmarks, lexicon-schemas, lexicon-schema""",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)


@inspect_app.command("events")
@handle_errors
def inspect_events(
    ctx: typer.Context,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List all event names from Mixpanel project.

    Calls the Mixpanel API to retrieve tracked event types. Use this
    to discover what events exist before querying.

    Output Structure (JSON):

        ["Sign Up", "Login", "Purchase", "Page View", "Add to Cart"]

    Examples:

        mp inspect events
        mp inspect events --format table
        mp inspect events --format json --jq '.[0:3]'

    **jq Examples:**

        --jq '.[0:5]'                                 # Get first 5 events
        --jq 'length'                                 # Count total events
        --jq '[.[] | select(contains("Purchase"))]'  # Find events containing "Purchase"
        --jq 'sort'                                   # Sort alphabetically
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching events..."):
        events = workspace.events()
    output_result(ctx, events, format=format, jq_filter=jq_filter)


@inspect_app.command("properties")
@handle_errors
def inspect_properties(
    ctx: typer.Context,
    event: Annotated[
        str,
        typer.Option("--event", "-e", help="Event name."),
    ],
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List properties for a specific event.

    Calls the Mixpanel API to retrieve property names tracked with an event.
    Shows both custom event properties and default Mixpanel properties.

    Output Structure (JSON):

        ["country", "browser", "device", "$city", "$region", "plan_type"]

    Examples:

        mp inspect properties -e "Sign Up"
        mp inspect properties -e "Purchase" --format table

    **jq Examples:**

        --jq '.[0:10]'                                    # Get first 10 properties
        --jq '[.[] | select(startswith("$") | not)]'     # User-defined properties (no $ prefix)
        --jq '[.[] | select(startswith("$"))]'           # Mixpanel system properties ($ prefix)
        --jq 'length'                                     # Count properties
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching properties..."):
        properties = workspace.properties(event)
    output_result(ctx, properties, format=format, jq_filter=jq_filter)


@inspect_app.command("values")
@handle_errors
def inspect_values(
    ctx: typer.Context,
    property_name: Annotated[
        str,
        typer.Option("--property", "-p", help="Property name."),
    ],
    event: Annotated[
        str | None,
        typer.Option("--event", "-e", help="Event name (optional)."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum values to return."),
    ] = 100,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List sample values for a property.

    Calls the Mixpanel API to retrieve sample values for a property.
    Useful for understanding the data shape before writing queries.

    Output Structure (JSON):

        ["US", "UK", "DE", "FR", "CA", "AU", "JP"]

    Examples:

        mp inspect values -p country
        mp inspect values -p country -e "Sign Up" --limit 20
        mp inspect values -p browser --format table

    **jq Examples:**

        --jq '.[0:5]'                          # Get first 5 values
        --jq 'length'                          # Count unique values
        --jq '[.[] | select(test("^U"))]'      # Filter values matching pattern
        --jq 'sort'                            # Sort values alphabetically
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching values..."):
        values = workspace.property_values(
            property_name=property_name,
            event=event,
            limit=limit,
        )
    output_result(ctx, values, format=format, jq_filter=jq_filter)


@inspect_app.command("subproperties")
@handle_errors
def inspect_subproperties(
    ctx: typer.Context,
    property_name: Annotated[
        str,
        typer.Option("--property", "-p", help="List-of-object property name."),
    ],
    event: Annotated[
        str | None,
        typer.Option("--event", "-e", help="Event name (strongly recommended)."),
    ] = None,
    sample_size: Annotated[
        int,
        typer.Option("--sample-size", "-s", help="Number of raw values to sample."),
    ] = 50,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Discover subproperties of a list-of-object event property.

    Samples raw values via the Mixpanel property-values endpoint, parses
    each as JSON, and infers a scalar type per discovered subproperty.
    Use this when an event property like ``cart`` is a list of objects
    (e.g. ``[{"Brand": "nike", "Price": 50}, ...]``) — the discovered
    subproperty names and types feed directly into ``Filter.list_contains``
    and ``GroupBy.list_item`` (Python API).

    Output Structure (JSON):

        [
          {"name": "Brand", "type": "string", "sample_values": ["nike", "puma"]},
          {"name": "Category", "type": "string", "sample_values": ["hats", "jeans"]},
          {"name": "Price", "type": "number", "sample_values": [51, 87, 102]}
        ]

    Examples:

        mp inspect subproperties -p cart -e "Cart Viewed"
        mp inspect subproperties -p line_items -e Purchase --sample-size 100
        mp inspect subproperties -p cart -e "Cart Viewed" --format table

    **jq Examples:**

        --jq '[.[] | select(.type == "number")]'      # Numeric subproperties only
        --jq '[.[].name]'                              # Subproperty names only
        --jq '.[] | select(.name == "Brand")'          # Find a specific subproperty
        --jq '[.[] | {name, type}]'                    # Drop sample_values
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Sampling subproperties..."):
        subs = workspace.subproperties(
            property_name=property_name,
            event=event,
            sample_size=sample_size,
        )
    data = [sp.to_dict() for sp in subs]
    output_result(
        ctx,
        data,
        columns=["name", "type", "sample_values"],
        format=format,
        jq_filter=jq_filter,
    )


@inspect_app.command("funnels")
@handle_errors
def inspect_funnels(
    ctx: typer.Context,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List saved funnels in Mixpanel project.

    Calls the Mixpanel API to retrieve saved funnel definitions.
    Use the funnel_id with 'mp query funnel' to run funnel analysis.

    Output Structure (JSON):

        [
          {"funnel_id": 12345, "name": "Onboarding Flow"},
          {"funnel_id": 12346, "name": "Purchase Funnel"},
          {"funnel_id": 12347, "name": "Trial to Paid"}
        ]

    Examples:

        mp inspect funnels
        mp inspect funnels --format table

    **jq Examples:**

        --jq '[.[].funnel_id]'                               # Get all funnel IDs
        --jq '.[] | select(.name | test("Purchase"; "i"))'   # Find funnel by name pattern
        --jq '[.[].name]'                                    # Get funnel names only
        --jq 'length'                                        # Count funnels
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching funnels..."):
        funnels = workspace.funnels()
    data = [{"funnel_id": f.funnel_id, "name": f.name} for f in funnels]
    output_result(
        ctx, data, columns=["funnel_id", "name"], format=format, jq_filter=jq_filter
    )


@inspect_app.command("cohorts")
@handle_errors
def inspect_cohorts(
    ctx: typer.Context,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List saved cohorts in Mixpanel project.

    Calls the Mixpanel API to retrieve saved cohort definitions.
    Shows cohort ID, name, user count, and description.

    Output Structure (JSON):

        [
          {"id": 1001, "name": "Power Users", "count": 5420, "description": "Users with 10+ sessions"},
          {"id": 1002, "name": "Trial Users", "count": 892, "description": "Active trial accounts"},
          {"id": 1003, "name": "Churned", "count": 2341, "description": "No activity in 30 days"}
        ]

    Examples:

        mp inspect cohorts
        mp inspect cohorts --format table

    **jq Examples:**

        --jq '[.[] | select(.count > 1000)]'           # Cohorts with more than 1000 users
        --jq '[.[].name]'                              # Get cohort names only
        --jq 'sort_by(.count) | reverse'               # Sort by user count descending
        --jq '.[] | select(.name == "Power Users")'    # Find cohort by name
    """
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching cohorts..."):
        cohorts = workspace.cohorts()
    data = [
        {
            "id": c.id,
            "name": c.name,
            "count": c.count,
            "description": c.description,
        }
        for c in cohorts
    ]
    output_result(
        ctx,
        data,
        columns=["id", "name", "count", "description"],
        format=format,
        jq_filter=jq_filter,
    )


@inspect_app.command("top-events")
@handle_errors
def inspect_top_events(
    ctx: typer.Context,
    type_: Annotated[
        str,
        typer.Option("--type", "-t", help="Count type: general, unique, average."),
    ] = "general",
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum events to return."),
    ] = 10,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List today's top events by count.

    Calls the Mixpanel API to retrieve today's most frequent events.
    Useful for quick overview of project activity.

    Output Structure (JSON):

        [
          {"event": "Page View", "count": 15234, "percent_change": 12.5},
          {"event": "Login", "count": 8921, "percent_change": -3.2},
          {"event": "Purchase", "count": 1456, "percent_change": 8.7}
        ]

    Examples:

        mp inspect top-events
        mp inspect top-events --limit 20 --format table
        mp inspect top-events --type unique

    **jq Examples:**

        --jq '[.[] | select(.percent_change > 0)]'    # Events with positive growth
        --jq '[.[].event]'                            # Get just event names
        --jq '[.[] | select(.count > 10000)]'         # Events with count over 10000
        --jq 'max_by(.percent_change)'                # Event with highest growth
    """
    validated_type = validate_count_type(type_)
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching top events..."):
        events = workspace.top_events(type=validated_type, limit=limit)
    data = [
        {
            "event": e.event,
            "count": e.count,
            "percent_change": e.percent_change,
        }
        for e in events
    ]
    output_result(
        ctx,
        data,
        columns=["event", "count", "percent_change"],
        format=format,
        jq_filter=jq_filter,
    )


@inspect_app.command("bookmarks")
@handle_errors
def inspect_bookmarks(
    ctx: typer.Context,
    type_: Annotated[
        str | None,
        typer.Option(
            "--type",
            "-t",
            help="Filter by type: insights, funnels, retention, flows, launch-analysis.",
        ),
    ] = None,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List saved reports (bookmarks) in Mixpanel project.

    Calls the Mixpanel API to retrieve saved report definitions.
    Use the bookmark ID with 'mp query saved-report' or 'mp query flows'.

    Output Structure (JSON):

        [
          {"id": 98765, "name": "Weekly KPIs", "type": "insights", "modified": "2024-01-15T10:30:00"},
          {"id": 98766, "name": "Conversion Funnel", "type": "funnels", "modified": "2024-01-14T15:45:00"},
          {"id": 98767, "name": "User Retention", "type": "retention", "modified": "2024-01-13T09:20:00"}
        ]

    Examples:

        mp inspect bookmarks
        mp inspect bookmarks --type insights
        mp inspect bookmarks --type funnels --format table

    **jq Examples:**

        --jq '[.[] | select(.type == "insights")]'    # Get bookmarks by type
        --jq '[.[].id]'                               # Get bookmark IDs only
        --jq 'sort_by(.modified) | reverse'           # Sort by modified date (newest first)
        --jq '.[] | select(.name | test("KPI"; "i"))' # Find bookmark by name
    """
    workspace = get_workspace(ctx)

    with status_spinner(ctx, "Fetching bookmarks..."):
        bookmarks = workspace.list_bookmarks(bookmark_type=type_)  # type: ignore[arg-type]
    data = [
        {
            "id": b.id,
            "name": b.name,
            "type": b.type,
            "modified": b.modified,
        }
        for b in bookmarks
    ]
    output_result(
        ctx,
        data,
        columns=["id", "name", "type", "modified"],
        format=format,
        jq_filter=jq_filter,
    )


@inspect_app.command("lexicon-schemas")
@handle_errors
def inspect_lexicon_schemas(
    ctx: typer.Context,
    type_: Annotated[
        str | None,
        typer.Option(
            "--type", "-t", help="Entity type: event, profile, custom_event, etc."
        ),
    ] = None,
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """List Lexicon schemas from Mixpanel data dictionary.

    Retrieves documented event and profile property schemas from the
    Mixpanel Lexicon. Shows schema names, types, and property counts.

    Output Structure (JSON):

        [
          {"entity_type": "event", "name": "Purchase", "property_count": 12, "description": "User completed purchase"},
          {"entity_type": "event", "name": "Sign Up", "property_count": 8, "description": "New user registration"},
          {"entity_type": "profile", "name": "Plan Type", "property_count": 3, "description": "User subscription tier"}
        ]

    Examples:

        mp inspect lexicon-schemas
        mp inspect lexicon-schemas --type event
        mp inspect lexicon-schemas --type profile --format table

    **jq Examples:**

        --jq '[.[] | select(.entity_type == "event")]'             # Get only event schemas
        --jq '[.[].name]'                                          # Get schema names
        --jq '[.[] | select(.property_count > 10)]'                # Schemas with many properties
        --jq '[.[] | select(.description | test("purchase"; "i"))]' # Search by description
    """
    validated_type = validate_entity_type(type_) if type_ is not None else None
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching schemas..."):
        schemas = workspace.lexicon_schemas(entity_type=validated_type)
    data = [
        {
            "entity_type": s.entity_type,
            "name": s.name,
            "property_count": len(s.schema_json.properties),
            "description": s.schema_json.description,
        }
        for s in schemas
    ]
    output_result(
        ctx,
        data,
        columns=["entity_type", "name", "property_count", "description"],
        format=format,
        jq_filter=jq_filter,
    )


@inspect_app.command("lexicon-schema")
@handle_errors
def inspect_lexicon_schema(
    ctx: typer.Context,
    type_: Annotated[
        str,
        typer.Option(
            "--type", "-t", help="Entity type: event, profile, custom_event, etc."
        ),
    ],
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Entity name."),
    ],
    format: FormatOption = "json",
    jq_filter: JqOption = None,
) -> None:
    """Get a single Lexicon schema from Mixpanel data dictionary.

    Retrieves the full schema definition for a specific event or profile
    property, including all property definitions and metadata.

    Output Structure (JSON):

        {
          "entity_type": "event",
          "name": "Purchase",
          "schema_json": {
            "description": "User completed a purchase",
            "properties": {
              "amount": {"type": "number", "description": "Purchase amount in USD"},
              "currency": {"type": "string", "description": "Currency code"},
              "product_id": {"type": "string", "description": "Product identifier"}
            },
            "metadata": {"hidden": false, "dropped": false, "tags": ["revenue"]}
          }
        }

    Examples:

        mp inspect lexicon-schema --type event --name "Purchase"
        mp inspect lexicon-schema -t event -n "Sign Up"
        mp inspect lexicon-schema -t profile -n "Plan Type" --format json

    **jq Examples:**

        --jq '.schema_json.properties | keys'                                                     # Get property names only
        --jq '.schema_json.properties | to_entries | [.[] | {name: .key, type: .value.type}]'    # Get property types
        --jq '.schema_json.description'                                                           # Get description
        --jq '.schema_json.metadata.hidden'                                                       # Check if schema is hidden
    """
    validated_type = validate_entity_type(type_)
    workspace = get_workspace(ctx)
    with status_spinner(ctx, "Fetching schema..."):
        schema = workspace.lexicon_schema(validated_type, name)
    output_result(ctx, schema.to_dict(), format=format, jq_filter=jq_filter)
