"""Targeted coverage for the rrweb analyzer (`_internal/replays/rrweb_analyzer.py`).

Synthetic event streams hit the paths that
`tests/unit/test_replay_bundle.py::TestRrwebAnalyzer` doesn't exercise:
mutation adds/removes/text/attribute changes, console-error plugin events,
selection events with text extraction, mouse-interaction subtypes
(double / right / focus / touch_start), per-source debouncing, and the
DOM tracker's ancestor-traversal fallback.

It also covers screenshot recordings (mobile, React Native, and Flutter):
wireframe screens, the touch gesture state machine, screenshot clicks,
recording-type detection, and input hardening.

Most event streams are hand-built here. ``TestRealMobileFixtures`` loads
the real replays in ``tests/fixtures/rrweb/`` and compares our output with
the upstream analyzer's output in ``tests/fixtures/rrweb/upstream/``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from mixpanel_headless._internal.replays.rrweb_analyzer import (
    DOMTracker,
    EventAnalyzer,
    MarkdownReporter,
    MobileWireframeTracker,
    RrwebAnalyzer,
    _render_markdown,
    actions_contain_wireframes,
    analyze_events,
    detect_capture,
    hit_test,
    timeline_contains_wireframes,
)
from mixpanel_headless.types import UserAction

# =============================================================================
# Tiny event builders
# =============================================================================


def _meta(ts: int, href: str) -> dict[str, Any]:
    """Meta event (type 4) carrying a URL."""
    return {
        "type": 4,
        "data": {"href": href, "width": 1280, "height": 800},
        "timestamp": ts,
    }


def _full_snapshot(ts: int, root: dict[str, Any]) -> dict[str, Any]:
    """FullSnapshot (type 2) wrapping a DOM root."""
    return {
        "type": 2,
        "data": {"node": root, "initialOffset": {"left": 0, "top": 0}},
        "timestamp": ts,
    }


def _mutation(ts: int, **payload: Any) -> dict[str, Any]:
    """IncrementalSnapshot Mutation (source 0)."""
    return {"type": 3, "data": {"source": 0, **payload}, "timestamp": ts}


def _click(ts: int, node_id: int, *, click_type: int = 2) -> dict[str, Any]:
    """IncrementalSnapshot MouseInteraction (source 2)."""
    return {
        "type": 3,
        "data": {"source": 2, "type": click_type, "id": node_id, "x": 0, "y": 0},
        "timestamp": ts,
    }


def _scroll(ts: int, node_id: int = 1) -> dict[str, Any]:
    """IncrementalSnapshot Scroll (source 3)."""
    return {
        "type": 3,
        "data": {"source": 3, "id": node_id, "x": 0, "y": 0},
        "timestamp": ts,
    }


def _input(
    ts: int, node_id: int, *, text: str = "", checked: bool | None = None
) -> dict[str, Any]:
    """IncrementalSnapshot Input (source 5)."""
    data: dict[str, Any] = {"source": 5, "id": node_id, "text": text}
    if checked is not None:
        data["isChecked"] = checked
    return {"type": 3, "data": data, "timestamp": ts}


def _selection(
    ts: int, start: int, end: int, *, start_offset: int = 0, end_offset: int = 0
) -> dict[str, Any]:
    """IncrementalSnapshot Selection (source 14)."""
    return {
        "type": 3,
        "data": {
            "source": 14,
            "ranges": [
                {
                    "start": start,
                    "end": end,
                    "startOffset": start_offset,
                    "endOffset": end_offset,
                }
            ],
        },
        "timestamp": ts,
    }


def _plugin_console_error(ts: int, *messages: str) -> dict[str, Any]:
    """Plugin event (type 6) — rrweb console-plugin error payload."""
    return {
        "type": 6,
        "data": {
            "plugin": "rrweb/console@1",
            "payload": {"level": "error", "payload": [f'"{m}"' for m in messages]},
        },
        "timestamp": ts,
    }


def _element_node(
    node_id: int,
    tag: str,
    *,
    attributes: dict[str, str] | None = None,
    text: str | None = None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a type=2 element node, optionally with a single text child."""
    child_nodes: list[dict[str, Any]] = list(children or [])
    if text is not None:
        child_nodes.append({"id": node_id * 1000, "type": 3, "textContent": text})
    return {
        "id": node_id,
        "type": 2,
        "tagName": tag,
        "attributes": attributes or {},
        "childNodes": child_nodes,
    }


def _document_root(*element_children: dict[str, Any]) -> dict[str, Any]:
    """Wrap element nodes in a synthetic document root."""
    return {
        "id": 1,
        "type": 0,
        "childNodes": [
            _element_node(
                2,
                "html",
                attributes={"lang": "en"},
                children=[
                    _element_node(
                        3, "body", attributes={}, children=list(element_children)
                    )
                ],
            ),
        ],
    }


# =============================================================================
# Convenience entry points
# =============================================================================


class TestAnalyzeEventsWrapper:
    """`analyze_events()` convenience function validation + happy path."""

    def test_empty_raises_value_error(self) -> None:
        """Empty event list raises ValueError per the documented contract."""
        with pytest.raises(ValueError, match="cannot be empty"):
            analyze_events([])

    def test_non_list_raises_value_error(self) -> None:
        """Passing a non-list raises ValueError."""
        with pytest.raises(ValueError, match="must be a list"):
            analyze_events("not a list")  # type: ignore[arg-type]

    def test_returns_string(self) -> None:
        """Successful analyze returns the markdown string."""
        events = [_meta(1000, "/x")]
        out = analyze_events(events)
        assert "Navigated to /x" in out

    def test_actions_carry_description(self) -> None:
        """analyze() stamps the full phrase on UserAction.description.

        This is the field Replay.summary_markdown renders; the regression
        it guards against is the action carrying only the bare target_desc.
        """
        result = RrwebAnalyzer().analyze([_meta(1000, "/x")])
        assert result.actions
        assert result.actions[0].description == "Navigated to /x"
        # The structured description and the rendered markdown agree.
        assert result.actions[0].description in result.markdown_summary


# =============================================================================
# Console errors (the bug the previous from-scratch impl had)
# =============================================================================


class TestConsoleErrors:
    """Plugin events with rrweb/console@* + level=error produce console_error actions."""

    def test_console_error_emitted(self) -> None:
        """Plugin payload with level=error becomes a console_error action."""
        events = [
            _meta(1000, "/x"),
            _plugin_console_error(2000, "TypeError: bad"),
        ]
        result = RrwebAnalyzer().analyze(events)
        errors = [a for a in result.actions if a.action == "console_error"]
        assert len(errors) == 1
        assert "TypeError: bad" in errors[0].target_desc
        # Also recorded in the structured errors list.
        assert len(result.errors) == 1
        assert result.errors[0].message == "TypeError: bad"

    def test_non_error_plugin_ignored(self) -> None:
        """Plugin events with non-error level (e.g. warn) do NOT emit actions."""
        events = [
            _meta(1000, "/x"),
            {
                "type": 6,
                "data": {
                    "plugin": "rrweb/console@1",
                    "payload": {"level": "warn", "payload": ['"deprecation"']},
                },
                "timestamp": 2000,
            },
        ]
        result = RrwebAnalyzer().analyze(events)
        assert not any(a.action == "console_error" for a in result.actions)

    def test_unrelated_plugin_ignored(self) -> None:
        """Plugin events from non-rrweb-console plugins are ignored."""
        events = [
            _meta(1000, "/x"),
            {
                "type": 6,
                "data": {"plugin": "rrweb/canvas@1", "payload": {}},
                "timestamp": 2000,
            },
        ]
        result = RrwebAnalyzer().analyze(events)
        assert not any(a.action == "console_error" for a in result.actions)

    def test_empty_message_not_emitted(self) -> None:
        """A console error with no messages produces no action."""
        events = [
            _meta(1000, "/x"),
            {
                "type": 6,
                "data": {
                    "plugin": "rrweb/console@1",
                    "payload": {"level": "error", "payload": []},
                },
                "timestamp": 2000,
            },
        ]
        result = RrwebAnalyzer().analyze(events)
        assert not any(a.action == "console_error" for a in result.actions)


# =============================================================================
# Debouncing — the other big bug in the previous impl
# =============================================================================


class TestDebouncing:
    """Scroll / input / selection emit one action per debounce window."""

    def test_scroll_debounced(self) -> None:
        """Five scrolls within 1s produce one scroll action."""
        events = [
            _meta(1000, "/x"),
            _scroll(2000),
            _scroll(2100),
            _scroll(2200),
            _scroll(2300),
            _scroll(2400),
        ]
        result = RrwebAnalyzer().analyze(events)
        scrolls = [a for a in result.actions if a.action == "scroll"]
        # First scroll passes (last_scroll_time=0, gap > 1000); subsequent
        # within 1s are suppressed.
        assert len(scrolls) == 1

    def test_scroll_re_fires_after_gap(self) -> None:
        """A scroll more than 1s after the previous one re-fires."""
        events = [
            _meta(1000, "/x"),
            _scroll(2000),
            _scroll(5000),  # 3s later → re-fires
        ]
        result = RrwebAnalyzer().analyze(events)
        scrolls = [a for a in result.actions if a.action == "scroll"]
        assert len(scrolls) == 2

    def test_input_debounced_per_node(self) -> None:
        """Two inputs on the same node within 1s collapse; two nodes don't."""
        root = _document_root(
            _element_node(10, "input", attributes={"id": "email", "type": "text"}),
            _element_node(
                11, "input", attributes={"id": "password", "type": "password"}
            ),
        )
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _input(2000, 10, text="a"),
            _input(2500, 10, text="ab"),  # within 1s of prev on node 10 → suppressed
            _input(2100, 11, text="x"),  # different node → emitted
        ]
        result = RrwebAnalyzer().analyze(events)
        inputs = [a for a in result.actions if a.action == "input"]
        assert len(inputs) == 2

    def test_input_checkbox(self) -> None:
        """Checkbox input (is_checked) emits a 'Set ... to checked' description."""
        root = _document_root(
            _element_node(20, "input", attributes={"type": "checkbox", "id": "agree"})
        )
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _input(2000, 20, checked=True),
        ]
        result = RrwebAnalyzer().analyze(events)
        markdown = result.markdown_summary
        assert "to checked" in markdown

    def test_input_no_text_no_check_modified_fallback(self) -> None:
        """Input with empty text + no is_checked emits 'Modified ...'."""
        root = _document_root(
            _element_node(30, "input", attributes={"type": "text", "id": "foo"})
        )
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _input(2000, 30),  # no text, no isChecked
        ]
        result = RrwebAnalyzer().analyze(events)
        assert "Modified" in result.markdown_summary


# =============================================================================
# Mouse-interaction subtypes
# =============================================================================


