"""Pytest harness parametrizing over the committed corpus (design D7).

One test per vector (id = vector id) via ``pytest_generate_tests``. Runs
under the normal repo toolchain:

    ```bash
    uv run pytest conformance/runner -o addopts="" -q
    ```

The pytest-free equivalent for worktree smoke runs is
``python -m conformance.runner`` (design D9.2).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from conformance.record.clock import RecordClock
from conformance.runner.execute import run_vector
from conformance.runner.loading import LoadedVector, load_vectors

VECTORS_ROOT = Path(__file__).resolve().parents[1] / "vectors"
"""The committed corpus root (design D3 layout)."""


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize ``test_vector`` over every committed vector (design D7).

    Args:
        metafunc: The pytest metafunc for the collected test function.
    """
    if "vector" not in metafunc.fixturenames:
        return
    vectors = load_vectors(VECTORS_ROOT)
    metafunc.parametrize("vector", vectors, ids=[vector.id for vector in vectors])


@pytest.fixture(scope="session")
def replay_clock() -> Iterator[RecordClock]:
    """Install the D1.4 replay clock for the whole corpus run.

    Frozen ``RECORD_EPOCH`` + deterministic UUID stream + virtual sleep —
    identical to record mode so re-execution is bit-stable and backoff
    vectors replay instantly (design D7).

    Yields:
        The active clock (per-vector state reset happens in ``test_vector``).
    """
    clock = RecordClock()
    clock.start()
    try:
        yield clock
    finally:
        clock.stop()


def test_vector(vector: LoadedVector, replay_clock: RecordClock) -> None:
    """Replay one vector and assert every diff came back clean.

    Args:
        vector: The parametrized vector.
        replay_clock: The session-scoped replay clock (reset per vector).

    Raises:
        AssertionError: With the vector's failure reasons on any diff.
    """
    replay_clock.reset_test_state()
    outcome = run_vector(vector)
    assert outcome.passed, "\n".join([f"vector {vector.id} failed:"] + outcome.reasons)
