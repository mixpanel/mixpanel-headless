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

    def test_annotated_union_alternatives_render_clean(
        self, help_mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Per-alternative ``Annotated[int, Field(...)]`` unions render as bare types.

        The strict per-alternative bound annotations (``Annotated[int,
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

    def test_annotated_nested_in_generic_renders_clean(
        self, help_mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``Annotated`` nested inside a generic renders as the bare type.

        ``RetentionQuery.bucket_sizes`` is ``list[StrictInt] | None``,
        which pydantic stores as ``list[Annotated[int, Strict(...)]] |
        None`` — the ``Annotated`` wrapper and ``Strict(...)`` metadata
        must not leak into the field listing an LLM reads.
        """
        from mixpanel_headless.query_models import RetentionQuery

        help_mod.show_fields(RetentionQuery)
        out = capsys.readouterr().out
        assert "Annotated[" not in out
        assert "Strict(" not in out
        assert "bucket_sizes: list[int] | None" in out


class TestPerAlternativeConstraintRendering:
    """Numeric bounds declared per union alternative still show in the listing.

    Moving ``ge``/``le``/``gt`` bounds from the field into per-alternative
    ``Annotated[..., Field(...)]`` metadata removed them from
    ``FieldInfo.metadata``; the help listing must collect them from the
    union alternatives so LLM callers still see the valid range.
    """

    def test_percentile_value_bounds_shown(
        self, help_mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """InsightsQuery.percentile_value shows its 0-100 range."""
        from mixpanel_headless.query_models import InsightsQuery

        help_mod.show_fields(InsightsQuery)
        out = capsys.readouterr().out
        line = next(
            ln for ln in out.splitlines() if ln.strip().startswith("percentile_value:")
        )
        assert "ge=0" in line
        assert "le=100" in line

    def test_bucket_size_bound_shown(
        self, help_mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """GroupBy.bucket_size shows its gt=0 bound."""
        from mixpanel_headless.types import GroupBy

        help_mod.show_fields(GroupBy)
        out = capsys.readouterr().out
        line = next(
            ln for ln in out.splitlines() if ln.strip().startswith("bucket_size:")
        )
        assert "gt=0" in line

    def test_field_level_constraints_still_shown(
        self, help_mod: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Field-level metadata constraints (rolling gt=0) keep rendering."""
        from mixpanel_headless.query_models import InsightsQuery

        help_mod.show_fields(InsightsQuery)
        out = capsys.readouterr().out
        line = next(ln for ln in out.splitlines() if ln.strip().startswith("rolling:"))
        assert "gt=0" in line
