"""Tests for the schema graph: full lexicon + event<->property relationships (PR3).

Five layers:

- ``SchemaGraphResult`` DataFrame views, networkx export, convenience accessors;
- the ``MixpanelAPIClient`` bulk lexicon calls (URL/params, shape handling);
- ``DiscoveryService.get_schema_graph`` adjacency building + caching;
- the ``Workspace.schema_graph`` facade;
- the ``mp inspect schema-graph`` CLI command.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
import typer.testing
from pydantic import SecretStr

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless._internal.services.discovery import DiscoveryService
from mixpanel_headless.cli.main import app
from mixpanel_headless.exceptions import MixpanelHeadlessError
from mixpanel_headless.types import SchemaGraphResult
from mixpanel_headless.workspace import Workspace

runner = typer.testing.CliRunner()

_SESSION = Session(
    account=ServiceAccount(
        name="t",
        region="us",
        username="u",
        secret=SecretStr("s"),
        default_project="12345",
    ),
    project=Project(id="12345"),
)


def _sample_result() -> SchemaGraphResult:
    """Build a small SchemaGraphResult covering an edge, an orphan, and a user prop."""
    return SchemaGraphResult(
        computed_at="2026-06-03T00:00:00+00:00",
        events=[{"name": "Purchase", "displayName": "Purchase", "count": 10}],
        properties=[
            # densityLocal is a property-level field; it repeats onto each edge.
            {"name": "amount", "densityLocal": 0.9, "events": [{"name": "Purchase"}]},
            {"name": "orphan", "events": []},
        ],
        user_properties=[
            {"name": "plan", "resourceType": "User", "displayName": "Plan"}
        ],
        event_to_properties={"Purchase": ["amount"]},
        property_to_events={"amount": ["Purchase"], "orphan": []},
        include_density=True,
    )


class TestSchemaGraphResult:
    """DataFrame views, graph, and convenience accessors."""

    def test_events_df_shape(self) -> None:
        """events_df has the expected columns and row."""
        df = _sample_result().events_df
        assert list(df.columns) == [
            "name",
            "display_name",
            "description",
            "hidden",
            "dropped",
            "verified",
            "count",
        ]
        assert df.iloc[0]["name"] == "Purchase"
        assert df.iloc[0]["display_name"] == "Purchase"

    def test_properties_df_covers_event_and_user(self) -> None:
        """properties_df includes event and user properties with resource_type."""
        df = _sample_result().properties_df
        by_name = {r["name"]: r for r in df.to_dict("records")}
        assert by_name["amount"]["resource_type"] == "event"
        assert by_name["plan"]["resource_type"] == "user"
        assert by_name["plan"]["display_name"] == "Plan"

    def test_relationships_df_is_edge_list(self) -> None:
        """relationships_df is one row per (event, property) with density."""
        df = _sample_result().relationships_df
        assert list(df.columns) == ["event", "property", "density_local"]
        assert len(df) == 1
        row = df.iloc[0]
        assert row["event"] == "Purchase"
        assert row["property"] == "amount"
        assert row["density_local"] == 0.9

    def test_df_is_relationships(self) -> None:
        """The headline ``df`` is the relationship edge list."""
        result = _sample_result()
        assert result.df.equals(result.relationships_df)

    def test_convenience_accessors(self) -> None:
        """properties_for_event / events_for_property / orphan_properties."""
        result = _sample_result()
        assert result.properties_for_event("Purchase") == ["amount"]
        assert result.events_for_property("amount") == ["Purchase"]
        assert result.orphan_properties() == ["orphan"]
        assert result.properties_for_event("missing") == []

    def test_orphan_properties_skips_nameless(self) -> None:
        """A property dict without a name never leaks into orphan_properties."""
        result = SchemaGraphResult(
            computed_at="t",
            properties=[{"events": []}, {"name": "real", "events": []}],
        )
        assert result.orphan_properties() == ["real"]

    def test_to_graph_is_bipartite(self) -> None:
        """to_graph yields a directed event->property graph with node kinds."""
        g = _sample_result().to_graph()
        assert g.nodes["Purchase"]["kind"] == "event"
        assert g.nodes["amount"]["kind"] == "property"
        assert g.nodes["orphan"]["kind"] == "property"
        assert list(g.successors("Purchase")) == ["amount"]
        assert g.edges["Purchase", "amount"]["density_local"] == 0.9
        # no property->anything edges
        assert list(g.successors("amount")) == []
        assert list(g.successors("orphan")) == []

    def test_to_graph_cached(self) -> None:
        """to_graph caches the constructed graph."""
        result = _sample_result()
        assert result.to_graph() is result.to_graph()

    def test_empty_result_has_typed_empty_frames(self) -> None:
        """An empty result returns empty DataFrames with the right columns."""
        result = SchemaGraphResult(computed_at="t")
        assert result.events_df.empty
        assert list(result.relationships_df.columns) == [
            "event",
            "property",
            "density_local",
        ]
        assert result.to_graph().number_of_nodes() == 0

    def test_to_dict_round_trips_fields(self) -> None:
        """to_dict exposes all the structured fields."""
        d = _sample_result().to_dict()
        assert d["event_to_properties"] == {"Purchase": ["amount"]}
        assert d["include_density"] is True
        assert "user_properties" in d

    def test_dataframes_are_cached(self) -> None:
        """Each DataFrame view is built once and cached for reuse."""
        result = _sample_result()
        assert result.events_df is result.events_df
        assert result.properties_df is result.properties_df
        assert result.relationships_df is result.relationships_df


def _client(handler: Any) -> MixpanelAPIClient:
    """Build a client wired to a MockTransport handler."""
    return MixpanelAPIClient(session=_SESSION, _transport=httpx.MockTransport(handler))


class TestApiClientBulkLexicon:
    """The bulk no-filter lexicon calls."""

    def test_list_property_definitions_include_events_params(self) -> None:
        """include_events adds includeEvents=true and resourceType to the query."""
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(
                200, json=[{"name": "amount", "events": [{"name": "Purchase"}]}]
            )

        rows = _client(handler).list_property_definitions(
            resource_type="Event", include_events=True
        )
        assert seen["params"]["resourceType"] == "Event"
        assert seen["params"]["includeEvents"] == "true"
        assert rows[0]["events"][0]["name"] == "Purchase"

    def test_list_property_definitions_density_toggle(self) -> None:
        """include_density adds includeDensity=true only when requested."""
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=[])

        _client(handler).list_property_definitions(include_density=True)
        assert seen["params"]["includeDensity"] == "true"

    def test_list_event_definitions_returns_bare_list(self) -> None:
        """list_event_definitions returns the bare list the API sends."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"name": "Purchase"}])

        rows = _client(handler).list_event_definitions()
        assert rows == [{"name": "Purchase"}]

    def test_list_event_definitions_raises_on_unexpected_shape(self) -> None:
        """A non-list response (no results envelope to unwrap) is rejected."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        with pytest.raises(MixpanelHeadlessError, match="expected list"):
            _client(handler).list_event_definitions()

    def test_list_property_definitions_raises_on_unexpected_shape(self) -> None:
        """A non-list property response is rejected."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        with pytest.raises(MixpanelHeadlessError, match="expected list"):
            _client(handler).list_property_definitions()


