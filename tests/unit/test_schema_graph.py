"""Tests for the schema graph: full lexicon + event<->property relationships (PR3).

Five layers:

- ``SchemaGraphResult`` DataFrame views, networkx export, convenience accessors;
- the ``MixpanelAPIClient`` bulk lexicon calls (URL/params, shape handling),
  including the query-API per-event properties gather that supplies the
  relationship edges;
- ``DiscoveryService.get_schema_graph`` adjacency building + caching;
- the ``Workspace.schema_graph`` facade;
- the ``mp inspect schema-graph`` CLI command.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
import typer.testing
from pydantic import SecretStr

from mixpanel_headless._internal.api_client import (
    MixpanelAPIClient,
    _canonical_resource_type,
)
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
        # event_to_properties / property_to_events are derived from ``properties``
        # in __post_init__ (init=False), so they are no longer passed here.
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

    def test_density_local_none_when_density_not_requested(self) -> None:
        """Without include_density, density_local is None on each edge + graph edge."""
        result = SchemaGraphResult(
            computed_at="t",
            events=[{"name": "Purchase"}],
            properties=[{"name": "amount", "events": [{"name": "Purchase"}]}],
        )
        assert result.include_density is False
        assert result.relationships_df.iloc[0]["density_local"] is None
        assert result.to_graph().edges["Purchase", "amount"]["density_local"] is None

    def test_non_dict_event_entry_is_filtered(self) -> None:
        """Non-dict / nameless entries in a property's events list are dropped."""
        result = SchemaGraphResult(
            computed_at="t",
            properties=[
                {
                    "name": "amount",
                    "events": ["NotADict", {"no": "name"}, {"name": "Purchase"}],
                }
            ],
        )
        # Only the well-formed {"name": "Purchase"} entry survives.
        assert list(result.relationships_df["event"]) == ["Purchase"]
        assert result.property_to_events["amount"] == ["Purchase"]
        assert list(result.to_graph().successors("Purchase")) == ["amount"]

    def test_relationships_df_skips_nameless_property(self) -> None:
        """A property without a name is skipped by the relationships edge list."""
        result = SchemaGraphResult(
            computed_at="t",
            properties=[
                {"events": [{"name": "Purchase"}]},  # no name -> skipped
                {"name": "amount", "events": [{"name": "Purchase"}]},
            ],
        )
        assert list(result.relationships_df["property"]) == ["amount"]

    def test_events_for_property_unknown_returns_empty(self) -> None:
        """events_for_property on an unknown property name returns []."""
        assert _sample_result().events_for_property("missing") == []

    def test_property_without_events_key(self) -> None:
        """A property dict lacking an ``events`` key contributes no edges."""
        result = SchemaGraphResult(computed_at="t", properties=[{"name": "amount"}])
        assert result.relationships_df.empty
        assert result.property_to_events == {"amount": []}
        assert result.orphan_properties() == ["amount"]

    def test_maps_derived_from_properties(self) -> None:
        """event_to_properties / property_to_events are derived, not passed in.

        Events with no properties are still seeded (so the event is a known key
        and a graph node); the inverse map is built from each property's events.
        """
        result = SchemaGraphResult(
            computed_at="t",
            events=[{"name": "Purchase"}, {"name": "Login"}],
            properties=[{"name": "amount", "events": [{"name": "Purchase"}]}],
        )
        assert result.event_to_properties == {"Purchase": ["amount"], "Login": []}
        assert result.property_to_events == {"amount": ["Purchase"]}
        assert result.properties_for_event("Login") == []
        assert result.to_graph().nodes["Login"]["kind"] == "event"

    def test_meta_records_drop_counts(self) -> None:
        """meta carries entity counts and per-row drop counts."""
        result = SchemaGraphResult(
            computed_at="t",
            events=[{"name": "Purchase"}, {"count": 5}],  # one nameless event
            properties=[
                {"name": "amount", "events": [{"name": "Purchase"}, "bad"]},
                {"events": []},  # nameless property
            ],
            user_properties=[{"name": "plan"}],
        )
        assert result.meta["event_count"] == 2
        assert result.meta["event_property_count"] == 2
        assert result.meta["user_property_count"] == 1
        assert result.meta["events_without_name"] == 1
        assert result.meta["properties_without_name"] == 1
        assert result.meta["property_event_entries_dropped"] == 1
        assert result.meta["relationship_edges"] == 1

    def test_to_dict_contains_all_fields(self) -> None:
        """to_dict exposes every public field."""
        d = _sample_result().to_dict()
        for key in (
            "computed_at",
            "events",
            "properties",
            "user_properties",
            "event_to_properties",
            "property_to_events",
            "include_density",
            "meta",
            "params",
        ):
            assert key in d


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

    def test_list_property_definitions_default_params(self) -> None:
        """A default bulk call pins the canonical params and omits the toggles.

        ``resourceType=Event`` + ``includeCustom`` / ``includeZeroCounts`` are
        sent; ``includeEvents`` / ``includeDensity`` are absent unless requested.
        """
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=[])

        _client(handler).list_property_definitions()
        assert seen["params"]["resourceType"] == "Event"
        assert seen["params"]["includeCustom"] == "true"
        assert seen["params"]["includeZeroCounts"] == "true"
        assert "includeEvents" not in seen["params"]
        assert "includeDensity" not in seen["params"]

    def test_get_property_definitions_normalizes_resource_type(self) -> None:
        """get_* sends the name filter and the normalized camelCase resourceType."""
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=[])

        _client(handler).get_property_definitions(["amount"], resource_type="user")
        assert seen["params"]["name[]"] == "amount"
        assert seen["params"]["resourceType"] == "User"
        # get_* must not send the bulk-only include toggles.
        assert "includeCustom" not in seen["params"]
        assert "includeZeroCounts" not in seen["params"]

    def test_get_event_definitions_sends_name_filter(self) -> None:
        """get_event_definitions sends a name[] filter (the bulk list does not)."""
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=[])

        _client(handler).get_event_definitions(["Purchase"])
        assert seen["params"]["name[]"] == "Purchase"


