"""Property-based tests for the rrweb analyzer's screenshot-recording path.

Random mixed streams (wireframe screens, touches, drags, cancels, mouse
events, scroll events, Meta events, and console errors) check these
invariants:

- The analyzer never raises, also on malformed wireframe input and on
  events with a timestamp of zero or less (such actions are dropped).
- Actions come out in timestamp order, and the markdown renders from them.
- No two consecutive screen actions have the same description.
- The screen count never exceeds the per-session cap.
- Screenshot taps and clicks report coordinates only, never a DOM element.
- ``rage_taps`` never raises, reports only ``rage`` or ``dead`` bursts
  within its limits, and ignores DOM recordings.
- A DOM recording (no wireframe, and a Meta ``href`` or no Meta event at
  all) keeps the web behavior: the touch inputs that only screenshot
  recordings use change nothing, and the output matches a small model of
  the web rules.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from mixpanel_headless._internal.replays.rrweb_analyzer import (
    MobileWireframeTracker,
    RrwebAnalyzer,
    _render_markdown,
    detect_capture,
    hit_target_desc,
)
from mixpanel_headless.types import Replay, ReplayBundle

# =============================================================================
# Strategies
# =============================================================================

_timestamps = st.integers(min_value=-5, max_value=20_000)
"""Event timestamps, with some zero or negative values."""

_coordinate = st.one_of(
    st.integers(min_value=-2000, max_value=2000),
    st.floats(allow_nan=True, allow_infinity=True),
    st.none(),
    st.booleans(),
    st.text(max_size=2),
)
"""Raw coordinate values: usable numbers and malformed values."""

_node_ids = st.sampled_from([28, 5, None])
"""rrweb node ids: the screenshot image, another id, and no id."""

_element = st.one_of(
    st.fixed_dictionaries(
        {
            "role": st.one_of(
                st.sampled_from(["text", "button", "input", "switch", " image "]),
                st.integers(),
                st.none(),
            ),
            "text": st.one_of(
                st.sampled_from(["Home", "Details", "A | B", "", "  "]),
                st.text(max_size=60),
                st.none(),
            ),
            "bounds": st.one_of(
                st.lists(_coordinate, min_size=4, max_size=4),
                st.lists(st.integers(-50, 500), min_size=0, max_size=5),
                st.none(),
                st.text(max_size=3),
            ),
        }
    ),
    st.integers(),
    st.none(),
    st.text(max_size=3),
)
"""One wireframe element: mostly well-formed, sometimes malformed."""

_payload = st.one_of(
    st.fixed_dictionaries({"elements": st.lists(_element, max_size=4)}),
    st.fixed_dictionaries(
        {"elements": st.one_of(st.none(), st.text(max_size=3), st.integers())}
    ),
    st.none(),
    st.lists(st.integers(), max_size=2),
    st.text(max_size=3),
)
"""A wireframe payload: mostly well-formed, sometimes the wrong type."""


@st.composite
def _wireframe_event(draw: st.DrawFn) -> dict[str, Any]:
    """Draw one Custom event, usually an ``mp_wireframe`` screen.

    Args:
        draw: Hypothesis draw callable.

    Returns:
        An rrweb Custom event dict.
    """
    return {
        "type": 5,
        "timestamp": draw(_timestamps),
        "data": {
            "tag": draw(st.sampled_from(["mp_wireframe", "mp_wireframe", "other"])),
            "payload": draw(_payload),
        },
    }


@st.composite
def _input_event(draw: st.DrawFn, *, dom_only: bool = False) -> dict[str, Any]:
    """Draw one event that is not a wireframe.

    Args:
        draw: Hypothesis draw callable.
        dom_only: When True, Meta events always carry an ``href`` and no
            Custom event is drawn, so the stream stays a DOM recording.

    Returns:
        An rrweb event dict.
    """
    ts = draw(_timestamps)
    kinds = [
        "touch_start",
        "touch_end",
        "touch_cancel",
        "touch_move",
        "mouse",
        "scroll",
        "meta",
        "console",
    ]
    if dom_only:
        kinds.append("other_custom")
    kind = draw(st.sampled_from(kinds))
    if kind in ("touch_start", "touch_end"):
        data: dict[str, Any] = {
            "source": 2,
            "type": 7 if kind == "touch_start" else 9,
            "id": draw(_node_ids),
            "x": draw(_coordinate),
            "y": draw(_coordinate),
        }
    elif kind == "touch_cancel":
        data = {"source": 2, "type": 10, "id": draw(_node_ids)}
    elif kind == "touch_move":
        positions = draw(
            st.lists(
                st.one_of(
                    st.fixed_dictionaries({"x": _coordinate, "y": _coordinate}),
                    st.none(),
                ),
                max_size=3,
            )
        )
        data = {"source": 6, "positions": positions}
    elif kind == "mouse":
        data = {
            "source": 2,
            "type": draw(st.integers(min_value=0, max_value=5)),
            "id": draw(_node_ids),
            "x": draw(_coordinate),
            "y": draw(_coordinate),
        }
    elif kind == "scroll":
        data = {"source": 3, "id": 1, "x": 0, "y": 0}
    elif kind == "meta":
        if dom_only:
            data = {"href": draw(st.sampled_from(["/a", "/b"])), "width": 1280}
        else:
            href = draw(st.sampled_from([None, "", "/a"]))
            data = {"width": 411} if href is None else {"href": href, "width": 411}
        return {"type": 4, "timestamp": ts, "data": data}
    elif kind == "other_custom":
        return {"type": 5, "timestamp": ts, "data": {"tag": "other", "payload": {}}}
    else:
        data = {
            "plugin": "rrweb/console@1",
            "payload": {"level": "error", "payload": ['"boom"']},
        }
        return {"type": 6, "timestamp": ts, "data": data}
    return {"type": 3, "timestamp": ts, "data": data}


_mixed_streams = st.lists(
    st.one_of(_wireframe_event(), _input_event()), min_size=1, max_size=40
)
"""Random mixed streams of screens and inputs."""


@st.composite
def _dom_streams(draw: st.DrawFn) -> list[dict[str, Any]]:
    """Draw a DOM-recording stream: no wireframe, and Meta events with ``href``.

    Args:
        draw: Hypothesis draw callable.

    Returns:
        A list of rrweb event dicts that :func:`detect_capture` reads as a
        DOM recording.
    """
    return draw(st.lists(_input_event(dom_only=True), min_size=1, max_size=40))


# =============================================================================
# Helpers
# =============================================================================

_SCREENSHOT_POINT_RE = re.compile(r"^(Tapped|Clicked)( at \(-?\d+, -?\d+\))?$")
"""The only forms of a tap or click description in a screenshot recording."""

_SCREENSHOT_TARGET_RE = re.compile(r"^\(-?\d+, -?\d+\)$")
"""The ``target_desc`` form of a tap or click with coordinates."""

_WEB_VERBS = {2: "Clicked", 3: "Right-clicked", 4: "Double-clicked", 5: "Focused"}
"""The web description verb for each DOM mouse interaction type."""


def _without_screenshot_only_inputs(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop the inputs that only screenshot recordings use.

    These are touch end, touch cancel, touch moves, and Custom events.

    Args:
        events: An rrweb event list.

    Returns:
        A new list without those events.
    """
    kept: list[dict[str, Any]] = []
    for event in events:
        data = event["data"]
        if event["type"] == 5:
            continue
        if event["type"] == 3 and data.get("source") == 6:
            continue
        if (
            event["type"] == 3
            and data.get("source") == 2
            and data.get("type") in (9, 10)
        ):
            continue
        kept.append(event)
    return kept