class TestMouseInteractions:
    """All five interaction types (click / dbl / right / focus / touch_start)."""

    @pytest.mark.parametrize(
        "click_type,expected_verb,expected_action",
        [
            (2, "Clicked", "click"),
            (3, "Right-clicked", "click"),
            (4, "Double-clicked", "click"),
            (5, "Focused", "click"),
            (7, "Tapped", "touch_start"),
        ],
    )
    def test_each_interaction_type(
        self, click_type: int, expected_verb: str, expected_action: str
    ) -> None:
        """Each rrweb interaction type maps to its documented verb + action literal."""
        root = _document_root(
            _element_node(40, "button", attributes={"id": "go"}, text="Go")
        )
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _click(2000, 40, click_type=click_type),
        ]
        result = RrwebAnalyzer().analyze(events)
        # Description contains the upstream-style verb.
        assert expected_verb in result.markdown_summary
        # Structured action carries the documented literal.
        action_matches = [a for a in result.actions if a.action == expected_action]
        assert len(action_matches) >= 1

    def test_unknown_interaction_type_ignored(self) -> None:
        """An unrecognized MouseInteraction type produces no action."""
        root = _document_root(_element_node(50, "div", attributes={"id": "x"}))
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _click(2000, 50, click_type=99),  # not in the enum
        ]
        result = RrwebAnalyzer().analyze(events)
        assert not any(a.action in ("click", "touch_start") for a in result.actions)

    def test_click_on_unknown_node_describes_as_element(self) -> None:
        """Click with a present but unknown node id emits 'Clicked element'.

        DOMTracker.get_node_description returns 'element' for unknown ids.
        Only a missing node id (``None``) triggers the "unknown element"
        drop path; a present id — including ``0`` — is looked up.
        """
        events = [
            _meta(1000, "/x"),
            _click(2000, 999),  # node 999 never registered
        ]
        result = RrwebAnalyzer().analyze(events)
        clicks = [a for a in result.actions if a.action == "click"]
        assert len(clicks) == 1
        assert clicks[0].target_desc == "element"

    def test_click_with_no_node_id_is_dropped(self) -> None:
        """Click event without a node id resolves to the drop path."""
        events = [
            _meta(1000, "/x"),
            {
                "type": 3,
                "data": {"source": 2, "type": 2, "x": 0, "y": 0},
                "timestamp": 2000,
            },
        ]
        result = RrwebAnalyzer().analyze(events)
        assert not any(a.action == "click" for a in result.actions)

    def test_data_selectors_propagated_to_click_metadata(self) -> None:
        """A clicked element's ``data-*`` selectors land in UserAction.metadata.

        Regression for the originally-broken ``selector_label_fn``: before
        this fix, click metadata only ever carried ``{"interaction": verb}``,
        so the analyzer never surfaced ``data-testid`` and the public helper
        always fell through to the URL. The metadata must now expose every
        ``data-*`` attribute on the clicked node.
        """
        root = _document_root(
            _element_node(
                40,
                "button",
                attributes={
                    "id": "go",
                    "data-testid": "signin-button",
                    "data-cy": "signin",
                },
                text="Sign in",
            )
        )
        events = [_full_snapshot(1500, root), _click(2000, 40, click_type=2)]
        result = RrwebAnalyzer().analyze(events)
        clicks = [a for a in result.actions if a.action == "click"]
        assert len(clicks) == 1
        assert clicks[0].metadata.get("data-testid") == "signin-button"
        assert clicks[0].metadata.get("data-cy") == "signin"
        # Non-data attributes stay out of metadata (they feed target_desc only).
        assert "id" not in clicks[0].metadata

    def test_selector_label_fn_uses_propagated_testid(self) -> None:
        """End-to-end: selector_label_fn groups by the analyzer-populated id.

        Without the propagation fix this label would be the default
        ``click:button "Checkout"@/cart``; with it, the helper reads the
        ``data-testid`` off metadata and produces the stable selector label.
        """
        from mixpanel_headless.replay_labels import selector_label_fn

        root = _document_root(
            _element_node(
                41, "button", attributes={"data-testid": "checkout"}, text="Checkout"
            )
        )
        events = [
            _meta(1000, "/cart"),
            _full_snapshot(1500, root),
            _click(2000, 41, click_type=2),
        ]
        result = RrwebAnalyzer().analyze(events)
        click = next(a for a in result.actions if a.action == "click")
        assert selector_label_fn("data-testid")(click) == "click:checkout@/cart"


# =============================================================================
# Selection events with text excerpt
# =============================================================================


class TestSelectionEvents:
    """Selection events emit a 'Selected ...' action with text extraction."""

    def test_selection_extracts_text(self) -> None:
        """A selection over a known text node emits 'Selected '{excerpt}''."""
        # The DOMTracker copies text-child content up to its parent if the
        # parent is interactive, but bare text nodes go in directly.
        # For selection, the analyzer looks at `node.text` of the start node.
        root = _document_root(
            _element_node(60, "p", text="hello world from acme"),
        )
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            # Text content "hello world from acme" — select chars 6..11 = "world"
            _selection(2000, 60, 60, start_offset=6, end_offset=11),
        ]
        result = RrwebAnalyzer().analyze(events)
        selects = [a for a in result.actions if a.action == "select"]
        assert len(selects) == 1
        # The selection action's description includes 'Selected'.
        assert "Selected" in result.markdown_summary

    def test_selection_without_text_fallback(self) -> None:
        """Selection with empty ranges produces no action."""
        events = [
            _meta(1000, "/x"),
            {"type": 3, "data": {"source": 14, "ranges": []}, "timestamp": 2000},
        ]
        result = RrwebAnalyzer().analyze(events)
        assert not any(a.action == "select" for a in result.actions)

    def test_selection_unknown_node_fallback(self) -> None:
        """Selection over an unknown node emits the 'Selected text' fallback."""
        events = [
            _meta(1000, "/x"),
            _selection(2000, 999, 999, start_offset=0, end_offset=5),
        ]
        result = RrwebAnalyzer().analyze(events)
        selects = [a for a in result.actions if a.action == "select"]
        assert len(selects) == 1
        assert "Selected text" in result.markdown_summary


# =============================================================================
# Mutations: adds / removes / text changes / attribute changes
# =============================================================================


class TestMutations:
    """The DOM tracker applies adds/removes/text/attribute mutations."""

    def test_mutation_adds(self) -> None:
        """A node added via mutation is clickable afterward."""
        root = _document_root()  # empty body
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _mutation(
                1800,
                adds=[
                    {
                        "parentId": 3,
                        "node": _element_node(70, "button", text="Click me"),
                    }
                ],
            ),
            _click(2000, 70),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert any("Click me" in (a.target_desc or "") for a in result.actions)

    def test_mutation_removes(self) -> None:
        """A removed node's description falls back to 'element' on later click."""
        root = _document_root(_element_node(80, "button", text="Bye"))
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _mutation(1800, removes=[{"id": 80}]),
            _click(2000, 80),
        ]
        result = RrwebAnalyzer().analyze(events)
        clicks = [a for a in result.actions if a.action == "click"]
        # The button is gone — get_node_description falls back to 'element'.
        assert len(clicks) == 1
        assert clicks[0].target_desc == "element"

    def test_mutation_text_change(self) -> None:
        """update_text() changes the interactive parent's text + invalidates cache."""
        root = _document_root(_element_node(90, "button", text="Old"))
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _click(1700, 90),  # primes the cache with "Old"
            _mutation(1800, texts=[{"id": 90 * 1000, "value": "New"}]),
            _click(2900, 90),  # outside scroll debounce; new description
        ]
        result = RrwebAnalyzer().analyze(events)
        # At least one click description references the new text.
        clicks = [a for a in result.actions if a.action == "click"]
        assert any('"New"' in (a.target_desc or "") for a in clicks)

    def test_mutation_attribute_change(self) -> None:
        """update_attributes() adds descriptive attributes that show up in clicks."""
        root = _document_root(_element_node(100, "button"))  # no descriptive attrs
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _mutation(
                1800,
                attributes=[{"id": 100, "attributes": {"aria-label": "Submit form"}}],
            ),
            _click(2000, 100),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert any("Submit form" in (a.target_desc or "") for a in result.actions)

    def test_mutation_text_change_for_unknown_node(self) -> None:
        """Text change for an unknown node id is a no-op (no crash)."""
        events = [
            _meta(1000, "/x"),
            _mutation(1800, texts=[{"id": 999, "value": "ghost"}]),
        ]
        # Should not raise.
        result = RrwebAnalyzer().analyze(events)
        assert result.actions


# =============================================================================
# DOMTracker description fallbacks (aria-label / title / alt / placeholder / id / href)
# =============================================================================


class TestDescriptionFallbacks:
    """Each descriptive-attribute priority gets exercised."""

    @pytest.mark.parametrize(
        "attributes,text,fragment",
        [
            ({"aria-label": "Save changes"}, None, '"Save changes"'),
            ({"title": "tooltip-text"}, None, '"tooltip-text"'),
            ({"alt": "logo"}, None, 'alt="logo"'),
            ({}, "Sign in", '"Sign in"'),
            ({"placeholder": "search…"}, None, 'placeholder="search…"'),
            ({"id": "go"}, None, "#go"),
        ],
    )
    def test_button_description(
        self, attributes: dict[str, str], text: str | None, fragment: str
    ) -> None:
        """Each priority fallback produces the documented description fragment."""
        root = _document_root(
            _element_node(200, "button", attributes=attributes, text=text)
        )
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _click(2000, 200),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert any(fragment in (a.target_desc or "") for a in result.actions)

    def test_anchor_with_http_href_appends_path(self) -> None:
        """<a href="https://..."> with a meaningful path appends 'to /path'."""
        root = _document_root(
            _element_node(
                210,
                "a",
                attributes={"href": "https://example.com/docs/intro"},
                text="Docs",
            )
        )
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _click(2000, 210),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert any("to /docs/intro" in (a.target_desc or "") for a in result.actions)

    def test_input_with_type(self) -> None:
        """Input description includes type=... fragment."""
        root = _document_root(
            _element_node(220, "input", attributes={"type": "email", "id": "email"})
        )
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _input(2000, 220, text="alice@example.com"),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert any("type=email" in (a.target_desc or "") for a in result.actions)

    def test_ancestor_traversal_fallback(self) -> None:
        """Element with no description uses ancestor context (e.g. 'span in button')."""
        # Build a button with a child span that has no descriptive info of its own.
        span = _element_node(300, "span")
        button = _element_node(
            301,
            "button",
            attributes={"id": "go"},
            text="Go",
            children=[span],
        )
        root = _document_root(button)
        events = [
            _meta(1000, "/x"),
            _full_snapshot(1500, root),
            _click(2000, 300),  # click on the span
        ]
        result = RrwebAnalyzer().analyze(events)
        clicks = [a for a in result.actions if a.action == "click"]
        # span has no own description; ancestor context kicks in.
        assert any("in button" in (a.target_desc or "") for a in clicks)


# =============================================================================
# DOMTracker direct API exercises
# =============================================================================


class TestDOMTrackerDirect:
    """Direct DOMTracker exercises beyond what analyzer integration covers."""

    def test_sanitize_value_strips_and_drops_none_string(self) -> None:
        """Strings that strip to '' or 'none' return empty; ints pass through."""
        assert DOMTracker._sanitize_value("  ") == ""
        assert DOMTracker._sanitize_value("None") == ""
        assert DOMTracker._sanitize_value("hi  ") == "hi"
        assert DOMTracker._sanitize_value(42) == 42

    def test_describe_unknown_node_returns_element(self) -> None:
        """Asking for an unknown node id returns the 'element' sentinel."""
        assert DOMTracker().get_node_description(9999) == "element"

    def test_max_nodes_warning(self) -> None:
        """Hitting MAX_NODES sets the reached_max_nodes flag."""
        tracker = DOMTracker()
        tracker.MAX_NODES = 2
        tracker.add_node(_element_node(1, "div"))
        tracker.add_node(_element_node(2, "div"))
        tracker.add_node(_element_node(3, "div"))
        assert tracker.reached_max_nodes

    def test_max_nodes_caps_growth_after_trip(self) -> None:
        """The cap holds for EVERY new node past the trip, not just the first.

        Regression guard: reached_max_nodes used to be ANDed into the skip
        condition, so only the first over-limit node was dropped and every
        subsequent one was still added — the map grew past MAX_NODES. The flag
        must gate the log only; the skip must fire for all new nodes at the cap.
        """
        tracker = DOMTracker()
        tracker.MAX_NODES = 2
        for node_id in range(1, 8):  # add 7 distinct nodes, cap is 2
            tracker.add_node(_element_node(node_id, "div"))
        assert tracker.reached_max_nodes
        assert len(tracker.nodes) == 2  # nodes 1 and 2 only; 3-7 all skipped

    def test_max_nodes_still_updates_existing_nodes_at_cap(self) -> None:
        """At the cap, re-adding an already-tracked node is allowed (no growth).

        The skip only targets NEW nodes (``node_id not in self.nodes``); an
        update to a known node must still fall through so its metadata refreshes.
        """
        tracker = DOMTracker()
        tracker.MAX_NODES = 2
        tracker.add_node(_element_node(1, "button", attributes={"id": "first"}))
        tracker.add_node(_element_node(2, "div"))
        tracker.add_node(_element_node(3, "div"))  # trips the cap, skipped
        # Re-add node 1 with new attributes — known id, so it updates in place.
        tracker.add_node(_element_node(1, "button", attributes={"id": "updated"}))
        assert len(tracker.nodes) == 2
        assert tracker.nodes[1]["attributes"]["id"] == "updated"


# =============================================================================
# MarkdownReporter
# =============================================================================


class TestMarkdownReporter:
    """Reporter renders ts/desc pairs as `{ts_seconds}: {desc}` lines."""

    def test_empty_returns_no_actions_sentinel(self) -> None:
        """Empty description list returns the 'No user actions recorded.' sentinel."""
        assert MarkdownReporter([]).generate() == "No user actions recorded."

    def test_renders_seconds(self) -> None:
        """Timestamps in ms are divided by 1000 for the line format."""
        out = MarkdownReporter([(2_500, "Did a thing")]).generate()
        assert out == "2: Did a thing"

    def test_multiple_lines_joined(self) -> None:
        """Multiple (ts, desc) pairs join with newline."""
        out = MarkdownReporter([(1_000, "a"), (2_000, "b")]).generate()
        assert out == "1: a\n2: b"

    def test_collapses_consecutive_duplicates(self) -> None:
        """Consecutive identical descriptions coalesce into a (×N) suffix."""
        out = MarkdownReporter(
            [(1_000, "Clicked X"), (1_200, "Clicked X"), (1_400, "Clicked X")]
        ).generate()
        # First timestamp of the run is shown; the run length is the suffix.
        assert out == "1: Clicked X (×3)"

    def test_non_adjacent_duplicates_not_collapsed(self) -> None:
        """Identical descriptions split by a different line stay separate."""
        out = MarkdownReporter(
            [(1_000, "Clicked X"), (2_000, "Scrolled"), (3_000, "Clicked X")]
        ).generate()
        assert out == "1: Clicked X\n2: Scrolled\n3: Clicked X"