class TestDiscoveryGetSchemaGraph:
    """DiscoveryService.get_schema_graph composition + caching."""

    def _mock_api(self) -> MagicMock:
        """Mock api client returning small lexicon lists."""
        api = MagicMock()
        api.list_event_definitions.return_value = [
            {"name": "Purchase", "displayName": "Purchase"},
            {"name": "Login"},
        ]

        def list_props(
            *, resource_type: str = "Event", **_: Any
        ) -> list[dict[str, Any]]:
            if resource_type == "User":
                return [{"name": "plan", "resourceType": "User"}]
            return [
                {"name": "amount", "events": [{"name": "Purchase"}]},
                {"name": "ts", "events": [{"name": "Purchase"}, {"name": "Login"}]},
            ]

        api.list_property_definitions.side_effect = list_props
        return api

    def test_builds_adjacency_maps(self) -> None:
        """Adjacency maps are built from the property event lists."""
        svc = DiscoveryService(self._mock_api())
        result = svc.get_schema_graph()
        assert result.event_to_properties["Purchase"] == ["amount", "ts"]
        assert result.event_to_properties["Login"] == ["ts"]
        assert result.property_to_events["amount"] == ["Purchase"]
        assert result.user_properties == [{"name": "plan", "resourceType": "User"}]
        assert result.meta["event_count"] == 2

    def test_caches_and_force_refresh(self) -> None:
        """Results are cached; force_refresh re-fetches."""
        api = self._mock_api()
        svc = DiscoveryService(api)
        svc.get_schema_graph()
        svc.get_schema_graph()
        assert api.list_event_definitions.call_count == 1
        svc.get_schema_graph(force_refresh=True)
        assert api.list_event_definitions.call_count == 2

    def test_skip_user_properties(self) -> None:
        """include_user_properties=False skips the user call."""
        api = self._mock_api()
        result = DiscoveryService(api).get_schema_graph(include_user_properties=False)
        assert result.user_properties == []
        # only the Event resource_type call was made
        resource_types = [
            c.kwargs.get("resource_type")
            for c in api.list_property_definitions.call_args_list
        ]
        assert "User" not in resource_types

    def test_clear_cache_resets_schema_graph(self) -> None:
        """clear_cache drops the schema-graph cache so the next call re-fetches."""
        api = self._mock_api()
        svc = DiscoveryService(api)
        svc.get_schema_graph()
        assert api.list_event_definitions.call_count == 1
        svc.clear_cache()
        svc.get_schema_graph()
        assert api.list_event_definitions.call_count == 2

    def test_density_flows_from_property_to_edges(self) -> None:
        """A property-level densityLocal lands on every edge and graph edge."""
        api = MagicMock()
        api.list_event_definitions.return_value = [{"name": "Purchase"}]
        api.list_property_definitions.return_value = [
            {"name": "amount", "densityLocal": 0.75, "events": [{"name": "Purchase"}]}
        ]
        result = DiscoveryService(api).get_schema_graph(
            include_density=True, include_user_properties=False
        )
        assert result.include_density is True
        assert result.relationships_df.iloc[0]["density_local"] == 0.75
        assert result.to_graph().edges["Purchase", "amount"]["density_local"] == 0.75


