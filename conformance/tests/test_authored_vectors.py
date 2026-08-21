"""Structural guards over the PR-7 authored corpus (design D13/D4.3/D3.1).

The authored bundles are hand-written data, outside the record plugin's
emit-time schema self-validation — so this suite re-applies the same
guarantees the extracted corpus gets for free: every authored vector
validates against ``conformance/schema/vector.schema.json``, carries
``origin: "authored"`` with a capability-prefixed id, and the D13/D4.3
seed surfaces (compat cases, wire-path gate features, the nine uncovered
validation codes) are actually present. The ``bookmark_enums`` snapshot
(design D4.2 item 10) is drift-guarded against the live module here, and
regenerated only by explicitly running
``python -m conformance.record.enums_snapshot --write`` (design D8's
"explicit flag").
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

_CONFORMANCE_ROOT = Path(__file__).resolve().parents[1]
_AUTHORED_ROOT = _CONFORMANCE_ROOT / "vectors" / "authored"
_SCHEMA_PATH = _CONFORMANCE_ROOT / "schema" / "vector.schema.json"

_UNCOVERED_CODES = (
    "B8_MISSING_EVENT_NAME",
    "B11_INVALID_PER_USER",
    "B13_INVALID_DATE_RANGE_TYPE",
    "B19_INVALID_FILTERS_DETERMINER",
    "B20B_FILTER_VALUE_NOT_FINITE",
    "V16_FORMULA_SYNTAX",
    "V21_INVALID_EVENT_TYPE",
    "V23_ROLLING_TOO_LARGE",
    "U25",
)
"""The nine validation codes with no extracted coverage (design D4.3)."""


@cache
def _load_authored() -> tuple[tuple[str, dict[str, Any]], ...]:
    """Load every authored vector as ``(bundle-relative-path, body)`` pairs.

    Returns:
        One pair per vector line across all authored bundles, ``$bundle``
        headers skipped.

    Raises:
        AssertionError: If the authored tree is missing (PR-7 output must
            be committed alongside this test).
    """
    assert _AUTHORED_ROOT.is_dir(), f"missing authored corpus at {_AUTHORED_ROOT}"
    loaded: list[tuple[str, dict[str, Any]]] = []
    for bundle in sorted(_AUTHORED_ROOT.rglob("*.jsonl")):
        rel = str(bundle.relative_to(_AUTHORED_ROOT))
        for line in bundle.read_text(encoding="utf-8").splitlines():
            obj = json.loads(line)
            if "$bundle" in obj:
                continue
            loaded.append((rel, obj))
    return tuple(loaded)


@cache
def _schema_validator() -> Draft202012Validator:
    """Build the vector-schema validator once per session.

    Returns:
        A draft-2020-12 validator over the committed vector schema.
    """
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def test_authored_bundles_exist_per_design_d18() -> None:
    """Every PR-7 bundle from the design D18 task list is present.

    Raises:
        AssertionError: If a mandated authored bundle is missing.
    """
    expected = {
        "compat/pythoncompat.jsonl",
        "compat/wirestub.jsonl",
        "validation/uncovered-codes.jsonl",
        "parse/phase008.jsonl",
        "replays/rrweb-seed.jsonl",
        "streaming/jsonl-chunks.jsonl",
        "bookmarks/date-builders.jsonl",
    }
    present = {
        str(path.relative_to(_AUTHORED_ROOT))
        for path in _AUTHORED_ROOT.rglob("*.jsonl")
    }
    assert expected <= present, sorted(expected - present)


def test_every_authored_vector_is_schema_valid() -> None:
    """All authored vectors validate against the vector schema (design D3).

    Raises:
        AssertionError: With every schema violation found, if any.
    """
    validator = _schema_validator()
    violations: list[str] = []
    for rel, body in _load_authored():
        for error in validator.iter_errors(body):
            violations.append(f"{rel} {body.get('id')}: {error.message}")
    assert violations == [], "\n".join(violations)


def test_every_authored_vector_carries_authored_origin_and_prefixed_id() -> None:
    """Authored vectors are marked ``origin: authored`` with matching ids.

    The id's leading segment must equal the vector's ``capability`` for
    ``compat``/``validation``/``parse``-style bundles (design D3 id rule),
    and ``source_test`` must be absent (schema: extracted-only field).

    Raises:
        AssertionError: On any origin/id/source_test violation.
    """
    bad: list[str] = []
    for rel, body in _load_authored():
        vector_id = str(body.get("id"))
        if body.get("origin") != "authored":
            bad.append(f"{rel} {vector_id}: origin != authored")
        if "source_test" in body:
            bad.append(f"{rel} {vector_id}: authored vector carries source_test")
        if not vector_id.startswith(f"{body.get('capability')}/"):
            bad.append(f"{rel} {vector_id}: id not prefixed by capability")
    assert bad == [], "\n".join(bad)


def test_compat_bundle_covers_the_d13_case_list() -> None:
    """The pythoncompat bundle covers the design D13 mandated cases.

    Spot-checks the named traps: ``zfill("-1", 3)``, the non-BMP zfill
    case, ``python_str(True/None)``, and the float exponent window
    (``1e16`` / ``1e-4`` / ``1e-5``) plus negative zero.

    Raises:
        AssertionError: If a mandated case is missing or wrong.
    """
    by_id = {
        body["id"]: body
        for rel, body in _load_authored()
        if rel == "compat/pythoncompat.jsonl"
    }
    zfill = by_id["compat/compat.zfill/authored-neg-one-width-3"]
    assert zfill["call"]["input"] == {"value": "-1", "width": 3}
    assert zfill["expect"]["output"] == "-01"
    non_bmp = by_id["compat/compat.zfill/authored-non-bmp"]
    assert non_bmp["call"]["input"]["value"] == "\U0001f600"
    assert by_id["compat/compat.python_str/authored-true"]["expect"]["output"] == "True"
    assert by_id["compat/compat.python_str/authored-none"]["expect"]["output"] == "None"
    floats = {
        "authored-exponent-1e16": "1e+16",
        "authored-exponent-1e-4": "0.0001",
        "authored-exponent-1e-5": "1e-05",
        "authored-negative-zero": "-0.0",
    }
    for slug, expected in floats.items():
        vector = by_id[f"compat/compat.python_float_str/{slug}"]
        assert vector["expect"]["output"] == expected, slug


def test_wirestub_bundle_covers_the_d13_wire_path_features() -> None:
    """The wire-stub gate bundle exercises every D13 wire-path feature.

    Raises:
        AssertionError: If a mandated replay feature has no vector.
    """
    vectors = [body for rel, body in _load_authored() if rel == "compat/wirestub.jsonl"]
    assert len(vectors) >= 8

    def interactions(body: dict[str, Any]) -> list[dict[str, Any]]:
        """Return a vector's recorded interactions.

        Args:
            body: The vector object.

        Returns:
            The ``expect.interactions`` list.
        """
        result: list[dict[str, Any]] = body["expect"]["interactions"]
        return result

    assert any(len(interactions(v)) == 1 for v in vectors)
    assert any(len(interactions(v)) > 1 for v in vectors)
    assert any(
        "transport_error" in i["response"] for v in vectors for i in interactions(v)
    )
    assert any("body_stream" in i["response"] for v in vectors for i in interactions(v))
    assert any(
        isinstance(i["request"].get("headers_contain", {}).get("authorization"), dict)
        for v in vectors
        for i in interactions(v)
    )
    assert any(
        i["request"].get("params_absent") for v in vectors for i in interactions(v)
    )
    grouped = [
        v
        for v in vectors
        if sum(1 for i in interactions(v) if i.get("unordered_group") == 1) == 2
    ]
    assert grouped, "no 2-member unordered_group vector"


@pytest.mark.parametrize("code", _UNCOVERED_CODES)
def test_each_uncovered_validation_code_has_a_seed_vector(code: str) -> None:
    """Every design D4.3 uncovered code appears in an authored expectation.

    Args:
        code: The validation code under test.

    Raises:
        AssertionError: If no authored vector expects the code.
    """
    for rel, body in _load_authored():
        if rel != "validation/uncovered-codes.jsonl":
            continue
        output = body["expect"].get("output") or []
        if any(error.get("code") == code for error in output):
            return
    pytest.fail(f"no authored seed vector expects {code}")


def test_enums_snapshot_matches_live_module() -> None:
    """The committed bookmark_enums snapshot matches the live constants.

    Regeneration is an explicit act (design D8):
    ``uv run python -m conformance.record.enums_snapshot --write``.

    Raises:
        AssertionError: If the file is missing or stale.
    """
    from conformance.record.enums_snapshot import SNAPSHOT_PATH, render_snapshot

    assert SNAPSHOT_PATH.is_file(), (
        "missing enums snapshot — run "
        "`uv run python -m conformance.record.enums_snapshot --write`"
    )
    assert SNAPSHOT_PATH.read_text(encoding="utf-8") == render_snapshot(), (
        "bookmark_enums snapshot is stale — regenerate explicitly with "
        "`uv run python -m conformance.record.enums_snapshot --write`"
    )


def test_enums_snapshot_serializes_frozensets_sorted() -> None:
    """Frozenset constants serialize as sorted arrays (design D4.2 item 10).

    Raises:
        AssertionError: If any array constant is unsorted or the snapshot
            misses the known headline constants.
    """
    from conformance.record.enums_snapshot import build_snapshot

    snapshot = build_snapshot()
    constants = snapshot["constants"]
    assert "VALID_MATH_TYPES" in constants
    assert "MAX_CONVERSION_WINDOW" in constants
    for name, value in constants.items():
        if isinstance(value, list):
            assert value == sorted(value), f"{name} not sorted"