def _web_model(events: list[dict[str, Any]]) -> list[str]:
    """Model the web rules for a DOM stream that has no full snapshot.

    Without a full snapshot every node id describes as ``element``. A
    mouse interaction or touch start with no node id is dropped. Scroll
    events share a 1-second debounce. Other events emit nothing. An action
    with a timestamp of zero or less is dropped, but a dropped scroll still
    moves the debounce.

    Args:
        events: A DOM-recording event list from :func:`_dom_streams`.

    Returns:
        The expected action descriptions, in order.
    """
    out: list[str] = []
    last_scroll = 0
    for event in sorted(events, key=lambda e: int(e["timestamp"])):
        data = event["data"]
        ts = int(event["timestamp"])
        if event["type"] == 3 and data.get("source") == 3:
            if ts - last_scroll > 1000 and ts > 0:
                out.append("Scrolled")
            last_scroll = ts
            continue
        if ts <= 0:
            continue
        if event["type"] == 4 and data.get("href"):
            out.append(f"Navigated to {data['href']}")
        elif event["type"] == 6:
            out.append("Console error: boom")
        elif event["type"] == 3 and data.get("source") == 2:
            if data.get("id") is None:
                continue
            if data.get("type") == 7:
                out.append("Tapped element")
            elif data.get("type") in _WEB_VERBS:
                out.append(f"{_WEB_VERBS[data['type']]} element")
    return out


# =============================================================================
# Properties
# =============================================================================


@given(events=_mixed_streams)
@settings(deadline=None)
def test_analyzer_never_raises_and_actions_are_sorted(
    events: list[dict[str, Any]],
) -> None:
    """The analyzer never raises; actions are sorted; markdown renders from them.

    Args:
        events: A random mixed stream.
    """
    result = RrwebAnalyzer().analyze(events)
    stamps = [a.timestamp for a in result.actions]
    assert stamps == sorted(stamps)
    if result.actions:
        assert result.markdown_summary == _render_markdown(result.actions)
    else:
        assert result.markdown_summary == "No user actions recorded."


