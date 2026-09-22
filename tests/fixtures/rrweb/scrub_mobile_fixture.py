"""Scrub a raw mobile session replay into a small, committable rrweb fixture.

Mobile session replays hold one base64 JPEG screenshot per screen change.
These screenshots make up most of the file size, and they can show real
screen content. This dev tool replaces every ``data:image/...`` string with
a short placeholder. It can also trim the stream to a time window, and it
keeps the context events that a trimmed stream needs to stay valid.

The tool uses the standard library only. Run it from the repository root:

```bash
python tests/fixtures/rrweb/scrub_mobile_fixture.py RAW.json OUT.json
python tests/fixtures/rrweb/scrub_mobile_fixture.py RAW.json OUT.json \\
    --start-ms 1789663310000 --end-ms 1789663330000
```

The input is either a JSON list of rrweb events or a JSON object with an
``rrweb_events`` list (the shape of a saved ``Replay``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: Value that replaces every inline image in the output.
IMAGE_PLACEHOLDER = "data:image/jpeg;base64,REDACTED"

#: Largest output size, in bytes, that still gets indented JSON.
INDENT_LIMIT_BYTES = 200 * 1024

#: rrweb event type codes that the trim step keeps as context.
_FULL_SNAPSHOT = 2
_META = 4
_CUSTOM = 5

#: Custom event tag that the mobile SDKs use for screen wireframes.
_WIREFRAME_TAG = "mp_wireframe"


def redact_images(value: Any) -> Any:
    """Return a deep copy of ``value`` with every inline image replaced.

    A string that starts with ``data:image/`` becomes
    :data:`IMAGE_PLACEHOLDER`. All other values are copied unchanged.

    Args:
        value: Any JSON-compatible value (dict, list, str, number, bool,
            or None).

    Returns:
        A new value with the same shape as ``value``.

    Example:
        ```python
        redact_images({"src": "data:image/jpeg;base64,/9j/4AAQ"})
        # {"src": "data:image/jpeg;base64,REDACTED"}
        ```
    """
    if isinstance(value, str):
        return IMAGE_PLACEHOLDER if value.startswith("data:image/") else value
    if isinstance(value, list):
        return [redact_images(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_images(item) for key, item in value.items()}
    return value


def _is_wireframe(event: dict[str, Any]) -> bool:
    """Tell if an rrweb event is a mobile ``mp_wireframe`` Custom event.

    Args:
        event: One rrweb event.

    Returns:
        True when the event is type 5 with the tag ``mp_wireframe``.
    """
    data = event.get("data")
    return (
        event.get("type") == _CUSTOM
        and isinstance(data, dict)
        and data.get("tag") == _WIREFRAME_TAG
    )


def _timestamp(event: dict[str, Any]) -> int:
    """Return the timestamp of an rrweb event, or 0 when it has none.

    Args:
        event: One rrweb event.

    Returns:
        The integer ``timestamp`` value, or 0 when the key is missing or
        not a number.
    """
    value = event.get("timestamp")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def trim_window(
    events: list[dict[str, Any]], start_ms: int, end_ms: int
) -> list[dict[str, Any]]:
    """Keep the events in ``[start_ms, end_ms]`` plus their context events.

    The trimmed stream stays self-consistent. Before the window, the
    function keeps these events:

    - the first Meta event (type 4);
    - the most recent Meta event before ``start_ms``;
    - the most recent FullSnapshot (type 2) before ``start_ms``;
    - the most recent ``mp_wireframe`` event before ``start_ms``.

    The output keeps the input order. The function does not change the
    events.

    Args:
        events: rrweb events, in timestamp order.
        start_ms: First timestamp to keep (inclusive, Unix ms).
        end_ms: Last timestamp to keep (inclusive, Unix ms).

    Returns:
        A new list with the kept events.

    Raises:
        ValueError: If ``start_ms`` is greater than ``end_ms``.

    Example:
        ```python
        kept = trim_window(events, 1789663310000, 1789663330000)
        ```
    """
    if start_ms > end_ms:
        raise ValueError(f"start_ms ({start_ms}) is after end_ms ({end_ms})")
    keep: set[int] = set()
    first_meta: int | None = None
    last_meta: int | None = None
    last_snapshot: int | None = None
    last_wireframe: int | None = None
    for index, event in enumerate(events):
        ts = _timestamp(event)
        if start_ms <= ts <= end_ms:
            keep.add(index)
        if event.get("type") == _META and first_meta is None:
            first_meta = index
        if ts >= start_ms:
            continue
        if event.get("type") == _META:
            last_meta = index
        elif event.get("type") == _FULL_SNAPSHOT:
            last_snapshot = index
        elif _is_wireframe(event):
            last_wireframe = index
    for context in (first_meta, last_meta, last_snapshot, last_wireframe):
        if context is not None:
            keep.add(context)
    return [event for index, event in enumerate(events) if index in keep]


def dump_fixture(events: list[dict[str, Any]]) -> str:
    """Serialize events as stable JSON text for a committed fixture.

    The function uses ``indent=1`` when the result is at most
    :data:`INDENT_LIMIT_BYTES`, so that diffs are easy to review. It uses
    compact separators when the indented text is too large. Key order
    follows the input. The text ends with a newline.

    Args:
        events: rrweb events to write.

    Returns:
        The JSON text.
    """
    text = json.dumps(events, indent=1, ensure_ascii=False)
    if len(text.encode("utf-8")) > INDENT_LIMIT_BYTES:
        text = json.dumps(
            events, indent=None, separators=(",", ":"), ensure_ascii=False
        )
    return text + "\n"


def load_events(path: Path) -> list[dict[str, Any]]:
    """Read rrweb events from a raw replay file.

    Args:
        path: A JSON file that holds a list of events, or an object with an
            ``rrweb_events`` list.

    Returns:
        The list of events.

    Raises:
        ValueError: If the file holds no event list.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("rrweb_events")
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of rrweb events")
    return [event for event in raw if isinstance(event, dict)]


def scrub(
    events: list[dict[str, Any]],
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Trim (optional) and redact a list of rrweb events.

    Args:
        events: rrweb events, in timestamp order.
        start_ms: First timestamp to keep, or None for no lower bound.
        end_ms: Last timestamp to keep, or None for no upper bound.

    Returns:
        A new list of events with every inline image replaced.

    Raises:
        ValueError: If ``start_ms`` is greater than ``end_ms``.
    """
    if start_ms is not None or end_ms is not None:
        low = start_ms if start_ms is not None else -sys.maxsize
        high = end_ms if end_ms is not None else sys.maxsize
        events = trim_window(events, low, high)
    redacted: list[dict[str, Any]] = redact_images(events)
    return redacted


def main(argv: list[str] | None = None) -> int:
    """Run the command line tool.

    Args:
        argv: Command line arguments without the program name, or None to
            read ``sys.argv``.

    Returns:
        The process exit code (0 on success).

    Raises:
        ValueError: If the input holds no event list, or if the window
            is reversed.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="raw replay JSON file")
    parser.add_argument("dest", type=Path, help="fixture file to write")
    parser.add_argument("--start-ms", type=int, default=None)
    parser.add_argument("--end-ms", type=int, default=None)
    args = parser.parse_args(argv)
    events = scrub(load_events(args.source), args.start_ms, args.end_ms)
    text = dump_fixture(events)
    args.dest.write_text(text, encoding="utf-8")
    size_kb = len(text.encode("utf-8")) / 1024
    print(f"{args.dest}: {len(events)} events, {size_kb:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
