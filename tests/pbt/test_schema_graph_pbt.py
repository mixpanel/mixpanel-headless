"""Property-based tests for the schema graph (PR3).

Invariants over randomly generated lexicons:
- ``property_to_events`` is the exact inverse of ``event_to_properties``.
- the networkx graph has one node per distinct event/property and one edge per
  adjacency entry, with no property->* edges.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.services.discovery import DiscoveryService

# Event and property names are drawn from disjoint namespaces (the realistic
# case); to_graph keys nodes by bare name, so a shared name would intentionally
# collapse to a single node.
_base = st.text(alphabet="abcdef", min_size=1, max_size=5)
_events = st.lists(_base.map(lambda s: f"evt_{s}"), min_size=1, max_size=6, unique=True)
_props = st.lists(_base.map(lambda s: f"prop_{s}"), min_size=1, max_size=6, unique=True)


def _build(events: list[str], props: list[str], edges: dict[str, list[str]]) -> Any:
    """Run get_schema_graph against a mocked api client built from edges."""
    api = MagicMock()
    api.list_event_definitions.return_value = [{"name": e} for e in events]

    def list_props(*, resource_type: str = "Event", **_: Any) -> list[dict[str, Any]]:
        if resource_type == "User":
            return []
        return [
            {"name": p, "events": [{"name": e} for e in edges.get(p, [])]}
            for p in props
        ]

    api.list_property_definitions.side_effect = list_props
    return DiscoveryService(api).get_schema_graph(include_user_properties=False)


@given(events=_events, props=_props, data=st.data())
def test_inverse_maps(events: list[str], props: list[str], data: st.DataObject) -> None:
    """property_to_events is the inverse of event_to_properties."""
    edges = {
        p: data.draw(st.lists(st.sampled_from(events), max_size=3, unique=True))
        for p in props
    }
    result = _build(events, props, edges)

    # Forward edges reconstructed from property_to_events match event_to_properties.
    forward: set[tuple[str, str]] = set()
    for prop, evs in result.property_to_events.items():
        for ev in evs:
            forward.add((ev, prop))
    inverse: set[tuple[str, str]] = set()
    for ev, ps in result.event_to_properties.items():
        for prop in ps:
            inverse.add((ev, prop))
    assert forward == inverse


@given(events=_events, props=_props, data=st.data())
def test_graph_counts(events: list[str], props: list[str], data: st.DataObject) -> None:
    """Graph has one edge per adjacency entry and no property->* edges."""
    edges = {
        p: data.draw(st.lists(st.sampled_from(events), max_size=3, unique=True))
        for p in props
    }
    result = _build(events, props, edges)
    g = result.to_graph()

    expected_edges = sum(len(v) for v in result.property_to_events.values())
    assert g.number_of_edges() == expected_edges
    # property nodes have no outgoing edges
    for p in props:
        assert g.out_degree(p) == 0


@given(events=_events, props=_props, data=st.data())
def test_orphan_properties_matches_empty_adjacency(
    events: list[str], props: list[str], data: st.DataObject
) -> None:
    """orphan_properties() is exactly the properties whose events list is empty."""
    edges = {
        p: data.draw(st.lists(st.sampled_from(events), max_size=3, unique=True))
        for p in props
    }
    result = _build(events, props, edges)
    expected = {p for p in props if not edges[p]}
    assert set(result.orphan_properties()) == expected


@given(events=_events, props=_props, data=st.data())
def test_graph_edges_when_relationships_exist(
    events: list[str], props: list[str], data: st.DataObject
) -> None:
    """Forcing one property to carry an edge exercises the non-empty graph path.

    The first property always gets >=1 event, so this never passes vacuously on
    an all-empty draw; the graph edge count must match the adjacency total.
    """
    edges = {
        props[0]: data.draw(
            st.lists(st.sampled_from(events), min_size=1, max_size=3, unique=True)
        )
    }
    for p in props[1:]:
        edges[p] = data.draw(st.lists(st.sampled_from(events), max_size=3, unique=True))
    result = _build(events, props, edges)
    g = result.to_graph()
    assert g.number_of_edges() >= 1
    assert g.number_of_edges() == sum(
        len(v) for v in result.property_to_events.values()
    )
