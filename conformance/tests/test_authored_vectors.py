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


def _mobile_replay_vectors() -> list[dict[str, Any]]:
    """Build the authored mobile replay vectors in memory.

    Returns:
        The vector objects that ``gen_replay_mobile_vectors`` writes.
    """
    from conformance.record.gen_replay_mobile_vectors import build_vectors

    return build_vectors()


def test_mobile_replay_vectors_are_schema_valid_and_authored() -> None:
    """Every generated mobile replay vector passes the authored-vector rules.

    The bundle is written only after the library change is on main (its
    stamp must be a main SHA), so this test checks the vectors before
    they are committed.

    Raises:
        AssertionError: On a schema, origin, id, or capability violation.
    """
    validator = _schema_validator()
    bad: list[str] = []
    ids: set[str] = set()
    for body in _mobile_replay_vectors():
        vector_id = str(body["id"])
        bad.extend(f"{vector_id}: {e.message}" for e in validator.iter_errors(body))
        if body["origin"] != "authored" or body["capability"] != "replays":
            bad.append(f"{vector_id}: wrong origin or capability")
        if not vector_id.startswith("replays/"):
            bad.append(f"{vector_id}: id not prefixed by capability")
        if vector_id in ids:
            bad.append(f"{vector_id}: duplicate id")
        ids.add(vector_id)
    assert bad == [], "\n".join(bad)


def test_mobile_replay_vectors_cover_every_member() -> None:
    """The generated vectors cover all four mobile replay members.

    Raises:
        AssertionError: If an api has no vector, or ``rage_taps`` lacks a
            ``dead`` row, a ``rage`` row, or an empty result.
    """
    by_api: dict[str, list[Any]] = {}
    for body in _mobile_replay_vectors():
        by_api.setdefault(body["call"]["api"], []).append(body["expect"]["output"])
    assert set(by_api) == {
        "replay.capture",
        "replay.has_wireframes",
        "replay.screen_path",
        "replay_bundle.rage_taps",
    }
    kinds = {row["kind"] for rows in by_api["replay_bundle.rage_taps"] for row in rows}
    assert kinds == {"dead", "rage"}
    assert [] in by_api["replay_bundle.rage_taps"]
    assert set(by_api["replay.capture"]) == {"dom", "screenshot"}


def test_mobile_replay_vectors_replay_clean_through_the_runner() -> None:
    """Each generated vector passes the corpus runner against the registry.

    Raises:
        AssertionError: With the failure reasons of any vector that fails.
    """
    from conformance.record.clock import RecordClock
    from conformance.runner.execute import run_vector
    from conformance.runner.loading import LoadedVector

    failures: list[str] = []
    clock = RecordClock()
    clock.start()
    try:
        for body in _mobile_replay_vectors():
            clock.reset_test_state()
            outcome = run_vector(
                LoadedVector(
                    id=str(body["id"]),
                    kind=str(body["kind"]),
                    body=body,
                    bundle=Path("authored/replays/rrweb-mobile.jsonl"),
                )
            )
            if not outcome.passed:
                failures.extend([str(body["id"]), *outcome.reasons])
    finally:
        clock.stop()
    assert failures == [], "\n".join(failures)


def test_mobile_replay_bundle_matches_generator_when_present() -> None:
    """A committed mobile replay bundle equals a fresh generator run.

    The bundle does not exist until the library change is on main. After
    that, a change in analyzer behavior without a regenerated bundle fails
    here.

    Raises:
        AssertionError: If the committed bundle differs from the generator
            output under its own stamp.
    """
    from conformance.record.gen_replay_mobile_vectors import OUT_PATH, render_bundle

    if not OUT_PATH.exists():
        pytest.skip("mobile replay bundle is written after the merge to main")
    text = OUT_PATH.read_text(encoding="utf-8")
    header = json.loads(text.splitlines()[0])["$bundle"]
    assert text == render_bundle(str(header["source_commit"]))


def _analyze_mobile_vectors() -> list[dict[str, Any]]:
    """Build the authored mobile analyzer vectors in memory.

    Returns:
        The vector objects that ``gen_replay_analyze_vectors`` writes.
    """
    from conformance.record.gen_replay_analyze_vectors import build_vectors

    return build_vectors()


