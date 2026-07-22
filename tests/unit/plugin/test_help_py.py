"""Tests for the plugin's help.py live-docs introspection.

help.py is the mixpanelyst skill's API-lookup script; LLM agents run
``python help.py Metric`` to learn construction patterns. These tests
pin that the converted pydantic dataclasses render as clean field
listings (not raw ``FieldInfo(...)`` reprs) and that ``ClassVar``
pseudo-fields never appear as constructor fields.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_HELP_PATH = (
    Path(__file__).parents[3]
    / "mixpanel-plugin"
    / "skills"
    / "mixpanelyst"
    / "scripts"
    / "help.py"
)


@pytest.fixture(scope="module")
def help_mod() -> ModuleType:
    """Load help.py as a module from the plugin directory."""
    spec = importlib.util.spec_from_file_location("mp_plugin_help", _HELP_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestShowFieldsPydanticDataclass:
    """show_fields renders converted pydantic dataclasses cleanly."""

    def test_metric_renders_without_fieldinfo_repr(
        self, help_mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Metric fields show clean types/defaults, not FieldInfo reprs."""
        from mixpanel_headless.types import Metric

        help_mod.show_fields(Metric)
        out = capsys.readouterr().out
        assert "FieldInfo(" not in out
        assert "event" in out
        assert "(required)" in out

    def test_filter_excludes_classvar_pseudo_fields(
        self, help_mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Filter's ClassVar frozensets are not listed as fields."""
        from mixpanel_headless.types import Filter

        help_mod.show_fields(Filter)
        out = capsys.readouterr().out
        assert "_NUMERIC_OPS" not in out
        assert "_DATE_OPS" not in out
        assert "FieldInfo(" not in out
        assert "property" in out

    def test_base_model_rendering_unchanged(
        self, help_mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """BaseModel rendering (InsightsQuery) keeps working."""
        from mixpanel_headless.query_models import InsightsQuery

        help_mod.show_fields(InsightsQuery)
        out = capsys.readouterr().out
        assert "events" in out
        assert "(required)" in out
        assert "FieldInfo(" not in out

    def test_annotated_union_arms_render_clean(
        self, help_mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Per-arm ``Annotated[int, Field(...)]`` unions render as bare types.

        The strict per-arm bound annotations (``Annotated[int,
        Field(strict=True, gt=0)] | ...`` on ``GroupBy.bucket_size``)
        must not leak ``Annotated[...]`` / ``FieldInfo(...)`` reprs
        into the field listing an LLM reads.
        """
        from mixpanel_headless.types import GroupBy

        help_mod.show_fields(GroupBy)
        out = capsys.readouterr().out
        assert "FieldInfo(" not in out
        assert "Annotated[" not in out
        assert "bucket_size: int | float | None" in out
