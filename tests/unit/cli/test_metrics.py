# ruff: noqa: ARG001, ARG005
"""Tests for the saved-metrics CLI commands.

Tests cover all metrics subcommands:
- list: List saved metrics with local filters
- get: Get one saved metric by ID
- delete: Delete one or more saved metrics
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import typer.testing

from mixpanel_headless.cli.main import app
from mixpanel_headless.exceptions import ParamValidationError, QueryError
from mixpanel_headless.types import SavedMetric
from tests.unit._saved_metric_fixtures import (
    behavior_metric_json,
    formula_metric_json,
    warehouse_metric_json,
)

runner = typer.testing.CliRunner()


def _metrics() -> list[SavedMetric]:
    """Return three typed saved metrics: a behavior metric, a formula, a warehouse metric.

    Returns:
        SavedMetric objects built from the shared fixtures.
    """
    return [
        SavedMetric.model_validate(behavior_metric_json(1, "Weekly signups")),
        SavedMetric.model_validate(formula_metric_json(2, "Signup conversion")),
        SavedMetric.model_validate(warehouse_metric_json(3, "Warehouse revenue")),
    ]


class TestMetricsList:
    """Tests for mp metrics list."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_returns_json_list(self, mock_get_ws: MagicMock) -> None:
        """A plain list prints every metric as JSON with the default filters."""
        mock_ws = MagicMock()
        mock_ws.list_metrics.return_value = _metrics()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "list"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert [m["id"] for m in data] == [1, 2, 3]
        assert data[0]["definition"]["measurement"] == {"math": "unique"}
        assert data[0]["created"] == "2026-03-01T12:00:00"
        mock_ws.list_metrics.assert_called_once_with(
            metric_type=None, verified=None, name_contains=None, viewable_only=False
        )

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_passes_filters(self, mock_get_ws: MagicMock) -> None:
        """Each list option maps to its list_metrics argument."""
        mock_ws = MagicMock()
        mock_ws.list_metrics.return_value = []
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "metrics",
                "list",
                "--type",
                "formula",
                "--verified",
                "--name-contains",
                "rate",
                "--viewable-only",
            ],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == []
        mock_ws.list_metrics.assert_called_once_with(
            metric_type="formula",
            verified=True,
            name_contains="rate",
            viewable_only=True,
        )

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_no_verified_flag(self, mock_get_ws: MagicMock) -> None:
        """--no-verified asks for unverified metrics only."""
        mock_ws = MagicMock()
        mock_ws.list_metrics.return_value = []
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "list", "--no-verified"])
        assert result.exit_code == 0, result.output
        assert mock_ws.list_metrics.call_args.kwargs["verified"] is False

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_table_shows_can_view(self, mock_get_ws: MagicMock) -> None:
        """The table view has a CAN VIEW column and leaves out the definition."""
        mock_ws = MagicMock()
        mock_ws.list_metrics.return_value = _metrics()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "list", "--format", "table"])
        assert result.exit_code == 0, result.output
        assert "CAN VIEW" in result.stdout
        assert "Warehouse revenue" in result.stdout
        assert "DEFINITION" not in result.stdout
        assert "measurement" not in result.stdout

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_jq_filter(self, mock_get_ws: MagicMock) -> None:
        """--jq filters the JSON output."""
        mock_ws = MagicMock()
        mock_ws.list_metrics.return_value = _metrics()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app, ["metrics", "list", "--jq", "[.[] | select(.can_view == false) | .id]"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == [3]


class TestMetricsGet:
    """Tests for mp metrics get."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_returns_json(self, mock_get_ws: MagicMock) -> None:
        """get prints the full metric, definition included."""
        mock_ws = MagicMock()
        mock_ws.get_metric.return_value = _metrics()[1]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "get", "2"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["definition"]["formula"]["definition"] == "A / B * 100"
        mock_ws.get_metric.assert_called_once_with(2)

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_not_found_exits_nonzero(self, mock_get_ws: MagicMock) -> None:
        """A 404 from the server exits with a non-zero code and an error on stderr."""
        mock_ws = MagicMock()
        mock_ws.get_metric.side_effect = QueryError(
            "Metric not found for id 9", status_code=404
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "get", "9"])
        assert result.exit_code != 0
        assert "Metric not found" in result.stderr

    def test_rejects_non_integer_id(self) -> None:
        """A non-integer ID is a usage error."""
        result = runner.invoke(app, ["metrics", "get", "abc"])
        assert result.exit_code == 2


class TestMetricsDelete:
    """Tests for mp metrics delete."""

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_one_id_uses_checked_delete(self, mock_get_ws: MagicMock) -> None:
        """One ID goes through delete_metric (existence check) with a stderr message."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "delete", "104700"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_metric.assert_called_once_with(104700)
        mock_ws.delete_metrics.assert_not_called()
        assert result.stdout == ""
        assert "Deleted saved metric 104700" in result.stderr

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_several_ids_use_one_bulk_delete(self, mock_get_ws: MagicMock) -> None:
        """Several IDs go through one delete_metrics call; stderr names the skip rule."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "delete", "1", "2", "3"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_metrics.assert_called_once_with([1, 2, 3])
        mock_ws.delete_metric.assert_not_called()
        assert "1, 2, 3" in result.stderr
        assert "skips" in result.stderr

    @patch("mixpanel_headless.cli.commands.metrics.get_workspace")
    def test_not_found_refusal_exits_nonzero(self, mock_get_ws: MagicMock) -> None:
        """The SM5 refusal of delete_metric exits non-zero with the message."""
        mock_ws = MagicMock()
        mock_ws.delete_metric.side_effect = ParamValidationError(
            "Saved metric 5 was not found in project 12345; nothing was deleted.",
            code="SM5_NOT_FOUND_FOR_DELETE",
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["metrics", "delete", "5"])
        assert result.exit_code != 0
        assert "nothing was deleted" in result.stderr

    def test_requires_an_id(self) -> None:
        """delete with no ID is a usage error."""
        result = runner.invoke(app, ["metrics", "delete"])
        assert result.exit_code == 2
