"""Fixtures shared by every live suite.

``tests/conftest.py`` removes the storage location variables before each
test to keep unit tests hermetic. A live test needs the locations that were
set for the run, so this module puts back the config and storage locations
that ``tests/live/_live_settings.py`` captured at import. Tests that point
HOME at a tmp directory (``tmp_mp_home``) set their own values afterwards.
"""

from __future__ import annotations

import pytest

from tests.live._live_settings import LOCATION_OVERRIDES


@pytest.fixture(autouse=True)
def _reapply_live_location_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put back the config and storage locations captured at import.

    Args:
        monkeypatch: Restores the environment after the test.
    """
    for name, value in LOCATION_OVERRIDES.items():
        monkeypatch.setenv(name, value)