# =============================================================================
# Mobile and screenshot recordings: builders ported from the upstream analyzer
# =============================================================================
#
# Screenshot recordings (the iOS, Android, React Native, and Flutter SDKs) have
# no DOM. The SDK sends each screen as an rrweb Custom event (type 5) with the
# tag ``mp_wireframe`` and sends the finger input as rrweb touch events. The
# builders and the test cases below are ported from the upstream analyzer's
# test module. The expected text is the upstream text, except where a test
# docstring names an intentional difference.


def _el(role: Any, text: Any = None, bounds: Any = (0, 0, 0, 0)) -> dict[str, Any]:
    """Build one wireframe element.

    Args:
        role: The element role (``text``, ``button``, ``input``, …). Typed as
            ``Any`` so hardening tests can pass a malformed value.
        text: The element label, or None for a masked or label-less element.
        bounds: The ``[x, y, w, h]`` rect. A tuple is copied into a list;
            any other value passes through unchanged for hardening tests.

    Returns:
        The element dict as the mobile SDK sends it.
    """
    rect = list(bounds) if isinstance(bounds, tuple) else bounds
    return {"role": role, "text": text, "bounds": rect}


def _wireframe(ts: int, *elements: Any, tag: str = "mp_wireframe") -> dict[str, Any]:
    """Build an ``mp_wireframe`` Custom event (type 5).

    Args:
        ts: Unix ms timestamp.
        *elements: The screen elements, in client order.
        tag: The Custom event tag. Other tags are not wireframes.

    Returns:
        The rrweb Custom event dict.
    """
    payload = {"elements": list(elements)}
    return {"type": 5, "timestamp": ts, "data": {"tag": tag, "payload": payload}}


def _touch_start(
    ts: int, x: Any = 10, y: Any = 20, node_id: int = 28
) -> dict[str, Any]:
    """Build a MouseInteraction TOUCH_START (type 3 / source 2 / type 7).

    Node 28 is the id of the single screenshot image that the mobile SDK
    puts in its synthetic full snapshot.

    Args:
        ts: Unix ms timestamp.
        x: Finger-down x coordinate.
        y: Finger-down y coordinate.
        node_id: The rrweb node id of the touch target.

    Returns:
        The rrweb IncrementalSnapshot event dict.
    """
    return {
        "type": 3,
        "timestamp": ts,
        "data": {"source": 2, "type": 7, "id": node_id, "x": x, "y": y},
    }


def _touch_end(ts: int, x: Any = 10, y: Any = 20, node_id: int = 28) -> dict[str, Any]:
    """Build a MouseInteraction TOUCH_END (type 9): the finger lifts.

    Args:
        ts: Unix ms timestamp.
        x: Lift-off x coordinate.
        y: Lift-off y coordinate.
        node_id: The rrweb node id of the touch target.

    Returns:
        The rrweb IncrementalSnapshot event dict.
    """
    return {
        "type": 3,
        "timestamp": ts,
        "data": {"source": 2, "type": 9, "id": node_id, "x": x, "y": y},
    }


def _touch_cancel(ts: int, node_id: int = 28) -> dict[str, Any]:
    """Build a MouseInteraction TOUCH_CANCEL (type 10).

    The system takes the gesture away (a scroll view's pan or a system
    gesture claims the touch). A cancel has no lift-off, so it has no x/y.

    Args:
        ts: Unix ms timestamp.
        node_id: The rrweb node id of the touch target.

    Returns:
        The rrweb IncrementalSnapshot event dict.
    """
    return {
        "type": 3,
        "timestamp": ts,
        "data": {"source": 2, "type": 10, "id": node_id},
    }


def _touch_move(
    ts: int, positions: list[tuple[Any, Any]], node_id: int = 28
) -> dict[str, Any]:
    """Build a TOUCH_MOVE incremental snapshot (type 3 / source 6).

    Args:
        ts: Unix ms timestamp.
        positions: ``(x, y)`` finger-drag samples. The travel across them
            separates a scroll from a tap.
        node_id: The rrweb node id of the touch target.

    Returns:
        The rrweb IncrementalSnapshot event dict.
    """
    return {
        "type": 3,
        "timestamp": ts,
        "data": {
            "source": 6,
            "positions": [
                {"x": px, "y": py, "id": node_id, "timeOffset": 0}
                for px, py in positions
            ],
        },
    }


def _touch(
    ts: int, x: Any = 10, y: Any = 20, node_id: int = 28
) -> list[dict[str, Any]]:
    """Build a complete stationary tap: finger down, then up at the same point.

    Args:
        ts: Unix ms timestamp for both events.
        x: Tap x coordinate.
        y: Tap y coordinate.
        node_id: The rrweb node id of the touch target.

    Returns:
        A ``[TOUCH_START, TOUCH_END]`` event pair.
    """
    return [_touch_start(ts, x, y, node_id), _touch_end(ts, x, y, node_id)]


def _screenshot_click(
    ts: int, x: Any = 5, y: Any = 6, *, click_type: int = 2, node_id: int = 28
) -> dict[str, Any]:
    """Build a MouseInteraction event on the screenshot image.

    Flutter web and Flutter desktop send mouse events instead of touches.

    Args:
        ts: Unix ms timestamp.
        x: Pointer x coordinate.
        y: Pointer y coordinate.
        click_type: The MouseInteraction type (0 MouseUp, 1 MouseDown,
            2 Click, 3 ContextMenu, 4 DblClick, 5 Focus).
        node_id: The rrweb node id of the target.

    Returns:
        The rrweb IncrementalSnapshot event dict.
    """
    return {
        "type": 3,
        "timestamp": ts,
        "data": {"source": 2, "type": click_type, "id": node_id, "x": x, "y": y},
    }


def _meta_no_href(ts: int) -> dict[str, Any]:
    """Build a Meta event (type 4) without ``href``, as the mobile SDKs send it.

    Args:
        ts: Unix ms timestamp.

    Returns:
        The rrweb Meta event dict.
    """
    return {"type": 4, "timestamp": ts, "data": {"width": 411, "height": 914}}


# =============================================================================
# Upstream mobile test cases (ported)
# =============================================================================


