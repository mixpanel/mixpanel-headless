"""Tests for the fixture writer of scripts/probe_saved_metrics.py.

The probe names every entity it creates with a prefix that is unique to the
run, so that its cleanup can find the run's rows. That prefix must not reach
the fixtures: a long name with no spaces matches the conformance recorder's
secret check, and record-mode extraction then aborts. These tests load the
script as a module and check the fixture output without any network call.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "probe_saved_metrics.py"
_RUN_PREFIX = "zz-probe-20260930T083034Z-3f9a1c-"

# The conformance recorder's secret check (``_ENTROPY_SHAPE`` and
# ``_ENTROPY_MIN_DISTINCT_CHARS`` in conformance/record/emit.py): a string of
# 40 or more token characters with at least 10 distinct characters.
_ENTROPY_SHAPE = re.compile(r"^[A-Za-z0-9+/=_-]{40,}$")
_ENTROPY_MIN_DISTINCT_CHARS = 10


@pytest.fixture(scope="module")
def probe() -> Iterator[ModuleType]:
    """Load scripts/probe_saved_metrics.py as a module, then unload it."""
    spec = importlib.util.spec_from_file_location("probe_saved_metrics", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def _strings(node: Any) -> Iterator[str]:
    """Yield every string inside a parsed JSON value."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _matches_entropy_rule(value: str) -> bool:
    """Return True when the recorder's secret check would refuse the string."""
    return (
        _ENTROPY_SHAPE.fullmatch(value) is not None
        and not value.startswith("/")
        and value.count("/") <= 2
        and len(set(value)) >= _ENTROPY_MIN_DISTINCT_CHARS
    )


def _stub_run(probe: ModuleType) -> Any:
    """Build a probe run with one create record and one 400 error record."""
    create = probe.ProbeRecord(
        name="create_metric_event_total",
        method="POST",
        path="/projects/1/metrics",
        request_body={"name": f"{_RUN_PREFIX}simple-two-events"},
        status=200,
        response_body={
            "results": {
                "7": {
                    "id": 7,
                    "name": f"{_RUN_PREFIX}simple-two-events",
                    "created_by": {"id": 5, "email": "a@b.c", "name": "A"},
                }
            },
            "status": "ok",
        },
    )
    error = probe.ProbeRecord(
        name="error_400_unknown_key",
        method="POST",
        path="/projects/1/metrics",
        request_body={"name": f"{_RUN_PREFIX}bad-key"},
        status=400,
        response_body={
            "error": (
                "root: Additional properties are not allowed: "
                f"{{&#x27;name&#x27;: &#x27;{_RUN_PREFIX}bad-key&#x27;}}"
            ),
            "status": "error",
        },
    )
    return probe.ProbeRun(
        ws=SimpleNamespace(api=SimpleNamespace(project_id=1)),
        prefix=_RUN_PREFIX,
        target=SimpleNamespace(),
        records=[create, error],
        created_metrics=[7],
    )


class TestFixtureNames:
    """Tests that fixtures carry the short prefix, not the run's unique one."""

    def test_written_fixtures_use_the_short_prefix(
        self, probe: ModuleType, tmp_path: Path
    ) -> None:
        """Names and names inside error text use ``zz-probe-`` in fixtures."""
        out_dir = tmp_path / "fixtures"
        probe.write_outputs(_stub_run(probe), out_dir, tmp_path / "log.json")

        created = json.loads((out_dir / "create_metric.json").read_text())
        error_text = (out_dir / "error_400_unknown_key.json").read_text()
        assert created["results"]["7"]["name"] == "zz-probe-simple-two-events"
        assert "zz-probe-bad-key" in error_text
        for path in out_dir.iterdir():
            assert _RUN_PREFIX not in path.read_text(), path.name

    def test_written_fixtures_pass_the_recorder_secret_check(
        self, probe: ModuleType, tmp_path: Path
    ) -> None:
        """No string in a written fixture matches the recorder's entropy rule."""
        out_dir = tmp_path / "fixtures"
        probe.write_outputs(_stub_run(probe), out_dir, tmp_path / "log.json")

        hits = [
            value
            for path in out_dir.iterdir()
            for value in _strings(json.loads(path.read_text()))
            if _matches_entropy_rule(value)
        ]
        assert hits == []

    def test_the_long_names_would_fail_the_check(self) -> None:
        """A name with the run's unique prefix does match the entropy rule."""
        assert _matches_entropy_rule(f"{_RUN_PREFIX}simple-two-events")

    def test_the_probe_log_keeps_the_run_prefix(
        self, probe: ModuleType, tmp_path: Path
    ) -> None:
        """The local probe log keeps the real prefix as the run's audit record."""
        log_path = tmp_path / "log.json"
        probe.write_outputs(_stub_run(probe), tmp_path / "fixtures", log_path)

        log = json.loads(log_path.read_text())
        assert log["prefix"] == _RUN_PREFIX
        assert _RUN_PREFIX in log_path.read_text()

    def test_canonical_names_leave_other_values_alone(self, probe: ModuleType) -> None:
        """Only the run prefix changes; other strings, numbers, and keys stay."""
        value = {
            "name": f"{_RUN_PREFIX}x",
            "other": "zz-probe-elsewhere",
            "id": 7,
            "items": [f"text {_RUN_PREFIX}y", None, True],
        }
        assert probe.canonical_fixture_names(value, _RUN_PREFIX) == {
            "name": "zz-probe-x",
            "other": "zz-probe-elsewhere",
            "id": 7,
            "items": ["text zz-probe-y", None, True],
        }