def test_analyze_mobile_vectors_are_schema_valid_and_authored() -> None:
    """Every generated mobile analyzer vector passes the authored-vector rules.

    Raises:
        AssertionError: On a schema, origin, id, or capability violation.
    """
    validator = _schema_validator()
    bad: list[str] = []
    ids: set[str] = set()
    for body in _analyze_mobile_vectors():
        vector_id = str(body["id"])
        bad.extend(f"{vector_id}: {e.message}" for e in validator.iter_errors(body))
        if body["origin"] != "authored" or body["capability"] != "replays":
            bad.append(f"{vector_id}: wrong origin or capability")
        if not vector_id.startswith("replays/rrweb_analyzer.analyze/authored-mobile-"):
            bad.append(f"{vector_id}: unexpected id prefix")
        if vector_id in ids:
            bad.append(f"{vector_id}: duplicate id")
        ids.add(vector_id)
    assert bad == [], "\n".join(bad)


def test_analyze_mobile_vectors_cover_fixtures_actions_and_scales() -> None:
    """The vectors cover every mobile fixture, action kind, and scale shape.

    Raises:
        AssertionError: If a fixture is missing, an action kind never
            appears, or a scale value is not exercised.
    """
    from conformance.record.gen_replay_analyze_vectors import FIXTURES

    vectors = _analyze_mobile_vectors()
    ids = {str(body["id"]) for body in vectors}
    for name, _keep in FIXTURES:
        assert any(name in vector_id for vector_id in ids), name
    assert len(FIXTURES) == 9
    actions: set[str] = set()
    scales: set[float] = set()
    for body in vectors:
        for action in body["expect"]["output"]["actions"]:
            actions.add(action["action"])
            if action["action"] == "screen":
                scales.add(action["metadata"]["scale"])
    assert {"screen", "touch_start", "scroll", "click"} <= actions
    assert {1.0, 2.0, 1.25, 0.5, 1.05, 0.95} <= scales


def _analyze_mobile_output(slug: str) -> dict[str, Any]:
    """Return the ``expect.output`` of one mobile analyzer vector.

    Args:
        slug: The id suffix after ``authored-mobile-``.

    Returns:
        The analyzer output.
    """
    by_id = {str(body["id"]): body for body in _analyze_mobile_vectors()}
    body = by_id[f"replays/rrweb_analyzer.analyze/authored-mobile-{slug}"]
    output: dict[str, Any] = body["expect"]["output"]
    return output


def _action_counts(output: dict[str, Any]) -> dict[str, int]:
    """Count the actions of one analyzer output by kind.

    Args:
        output: The analyzer output.

    Returns:
        Action kind -> count.
    """
    counts: dict[str, int] = {}
    for action in output["actions"]:
        counts[action["action"]] = counts.get(action["action"], 0) + 1
    return counts


def test_analyze_mobile_trimmed_prefixes_keep_their_actions() -> None:
    """The two trimmed fixtures keep the actions they are carried for.

    A fixture or analyzer change that hollows out a prefix fails here
    instead of silently shrinking the coverage.

    Raises:
        AssertionError: If a prefix loses screens, taps, scrolls, or the
            overlapping finger-downs of the rage burst.
    """
    from conformance.record.gen_replay_analyze_vectors import _cases

    snacks = _analyze_mobile_output("android-snacks-001-first-18")
    assert _action_counts(snacks) == {"screen": 3, "touch_start": 3}
    rage = _analyze_mobile_output("flutter-android-rage-001-first-73")
    assert _action_counts(rage) == {"screen": 6, "scroll": 2, "touch_start": 10}
    events = dict(_cases())["flutter-android-rage-001-first-73"]
    down = False
    overlapping = 0
    for event in events:
        data = event.get("data", {})
        if event.get("type") != 3 or data.get("source") != 2:
            continue
        if data.get("type") == 7:
            overlapping += int(down)
            down = True
        elif data.get("type") == 9:
            down = False
    assert overlapping >= 1


def test_analyze_mobile_tolerance_case_discriminates() -> None:
    """Inside the tolerance the bounds stay raw, and the tap proves it.

    The same tap against a stream that does scale (by 1.05) misses the
    button, so the ``stays-raw`` vector's ``button:Next`` target is only
    possible without scaling.

    Raises:
        AssertionError: If the raw case scales or the tap stops
            discriminating.
    """
    from conformance.record.adapters import analyze_rrweb
    from conformance.record.gen_replay_analyze_vectors import _scaled_stream

    raw = _analyze_mobile_output("scale-within-tolerance-stays-raw")
    screen = next(a for a in raw["actions"] if a["action"] == "screen")
    assert screen["metadata"]["scale"] == 1.0
    tap = next(a for a in raw["actions"] if a["action"] == "touch_start")
    assert tap["target_desc"] == "button:Next"
    scaled = analyze_rrweb(_scaled_stream(420, 400, tap=(100, 701)))
    scaled_tap = next(a for a in scaled.actions if a.action == "touch_start")
    assert scaled_tap.target_desc != "button:Next"