class TestApiClientPerEventProperties:
    """The query-API per-event properties gather (the relationship source).

    The App API's ``includeEvents=true`` bulk call computes this same join
    behind a ~120s gateway deadline it cannot meet on large projects, so the
    schema graph fetches the edges from the query API instead. The gather is
    two-phase (DF-802): a fast no-flags event-list fetch defines the name
    universe, then the per-event property fetches run in ``name[]`` chunks so
    no single request outlives the ~210s edge-gateway deadline.
    """

    @staticmethod
    def _two_phase_handler(
        listing_rows: list[Any],
        requests_seen: list[dict[str, Any]],
        chunk_rows_fn: Any = None,
    ) -> Any:
        """Build a MockTransport handler for the two-phase gather.

        Args:
            listing_rows: Rows the no-flags event-list request returns.
            requests_seen: Mutable list; each request's URL/params/timeout
                is appended for assertion.
            chunk_rows_fn: Optional callable mapping a decoded ``name[]``
                list to the chunk response rows. Defaults to one row per
                name with a single ``amount`` property.

        Returns:
            A handler suitable for ``httpx.MockTransport``.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            requests_seen.append(
                {
                    "url": str(request.url.copy_with(query=None)),
                    "params": params,
                    "timeout": request.extensions.get("timeout"),
                }
            )
            if "fetch_per_event_properties" not in params:
                return httpx.Response(200, json={"results": listing_rows})
            names = json.loads(params["name[]"])
            if chunk_rows_fn is not None:
                return httpx.Response(200, json={"results": chunk_rows_fn(names)})
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"name": name, "properties": [{"name": "amount"}]}
                        for name in names
                    ]
                },
            )

        return handler

    def test_two_phase_url_params_and_unwrap(self) -> None:
        """A listing fetch precedes one name[]-scoped per-event chunk fetch."""
        seen: list[dict[str, Any]] = []
        handler = self._two_phase_handler([{"name": "Purchase"}], seen)

        rows = _client(handler).list_per_event_properties()

        assert len(seen) == 2
        listing, chunk = seen
        for req in (listing, chunk):
            assert (
                req["url"] == "https://mixpanel.com/api/query/data_definitions/events"
            )
            assert req["params"]["project_id"] == "12345"
        assert "fetch_per_event_properties" not in listing["params"]
        assert "name[]" not in listing["params"]
        assert chunk["params"]["fetch_per_event_properties"] == "true"
        assert chunk["params"]["name[]"] == json.dumps(["Purchase"])
        assert rows == [{"name": "Purchase", "properties": [{"name": "amount"}]}]

    def test_chunks_names_in_batches_of_200(self) -> None:
        """201 unique names split into a 200-name chunk plus a 1-name chunk."""
        names = [f"ev{i}" for i in range(201)]
        seen: list[dict[str, Any]] = []
        handler = self._two_phase_handler([{"name": n} for n in names], seen)

        rows = _client(handler).list_per_event_properties()

        chunk_requests = [r for r in seen if "name[]" in r["params"]]
        assert len(chunk_requests) == 2
        assert json.loads(chunk_requests[0]["params"]["name[]"]) == names[:200]
        assert json.loads(chunk_requests[1]["params"]["name[]"]) == names[200:]
        assert [row["name"] for row in rows] == names

    def test_dedupes_names_and_skips_nameless(self) -> None:
        """Duplicate, empty, and non-dict listing rows never reach name[]."""
        listing = [
            {"name": "A"},
            {"name": "A"},
            {"id": 7},
            {"name": None},
            {"name": ""},
            "junk",
            {"name": "B"},
        ]
        seen: list[dict[str, Any]] = []
        handler = self._two_phase_handler(listing, seen)

        rows = _client(handler).list_per_event_properties()

        chunk_requests = [r for r in seen if "name[]" in r["params"]]
        assert len(chunk_requests) == 1
        assert json.loads(chunk_requests[0]["params"]["name[]"]) == ["A", "B"]
        assert [row["name"] for row in rows] == ["A", "B"]

    def test_no_chunk_call_when_no_names(self) -> None:
        """An empty name universe returns [] without a per-event request."""
        seen: list[dict[str, Any]] = []
        handler = self._two_phase_handler([], seen)

        rows = _client(handler).list_per_event_properties()

        assert rows == []
        assert len(seen) == 1

    def test_uses_export_timeout(self) -> None:
        """Both phases run under the long export timeout, not the default."""
        seen: list[dict[str, Any]] = []
        handler = self._two_phase_handler([{"name": "Purchase"}], seen)

        _client(handler).list_per_event_properties()

        assert [req["timeout"]["read"] for req in seen] == [600.0, 600.0]

    def test_paces_between_chunks(self) -> None:
        """Consecutive chunk fetches pause; a single chunk does not."""
        names = [f"ev{i}" for i in range(201)]
        seen: list[dict[str, Any]] = []
        handler = self._two_phase_handler([{"name": n} for n in names], seen)

        with patch("mixpanel_headless._internal.api_client.time.sleep") as mock_sleep:
            _client(handler).list_per_event_properties()
        assert mock_sleep.call_args_list == [((0.5,),)]

        seen.clear()
        single = self._two_phase_handler([{"name": "Purchase"}], seen)
        with patch("mixpanel_headless._internal.api_client.time.sleep") as mock_sleep:
            _client(single).list_per_event_properties()
        mock_sleep.assert_not_called()

    def test_raises_on_unexpected_listing_shape(self) -> None:
        """A non-list event-list payload is rejected before any chunk fetch."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": {"unexpected": "shape"}})

        with pytest.raises(MixpanelHeadlessError, match="expected list"):
            _client(handler).list_per_event_properties()

    def test_raises_on_unexpected_chunk_shape(self) -> None:
        """A non-list per-event chunk payload is rejected."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "fetch_per_event_properties" not in dict(request.url.params):
                return httpx.Response(200, json={"results": [{"name": "Purchase"}]})
            return httpx.Response(200, json={"results": {"unexpected": "shape"}})

        with pytest.raises(MixpanelHeadlessError, match="expected list"):
            _client(handler).list_per_event_properties()


class TestCanonicalResourceType:
    """The resource-type value normalizer."""

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("event", "Event"),
            ("events", "Event"),
            ("Event", "Event"),
            ("user", "User"),
            ("people", "User"),
            ("User", "User"),
            ("groupprofile", "groupprofile"),  # unknown spelling passes through
        ],
    )
    def test_normalizes(self, given: str, expected: str) -> None:
        """Known spellings map to canonical values; unknowns pass through."""
        assert _canonical_resource_type(given) == expected


class TestDiscoveryGetSchemaGraph:
    """DiscoveryService.get_schema_graph composition + caching."""

    def _mock_api(self) -> MagicMock:
        """Mock api client returning small lexicon lists.

        The flat property rows carry no ``events`` lists; the relationship
        edges come from the query-API per-event gather and are inverted
        client-side.
        """
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
            return [{"name": "amount"}, {"name": "ts"}]

        api.list_property_definitions.side_effect = list_props
        api.list_per_event_properties.return_value = [
            {"name": "Purchase", "properties": [{"name": "amount"}, {"name": "ts"}]},
            {"name": "Login", "properties": [{"name": "ts"}]},
        ]
        return api

    def test_builds_adjacency_maps(self) -> None:
        """Adjacency maps are built from the inverted per-event gather."""
        svc = DiscoveryService(self._mock_api())
        result = svc.get_schema_graph()
        assert result.event_to_properties["Purchase"] == ["amount", "ts"]
        assert result.event_to_properties["Login"] == ["ts"]
        assert result.property_to_events["amount"] == ["Purchase"]
        assert result.property_to_events["ts"] == ["Purchase", "Login"]
        assert result.user_properties == [{"name": "plan", "resourceType": "User"}]
        assert result.meta["event_count"] == 2

    def test_flat_properties_call_omits_include_events(self) -> None:
        """No list_property_definitions call requests the App API join.

        The App API's ``includeEvents=true`` join times out server-side on
        large projects; the edges must come from list_per_event_properties.
        """
        api = self._mock_api()
        DiscoveryService(api).get_schema_graph()
        assert api.list_per_event_properties.call_count == 1
        for call in api.list_property_definitions.call_args_list:
            assert not call.kwargs.get("include_events")

    def test_per_event_rows_malformed_entries_skipped(self) -> None:
        """Nameless events and malformed property entries contribute no edges."""
        api = self._mock_api()
        api.list_per_event_properties.return_value = [
            {"properties": [{"name": "amount"}]},  # nameless event -> dropped
            {"name": "Purchase", "properties": ["bad", {"no": "name"}]},
            {"name": "Login", "properties": [{"name": "ts"}]},
            {"name": "NoProps"},  # no properties key -> no edges
        ]
        result = DiscoveryService(api).get_schema_graph()
        assert result.property_to_events["amount"] == []
        assert result.property_to_events["ts"] == ["Login"]

    def test_unknown_property_in_per_event_map_ignored(self) -> None:
        """A per-event property absent from the flat list creates no node."""
        api = self._mock_api()
        api.list_per_event_properties.return_value = [
            {"name": "Purchase", "properties": [{"name": "ghost"}]},
        ]
        result = DiscoveryService(api).get_schema_graph()
        assert "ghost" not in result.property_to_events
        assert result.event_to_properties["Purchase"] == []

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
            {"name": "amount", "densityLocal": 0.75}
        ]
        api.list_per_event_properties.return_value = [
            {"name": "Purchase", "properties": [{"name": "amount"}]}
        ]
        result = DiscoveryService(api).get_schema_graph(
            include_density=True, include_user_properties=False
        )
        assert result.include_density is True
        assert result.relationships_df.iloc[0]["density_local"] == 0.75
        assert result.to_graph().edges["Purchase", "amount"]["density_local"] == 0.75

    def test_debug_log_on_dropped_rows(self, caplog: pytest.LogCaptureFixture) -> None:
        """Dropped (nameless) rows emit a debug summary."""
        api = MagicMock()
        api.list_event_definitions.return_value = [{"name": "Purchase"}, {"count": 1}]
        api.list_property_definitions.return_value = [
            {"name": "amount"},
            {"description": "nameless"},
        ]
        api.list_per_event_properties.return_value = [
            {"name": "Purchase", "properties": [{"name": "amount"}]}
        ]
        logger_name = "mixpanel_headless._internal.services.discovery"
        with caplog.at_level(logging.DEBUG, logger=logger_name):
            DiscoveryService(api).get_schema_graph(include_user_properties=False)
        assert any("schema_graph dropped" in r.message for r in caplog.records)

    def test_no_debug_log_when_no_drops(self, caplog: pytest.LogCaptureFixture) -> None:
        """A clean gather emits no drop summary."""
        api = MagicMock()
        api.list_event_definitions.return_value = [{"name": "Purchase"}]
        api.list_property_definitions.return_value = [{"name": "amount"}]
        api.list_per_event_properties.return_value = [
            {"name": "Purchase", "properties": [{"name": "amount"}]}
        ]
        logger_name = "mixpanel_headless._internal.services.discovery"
        with caplog.at_level(logging.DEBUG, logger=logger_name):
            DiscoveryService(api).get_schema_graph(include_user_properties=False)
        assert not any("schema_graph dropped" in r.message for r in caplog.records)


class TestFacadeAndCli:
    """Workspace facade delegation and the CLI command."""

    def test_facade_delegates(self) -> None:
        """Workspace.schema_graph delegates to the discovery service."""
        api = MagicMock()
        api.list_event_definitions.return_value = [{"name": "Purchase"}]
        api.list_property_definitions.return_value = []
        api.list_per_event_properties.return_value = []
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
