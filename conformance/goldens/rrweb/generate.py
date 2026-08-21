"""Freeze rrweb-analyzer goldens for the TypeScript port's Layer-3 suite.

Runs the Python analyzer (``RrwebAnalyzer.analyze`` + ``analyze_events``)
over every fixture in ``tests/fixtures/rrweb/`` plus the synthetic
streams defined below, and writes one JSON golden per fixture into this
directory. The TS suite
(``packages/core/test/replays/rrweb-analyzer.golden.test.ts`` in the
mixpanel-headless-ts repo) asserts deep equality against the SAME files,
so a behavioural drift on either side turns red.

Regeneration
------------

    uv run python conformance/goldens/rrweb/generate.py

Then copy the outputs into the TS repo:

    cp conformance/goldens/rrweb/*.golden.json \\
       ../mixpanel-headless-ts/packages/core/test/replays/goldens/

Both copies are committed (Phase-3 plan §Layer-3,
``context/typescript-port-plan.md:351-354``; the TS-2 pinned-table
precedent for two-repo generated artifacts).

The frozen shape per fixture is
``{actions[], markdown, page_visits, console_errors}`` — every public
field of :class:`AnalyzerResult`, with ``UserAction`` projected through
its ``to_dict()`` codec so the comparison is byte-level.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mixpanel_headless._internal.replays.rrweb_analyzer import (
    RrwebAnalyzer,
    analyze_events,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "rrweb"
_OUT_DIR = Path(__file__).resolve().parent


def _synthetic_streams() -> dict[str, list[dict[str, Any]]]:
    """Build the synthetic fixtures that widen coverage past the sample.

    The sample replay exercises navigate / input / click / scroll. These
    add the branches a real recording rarely contains in one stream:
    console-plugin errors, text selection, mutation adds / removes /
    text / attribute changes, the ancestor-description fallback, and the
    duplicate-run collapse in the markdown reporter.

    Returns:
        A ``{fixture_name: events}`` mapping. Each value is a raw rrweb
        event list suitable for :meth:`RrwebAnalyzer.analyze`.
    """
    root = {
        "id": 1,
        "type": 0,
        "childNodes": [
            {
                "id": 2,
                "type": 2,
                "tagName": "html",
                "attributes": {"lang": "en"},
                "childNodes": [
                    {
                        "id": 3,
                        "type": 2,
                        "tagName": "body",
                        "attributes": {},
                        "childNodes": [
                            {
                                "id": 10,
                                "type": 2,
                                "tagName": "p",
                                "attributes": {},
                                "childNodes": [
                                    {
                                        "id": 11,
                                        "type": 3,
                                        "textContent": "hello 𝒳 world",
                                    }
                                ],
                            },
                            {
                                "id": 20,
                                "type": 2,
                                "tagName": "button",
                                "attributes": {
                                    "id": "go",
                                    "data-testid": "go-button",
                                },
                                "childNodes": [
                                    {"id": 21, "type": 3, "textContent": "Go"},
                                    {
                                        "id": 22,
                                        "type": 2,
                                        "tagName": "span",
                                        "attributes": {},
                                        "childNodes": [],
                                    },
                                ],
                            },
                            {
                                "id": 30,
                                "type": 2,
                                "tagName": "a",
                                "attributes": {"href": "https://x.test/docs/intro"},
                                "childNodes": [
                                    {"id": 31, "type": 3, "textContent": "Docs"}
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
    }
    return {
        "synthetic-mixed-001": [
            {
                "type": 4,
                "data": {"href": "https://x.test/users/12345/p?ref=a"},
                "timestamp": 1_700_000_000_000,
            },
            {
                "type": 2,
                "data": {"node": root, "initialOffset": {"left": 0, "top": 0}},
                "timestamp": 1_700_000_000_100,
            },
            # Selection over a non-BMP-bearing text node (code-point slice).
            {
                "type": 3,
                "data": {
                    "source": 14,
                    "ranges": [
                        {"start": 11, "end": 11, "startOffset": 6, "endOffset": 7}
                    ],
                },
                "timestamp": 1_700_000_001_000,
            },
            # Click on the span → ancestor-context description fallback.
            {
                "type": 3,
                "data": {"source": 2, "type": 2, "id": 22},
                "timestamp": 1_700_000_002_000,
            },
            # Three identical clicks → the markdown (×N) run collapse.
            {
                "type": 3,
                "data": {"source": 2, "type": 2, "id": 20},
                "timestamp": 1_700_000_003_000,
            },
            {
                "type": 3,
                "data": {"source": 2, "type": 2, "id": 20},
                "timestamp": 1_700_000_003_100,
            },
            {
                "type": 3,
                "data": {"source": 2, "type": 2, "id": 20},
                "timestamp": 1_700_000_003_200,
            },
            # Anchor with an http href → "to /docs/intro".
            {
                "type": 3,
                "data": {"source": 2, "type": 4, "id": 30},
                "timestamp": 1_700_000_004_000,
            },
            # Mutation: attribute change, text change, add, remove.
            {
                "type": 3,
                "data": {
                    "source": 0,
                    "attributes": [
                        {"id": 30, "attributes": {"aria-label": "Read the docs"}}
                    ],
                    "texts": [{"id": 21, "value": "Go now"}],
                    "adds": [
                        {
                            "parentId": 3,
                            "node": {
                                "id": 40,
                                "type": 2,
                                "tagName": "input",
                                "attributes": {"type": "checkbox", "id": "agree"},
                                "childNodes": [],
                            },
                        }
                    ],
                    "removes": [{"id": 10}],
                },
                "timestamp": 1_700_000_005_000,
            },
            {
                "type": 3,
                "data": {"source": 5, "id": 40, "isChecked": True},
                "timestamp": 1_700_000_006_000,
            },
            {
                "type": 3,
                "data": {"source": 3, "id": 1, "x": 0, "y": 120},
                "timestamp": 1_700_000_007_000,
            },
            {
                "type": 6,
                "data": {
                    "plugin": "rrweb/console@1",
                    "payload": {
                        "level": "error",
                        "payload": ['"TypeError: 𝒳 is not a function"'],
                    },
                },
                "timestamp": 1_700_000_008_000,
            },
            # Non-error plugin + unknown interaction type: both no-ops.
            {
                "type": 6,
                "data": {
                    "plugin": "rrweb/console@1",
                    "payload": {"level": "warn", "payload": ['"deprecated"']},
                },
                "timestamp": 1_700_000_009_000,
            },
            {
                "type": 3,
                "data": {"source": 2, "type": 99, "id": 20},
                "timestamp": 1_700_000_010_000,
            },
        ],
    }


def _freeze(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the analyzer over ``events`` and project the frozen shape.

    Args:
        events: Raw rrweb event dicts.

    Returns:
        A JSON-serializable dict with ``actions`` (each via
        ``UserAction.to_dict()``), ``markdown``, ``page_visits``, and
        ``console_errors``. ``markdown`` is also cross-checked against
        :func:`analyze_events`, which must agree exactly.
    """
    result = RrwebAnalyzer().analyze(events)
    if events:
        wrapper_markdown = analyze_events(events)
        if wrapper_markdown != result.markdown_summary:  # pragma: no cover
            raise AssertionError(
                "analyze_events() and RrwebAnalyzer().analyze() disagree"
            )
    return {
        "actions": [a.to_dict() for a in result.actions],
        "markdown": result.markdown_summary,
        "page_visits": [asdict(p) for p in result.pages],
        "console_errors": [asdict(e) for e in result.errors],
    }


def main() -> None:
    """Regenerate every golden file in this directory.

    Reads each ``*.json`` fixture under ``tests/fixtures/rrweb/`` plus
    the synthetic streams, freezes the analyzer output, and writes
    ``{name}.golden.json`` with sorted keys and a trailing newline.

    Returns:
        None. Files are written in place.
    """
    streams: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(_FIXTURE_DIR.glob("*.json")):
        with path.open() as handle:
            streams[path.stem] = json.load(handle)
    streams.update(_synthetic_streams())
    streams["empty-stream"] = []

    for name, events in sorted(streams.items()):
        out_path = _OUT_DIR / f"{name}.golden.json"
        payload = _freeze(events)
        with out_path.open("w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"wrote {out_path.relative_to(_REPO_ROOT)}")

    # The synthetic INPUT streams are generated too, so the TS suite
    # feeds byte-identical events rather than a hand-retyped twin.
    for name, events in sorted(_synthetic_streams().items()):
        in_path = _OUT_DIR / f"{name}.input.json"
        with in_path.open("w") as handle:
            json.dump(events, handle, indent=2)
            handle.write("\n")
        print(f"wrote {in_path.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