def test_analyze_mobile_scaled_bounds_round_half_to_even() -> None:
    """Scaled bounds that land on .5 round half to even.

    Raises:
        AssertionError: If ``[21, 301, 5, 3]`` at scale 0.5 is not
            ``[10, 150, 2, 2]``.
    """
    output = _analyze_mobile_output("scale-0-5-round-half-even")
    screen = next(a for a in output["actions"] if a["action"] == "screen")
    odd = next(e for e in screen["metadata"]["elements"] if e["text"] == "Odd")
    assert odd["bounds"] == [10, 150, 2, 2]


def test_analyze_mobile_bundle_keeps_float_spelling() -> None:
    """Integral float fields keep their ``.0`` spelling in the bundle text.

    ``metadata.scale`` is a float in Python; a port must see ``1.0`` and
    ``2.0``, never ``1`` or ``2``.

    Raises:
        AssertionError: If a scale is written as an integer token.
    """
    import re

    from conformance.record.gen_replay_analyze_vectors import render_bundle

    text = render_bundle("0" * 40)
    tokens = set(re.findall(r'"scale":(-?[0-9][0-9.eE+-]*)', text))
    assert {"1.0", "2.0", "1.25", "0.5"} <= tokens
    assert all("." in token or "e" in token.lower() for token in tokens), tokens


def test_analyze_mobile_vectors_replay_clean_through_the_runner() -> None:
    """Each generated mobile analyzer vector passes the corpus runner.

    Raises:
        AssertionError: With the failure reasons of any vector that fails.
    """
    from conformance.record.clock import RecordClock
    from conformance.runner.execute import run_vector
    from conformance.runner.loading import LoadedVector

    failures: list[str] = []
    clock = RecordClock()
    clock.start()
    try:
        for body in _analyze_mobile_vectors():
            clock.reset_test_state()
            outcome = run_vector(
                LoadedVector(
                    id=str(body["id"]),
                    kind=str(body["kind"]),
                    body=body,
                    bundle=Path("authored/replays/rrweb-analyze-mobile.jsonl"),
                )
            )
            if not outcome.passed:
                failures.extend([str(body["id"]), *outcome.reasons])
    finally:
        clock.stop()
    assert failures == [], "\n".join(failures)


def test_analyze_mobile_full_fixtures_match_goldens() -> None:
    """Untrimmed fixture vectors equal the committed rrweb goldens.

    The goldens under ``conformance/goldens/rrweb/`` freeze the analyzer's
    actions and markdown for the same streams; the vectors must agree.

    Raises:
        AssertionError: If an untrimmed vector's actions or markdown differ
            from its golden.
    """
    from conformance.record.gen_replay_analyze_vectors import FIXTURES

    goldens = Path(__file__).resolve().parents[1] / "goldens" / "rrweb"
    by_id = {str(body["id"]): body for body in _analyze_mobile_vectors()}
    for name, keep in FIXTURES:
        if keep is not None:
            continue
        body = by_id[f"replays/rrweb_analyzer.analyze/authored-mobile-{name}"]
        golden = json.loads((goldens / f"{name}.golden.json").read_text("utf-8"))
        output = body["expect"]["output"]
        assert output["actions"] == golden["actions"], name
        assert output["markdown_summary"] == golden["markdown"], name


def test_analyze_mobile_bundle_matches_generator_when_present() -> None:
    """A committed mobile analyzer bundle equals a fresh generator run.

    Raises:
        AssertionError: If the committed bundle differs from the generator
            output under its own stamp.
    """
    from conformance.record.gen_replay_analyze_vectors import (
        OUT_PATH,
        render_bundle,
    )

    if not OUT_PATH.exists():
        pytest.skip("mobile analyzer bundle is written after the merge to main")
    text = OUT_PATH.read_text(encoding="utf-8")
    header = json.loads(text.splitlines()[0])["$bundle"]
    assert text == render_bundle(str(header["source_commit"]))


def test_gen_replay_analyze_vectors_cli(tmp_path: Path) -> None:
    """The CLI writes the bundle to ``--out``.

    Args:
        tmp_path: pytest-provided scratch directory.

    Raises:
        AssertionError: If the written bundle differs from ``render_bundle``.
    """
    from conformance.record.gen_replay_analyze_vectors import main, render_bundle

    stamp = "0" * 40
    out = tmp_path / "nested" / "bundle.jsonl"
    assert main(["--commit", stamp, "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == render_bundle(stamp)
