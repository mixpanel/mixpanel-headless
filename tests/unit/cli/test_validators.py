"""Unit tests for CLI validators."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from typer import Exit

from mixpanel_headless._literal_types import CountType, HourDayUnit, TimeUnit
from mixpanel_headless.cli.validators import (
    read_json_object_file,
    validate_count_type,
    validate_hour_day_unit,
    validate_json_object,
    validate_literal,
    validate_time_unit,
)


class TestTypeAliases:
    """Tests for type alias definitions."""

    def test_time_unit_values(self) -> None:
        """TimeUnit should accept day, week, month."""
        from typing import get_args

        assert get_args(TimeUnit) == ("day", "week", "month")

    def test_hour_day_unit_values(self) -> None:
        """HourDayUnit should accept hour, day."""
        from typing import get_args

        assert get_args(HourDayUnit) == ("hour", "day")

    def test_count_type_values(self) -> None:
        """CountType should accept general, unique, average."""
        from typing import get_args

        assert get_args(CountType) == ("general", "unique", "average")


class TestValidateLiteral:
    """Tests for the generic validate_literal function."""

    def test_valid_value_returns_cast(self) -> None:
        """Test that valid values pass through."""
        result = validate_literal("day", TimeUnit, "--unit")
        assert result == "day"

    def test_invalid_value_raises_exit_code_3(self) -> None:
        """Test that invalid values raise typer.Exit with code 3."""
        with pytest.raises(Exit) as exc:
            validate_literal("invalid", TimeUnit, "--unit")
        assert exc.value.exit_code == 3

    def test_all_time_unit_values_valid(self) -> None:
        """Test all TimeUnit values pass validation."""
        for value in ("day", "week", "month"):
            result = validate_literal(value, TimeUnit, "--unit")
            assert result == value

    def test_all_hour_day_unit_values_valid(self) -> None:
        """Test all HourDayUnit values pass validation."""
        for value in ("hour", "day"):
            result = validate_literal(value, HourDayUnit, "--unit")
            assert result == value

    def test_all_count_type_values_valid(self) -> None:
        """Test all CountType values pass validation."""
        for value in ("general", "unique", "average"):
            result = validate_literal(value, CountType, "--type")
            assert result == value


class TestValidateTimeUnit:
    """Tests for validate_time_unit convenience function."""

    @pytest.mark.parametrize("value", ["day", "week", "month"])
    def test_valid_values(self, value: str) -> None:
        """Test that all valid TimeUnit values pass."""
        assert validate_time_unit(value) == value

    def test_invalid_value_rejected(self) -> None:
        """Test that hour is rejected (it's HourDayUnit, not TimeUnit)."""
        with pytest.raises(Exit):
            validate_time_unit("hour")

    def test_custom_param_name_in_error(self) -> None:
        """Test that custom param name is used in error output."""
        with pytest.raises(Exit) as exc:
            validate_time_unit("bad", "--time-unit")
        assert exc.value.exit_code == 3


class TestValidateHourDayUnit:
    """Tests for validate_hour_day_unit convenience function."""

    @pytest.mark.parametrize("value", ["hour", "day"])
    def test_valid_values(self, value: str) -> None:
        """Test that all valid HourDayUnit values pass."""
        assert validate_hour_day_unit(value) == value

    def test_week_rejected(self) -> None:
        """Test that week is rejected (it's TimeUnit, not HourDayUnit)."""
        with pytest.raises(Exit):
            validate_hour_day_unit("week")

    def test_month_rejected(self) -> None:
        """Test that month is rejected."""
        with pytest.raises(Exit):
            validate_hour_day_unit("month")


class TestValidateCountType:
    """Tests for validate_count_type convenience function."""

    @pytest.mark.parametrize("value", ["general", "unique", "average"])
    def test_valid_values(self, value: str) -> None:
        """Test that all valid CountType values pass."""
        assert validate_count_type(value) == value

    def test_invalid_value_rejected(self) -> None:
        """Test that invalid values are rejected."""
        with pytest.raises(Exit):
            validate_count_type("total")

    def test_typo_rejected(self) -> None:
        """Test that typos are caught."""
        with pytest.raises(Exit):
            validate_count_type("genral")  # typo


class TestValidateJsonObject:
    """Tests for validate_json_object."""

    def test_valid_object_returns_dict(self) -> None:
        """A JSON object string should parse to the equivalent dict."""
        result = validate_json_object('{"event": "X", "n": 1}', "--sentinel-event")
        assert result == {"event": "X", "n": 1}

    def test_invalid_json_raises_exit_code_3(self) -> None:
        """Malformed JSON should raise typer.Exit with code 3."""
        with pytest.raises(Exit) as exc:
            validate_json_object("not-json", "--sentinel-event")
        assert exc.value.exit_code == 3

    def test_non_object_json_raises_exit_code_3(self) -> None:
        """Valid JSON that is not an object (e.g. an array) should be rejected."""
        with pytest.raises(Exit) as exc:
            validate_json_object("[1, 2, 3]", "--sentinel-event")
        assert exc.value.exit_code == 3


class TestReadJsonObjectFile:
    """Tests for read_json_object_file."""

    def test_reads_a_file(self, tmp_path: Path) -> None:
        """A path to a JSON object file gives the dict."""
        path = tmp_path / "definition.json"
        path.write_text('{"behavior": {"type": "event"}}', encoding="utf-8")
        assert read_json_object_file(path, "--definition-file") == {
            "behavior": {"type": "event"}
        }

    def test_missing_file_exits_3(self, tmp_path: Path) -> None:
        """An unreadable path exits with code 3."""
        with pytest.raises(Exit) as exc:
            read_json_object_file(tmp_path / "nope.json", "--definition-file")
        assert exc.value.exit_code == 3

    def test_dash_reads_stdin(self) -> None:
        """A path of ``-`` reads the object from a piped stdin."""
        with (
            patch("mixpanel_headless.cli.validators._stdin_is_tty", return_value=False),
            patch("sys.stdin", io.StringIO('{"a": 1}')),
        ):
            assert read_json_object_file(Path("-"), "--definition-file") == {"a": 1}

    def test_dash_on_a_terminal_exits_3(self) -> None:
        """A path of ``-`` refuses to wait for input typed on a terminal."""
        with (
            patch("mixpanel_headless.cli.validators._stdin_is_tty", return_value=True),
            pytest.raises(Exit) as exc,
        ):
            read_json_object_file(Path("-"), "--definition-file")
        assert exc.value.exit_code == 3

    def test_non_object_exits_3(self, tmp_path: Path) -> None:
        """A file that holds a JSON array exits with code 3."""
        path = tmp_path / "list.json"
        path.write_text("[1]", encoding="utf-8")
        with pytest.raises(Exit) as exc:
            read_json_object_file(path, "--definition-file")
        assert exc.value.exit_code == 3
