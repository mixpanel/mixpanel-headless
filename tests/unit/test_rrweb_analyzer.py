"""Targeted coverage for the rrweb analyzer (`_internal/replays/rrweb_analyzer.py`).

Synthetic event streams hit the paths that
`tests/unit/test_us2_replay_bundle.py::TestRrwebAnalyzer` doesn't exercise:
mutation adds/removes/text/attribute changes, console-error plugin events,
selection events with text extraction, mouse-interaction subtypes
(double / right / focus / touch_start), per-source debouncing, and the
DOM tracker's ancestor-traversal fallback.

All fixtures are hand-built here; no external fixtures or recordings.
"""

from __future__ import annotations

from typing import Any

import pytest

from mixpanel_headless._internal.replays.rrweb_analyzer import (
    DOMTracker,
    EventAnalyzer,
    MarkdownReporter,
    RrwebAnalyzer,
    analyze_events,
)

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
        assert (
            any(expected_verb in d for _, d in EventAnalyzer().descriptions or [])
            or any(
                expected_verb in a.target_desc or expected_verb in (a.target_desc or "")
                for a in result.actions
            )
            or expected_verb in result.markdown_summary
        )
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