class TestUpstreamMobileCases:
    """The upstream analyzer's mobile test cases, asserted on the markdown."""

    def test_wireframe_custom_event_renders_screen(self) -> None:
        """A wireframe renders as one ``Wireframe:`` line of its elements."""
        events = [
            _wireframe(
                1000,
                _el("text", "Movie Search"),
                _el("button", "❤️ My Favorites"),
                _el("input"),  # masked/empty input -> no text
            )
        ]
        result = analyze_events(events)
        assert result == "1: Wireframe: Movie Search | button:❤️ My Favorites | input"

    def test_touchless_session_keeps_first_and_last_keyframe(self) -> None:
        """A session with no touches keeps only its first and last screens."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            _wireframe(1500, _el("text", "Browsing")),
            _wireframe(2000, _el("text", "Details")),
        ]
        result = analyze_events(events)
        assert result == "1: Wireframe: Home\n2: Wireframe: Details"

    def test_touch_emits_before_and_after_screen(self) -> None:
        """A tap emits the screen before it, the tap, and the screen after it."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            *_touch(2000, x=10, y=20),
            _wireframe(2500, _el("text", "Details")),
        ]
        result = analyze_events(events)
        assert result == (
            "1: Wireframe: Home\n2: Tapped at (10, 20)\n2: Wireframe: Details"
        )

    def test_churn_between_touches_is_dropped(self) -> None:
        """Only the screen immediately before the tap survives."""
        events = [
            _wireframe(1000, _el("text", "Frame1")),
            _wireframe(1100, _el("text", "Frame2")),
            _wireframe(1200, _el("text", "Frame3")),
            *_touch(2000),
        ]
        result = analyze_events(events)
        assert result == "1: Wireframe: Frame3\n2: Tapped at (10, 20)"

    def test_late_result_still_captured_as_after_frame(self) -> None:
        """An "after" screen has no time limit, only a count limit."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            *_touch(2000),
            _wireframe(9000, _el("text", "Result")),
        ]
        result = analyze_events(events)
        assert result == (
            "1: Wireframe: Home\n2: Tapped at (10, 20)\n9: Wireframe: Result"
        )

    def test_final_screen_flushed_when_after_budget_exhausted(self) -> None:
        """Finalization flushes the last screen after the after-frame budget ends."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            *_touch(2000),
            _wireframe(2100, _el("text", "A")),  # after-frame 1
            _wireframe(2200, _el("text", "B")),  # after-frame 2 (budget exhausted)
            _wireframe(9000, _el("text", "Final")),  # flushed by finalization
        ]
        result = analyze_events(events)
        assert result == (
            "1: Wireframe: Home\n2: Tapped at (10, 20)\n2: Wireframe: A\n"
            "2: Wireframe: B\n9: Wireframe: Final"
        )

    def test_after_frames_capped_by_count(self) -> None:
        """At most two after-frames are kept; later churn is dropped."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            *_touch(2000),
            _wireframe(2100, _el("text", "A")),
            _wireframe(2200, _el("text", "B")),
            _wireframe(2300, _el("text", "C")),  # capped out, then overwritten
            _wireframe(2400, _el("text", "D")),  # flushed by finalization
        ]
        result = analyze_events(events)
        assert result == (
            "1: Wireframe: Home\n2: Tapped at (10, 20)\n2: Wireframe: A\n"
            "2: Wireframe: B\n2: Wireframe: D"
        )

    def test_repeated_taps_report_each_tap_but_screen_once(self) -> None:
        """Each tap is an action; the unchanged screen appears one time only.

        Intentional difference from the upstream analyzer: our markdown
        collapses consecutive identical lines into one line with a ``(×N)``
        suffix. Upstream prints three separate ``Tapped at (272, 827)``
        lines. The structured action list still holds three taps.
        """
        events = [
            _wireframe(1000, _el("text", "Home")),
            *_touch(1500, x=272, y=827),
            *_touch(1600, x=272, y=827),
            *_touch(1700, x=272, y=827),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert result.markdown_summary == (
            "1: Wireframe: Home\n1: Tapped at (272, 827) (×3)"
        )
        taps = [a for a in result.actions if a.action == "touch_start"]
        assert [a.timestamp for a in taps] == [1500, 1600, 1700]

    def test_swipe_is_scroll_not_tap(self) -> None:
        """A gesture that travels past the tap threshold is a scroll."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            _touch_start(2000, x=200, y=800),
            _touch_move(2050, [(200, 600), (200, 400)]),
            _touch_end(2100, x=200, y=390),
            _wireframe(2200, _el("text", "ScrolledContent")),
        ]
        result = analyze_events(events)
        assert "Tapped" not in result
        assert result == (
            "1: Wireframe: Home\n2: Scrolled\n2: Wireframe: ScrolledContent"
        )

    def test_cancelled_touch_is_neither_tap_nor_scroll(self) -> None:
        """A cancelled gesture emits no action but still arms the after-frames."""
        events = [
            _wireframe(1000, _el("text", "Feed top")),
            _touch_start(2000, x=200, y=800),
            _touch_move(2050, [(200, 600), (200, 400)]),
            _touch_cancel(2100),
            _wireframe(2200, _el("text", "Feed mid")),
        ]
        result = analyze_events(events)
        assert "Tapped" not in result
        assert "Scrolled" not in result
        assert result == "1: Wireframe: Feed top\n2: Wireframe: Feed mid"

    def test_cancel_closes_gesture_so_next_tap_is_not_a_phantom(self) -> None:
        """A cancel closes the open gesture, so no phantom tap appears later."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            _touch_start(2000, x=200, y=800),
            _touch_move(2050, [(200, 600), (200, 400)]),
            _touch_cancel(2100),
            *_touch(4000, x=100, y=100),
            _wireframe(4500, _el("text", "Detail")),
        ]
        result = analyze_events(events)
        assert result.count("Tapped") == 1
        assert "Tapped at (100, 100)" in result
        assert "Tapped at (200, 800)" not in result

    def test_unclosed_gesture_ending_on_cancel_is_not_flushed_as_tap(self) -> None:
        """A session that ends on a cancel flushes no tap."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            _touch_start(2000, x=10, y=20),
            _touch_cancel(2100),
        ]
        result = analyze_events(events)
        assert "Tapped" not in result
        assert result == "1: Wireframe: Home"

    def test_scroll_after_frames_captured(self) -> None:
        """A scroll arms the after-frames, like a tap."""
        events = [
            _wireframe(1000, _el("text", "Feed top")),
            _touch_start(2000, x=200, y=800),
            _touch_move(2050, [(200, 600), (200, 300)]),
            _touch_end(2100, x=200, y=290),
            _wireframe(2200, _el("text", "Feed mid")),
            _wireframe(2300, _el("text", "Feed bottom")),
        ]
        result = analyze_events(events)
        assert result == (
            "1: Wireframe: Feed top\n2: Scrolled\n"
            "2: Wireframe: Feed mid\n2: Wireframe: Feed bottom"
        )

    def test_scroll_rest_states_captured_between_scrolls(self) -> None:
        """The resting screen between two scrolls survives."""
        events = [
            _wireframe(1000, _el("text", "Screen A")),
            _touch_start(2000, x=200, y=800),
            _touch_move(2050, [(200, 600), (200, 400)]),
            _touch_end(2100, x=200, y=390),
            _wireframe(2500, _el("text", "Screen B")),
            _touch_start(4000, x=200, y=800),
            _touch_move(4050, [(200, 600), (200, 400)]),
            _touch_end(4100, x=200, y=390),
            _wireframe(4500, _el("text", "Screen C")),
        ]
        result = analyze_events(events)
        assert result == (
            "1: Wireframe: Screen A\n2: Scrolled\n2: Wireframe: Screen B\n"
            "4: Scrolled\n4: Wireframe: Screen C"
        )
        assert "Tapped" not in result

    def test_scroll_then_tap_surfaces_settled_scroll_screen(self) -> None:
        """The screen a scroll settles on is the "before" of the next tap."""
        events = [
            _wireframe(1000, _el("text", "List top")),
            _touch_start(2000, x=200, y=800),
            _touch_move(2050, [(200, 600), (200, 300)]),
            _touch_end(2100, x=200, y=290),
            _wireframe(2500, _el("text", "List scrolled")),
            *_touch(4000, x=100, y=100),
            _wireframe(4500, _el("text", "Item detail")),
        ]
        result = analyze_events(events)
        assert result == (
            "1: Wireframe: List top\n2: Scrolled\n2: Wireframe: List scrolled\n"
            "4: Tapped at (100, 100)\n4: Wireframe: Item detail"
        )

    def test_small_jitter_still_reads_as_tap(self) -> None:
        """Finger travel under the threshold is still a tap."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            _touch_start(2000, x=100, y=100),
            _touch_move(2010, [(103, 102)]),  # about 3.6 px of travel
            _touch_end(2020, x=102, y=101),
        ]
        result = analyze_events(events)
        assert result == "1: Wireframe: Home\n2: Tapped at (102, 101)"

    def test_tap_without_coordinates_omits_location(self) -> None:
        """A tap without coordinates renders as a bare ``Tapped``."""
        no_xy_start = {
            "type": 3,
            "timestamp": 1500,
            "data": {"source": 2, "type": 7, "id": 28},
        }
        no_xy_end = {
            "type": 3,
            "timestamp": 1500,
            "data": {"source": 2, "type": 9, "id": 28},
        }
        events = [_wireframe(1000, _el("text", "Home")), no_xy_start, no_xy_end]
        result = analyze_events(events)
        assert result == "1: Wireframe: Home\n1: Tapped"

    def test_unclosed_gesture_flushed_as_tap(self) -> None:
        """A gesture still open at the end is flushed as a tap at finger-down."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            _touch_start(2000, x=10, y=20),
        ]
        result = analyze_events(events)
        assert result == "1: Wireframe: Home\n2: Tapped at (10, 20)"

    def test_touch_without_any_wireframe_is_not_mobile(self) -> None:
        """A touch in a stream with no Meta event and no wireframe is a web tap.

        Same output as the upstream analyzer, for a different reason. Our
        analyzer decides the recording type before the walk: a stream with
        a wireframe, or with Meta events that all lack ``href``, is a
        screenshot recording. This stream has no Meta event at all, so it
        stays a DOM recording, and the touch takes the web path.
        """
        result = analyze_events(_touch(1500, x=10, y=20))
        assert "Tapped at" not in result
        assert result == "1: Tapped element"

    def test_web_touch_that_travels_is_a_tap_not_a_scroll(self) -> None:
        """A web touch is one tap at finger-down, even when the finger travels."""
        events = [
            _touch_start(1000, x=10, y=20),
            _touch_move(1100, positions=[(10, 400)]),
            _touch_end(1200, x=10, y=400),
        ]
        result = analyze_events(events)
        assert "Scrolled" not in result
        assert result == "1: Tapped element"

    def test_actions_contain_wireframes_detects_from_structured_actions(self) -> None:
        """Structured detection finds screen actions and nothing else.

        Intentional difference from the upstream analyzer: upstream finds a
        screen by the ``Wireframe:`` prefix of the description. Our actions
        carry a closed action label, so the check reads ``action ==
        "screen"``, and a description that only looks like a screen does
        not count.
        """
        screen = UserAction(
            timestamp=1,
            action="screen",
            target_node_id=None,
            target_desc="(screen)",
            url=None,
            description="Wireframe: Home",
        )
        tap = UserAction(
            timestamp=1,
            action="touch_start",
            target_node_id=None,
            target_desc="(10, 20)",
            url=None,
            description="Tapped element",
        )
        look_alike = UserAction(
            timestamp=1,
            action="click",
            target_node_id=None,
            target_desc="element",
            url=None,
            description="Wireframe: settings",
        )
        assert actions_contain_wireframes([screen])
        assert not actions_contain_wireframes([tap])
        assert not actions_contain_wireframes([look_alike])
        assert not actions_contain_wireframes([])

    def test_wireframe_distinct_screens_kept_separate(self) -> None:
        """Two different screens in a touchless session both survive."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            _wireframe(2000, _el("text", "Details")),
        ]
        result = analyze_events(events)
        assert result == "1: Wireframe: Home\n2: Wireframe: Details"

    def test_wireframe_empty_screen_renders_placeholder(self) -> None:
        """A wireframe with no elements renders ``(empty screen)``."""
        result = analyze_events([_wireframe(1000)])
        assert result == "1: Wireframe: (empty screen)"

    def test_wireframe_pipe_in_label_is_sanitized(self) -> None:
        """A ``|`` inside a label becomes ``/``, so the separator stays clear."""
        events = [
            _wireframe(
                1000,
                _el("text", "Home | Products"),
                _el("button", "Copy | Paste"),
            )
        ]
        result = analyze_events(events)
        assert result == "1: Wireframe: Home / Products | button:Copy / Paste"

    def test_wireframe_renders_element_bounds(self) -> None:
        """Each element carries its rect; an all-zero rect is omitted."""
        events = [
            _wireframe(
                1000,
                _el("text", "Movie Search", bounds=(16, 52, 200, 28)),
                _el("input", bounds=(16, 96, 344, 44)),
                _el("button", "Search", bounds=(300, 96, 60, 44)),
                _el("image", bounds=(0, 0, 0, 0)),
            )
        ]
        result = analyze_events(events)
        assert result == (
            "1: Wireframe: Movie Search [16,52,200,28] | input [16,96,344,44] "
            "| button:Search [300,96,60,44] | image"
        )

    def test_non_wireframe_custom_event_is_ignored(self) -> None:
        """A Custom event with another tag is not a screen."""
        events = [
            _wireframe(1000, _el("text", "ignored"), tag="some_other_plugin"),
            _wireframe(2000, _el("text", "Home")),
        ]
        result = analyze_events(events)
        assert "ignored" not in result
        assert result == "2: Wireframe: Home"

    def test_timeline_contains_wireframes_true_for_rendered_screen(self) -> None:
        """The rendered timeline of a wireframe session is detected."""
        timeline = analyze_events([_wireframe(1000, _el("text", "Home"))])
        assert timeline_contains_wireframes(timeline)

    def test_timeline_contains_wireframes_false_for_web_only_timeline(self) -> None:
        """A web-only timeline has no screens."""
        assert not timeline_contains_wireframes(
            "1: Clicked button 'Sign up'\n2: Scrolled"
        )
        assert not timeline_contains_wireframes("")

    def test_timeline_contains_wireframes_ignores_marker_inside_content(self) -> None:
        """The marker counts only at the description position of a line."""
        assert not timeline_contains_wireframes("1: Clicked 'Wireframe: settings'")
        assert not timeline_contains_wireframes("2: Event: Wireframe: opened")
        assert timeline_contains_wireframes("1: Clicked button\n2: Wireframe: Home")


# =============================================================================
# Recording-type detection (screenshot recording against DOM recording)
# =============================================================================


class TestDetectCapture:
    """``detect_capture`` decides the recording type once, before the walk."""

    def test_empty_stream_is_dom(self) -> None:
        """An empty stream is a DOM recording."""
        assert detect_capture([]) == "dom"

    def test_stream_without_meta_or_wireframe_is_dom(self) -> None:
        """A stream with no Meta event and no wireframe is a DOM recording.

        This keeps every existing web test and golden stable: many of them
        have no Meta event at all.
        """
        assert detect_capture(_touch(1500)) == "dom"

    def test_meta_with_href_is_dom(self) -> None:
        """A Meta event with ``href`` marks a DOM recording."""
        assert detect_capture([_meta(1000, "/x"), *_touch(1500)]) == "dom"

    def test_meta_without_href_is_screenshot(self) -> None:
        """Meta events that all lack ``href`` mark a screenshot recording."""
        assert detect_capture([_meta_no_href(1000), *_touch(1500)]) == "screenshot"

    def test_empty_href_counts_as_no_href(self) -> None:
        """An empty ``href`` string is not an ``href``."""
        assert detect_capture([_meta(1000, "")]) == "screenshot"

    def test_one_meta_with_href_is_enough_for_dom(self) -> None:
        """One Meta event with ``href`` makes the stream a DOM recording."""
        events = [_meta_no_href(1000), _meta(2000, "/x")]
        assert detect_capture(events) == "dom"

    def test_wireframe_wins_over_href(self) -> None:
        """Any ``mp_wireframe`` event marks a screenshot recording."""
        events = [_meta(1000, "/x"), _wireframe(2000, _el("text", "Home"))]
        assert detect_capture(events) == "screenshot"

    def test_other_custom_tag_is_not_a_wireframe(self) -> None:
        """A Custom event with another tag does not change the type."""
        events = [_meta(1000, "/x"), _wireframe(2000, tag="some_other_plugin")]
        assert detect_capture(events) == "dom"

    def test_meta_with_non_dict_data_counts_as_meta_without_href(self) -> None:
        """A Meta event whose ``data`` is not a dict has no ``href``."""
        events = [{"type": 4, "timestamp": 1, "data": []}]
        assert detect_capture(events) == "screenshot"

    def test_non_dict_events_are_skipped(self) -> None:
        """Malformed entries do not raise and do not count."""
        assert detect_capture(["junk", 3, None]) == "dom"


# =============================================================================
# Screenshot-recording rules that go past the upstream analyzer
# =============================================================================


class TestScreenshotRecordings:
    """Rules for screenshot recordings that differ from the upstream analyzer."""

    def test_touch_before_first_wireframe_uses_gesture_rules(self) -> None:
        """A touch before the first wireframe is still a gesture.

        Intentional difference from the upstream analyzer: upstream treats a
        touch as mobile only after the first wireframe arrives, so an early
        iOS touch renders ``Tapped element``. Our analyzer decides the
        recording type before the walk.
        """
        events = [
            *_touch(1500, x=30, y=40),
            _wireframe(3000, _el("text", "Home")),
        ]
        assert analyze_events(events) == "1: Tapped at (30, 40)\n3: Wireframe: Home"

    def test_early_cancelled_swipe_emits_nothing(self) -> None:
        """An early swipe that the system cancels emits no tap and no scroll.

        Intentional difference from the upstream analyzer: upstream renders
        ``Tapped element`` and a stray ``Scrolled`` for this iOS stream.
        """
        events = [
            _touch_start(1500, x=200, y=874),
            _touch_move(1550, [(200, 820), (200, 782)]),
            _touch_cancel(1600),
            _wireframe(3000, _el("text", "Home")),
        ]
        assert analyze_events(events) == "3: Wireframe: Home"

    def test_taps_without_wireframes_render_coordinates(self) -> None:
        """A screenshot recording without wireframes still shows tap points.

        Intentional difference from the upstream analyzer: upstream renders
        ``Tapped element`` with no coordinates when wireframes are off.
        """
        events = [
            _meta_no_href(1000),
            *_touch(2000, x=50, y=60),
            _touch_start(3000, x=200, y=800),
            _touch_move(3050, [(200, 500)]),
            _touch_end(3100, x=200, y=400),
        ]
        assert analyze_events(events) == "2: Tapped at (50, 60)\n3: Scrolled"

    def test_click_is_a_one_event_gesture(self) -> None:
        """A mouse click brackets the screens like a tap and shows its point.

        Intentional difference from the upstream analyzer: upstream renders
        ``Clicked element`` with no coordinates and samples no screens
        around a click. MouseDown and MouseUp stay ignored.
        """
        events = [
            _wireframe(1000, _el("text", "Home")),
            _wireframe(1500, _el("text", "Home settled")),
            _screenshot_click(2000, click_type=1),  # MouseDown
            _screenshot_click(2000, click_type=0),  # MouseUp
            _screenshot_click(2000, x=5, y=6),
            _wireframe(2500, _el("text", "Details")),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert result.markdown_summary == (
            "1: Wireframe: Home settled\n2: Clicked at (5, 6)\n2: Wireframe: Details"
        )
        clicks = [a for a in result.actions if a.action == "click"]
        assert len(clicks) == 1
        assert clicks[0].target_desc == "(5, 6)"
        assert clicks[0].metadata == {"interaction": "clicked", "x": 5, "y": 6}

    def test_click_without_coordinates(self) -> None:
        """A click without coordinates renders a bare ``Clicked``."""
        events = [
            _meta_no_href(1000),
            _screenshot_click(2000, x=None, y=None),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert result.markdown_summary == "2: Clicked"
        assert result.actions[0].target_desc == "(click)"
        assert result.actions[0].metadata == {"interaction": "clicked"}

    @pytest.mark.parametrize("click_type", [3, 4, 5])
    def test_other_mouse_interactions_are_ignored(self, click_type: int) -> None:
        """Right-click, double-click, and focus on the screenshot are ignored.

        Their only target is the screenshot image, so the DOM element
        description carries no information.
        """
        events = [_meta_no_href(1000), _screenshot_click(2000, click_type=click_type)]
        assert RrwebAnalyzer().analyze(events).actions == []

    def test_dom_element_description_is_never_used(self) -> None:
        """A tap on a tracked DOM node still renders coordinates only."""
        root = _document_root(
            _element_node(28, "img", attributes={"alt": "screenshot"})
        )
        events = [
            _meta_no_href(1000),
            _full_snapshot(1100, root),
            *_touch(2000, x=1, y=2),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert result.markdown_summary == "2: Tapped at (1, 2)"
        assert "screenshot" not in result.actions[0].target_desc

    def test_dom_recording_ignores_wireframe_only_inputs(self) -> None:
        """In a DOM recording, touch end, touch move, and cancel stay ignored."""
        events = [
            _meta(1000, "/x"),
            _touch_start(2000, x=10, y=20),
            _touch_move(2050, [(10, 400)]),
            _touch_end(2100, x=10, y=400),
            _touch_cancel(2200),
        ]
        assert analyze_events(events) == "1: Navigated to /x\n2: Tapped element"


# =============================================================================
# Structured actions for screenshot recordings
# =============================================================================


class TestScreenshotStructuredActions:
    """The action labels, targets, and metadata of screenshot actions."""

    def test_screen_action_fields(self) -> None:
        """A screen is a ``screen`` action targeted at its heading."""
        result = RrwebAnalyzer().analyze([_wireframe(1000, _el("text", "Home"))])
        (screen,) = result.actions
        assert screen.action == "screen"
        assert screen.target_desc == "Home"
        assert screen.description == "Wireframe: Home"
        assert screen.target_node_id is None
        assert screen.url is None
        assert screen.metadata["element_count"] == 1
        assert screen.metadata["scale"] == 1.0

    def test_screen_action_carries_current_url(self) -> None:
        """A screen action carries the URL of the latest Meta ``href``."""
        events = [_meta(500, "/app"), _wireframe(1000, _el("text", "Home"))]
        result = RrwebAnalyzer().analyze(events)
        screens = [a for a in result.actions if a.action == "screen"]
        assert screens[0].url == "/app"

    def test_tap_action_fields(self) -> None:
        """A tap is a ``touch_start`` action targeted at its point."""
        result = RrwebAnalyzer().analyze([_meta_no_href(1000), *_touch(2000, 7, 8)])
        (tap,) = result.actions
        assert tap.action == "touch_start"
        assert tap.target_desc == "(7, 8)"
        assert tap.description == "Tapped at (7, 8)"
        assert tap.metadata == {"interaction": "tapped", "x": 7, "y": 8}
        assert tap.target_node_id == 28

    def test_tap_without_coordinates_target(self) -> None:
        """A tap without coordinates targets the ``(tap)`` placeholder."""
        events = [_meta_no_href(1000), *_touch(2000, x=None, y=None)]
        (tap,) = RrwebAnalyzer().analyze(events).actions
        assert tap.target_desc == "(tap)"
        assert tap.metadata == {"interaction": "tapped"}

    def test_float_coordinates_are_truncated(self) -> None:
        """Float coordinates render as integers, as upstream does."""
        events = [_meta_no_href(1000), *_touch(2000, x=10.9, y=-3.7)]
        (tap,) = RrwebAnalyzer().analyze(events).actions
        assert tap.description == "Tapped at (10, -3)"
        assert tap.metadata == {"interaction": "tapped", "x": 10, "y": -3}

    def test_gesture_scroll_action_fields(self) -> None:
        """A swipe is a ``scroll`` action targeted at the viewport."""
        events = [
            _meta_no_href(1000),
            _touch_start(2000, x=0, y=0),
            _touch_end(2100, x=0, y=100),
        ]
        (scroll,) = RrwebAnalyzer().analyze(events).actions
        assert scroll.action == "scroll"
        assert scroll.target_desc == "(viewport)"
        assert scroll.description == "Scrolled"

    def test_touch_move_without_open_gesture_is_a_scroll(self) -> None:
        """A drag with no finger-down (the session starts mid-drag) is a scroll."""
        events = [_meta_no_href(1000), _touch_move(2000, [(1, 1)])]
        assert analyze_events(events) == "2: Scrolled"

    def test_touch_move_without_positions_and_gesture_is_ignored(self) -> None:
        """A drag with no samples and no open gesture emits nothing."""
        events = [_meta_no_href(1000), _touch_move(2000, [])]
        assert RrwebAnalyzer().analyze(events).actions == []

    def test_gesture_scroll_shares_the_scroll_debounce(self) -> None:
        """A gesture scroll right after a DOM scroll event is debounced."""
        events = [
            _meta_no_href(1000),
            _scroll(2000),
            _touch_start(2100, x=0, y=0),
            _touch_end(2200, x=0, y=300),
        ]
        assert analyze_events(events) == "2: Scrolled"

    def test_second_touch_start_flushes_open_gesture_as_tap(self) -> None:
        """A new finger-down flushes the open gesture as a tap first."""
        events = [
            _meta_no_href(1000),
            _touch_start(2000, x=1, y=1),
            *_touch(3000, x=2, y=2),
        ]
        assert analyze_events(events) == "2: Tapped at (1, 1)\n3: Tapped at (2, 2)"

    def test_touch_end_without_open_gesture_is_ignored(self) -> None:
        """A lift-off with no finger-down emits nothing."""
        events = [_meta_no_href(1000), _touch_end(2000)]
        assert RrwebAnalyzer().analyze(events).actions == []

    def test_cancel_without_open_gesture_is_ignored(self) -> None:
        """A cancel with no open gesture emits nothing and arms nothing."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            _touch_cancel(2000),
            _wireframe(2100, _el("text", "A")),
            _wireframe(2200, _el("text", "B")),
        ]
        # No gesture opened, so A is not an after-frame; B is the trailing screen.
        assert analyze_events(events) == "1: Wireframe: Home\n2: Wireframe: B"

    def test_gesture_without_start_coordinates_uses_end_point(self) -> None:
        """Travel is not tracked without a start point; the end point is the tap."""
        events = [
            _meta_no_href(1000),
            _touch_start(2000, x=None, y=None),
            _touch_move(2050, [(500, 500)]),
            _touch_end(2100, x=500, y=500),
        ]
        assert analyze_events(events) == "2: Tapped at (500, 500)"

    def test_touch_end_without_coordinates_uses_start_point(self) -> None:
        """A lift-off without coordinates reports the finger-down point."""
        events = [
            _meta_no_href(1000),
            _touch_start(2000, x=4, y=5),
            _touch_end(2100, x=None, y=None),
        ]
        assert analyze_events(events) == "2: Tapped at (4, 5)"

    def test_actions_are_sorted_and_markdown_matches_actions(self) -> None:
        """Actions come out in timestamp order; markdown renders from them."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            _wireframe(1800, _el("text", "Settled")),
            *_touch(2000),
            _wireframe(2500, _el("text", "Details")),
        ]
        result = RrwebAnalyzer().analyze(events)
        stamps = [a.timestamp for a in result.actions]
        assert stamps == sorted(stamps)
        assert result.markdown_summary == _render_markdown(result.actions)

    def test_finalize_is_idempotent(self) -> None:
        """A second ``finalize`` call adds nothing."""
        analyzer = EventAnalyzer(capture="screenshot")
        for event in [_wireframe(1000, _el("text", "Home")), _touch_start(2000)]:
            analyzer.process_event(event)
        analyzer.finalize()
        first = list(analyzer.user_actions)
        analyzer.finalize()
        assert analyzer.user_actions == first
        assert [a.action for a in first] == ["screen", "touch_start"]

    def test_default_event_analyzer_is_dom(self) -> None:
        """An ``EventAnalyzer`` built without a type is a DOM analyzer."""
        analyzer = EventAnalyzer()
        assert analyzer.capture == "dom"
        analyzer.process_event(_touch_start(2000))
        analyzer.finalize()
        assert [a.description for a in analyzer.user_actions] == ["Tapped element"]


# =============================================================================
# Wireframe tracker limits and input hardening
# =============================================================================


class TestWireframeTrackerLimits:
    """The screen cap and the label cut."""

    def test_screen_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The tracker stops at the screen cap."""
        monkeypatch.setattr(MobileWireframeTracker, "MAX_WIREFRAMES", 2)
        events: list[dict[str, Any]] = [_wireframe(1000, _el("text", "S0"))]
        for i in range(1, 6):
            events.extend(_touch(1000 + i * 100))
            events.append(_wireframe(1050 + i * 100, _el("text", f"S{i}")))
        result = RrwebAnalyzer().analyze(events)
        screens = [a for a in result.actions if a.action == "screen"]
        assert len(screens) == 2

    def test_long_label_is_cut(self) -> None:
        """A label over 50 characters is cut and gets an ellipsis."""
        label = "x" * 60
        result = analyze_events([_wireframe(1000, _el("button", label))])
        assert result == f"1: Wireframe: button:{'x' * 50}…"

    def test_label_and_role_are_stripped(self) -> None:
        """Label and role whitespace is stripped."""
        result = analyze_events([_wireframe(1000, _el(" button ", "  Go  "))])
        assert result == "1: Wireframe: button:Go"


