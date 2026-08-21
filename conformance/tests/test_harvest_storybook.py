"""Tests for the storybook harvest script (user ruling E1, design D3.1).

Locks the three safety-critical behaviors of
``conformance/record/harvest_storybook.py`` BEFORE implementation (TDD):

1. **Scrubbing** — internal demo-project ids, employee emails, and
   creator ids/names are re-keyed to synthetic values, and the
   verification pass detects any residue.
2. **Unwrapping** — the 9 ``{body, init}`` storybook fetch-mock wrapper
   files unwrap to their inner body + HTTP status; raw bodies pass
   through with status 200.
3. **Routing + emission** — each mock directory maps to the library
   entry point whose response it mocks, unroutable groups are skipped
   (never forced), and emitted vectors are schema-valid, carry
   ``origin: "authored"``, a ``parse/``-prefixed id, and REPLAY GREEN
   through the Python corpus runner.

The suite never touches the read-only analytics checkout: it builds a
miniature source tree under ``tmp_path`` with the same directory layout.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from conformance.record.harvest_storybook import (
    HarvestReport,
    harvest,
    route_for,
    scrub_text,
    unwrap_mock,
    verify_scrub_clean,
)
from conformance.runner.execute import run_vector
from conformance.runner.loading import load_vectors

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "vector.schema.json"


# ---------------------------------------------------------------------------
# unwrap_mock
# ---------------------------------------------------------------------------


def test_unwrap_mock_passes_raw_bodies_through_with_status_200() -> None:
    """A raw API body (no wrapper) is returned unchanged with status 200.

    Raises:
        AssertionError: If the body is altered or the status is wrong.
    """
    body = {"headers": ["$event"], "series": {}}
    unwrapped, status = unwrap_mock(body)
    assert unwrapped == body
    assert status == 200


def test_unwrap_mock_unwraps_storybook_wrapper_files() -> None:
    """A ``{body, init}`` wrapper unwraps to the inner body + init status.

    Raises:
        AssertionError: If the wrapper is served as a body, or the
            recorded status is not taken from ``init.status``.
    """
    wrapped = {
        "body": {"status": "error", "error": "Internal Error"},
        "init": {"status": 502},
    }
    unwrapped, status = unwrap_mock(wrapped)
    assert unwrapped == {"status": "error", "error": "Internal Error"}
    assert status == 502


def test_unwrap_mock_does_not_unwrap_bodies_with_extra_keys() -> None:
    """An object with ``body`` plus unrelated keys is NOT a wrapper.

    Raises:
        AssertionError: If a non-wrapper object is unwrapped.
    """
    body = {"body": {"x": 1}, "init": {"status": 400}, "other": True}
    unwrapped, status = unwrap_mock(body)
    assert unwrapped == body
    assert status == 200


# ---------------------------------------------------------------------------
# scrub_text / verify_scrub_clean
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dirty", "clean"),
    [
        ('"alix.becker@mixpanel.com"', '"user1@example.com"'),
        ('"areeb.iqbal@mixpanel.com"', '"user2@example.com"'),
        ('"mack.duan@mixpanel.com"', '"user3@example.com"'),
        ('"pablo.fierro@mixpanel.com"', '"user4@example.com"'),
        ('"test@mixpanel.com"', '"user5@example.com"'),
    ],
)
def test_scrub_text_rekeys_every_employee_email(dirty: str, clean: str) -> None:
    """Each of the 5 employee emails maps to a synthetic example.com user.

    Args:
        dirty: JSON text containing one real email.
        clean: The expected scrubbed text.

    Raises:
        AssertionError: If the email survives or maps incorrectly.
    """
    assert scrub_text(dirty) == clean


@pytest.mark.parametrize(
    ("dirty", "clean"),
    [
        ('"creator_name": "Alix Becker"', '"creator_name": "User One"'),
        ('"creator": "Alix B."', '"creator": "User O."'),
        ('"creator_name": "Iqbal, Areeb"', '"creator_name": "Two, User"'),
        ('"creator": "Iqbal, A."', '"creator": "Two, U."'),
        ('"creator_name": "Duan, Mack"', '"creator_name": "Three, User"'),
        ('"creator": "Duan, M."', '"creator": "Three, U."'),
        ('"creator_name": "Pablo "', '"creator_name": "UserFour "'),
        (
            '"title": "[Mack] E-Commerce Board"',
            '"title": "[UserThree] E-Commerce Board"',
        ),
    ],
)
def test_scrub_text_rekeys_every_creator_name_variant(dirty: str, clean: str) -> None:
    """Every observed creator-name spelling is re-keyed to a synthetic name.

    Args:
        dirty: JSON text containing one real-name variant.
        clean: The expected scrubbed text.

    Raises:
        AssertionError: If any name variant survives scrubbing.
    """
    assert scrub_text(dirty) == clean


@pytest.mark.parametrize(
    ("dirty", "clean"),
    [
        ('"project_id": 3018488', '"project_id": 12345'),
        ('"workspace_id":3536632', '"workspace_id":67890'),
        ("project_id=2855068", "project_id=12345"),
        ("workspace_id=3387988", "workspace_id=67890"),
        ('"creator_id": 766035', '"creator_id": 90001'),
        ('"last_modified_by_id":1430181', '"last_modified_by_id":90002'),
        ('"creator_id": 3023601', '"creator_id": 90003'),
        ('"creator_id": 5035079', '"creator_id": 90004'),
    ],
)
def test_scrub_text_rekeys_internal_numeric_ids(dirty: str, clean: str) -> None:
    """Demo project/workspace ids and creator ids map to synthetic ids.

    Args:
        dirty: Text containing one internal numeric id.
        clean: The expected scrubbed text.

    Raises:
        AssertionError: If an internal id survives scrubbing.
    """
    assert scrub_text(dirty) == clean


def test_scrub_text_respects_digit_boundaries() -> None:
    """Ids embedded inside LONGER numbers are never rewritten.

    ``13018488`` contains the demo project id ``3018488`` as a substring;
    a naive replace would corrupt unrelated values.

    Raises:
        AssertionError: If a longer number containing an internal id as a
            substring is altered.
    """
    assert scrub_text('"id": 13018488') == '"id": 13018488'
    assert scrub_text('"id": 30184880') == '"id": 30184880'


def test_verify_scrub_clean_flags_residue_and_passes_scrubbed_text() -> None:
    """The verification pass flags dirty text and accepts scrubbed text.

    Raises:
        AssertionError: If residue goes undetected, or scrubbed output
            still trips the verifier.
    """
    dirty = json.dumps(
        {
            "creator_email": "pablo.fierro@mixpanel.com",
            "creator_name": "Duan, Mack",
            "project_id": 3018488,
            "workspace_id": 3536632,
            "creator_id": 5035079,
        }
    )
    assert verify_scrub_clean(dirty) != []
    assert verify_scrub_clean(scrub_text(dirty)) == []


# ---------------------------------------------------------------------------
# route_for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel", "api", "input_kwargs"),
    [
        (
            "app/bookmarks/60327233.json",
            "workspace.get_bookmark",
            {"bookmark_id": 60327233},
        ),
        (
            "app/boards/board_9425929.json",
            "workspace.get_dashboard",
            {"dashboard_id": 9425929},
        ),
        (
            "query/insights/bookmark_60327233_with_formula.json",
            "workspace.query_saved_report",
            {"bookmark_id": 60327233},
        ),
        (
            "query/arb_funnels/bookmark_87176748.json",
            "workspace.query_saved_flows",
            {"bookmark_id": 87176748},
        ),
    ],
)
def test_route_for_maps_each_mock_group_to_its_entry_point(
    rel: str, api: str, input_kwargs: dict[str, Any]
) -> None:
    """Each harvestable mock directory routes to the method it mocks.

    Args:
        rel: Source-relative mock path.
        api: Expected dotted entry point.
        input_kwargs: Expected ``call.input``.

    Raises:
        AssertionError: On any routing mismatch.
    """
    route = route_for(PurePosixPath(rel))
    assert route is not None
    assert route.api == api
    assert route.input_kwargs == input_kwargs


def test_route_for_skips_metrics_and_unknown_paths() -> None:
    """Metrics timeseries mocks (no library entry point) do not route.

    Raises:
        AssertionError: If an unroutable path produces a route.
    """
    metrics = PurePosixPath(
        "query/metrics/node23a717d9-768c-4660-9948-81ed303ef826_in_the_last_7_day.json"
    )
    assert route_for(metrics) is None
    assert route_for(PurePosixPath("query/unknown/foo.json")) is None


def test_app_routes_carry_a_workspace_scoped_session() -> None:
    """App API routes pin ``workspace_id`` so paths are workspace-scoped.

    Query API routes carry no workspace (matching the phase008 authored
    session convention).

    Raises:
        AssertionError: If session workspace scoping is wrong per group.
    """
    app_route = route_for(PurePosixPath("app/bookmarks/60327233.json"))
    query_route = route_for(PurePosixPath("query/insights/bookmark_1.json"))
    assert app_route is not None and query_route is not None
    assert app_route.session["workspace_id"] == 67890
    assert "workspace_id" not in query_route.session


# ---------------------------------------------------------------------------
# harvest (end to end over a miniature source tree)
# ---------------------------------------------------------------------------


@pytest.fixture
def mini_source(tmp_path: Path) -> Path:
    """Build a miniature storybook mock tree mirroring the real layout.

    Contains one raw insights body (with internal identifiers to scrub),
    one 502 ``{body, init}`` wrapper, and one metrics file that must be
    skipped.

    Args:
        tmp_path: Pytest per-test temp directory.

    Returns:
        The miniature source root.
    """
    root = tmp_path / "mocks" / "api"
    insights = root / "query" / "insights"
    metrics = root / "query" / "metrics"
    insights.mkdir(parents=True)
    metrics.mkdir(parents=True)
    (insights / "bookmark_60327233.json").write_text(
        json.dumps(
            {
                "computed_at": "2024-07-19T22:34:17+00:00",
                "date_range": {
                    "from_date": "2024-01-01T00:00:00-08:00",
                    "to_date": "2024-01-07T00:00:00-08:00",
                },
                "headers": ["$event"],
                "series": {"Purchase": {"2024-01-01T00:00:00-08:00": 5}},
                "meta": {
                    "creator_email": "pablo.fierro@mixpanel.com",
                    "project_id": 3018488,
                },
            }
        ),
        encoding="utf-8",
    )
    (insights / "bookmark_76412137.json").write_text(
        json.dumps(
            {
                "body": {"status": "error", "error": "Internal Error"},
                "init": {"status": 502},
            }
        ),
        encoding="utf-8",
    )
    (metrics / "node1_in_the_last_7_day.json").write_text(
        json.dumps({"meta": {}, "timeseries": []}), encoding="utf-8"
    )
    return root


def test_harvest_emits_scrubbed_runner_green_vectors(
    mini_source: Path, tmp_path: Path
) -> None:
    """End to end: harvest emits schema-valid, scrubbed, replayable vectors.

    The emitted bundle must (1) validate against the vector schema,
    (2) carry ``origin: "authored"`` + ``parse/``-prefixed ids, (3) name
    each vector's source path in the ``$bundle`` provenance map, (4) show
    zero scrub residue, (5) skip the metrics file with a reason, and
    (6) replay green through the Python corpus runner — including the
    502 wrapper becoming an ``expect.error`` vector.

    Args:
        mini_source: The miniature mock tree.
        tmp_path: Pytest per-test temp directory.

    Raises:
        AssertionError: On any emitted-corpus violation.
    """
    out = tmp_path / "out"
    report = harvest(mini_source, out)
    assert isinstance(report, HarvestReport)
    assert report.emitted == 2
    assert len(report.skipped) == 1
    assert "metrics" in report.skipped[0][0]

    bundle = out / "insights.jsonl"
    assert bundle.is_file()
    text = bundle.read_text(encoding="utf-8")
    assert verify_scrub_clean(text) == []

    lines = [json.loads(line) for line in text.splitlines()]
    header, vectors = lines[0], lines[1:]
    assert header["$bundle"]["count"] == 2
    sources = header["$bundle"]["sources"]
    validator = Draft202012Validator(
        json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    )
    for vector in vectors:
        assert vector["origin"] == "authored"
        assert vector["capability"] == "parse"
        assert vector["kind"] == "parse"
        assert vector["id"].startswith("parse/")
        assert vector["id"] in sources
        assert sources[vector["id"]].endswith(".json")
        errors = [error.message for error in validator.iter_errors(vector)]
        assert errors == [], errors
    assert any("error" in vector["expect"] for vector in vectors)
    assert any("result" in vector["expect"] for vector in vectors)

    outcomes = [run_vector(loaded) for loaded in load_vectors(out)]
    assert all(outcome.passed for outcome in outcomes), [
        (outcome.id, outcome.reasons) for outcome in outcomes if not outcome.passed
    ]