@given(events=_mixed_streams)
@settings(deadline=None)
def test_consecutive_screens_differ_and_respect_the_cap(
    events: list[dict[str, Any]],
) -> None:
    """No two consecutive screens are identical, and the screen cap holds.

    Args:
        events: A random mixed stream.
    """
    screens = [
        a for a in RrwebAnalyzer().analyze(events).actions if a.action == "screen"
    ]
    assert len(screens) <= MobileWireframeTracker.MAX_WIREFRAMES
    for earlier, later in zip(screens, screens[1:], strict=False):
        assert earlier.description != later.description
    for screen in screens:
        assert screen.description.startswith("Wireframe: ")
        assert screen.timestamp > 0


@given(events=_mixed_streams, cap=st.integers(min_value=0, max_value=3))
@settings(deadline=None)
def test_lowered_screen_cap_holds(events: list[dict[str, Any]], cap: int) -> None:
    """With a small cap, the screen count never exceeds it.

    Args:
        events: A random mixed stream.
        cap: The lowered per-session screen cap.
    """
    with patch.object(MobileWireframeTracker, "MAX_WIREFRAMES", cap):
        actions = RrwebAnalyzer().analyze(events).actions
    assert sum(1 for a in actions if a.action == "screen") <= cap


@given(events=_mixed_streams)
@settings(deadline=None)
def test_screenshot_taps_and_clicks_report_points_only(
    events: list[dict[str, Any]],
) -> None:
    """In a screenshot recording, taps and clicks never name a DOM element.

    A tap or click targets its hit-test element, its point, or a
    placeholder; the description always shows the point only.

    Args:
        events: A random mixed stream.
    """
    if detect_capture(events) != "screenshot":
        return
    for action in RrwebAnalyzer().analyze(events).actions:
        if action.action in ("touch_start", "click"):
            assert _SCREENSHOT_POINT_RE.match(action.description), action.description
            if "hit" in action.metadata:
                assert action.metadata["attribution"] in ("bounds", "bounds_slop")
                assert action.target_desc == hit_target_desc(action.metadata["hit"])
            else:
                assert "attribution" not in action.metadata
                assert action.target_desc in ("(tap)", "(click)") or (
                    _SCREENSHOT_TARGET_RE.match(action.target_desc)
                )


@given(events=_dom_streams())
@settings(deadline=None)
def test_dom_recording_ignores_screenshot_only_inputs(
    events: list[dict[str, Any]],
) -> None:
    """In a DOM recording, touch end, cancel, drags, and Custom events change nothing.

    Args:
        events: A random DOM-recording stream.
    """
    assert detect_capture(events) == "dom"
    full = RrwebAnalyzer().analyze(events)
    remaining = _without_screenshot_only_inputs(events)
    if not remaining:
        # An empty input list returns the empty result before the walk, so
        # only the action lists compare.
        assert full.actions == []
        return
    reduced = RrwebAnalyzer().analyze(remaining)
    assert full.actions == reduced.actions
    assert full.markdown_summary == reduced.markdown_summary


@given(events=_dom_streams())
@settings(deadline=None)
def test_dom_recording_matches_the_web_model(events: list[dict[str, Any]]) -> None:
    """A DOM recording without wireframes keeps the web rules of the analyzer.

    Args:
        events: A random DOM-recording stream.
    """
    result = RrwebAnalyzer().analyze(events)
    assert [a.description for a in result.actions] == _web_model(events)
    assert not any(a.action == "screen" for a in result.actions)


@given(events=st.lists(_input_event(dom_only=True), max_size=20))
@settings(deadline=None)
def test_stream_without_meta_is_dom(events: list[dict[str, Any]]) -> None:
    """A stream with no Meta event and no wireframe is always a DOM recording.

    Args:
        events: A random stream; its Meta events are removed.
    """
    no_meta = [e for e in events if e["type"] != 4]
    assert detect_capture(no_meta) == "dom"


@given(
    events=_mixed_streams,
    threshold=st.integers(min_value=1, max_value=4),
    window_ms=st.integers(min_value=0, max_value=3000),
)
@settings(deadline=None)
def test_rage_taps_never_raises_and_respects_its_limits(
    events: list[dict[str, Any]], threshold: int, window_ms: int
) -> None:
    """``rage_taps`` never raises, and each row respects the burst limits.

    Args:
        events: A random mixed stream.
        threshold: The minimum finger-downs per burst.
        window_ms: The maximum burst span.
    """
    stamps = [e["timestamp"] for e in events if e["timestamp"] > 0] or [1]
    replay = Replay(
        replay_id="r",
        distinct_id=None,
        project_id=1,
        start_time=min(stamps),
        end_time=max(stamps),
        retention_days=30,
        rrweb_events=events,
        actions=RrwebAnalyzer().analyze(events).actions,
    )
    bundle = ReplayBundle(replays=[replay], computed_at="now", project_id=1)
    df = bundle.rage_taps(threshold=threshold, window_ms=window_ms)
    for row in df.to_dict("records"):
        assert row["kind"] in ("rage", "dead")
        assert int(row["count"]) >= threshold
        assert 0 <= int(row["t_end"]) - int(row["t_start"]) <= window_ms
    if replay.capture == "dom":
        assert df.empty
