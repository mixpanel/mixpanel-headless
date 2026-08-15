"""Payload-handoff producer for the D15b referee (task PR-11).

Builds the ``{"id", "bookmark_type", "params"}`` JSONL that
``harness.py`` consumes, by RE-EXECUTING every bookmark-capability
builder vector live under the replay clock — the handoff carries genuine
Python-built payloads, never stale recordings. Each live output is
cross-checked against the vector's recorded expectation (canonical-form
equality, design D6); any drift aborts the run, because a handoff that
disagrees with the committed corpus proves nothing.

Runs in the REPO environment (needs ``mixpanel_headless`` + dev extras,
unlike ``harness.py`` which runs in the recipe environments):

    ```bash
    uv run python -m conformance.referee_bookmark_parser.handoff \
        --vectors conformance/vectors \
        --out conformance/referee_bookmark_parser/handoff.jsonl
    ```
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from conformance.record.clock import RecordClock
from conformance.record.codecs import decode_input_kwargs
from conformance.record.registry import KIND_BUILDER, REGISTRY_BY_API
from conformance.referee_bookmark_parser.harness import (
    HANDOFF_ROUTES,
    wrap_payload,
)
from conformance.runner.canonical import canonicalize
from conformance.runner.execute import (
    _encode_result,
    _isolated_home,
    _resolve_builder_target,
)
from conformance.runner.loading import CorpusLoadError, load_vectors


class HandoffError(Exception):
    """Raised when the handoff cannot be produced faithfully.

    Covers corpus load failures, builder crashes at re-execution, and
    live-output drift from the recorded expectation — all infrastructure
    conditions, never referee verdicts.
    """


def _execute_builder(body: Mapping[str, Any]) -> object:
    """Re-execute one builder vector live and return its encoded output.

    Mirrors the corpus runner's builder path (registry resolution, input
    decoding, facade construction, output encoding) without the diffing —
    the caller cross-checks canonical equality itself.

    Args:
        body: The full vector object.

    Returns:
        The canonical-JSON-encoded live output.

    Raises:
        HandoffError: If the API is not a registered builder or the
            builder raises at re-execution.
    """
    call: Mapping[str, Any] = body["call"]
    api = str(call["api"])
    entry = REGISTRY_BY_API.get(api)
    if entry is None or entry.kind != KIND_BUILDER:
        raise HandoffError(f"api {api!r} is not a registered builder entry")
    decoded = decode_input_kwargs(call.get("input") or {})
    target = _resolve_builder_target(entry, decoded)
    try:
        raw = target(**decoded)
    except Exception as exc:
        raise HandoffError(
            f"builder {api!r} raised at re-execution: {type(exc).__name__}: {exc}"
        ) from exc
    return _encode_result(entry, raw)


def produce_handoff(vectors_root: Path) -> list[dict[str, object]]:
    """Produce the referee handoff entries from the committed corpus.

    Selects every ``kind == "builder"`` vector whose API is in
    :data:`conformance.referee_bookmark_parser.harness.HANDOFF_ROUTES`
    (the six bookmark-payload builders across the bookmarks / funnels /
    retention / flows capabilities), re-executes each live under the
    frozen replay clock, verifies the output still matches the recording,
    and wraps fragments per the D15b routing rules.

    Args:
        vectors_root: The corpus root (``conformance/vectors``).

    Returns:
        Handoff entries sorted by vector id, each exactly
        ``{"id", "bookmark_type", "params"}``.

    Raises:
        HandoffError: On corpus load failure, empty selection, builder
            crash, or live-vs-recorded output drift.
    """
    try:
        vectors = load_vectors(vectors_root)
    except CorpusLoadError as exc:
        raise HandoffError(f"corpus load failed: {exc}") from exc
    selected = [
        vector
        for vector in vectors
        if vector.kind == "builder"
        and str(vector.body.get("call", {}).get("api", "")) in HANDOFF_ROUTES
    ]
    if not selected:
        raise HandoffError(
            f"no bookmark-capability builder vectors found under {vectors_root}"
        )
    entries: list[dict[str, object]] = []
    clock = RecordClock()
    clock.start()
    try:
        for vector in selected:
            clock.reset_test_state()
            with _isolated_home():
                output = _execute_builder(vector.body)
            expected = vector.body.get("expect", {}).get("output")
            if canonicalize(output) != canonicalize(expected):
                raise HandoffError(
                    f"live output drift for {vector.id}: re-executed builder "
                    "output no longer matches the recorded expectation — "
                    "re-extract the corpus before producing a handoff"
                )
            api = str(vector.body["call"]["api"])
            bookmark_type, params = wrap_payload(api, output)
            entries.append(
                {"id": vector.id, "bookmark_type": bookmark_type, "params": params}
            )
    finally:
        clock.stop()
    return sorted(entries, key=lambda entry: str(entry["id"]))


def main(argv: list[str] | None = None) -> int:
    """Write the handoff JSONL (CLI entry point).

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        ``0`` on success; ``2`` on any :class:`HandoffError` (mirrors the
        D9.3 crash convention — there is no partial handoff).
    """
    parser = argparse.ArgumentParser(
        prog="python -m conformance.referee_bookmark_parser.handoff",
        description="Produce the D15b referee payload-handoff JSONL.",
    )
    parser.add_argument(
        "--vectors",
        required=True,
        type=Path,
        help="Corpus root directory (conformance/vectors).",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output handoff JSONL path.",
    )
    args = parser.parse_args(argv)
    try:
        entries = produce_handoff(args.vectors)
    except HandoffError as exc:
        print(f"[referee.handoff] ERROR: {exc}", file=sys.stderr)
        return 2
    lines = [json.dumps(entry, ensure_ascii=True, sort_keys=True) for entry in entries]
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[referee.handoff] wrote {len(entries)} entries to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