class TestWireframeHardening:
    """Malformed wireframe input is skipped or degraded, never raised."""

    @pytest.mark.parametrize("role", [7, None, "", "   ", ["button"], True])
    def test_role_not_a_usable_string_renders_as_element(self, role: Any) -> None:
        """A role that is not a non-blank string renders as ``element``.

        Intentional difference from the upstream analyzer: upstream raises
        on a role that is not a string.
        """
        result = analyze_events([_wireframe(1000, _el(role, "Go"))])
        assert result == "1: Wireframe: element:Go"

    def test_element_not_a_dict_is_skipped(self) -> None:
        """Elements that are not dicts are skipped.

        Intentional difference from the upstream analyzer: upstream raises
        on an element that is not a dict.
        """
        result = analyze_events(
            [_wireframe(1000, "junk", 5, None, ["text"], _el("text", "Home"))]
        )
        assert result == "1: Wireframe: Home"

    def test_all_elements_malformed_renders_empty_screen(self) -> None:
        """A screen of malformed elements renders ``(empty screen)``."""
        result = analyze_events([_wireframe(1000, "junk", 5)])
        assert result == "1: Wireframe: (empty screen)"

    @pytest.mark.parametrize("payload", [None, [], "screen", 3, {"elements": None}])
    def test_payload_wrong_type_renders_empty_screen(self, payload: Any) -> None:
        """A payload that is not a dict carries no elements.

        Intentional difference from the upstream analyzer: upstream raises
        on a truthy payload that is not a dict.
        """
        event = {
            "type": 5,
            "timestamp": 1000,
            "data": {"tag": "mp_wireframe", "payload": payload},
        }
        assert analyze_events([event]) == "1: Wireframe: (empty screen)"

    @pytest.mark.parametrize("elements", [{"role": "text"}, "text", 5])
    def test_elements_wrong_type_renders_empty_screen(self, elements: Any) -> None:
        """An ``elements`` value that is not a list carries no elements."""
        event = {
            "type": 5,
            "timestamp": 1000,
            "data": {"tag": "mp_wireframe", "payload": {"elements": elements}},
        }
        assert analyze_events([event]) == "1: Wireframe: (empty screen)"

    @pytest.mark.parametrize(
        "bounds",
        [
            [True, 0, 10, 10],
            [0, 0, False, 10],
            ["16", "52", "200", "28"],
            [1, 2, 3],
            [1, 2, 3, 4, 5],
            "0,0,10,10",
            None,
            [float("inf"), 0, 10, 10],
            [float("nan"), 0, 10, 10],
            [10**400, 0, 10, 10],
            {"x": 1},
        ],
    )
    def test_malformed_bounds_are_omitted(self, bounds: Any) -> None:
        """Bounds with a bool, a string, a bad length, or a bad number are omitted.

        Intentional difference from the upstream analyzer: upstream converts
        each value with ``int()``, so it renders ``True`` as ``1`` and a
        numeric string such as ``"16"`` as ``16``, and it raises on an
        infinite float. Our analyzer accepts finite numbers only.
        """
        result = analyze_events([_wireframe(1000, _el("button", "Go", bounds=bounds))])
        assert result == "1: Wireframe: button:Go"

    def test_float_bounds_are_truncated(self) -> None:
        """Finite float bounds render as integers."""
        result = analyze_events(
            [_wireframe(1000, _el("text", "Go", bounds=(1.9, 2.1, 30.5, 40.0)))]
        )
        assert result == "1: Wireframe: Go [1,2,30,40]"

    @pytest.mark.parametrize("ts", [0, -5])
    def test_wireframe_with_non_positive_timestamp_is_skipped(self, ts: int) -> None:
        """A wireframe with a timestamp of zero or less is skipped, not raised.

        Intentional difference from the upstream analyzer: upstream skips a
        missing timestamp only. Our ``UserAction`` rejects a timestamp of
        zero or less, so such a screen would fail the whole analysis.
        """
        events = [
            _wireframe(ts, _el("text", "Bad")),
            _wireframe(1000, _el("text", "Home")),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert result.markdown_summary == "1: Wireframe: Home"

    def test_only_bad_timestamp_wireframe_gives_no_actions(self) -> None:
        """A stream of one bad-timestamp wireframe has no actions."""
        result = RrwebAnalyzer().analyze([_wireframe(0, _el("text", "Bad"))])
        assert result.actions == []
        assert result.markdown_summary == "No user actions recorded."

    def test_custom_event_with_non_dict_data_is_ignored(self) -> None:
        """A Custom event whose ``data`` is not a dict is ignored."""
        events = [{"type": 5, "timestamp": 1000, "data": "mp_wireframe"}]
        assert RrwebAnalyzer().analyze(events).actions == []

    @pytest.mark.parametrize(
        "x,y",
        [
            (True, 5),
            (5, False),
            ("5", 5),
            (float("nan"), 5),
            (float("inf"), 5),
            pytest.param(10**400, 1, id="int-too-large-for-float"),
        ],
    )
    def test_unusable_tap_coordinates_omit_location(self, x: Any, y: Any) -> None:
        """A bool, a string, or a number that is not finite is not a location.

        Intentional difference from the upstream analyzer: upstream renders
        ``True`` as ``1`` and raises on a float that is not finite.
        """
        events = [_meta_no_href(1000), *_touch(2000, x=x, y=y)]
        assert analyze_events(events) == "2: Tapped"

    @pytest.mark.parametrize(
        "data",
        [
            {"source": 6, "positions": "junk"},
            {"source": 6, "positions": [None, "p", {"x": "1", "y": 2}]},
            {"source": 6, "positions": [{"x": float("inf"), "y": 1}]},
            {"source": 6},
        ],
    )
    def test_malformed_touch_move_is_harmless(self, data: dict[str, Any]) -> None:
        """Malformed drag samples add no travel, so the gesture stays a tap."""
        events = [
            _meta_no_href(1000),
            _touch_start(2000, x=1, y=1),
            {"type": 3, "timestamp": 2050, "data": data},
            _touch_end(2100, x=1, y=1),
        ]
        assert analyze_events(events) == "2: Tapped at (1, 1)"

    def test_huge_travel_does_not_overflow(self) -> None:
        """Very large coordinates classify as a scroll without an overflow."""
        events = [
            _meta_no_href(1000),
            _touch_start(2000, x=-1e308, y=-1e308),
            _touch_move(2050, [(1e308, 1e308)]),
            _touch_end(2100, x=1e308, y=1e308),
        ]
        assert analyze_events(events) == "2: Scrolled"


# =============================================================================
# Real mobile fixtures against the upstream analyzer's output
# =============================================================================
#
# The fixtures in ``tests/fixtures/rrweb/`` are real replays with the
# screenshot images replaced by a placeholder. ``upstream/mobile-expected.json``
# holds the upstream analyzer's markdown for each one. Our markdown collapses
# consecutive identical lines into one ``(×N)`` line with the first timestamp
# of the run, so the upstream text goes through the same collapse before the
# comparison.

_RRWEB_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rrweb"


def _load_fixture(name: str) -> list[dict[str, Any]]:
    """Load one real rrweb fixture.

    Args:
        name: The fixture name, without the ``.json`` suffix.

    Returns:
        The rrweb event list.
    """
    events: list[dict[str, Any]] = json.loads(
        (_RRWEB_FIXTURES / f"{name}.json").read_text(encoding="utf-8")
    )
    return events


def _upstream_markdown(name: str) -> str:
    """Return the upstream analyzer's markdown for one real fixture.

    Args:
        name: The fixture name.

    Returns:
        The upstream markdown timeline.
    """
    expected: dict[str, str] = json.loads(
        (_RRWEB_FIXTURES / "upstream" / "mobile-expected.json").read_text(
            encoding="utf-8"
        )
    )
    return expected[name]


def _collapse_upstream(markdown: str) -> str:
    """Apply our ``(×N)`` run collapse to an upstream markdown timeline.

    Args:
        markdown: Upstream ``{seconds}: {description}`` lines.

    Returns:
        The same timeline with consecutive identical descriptions collapsed,
        as our markdown renders it.
    """
    pairs: list[tuple[int, str]] = []
    for line in markdown.splitlines():
        seconds, description = line.split(": ", 1)
        pairs.append((int(seconds) * 1000, description))
    return MarkdownReporter(pairs).generate()


def _ours(name: str) -> str:
    """Return our markdown for one real fixture.

    Args:
        name: The fixture name.

    Returns:
        Our markdown timeline.
    """
    return RrwebAnalyzer().analyze(_load_fixture(name)).markdown_summary


class TestRealMobileFixtures:
    """Our output on real replays, compared with the upstream analyzer."""

    @pytest.mark.parametrize(
        "name",
        [
            "android-snacks-001",
            "android-wireframe-001",
            "android-wireframe-masked-001",
            "flutter-android-rage-001",
            "flutter-web-clicks-001",
            "ios-early-touch-001",
            "ios-wireframe-001",
            "rn-android-no-wireframe-001",
            "rn-ios-001",
        ],
    )
    def test_every_fixture_is_a_screenshot_recording(self, name: str) -> None:
        """Every real mobile, Flutter, and React Native replay is a screenshot recording.

        Args:
            name: The fixture name.
        """
        assert detect_capture(_load_fixture(name)) == "screenshot"

    @pytest.mark.parametrize(
        "name",
        [
            "android-snacks-001",
            "android-wireframe-001",
            "android-wireframe-masked-001",
            "flutter-android-rage-001",
            "ios-wireframe-001",
            "rn-ios-001",
        ],
    )
    def test_matches_upstream_after_run_collapse(self, name: str) -> None:
        """These fixtures give the upstream text, apart from our ``(×N)`` collapse.

        The upstream analyzer already reads these replays correctly: every
        touch comes after the first wireframe, and the input is touches, not
        mouse clicks.

        Args:
            name: The fixture name.
        """
        assert _ours(name) == _collapse_upstream(_upstream_markdown(name))

    def test_android_wireframe_timeline(self) -> None:
        """The two-screen Android replay gives screens and tap points."""
        lines = _ours("android-wireframe-001").splitlines()
        descriptions = [line.split(": ", 1)[1] for line in lines]
        assert descriptions[0].startswith("Wireframe: Home [16,38,54,27]")
        assert descriptions[1] == "Tapped at (383, 51)"
        assert descriptions[2].startswith("Wireframe: Settings [72,38,76,27]")
        assert descriptions[3] == "Tapped at (182, 142)"
        assert len(descriptions) == 4

    def test_flutter_rage_burst_collapses(self) -> None:
        """The Flutter rage burst shows as one collapsed tap line."""
        assert "Tapped at (257, 638) (×7)" in _ours("flutter-android-rage-001")

    def test_ios_early_touch_drops_the_stray_lines(self) -> None:
        """The early cancelled iOS swipe emits no action.

        Intentional difference from the upstream analyzer: upstream reads the
        touch before the first wireframe as a web tap (``Tapped element``)
        and the drag with no open gesture as ``Scrolled``. Our analyzer knows
        from the start that this is a screenshot recording, so the gesture
        opens, and the system cancel closes it with no action.
        """
        upstream = _upstream_markdown("ios-early-touch-001").splitlines()
        stray = {"Tapped element", "Scrolled"}
        assert {line.split(": ", 1)[1] for line in upstream} & stray == stray
        kept = [line for line in upstream if line.split(": ", 1)[1] not in stray]
        assert _ours("ios-early-touch-001") == _collapse_upstream("\n".join(kept))

    def test_rn_android_without_wireframes_reports_tap_points(self) -> None:
        """Taps in a recording without wireframes report their coordinates.

        Intentional difference from the upstream analyzer: upstream uses the
        web path when no wireframe arrives, so it renders ``Tapped element``
        for each tap. The Meta events have no ``href``, so our analyzer
        reads a screenshot recording and reports the tap points.
        """
        upstream = _upstream_markdown("rn-android-no-wireframe-001")
        assert upstream == (
            "1789671576: Tapped element\n"
            "1789671577: Tapped element\n"
            "1789671595: Tapped element"
        )
        assert _ours("rn-android-no-wireframe-001") == (
            "1789671576: Tapped at (364, 516)\n"
            "1789671577: Tapped at (364, 617)\n"
            "1789671595: Tapped at (340, 507)"
        )

    def test_flutter_web_clicks_report_points_and_screens(self) -> None:
        """Flutter web clicks report their points and bracket the screens.

        Intentional difference from the upstream analyzer: upstream renders
        ``Clicked element`` with no coordinates and samples no screens around
        a click, so it keeps only the first and the last screen. Our analyzer
        treats each click as a one-event gesture: the screen before it, the
        click point, and the screens after it.
        """
        upstream = _upstream_markdown("flutter-web-clicks-001").splitlines()
        ours = _ours("flutter-web-clicks-001").splitlines()

        upstream_clicks = [line for line in upstream if ": Clicked" in line]
        assert upstream_clicks == [
            "1789747584: Clicked element",
            "1789747601: Clicked element",
            "1789747604: Clicked element",
        ]
        our_clicks = [line for line in ours if ": Clicked" in line]
        assert our_clicks == [
            "1789747584: Clicked at (594, 833)",
            "1789747601: Clicked at (27, 27)",
            "1789747604: Clicked at (1100, 24)",
        ]

        # Every upstream screen is still in our timeline, in the same order,
        # and every extra line of ours is a screen.
        upstream_screens = [line for line in upstream if ": Wireframe: " in line]
        our_screens = [line for line in ours if ": Wireframe: " in line]
        remaining = iter(our_screens)
        assert all(screen in remaining for screen in upstream_screens)
        assert len(our_screens) > len(upstream_screens)
        assert len(ours) == len(our_clicks) + len(our_screens)


class TestNonPositiveTimestamps:
    """An action with a timestamp of zero or less is dropped on every path."""

    def test_dom_actions_with_non_positive_timestamps_are_dropped(self) -> None:
        """DOM navigations and clicks at timestamp 0 or less are dropped, not raised."""
        events = [
            _meta(0, "/zero"),
            _click(-10, 999),
            _meta(1000, "/x"),
            _click(2000, 999),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert result.markdown_summary == "1: Navigated to /x\n2: Clicked element"
        assert all(a.timestamp > 0 for a in result.actions)

    def test_screenshot_actions_with_non_positive_timestamps_are_dropped(
        self,
    ) -> None:
        """Screenshot taps, clicks, and scrolls at timestamp 0 or less are dropped."""
        events = [
            _meta_no_href(1),
            *_touch(0, x=1, y=1),
            _screenshot_click(-5),
            _touch_move(0, [(1, 1)]),
            *_touch(2000, x=2, y=2),
        ]
        result = RrwebAnalyzer().analyze(events)
        assert result.markdown_summary == "2: Tapped at (2, 2)"


# =============================================================================
# Structured screen data: heading, elements, scale, fingerprint
# =============================================================================


def _wireframe_vp(ts: int, viewport: Any, *elements: Any) -> dict[str, Any]:
    """Build an ``mp_wireframe`` Custom event that carries a ``viewport``.

    Args:
        ts: Unix ms timestamp.
        viewport: The payload ``viewport`` value (``[w, h]`` from the SDK).
        *elements: The screen elements, in client order.

    Returns:
        The rrweb Custom event dict.
    """
    payload = {"viewport": viewport, "elements": list(elements)}
    return {
        "type": 5,
        "timestamp": ts,
        "data": {"tag": "mp_wireframe", "payload": payload},
    }


def _meta_width(ts: int, width: Any, height: Any = 914) -> dict[str, Any]:
    """Build a Meta event without ``href`` that carries a screen size.

    Args:
        ts: Unix ms timestamp.
        width: The Meta ``width`` (the touch coordinate space).
        height: The Meta ``height``.

    Returns:
        The rrweb Meta event dict.
    """
    return {"type": 4, "timestamp": ts, "data": {"width": width, "height": height}}


def _only_screen(events: list[dict[str, Any]]) -> UserAction:
    """Analyze ``events`` and return the one screen action.

    Args:
        events: An rrweb stream with exactly one emitted screen.

    Returns:
        The screen action.
    """
    screens = [
        a for a in RrwebAnalyzer().analyze(events).actions if a.action == "screen"
    ]
    assert len(screens) == 1
    return screens[0]


class TestScreenHeading:
    """The ``target_desc`` of a screen action is an approximate heading."""

    def test_topmost_labeled_text_wins(self) -> None:
        """The labeled text element with the smallest y, then x, is the heading."""
        screen = _only_screen(
            [
                _wireframe(
                    1000,
                    _el("text", "Body", bounds=(16, 200, 100, 20)),
                    _el("text", "Right", bounds=(300, 38, 50, 20)),
                    _el("text", "Title", bounds=(16, 38, 80, 20)),
                )
            ]
        )
        assert screen.target_desc == "Title"

    def test_non_text_and_unlabeled_elements_are_skipped(self) -> None:
        """Buttons and label-less text elements are never the heading."""
        screen = _only_screen(
            [
                _wireframe(
                    1000,
                    _el("button", "Back", bounds=(0, 0, 40, 40)),
                    _el("text", None, bounds=(50, 5, 40, 40)),
                    _el("text", "   ", bounds=(50, 6, 40, 40)),
                    _el("text", "Settings", bounds=(72, 38, 76, 27)),
                )
            ]
        )
        assert screen.target_desc == "Settings"

    def test_offscreen_text_is_skipped(self) -> None:
        """A text element fully outside the screen width is not the heading."""
        screen = _only_screen(
            [
                _meta_width(500, 402),
                _wireframe(
                    1000,
                    _el("text", "Next page", bounds=(420, 10, 100, 20)),
                    _el("text", "Sliding", bounds=(-150, 12, 100, 20)),
                    _el("text", "Current", bounds=(16, 60, 100, 20)),
                ),
            ]
        )
        assert screen.target_desc == "Current"

    def test_without_bounds_first_labeled_text_in_client_order(self) -> None:
        """With no bounds at all, the first labeled text element is the heading."""
        screen = _only_screen(
            [_wireframe(1000, _el("button", "Go"), _el("text", "A"), _el("text", "B"))]
        )
        assert screen.target_desc == "A"

    def test_fallback_placeholder(self) -> None:
        """A screen with no labeled text element keeps ``(screen)``."""
        screen = _only_screen(
            [_wireframe(1000, _el("button", "Go", bounds=(0, 0, 10, 10)), _el("text"))]
        )
        assert screen.target_desc == "(screen)"

    def test_heading_label_is_cut_like_the_rendered_label(self) -> None:
        """The heading uses the cut label of the rendered string."""
        screen = _only_screen(
            [_wireframe(1000, _el("text", "x" * 60, bounds=(0, 1, 5, 5)))]
        )
        assert screen.target_desc == "x" * 50 + "…"


class TestScreenMetadata:
    """The structured metadata of a screen action."""

    def test_elements_are_sanitized(self) -> None:
        """Elements carry role, cut label, integer bounds, and the offscreen flag."""
        screen = _only_screen(
            [
                _meta_width(500, 411),
                _wireframe(
                    1000,
                    _el(" button ", "  Copy | Paste  ", bounds=(1.9, 2.0, 30, 40)),
                    _el(7, None, bounds=(0, 0, 0, 0)),
                    "junk",
                    _el("text", "y" * 60, bounds=(500, 10, 20, 20)),
                ),
            ]
        )
        assert screen.metadata["elements"] == [
            {
                "role": "button",
                "text": "Copy | Paste",
                "bounds": [1, 2, 30, 40],
                "offscreen": False,
                "background": False,
            },
            {
                "role": "element",
                "text": None,
                "bounds": None,
                "offscreen": False,
                "background": False,
            },
            {
                "role": "text",
                "text": "y" * 50 + "…",
                "bounds": [500, 10, 20, 20],
                "offscreen": True,
                "background": False,
            },
        ]
        assert screen.metadata["element_count"] == 3

    def test_viewport_is_recorded_when_valid(self) -> None:
        """A valid payload ``viewport`` is recorded as integer ``[w, h]``."""
        screen = _only_screen([_wireframe_vp(1000, [411.0, 914], _el("text", "A"))])
        assert screen.metadata["viewport"] == [411, 914]

    @pytest.mark.parametrize(
        "viewport", [None, [411], "411x914", [0, 914], [True, 914], ["411", 914]]
    )
    def test_invalid_viewport_is_omitted(self, viewport: Any) -> None:
        """A missing or malformed ``viewport`` is not recorded.

        Args:
            viewport: The malformed payload ``viewport``.
        """
        screen = _only_screen([_wireframe_vp(1000, viewport, _el("text", "A"))])
        assert "viewport" not in screen.metadata
        assert screen.metadata["scale"] == 1.0

    def test_scale_applies_when_widths_differ_by_more_than_five_percent(
        self,
    ) -> None:
        """Physical-pixel bounds scale into the Meta (touch) space.

        The rendered description keeps the raw bounds, as upstream does.
        """
        screen = _only_screen(
            [
                _meta_width(500, 411, 866),
                _wireframe_vp(
                    1000, [1080, 2400], _el("button", "Go", bounds=(0, 1080, 540, 200))
                ),
            ]
        )
        assert screen.metadata["scale"] == pytest.approx(411 / 1080)
        assert screen.metadata["elements"][0]["bounds"] == [0, 411, 206, 76]
        assert screen.description == "Wireframe: button:Go [0,1080,540,200]"

    @pytest.mark.parametrize("meta_width", [412, 411, 400])
    def test_small_width_difference_is_not_a_scale(self, meta_width: int) -> None:
        """A width ratio within 5% of 1.0 is rounding or system bars, not a scale.

        Args:
            meta_width: The Meta width against a 411-wide viewport.
        """
        screen = _only_screen(
            [
                _meta_width(500, meta_width),
                _wireframe_vp(1000, [411, 731], _el("text", "A", bounds=(1, 2, 3, 4))),
            ]
        )
        assert screen.metadata["scale"] == 1.0
        assert screen.metadata["elements"][0]["bounds"] == [1, 2, 3, 4]

    def test_no_scale_without_meta_width(self) -> None:
        """Without a Meta width there is nothing to scale against."""
        screen = _only_screen(
            [_wireframe_vp(1000, [1080, 2400], _el("text", "A", bounds=(0, 0, 9, 9)))]
        )
        assert screen.metadata["scale"] == 1.0

    @pytest.mark.parametrize("width", [None, 0, -5, "411", True, float("nan")])
    def test_unusable_meta_width_is_ignored(self, width: Any) -> None:
        """A Meta width that is not a positive finite number is ignored.

        Args:
            width: The malformed Meta width.
        """
        screen = _only_screen(
            [
                _meta_width(500, width),
                _wireframe_vp(
                    1000, [1080, 2400], _el("text", "A", bounds=(0, 0, 9, 9))
                ),
            ]
        )
        assert screen.metadata["scale"] == 1.0
        assert screen.metadata["elements"][0]["offscreen"] is False

    def test_offscreen_uses_the_scaled_viewport_without_meta_width(self) -> None:
        """Without a Meta width, the viewport width bounds the screen."""
        screen = _only_screen(
            [_wireframe_vp(1000, [400, 800], _el("text", "A", bounds=(410, 0, 9, 9)))]
        )
        assert screen.metadata["elements"][0]["offscreen"] is True

    def test_fingerprint_is_stable_and_short(self) -> None:
        """Identical screens share a fingerprint; different screens do not."""
        events = [
            _wireframe(1000, _el("text", "Home")),
            *_touch(1500),
            _wireframe(2000, _el("text", "Details")),
            *_touch(2500),
            _wireframe(3000, _el("text", "Home")),
        ]
        screens = [
            a for a in RrwebAnalyzer().analyze(events).actions if a.action == "screen"
        ]
        prints = [s.metadata["fingerprint"] for s in screens]
        assert prints[0] == prints[2]
        assert prints[0] != prints[1]
        assert all(len(p) == 12 and int(p, 16) >= 0 for p in prints)


# =============================================================================
# Tap-to-element attribution (hit test)
# =============================================================================


def _only_action(events: list[dict[str, Any]], action: str) -> UserAction:
    """Analyze ``events`` and return the one action with the given label.

    Args:
        events: An rrweb stream.
        action: The action label to select.

    Returns:
        The single matching action.
    """
    matches = [a for a in RrwebAnalyzer().analyze(events).actions if a.action == action]
    assert len(matches) == 1
    return matches[0]


class TestHitTest:
    """Screenshot taps and clicks name the element under the point."""

    def test_containing_labeled_button(self) -> None:
        """A tap inside a labeled button targets ``role:label``."""
        tap = _only_action(
            [
                _wireframe(1000, _el("button", "Save", bounds=(10, 10, 100, 40))),
                *_touch(2000, x=50, y=30),
            ],
            "touch_start",
        )
        assert tap.target_desc == "button:Save"
        assert tap.description == "Tapped at (50, 30)"
        assert tap.metadata["hit"] == {
            "role": "button",
            "text": "Save",
            "bounds": [10, 10, 100, 40],
        }
        assert tap.metadata["attribution"] == "bounds"
        assert (tap.metadata["x"], tap.metadata["y"]) == (50, 30)

    def test_text_hit_uses_bare_label(self) -> None:
        """A tap on a labeled text element targets the bare label."""
        tap = _only_action(
            [
                _wireframe(1000, _el("text", "Cupcake", bounds=(72, 104, 62, 21))),
                *_touch(2000, x=80, y=110),
            ],
            "touch_start",
        )
        assert tap.target_desc == "Cupcake"

    def test_unlabeled_hit_uses_role_and_bounds(self) -> None:
        """A label-less element targets ``role [x,y,w,h]`` (an icon, for example)."""
        tap = _only_action(
            [
                _wireframe(1000, _el("text", None, bounds=(363, 27, 48, 48))),
                *_touch(2000, x=383, y=51),
            ],
            "touch_start",
        )
        assert tap.target_desc == "text [363,27,48,48]"
        assert tap.metadata["hit"]["text"] is None

    def test_non_text_role_beats_text_role(self) -> None:
        """A button that contains the point beats a text label inside it."""
        tap = _only_action(
            [
                _wireframe(
                    1000,
                    _el("text", "Save", bounds=(20, 15, 40, 20)),
                    _el("button", None, bounds=(10, 10, 100, 40)),
                ),
                *_touch(2000, x=30, y=20),
            ],
            "touch_start",
        )
        assert tap.target_desc == "button [10,10,100,40]"

    def test_smallest_area_wins_among_equals(self) -> None:
        """Among containing elements of the same kind, the smallest wins."""
        tap = _only_action(
            [
                _wireframe(
                    1000,
                    _el("image", None, bounds=(0, 0, 400, 800)),
                    _el("image", "Avatar", bounds=(10, 10, 40, 40)),
                ),
                *_touch(2000, x=20, y=20),
            ],
            "touch_start",
        )
        assert tap.target_desc == "image:Avatar"

    def test_edges_are_inside(self) -> None:
        """A point on the rect edge is inside."""
        tap = _only_action(
            [
                _wireframe(1000, _el("button", "Go", bounds=(10, 10, 10, 10))),
                *_touch(2000, x=20, y=20),
            ],
            "touch_start",
        )
        assert tap.metadata["attribution"] == "bounds"

    def test_slop_catches_a_near_miss(self) -> None:
        """A tap 2 px below a button attributes to it with ``bounds_slop``."""
        tap = _only_action(
            [
                _wireframe(
                    1000,
                    _el("button", "Re-initialize", bounds=(16, 100, 379, 40)),
                    _el("text", "Status", bounds=(16, 168, 94, 20)),
                ),
                *_touch(2000, x=182, y=142),
            ],
            "touch_start",
        )
        assert tap.target_desc == "button:Re-initialize"
        assert tap.metadata["attribution"] == "bounds_slop"

    def test_slop_prefers_the_nearest_element(self) -> None:
        """Within the slop, the nearest element wins over the role preference."""
        tap = _only_action(
            [
                _wireframe(
                    1000,
                    _el("button", "Far", bounds=(0, 0, 100, 10)),
                    _el("text", "Near", bounds=(0, 17, 100, 10)),
                ),
                *_touch(2000, x=50, y=15),
            ],
            "touch_start",
        )
        assert tap.target_desc == "Near"

    def test_beyond_slop_is_no_hit(self) -> None:
        """A tap more than 8 px from every element has no hit."""
        tap = _only_action(
            [
                _wireframe(1000, _el("button", "Go", bounds=(0, 0, 10, 10))),
                *_touch(2000, x=30, y=30),
            ],
            "touch_start",
        )
        assert tap.target_desc == "(30, 30)"
        assert "hit" not in tap.metadata
        assert "attribution" not in tap.metadata

    def test_offscreen_and_boundless_elements_are_never_hit(self) -> None:
        """Offscreen elements and elements without bounds are not candidates."""
        tap = _only_action(
            [
                _meta_width(500, 100),
                _wireframe(
                    1000,
                    _el("button", "Offscreen", bounds=(100, 0, 50, 50)),
                    _el("button", "Nowhere"),
                ),
                *_touch(2000, x=101, y=10),
            ],
            "touch_start",
        )
        assert tap.target_desc == "(101, 10)"

    def test_hit_uses_scaled_bounds(self) -> None:
        """The hit test compares the touch point with the scaled bounds."""
        tap = _only_action(
            [
                _meta_width(500, 411, 866),
                _wireframe_vp(
                    1000, [1080, 2400], _el("button", "Go", bounds=(0, 1080, 540, 200))
                ),
                *_touch(2000, x=100, y=420),
            ],
            "touch_start",
        )
        assert tap.target_desc == "button:Go"
        assert tap.metadata["hit"]["bounds"] == [0, 411, 206, 76]

    def test_uses_the_screen_at_gesture_start(self) -> None:
        """The tap targets the screen under the finger-down, not the next one."""
        tap = _only_action(
            [
                _wireframe(1000, _el("button", "Before", bounds=(0, 0, 100, 100))),
                _touch_start(2000, x=50, y=50),
                _wireframe(2050, _el("button", "After", bounds=(0, 0, 100, 100))),
                _touch_end(2100, x=50, y=50),
            ],
            "touch_start",
        )
        assert tap.target_desc == "button:Before"

    def test_flushed_open_gesture_uses_its_screen(self) -> None:
        """A gesture flushed at the end still targets its own screen."""
        tap = _only_action(
            [
                _wireframe(1000, _el("button", "Before", bounds=(0, 0, 100, 100))),
                _touch_start(2000, x=50, y=50),
                _wireframe(2050, _el("button", "After", bounds=(0, 0, 100, 100))),
            ],
            "touch_start",
        )
        assert tap.target_desc == "button:Before"

    def test_tap_before_any_screen_has_no_hit(self) -> None:
        """A tap with no screen yet targets its point."""
        tap = _only_action(
            [
                *_touch(500, x=5, y=6),
                _wireframe(1000, _el("button", "Go", bounds=(0, 0, 100, 100))),
            ],
            "touch_start",
        )
        assert tap.target_desc == "(5, 6)"

    def test_skipped_wireframe_is_not_the_current_screen(self) -> None:
        """A wireframe with a timestamp of zero or less never becomes current."""
        events = [
            _wireframe(0, _el("button", "Bad", bounds=(0, 0, 100, 100))),
            _meta_no_href(1),
            *_touch(2000, x=5, y=6),
        ]
        tap = _only_action(events, "touch_start")
        assert tap.target_desc == "(5, 6)"

    def test_screenshot_click_is_hit_tested(self) -> None:
        """A screenshot click targets the element under the pointer."""
        click = _only_action(
            [
                _wireframe(1000, _el("button", "Buy", bounds=(0, 0, 100, 100))),
                _screenshot_click(2000, x=10, y=10),
            ],
            "click",
        )
        assert click.target_desc == "button:Buy"
        assert click.description == "Clicked at (10, 10)"
        assert click.metadata["attribution"] == "bounds"


class TestRealFixtureStructure:
    """Headings, targets, and scale on the real replays."""

    def test_android_headings_and_tap_targets(self) -> None:
        """The Android replay gives Home and Settings, the icon, and the button."""
        actions = (
            RrwebAnalyzer().analyze(_load_fixture("android-wireframe-001")).actions
        )
        assert [a.target_desc for a in actions] == [
            "Home",
            "text [363,27,48,48]",
            "Settings",
            "button:Re-initialize Session Replay",
        ]
        assert actions[1].metadata["attribution"] == "bounds"
        assert actions[3].metadata["attribution"] == "bounds_slop"

    def test_masked_physical_pixel_replay_scales(self) -> None:
        """The masked replay has physical-pixel bounds and gets a scale."""
        (screen,) = (
            RrwebAnalyzer()
            .analyze(_load_fixture("android-wireframe-masked-001"))
            .actions
        )
        assert screen.metadata["viewport"] == [1080, 2400]
        assert screen.metadata["scale"] == pytest.approx(411 / 1080)
        assert screen.target_desc == "(screen)"
        assert all(
            e["bounds"] is None or e["bounds"][0] + e["bounds"][2] <= 412
            for e in screen.metadata["elements"]
        )


# =============================================================================
# Crash inputs, node-id parity, background layers, clipped headings
# =============================================================================


class TestScaleCrashInputs:
    """Scaling inputs that used to raise now fall back to no scaling."""

    def test_sub_pixel_viewport_width_gives_no_scale(self) -> None:
        """A viewport width that truncates to 0 applies no scale (no division by 0)."""
        screen = _only_screen(
            [
                _meta_width(500, 411),
                _wireframe_vp(
                    1000, [0.5, 100], _el("button", "Go", bounds=(1, 2, 3, 4))
                ),
            ]
        )
        assert screen.metadata["scale"] == 1.0
        assert screen.metadata["elements"][0]["bounds"] == [1, 2, 3, 4]

    def test_sub_pixel_viewport_without_meta_width_flags_nothing_offscreen(
        self,
    ) -> None:
        """A zero-width viewport does not make every element offscreen."""
        screen = _only_screen(
            [_wireframe_vp(1000, [0.5, 100], _el("button", "Go", bounds=(1, 2, 3, 4)))]
        )
        assert screen.metadata["elements"][0]["offscreen"] is False

    def test_scaled_values_that_overflow_give_no_scale(self) -> None:
        """A huge Meta width whose scaled bounds are not finite applies no scale."""
        screen = _only_screen(
            [
                _meta_width(500, 1e308),
                _wireframe_vp(1000, [1, 1], _el("button", "Go", bounds=(5, 6, 7, 8))),
            ]
        )
        assert screen.metadata["scale"] == 1.0
        assert screen.metadata["elements"][0]["bounds"] == [5, 6, 7, 8]

    def test_lone_surrogate_label_does_not_raise(self) -> None:
        """A label with a lone surrogate (valid JSON) still gets a fingerprint."""
        screen = _only_screen([_wireframe(1000, _el("text", "bad \ud800 label"))])
        fingerprint = screen.metadata["fingerprint"]
        assert len(fingerprint) == 12
        expected = hashlib.sha1(
            screen.description.encode("utf-8", errors="replace"),
            usedforsecurity=False,
        ).hexdigest()[:12]
        assert fingerprint == expected


class TestNodeIdParity:
    """``target_node_id`` is an int or None on every path."""

    @pytest.mark.parametrize(
        ("raw", "expected"), [(28.0, 28), (True, None), (28.5, None), ("28", None)]
    )
    def test_screenshot_tap_node_id(self, raw: Any, expected: int | None) -> None:
        """A screenshot tap normalizes its node id.

        Args:
            raw: The raw rrweb node id.
            expected: The normalized ``target_node_id``.
        """
        events = [_meta_no_href(1), *_touch(2000, node_id=raw)]
        (tap,) = RrwebAnalyzer().analyze(events).actions
        assert tap.target_node_id == expected

    @pytest.mark.parametrize(("raw", "expected"), [(40.0, 40), (True, None)])
    def test_dom_click_node_id(self, raw: Any, expected: int | None) -> None:
        """A DOM click normalizes its node id.

        Args:
            raw: The raw rrweb node id.
            expected: The normalized ``target_node_id``.
        """
        root = _document_root(_element_node(40, "button", text="Go"))
        events = [_meta(1000, "/x"), _full_snapshot(1500, root), _click(2000, raw)]
        clicks = [
            a for a in RrwebAnalyzer().analyze(events).actions if a.action == "click"
        ]
        assert [c.target_node_id for c in clicks] == [expected]

    def test_dom_input_float_node_id(self) -> None:
        """A DOM input with an integral float node id keeps it as an int."""
        events = [_meta(1000, "/x"), _input(2000, 40.0, text="hi")]  # type: ignore[arg-type]
        inputs = [
            a for a in RrwebAnalyzer().analyze(events).actions if a.action == "input"
        ]
        assert inputs[0].target_node_id == 40
        assert type(inputs[0].target_node_id) is int


class TestBackgroundLayers:
    """Elements that cross both side edges are background layers."""

    def test_flag_is_set_only_when_both_edges_are_crossed(self) -> None:
        """``background`` is True only for a rect wider than the screen on both sides."""
        screen = _only_screen(
            [
                _meta_width(500, 402, 874),
                _wireframe(
                    1000,
                    _el("image", None, bounds=(-120, 731, 642, 286)),
                    _el("image", None, bounds=(-10, 0, 100, 10)),
                    _el("image", None, bounds=(0, 0, 402, 874)),
                ),
            ]
        )
        assert [e["background"] for e in screen.metadata["elements"]] == [
            True,
            False,
            False,
        ]

    def test_no_flag_without_a_screen_width(self) -> None:
        """Without a Meta width or viewport, nothing is a background."""
        screen = _only_screen(
            [_wireframe(1000, _el("image", None, bounds=(-120, 731, 642, 286)))]
        )
        assert screen.metadata["elements"][0]["background"] is False

    def test_ios_tab_bar_tap_hits_the_tab_icon(self) -> None:
        """A tab-bar tap hits the near tab icon, not the blur layer that contains it.

        The geometry comes from the iOS replay ``D4BE9CB5``: ``Tapped at
        (134, 821)`` used to target ``image [-118,731,638,286]``.
        """
        events = [
            _meta_width(500, 402, 874),
            _wireframe(
                1000,
                _el("text", None, bounds=(28, 826, 135, 14)),
                _el("image", None, bounds=(-118, 731, 638, 286)),
                _el("image", None, bounds=(138, 799, 28, 28)),
                _el("text", "SwiftUI Inputs", bounds=(116, 830, 71, 12)),
            ),
            *_touch(2000, x=134, y=821),
        ]
        tap = _only_action(events, "touch_start")
        assert tap.target_desc == "image [138,799,28,28]"
        assert tap.metadata["attribution"] == "bounds_slop"

    def test_background_alone_is_no_hit(self) -> None:
        """A tap on only a background layer has no hit."""
        events = [
            _meta_width(500, 402, 874),
            _wireframe(1000, _el("image", None, bounds=(-118, 731, 638, 286))),
            *_touch(2000, x=200, y=760),
        ]
        tap = _only_action(events, "touch_start")
        assert tap.target_desc == "(200, 760)"
        assert "hit" not in tap.metadata

    def test_hit_test_skips_background_in_the_slop_too(self) -> None:
        """A background layer near the point is not a slop candidate."""
        elements = [
            {
                "role": "image",
                "text": None,
                "bounds": [-10, 100, 500, 50],
                "offscreen": False,
                "background": True,
            }
        ]
        assert hit_test(elements, 50.0, 95.0) is None


class TestClippedHeading:
    """Text clipped above the top edge is not the heading."""

    def test_text_with_negative_y_is_skipped(self) -> None:
        """A label mostly scrolled above the top edge does not win (iOS ``B0BC49B1``)."""
        screen = _only_screen(
            [
                _wireframe(
                    1000,
                    _el(
                        "text",
                        "Hello world - wireframe txt",
                        bounds=(18, -109, 314, 113),
                    ),
                    _el("text", "SwiftUI Text", bounds=(16, 68, 190, 41)),
                )
            ]
        )
        assert screen.target_desc == "SwiftUI Text"

    def test_only_clipped_text_falls_back(self) -> None:
        """A screen whose only labeled text is clipped gets ``(screen)``."""
        screen = _only_screen(
            [_wireframe(1000, _el("text", "Gone", bounds=(0, -40, 100, 30)))]
        )
        assert screen.target_desc == "(screen)"

    def test_back_label_heading_stays(self) -> None:
        """A back-button label on the title row can still be the heading.

        The heading is approximate: the rule has no centered tie-break
        (React Native iOS ``9F276478``).
        """
        screen = _only_screen(
            [
                _wireframe(
                    1000,
                    _el("text", "Back", bounds=(27, 59, 39, 20)),
                    _el("text", "Session Replay Demo", bounds=(108, 59, 175, 20)),
                )
            ]
        )
        assert screen.target_desc == "Back"