class TestFacadeAndCli:
    """Workspace facade delegation and the CLI command."""

    def test_facade_delegates(self) -> None:
        """Workspace.schema_graph delegates to the discovery service."""
        api = MagicMock()
        api.list_event_definitions.return_value = [{"name": "Purchase"}]
        api.list_property_definitions.return_value = []
        ws = Workspace(session=_SESSION, _api_client=api)
        result = ws.schema_graph(include_user_properties=False)
        assert isinstance(result, SchemaGraphResult)
        assert "Purchase" in result.event_to_properties

    @patch("mixpanel_headless.cli.commands.inspect.get_workspace")
    def test_cli_json(self, mock_get_ws: MagicMock) -> None:
        """`mp inspect schema-graph` emits the structured dict as JSON."""
        mock_ws = MagicMock()
        mock_ws.schema_graph.return_value = _sample_result()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["inspect", "schema-graph"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["event_to_properties"] == {"Purchase": ["amount"]}

    @patch("mixpanel_headless.cli.commands.inspect.get_workspace")
    def test_cli_table_shows_relationships(self, mock_get_ws: MagicMock) -> None:
        """`--format table` renders the relationship edge list."""
        mock_ws = MagicMock()
        mock_ws.schema_graph.return_value = _sample_result()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["inspect", "schema-graph", "--format", "table"])
        assert result.exit_code == 0
        assert "Purchase" in result.stdout
        assert "amount" in result.stdout
