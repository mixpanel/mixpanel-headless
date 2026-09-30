# ruff: noqa: ARG001, ARG005
"""Tests for the saved-behaviors CLI commands.

Tests cover all behaviors subcommands:
- list: List saved behaviors with local filters
- get: Get one saved behavior by ID
- delete: Delete one or more saved behaviors
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import typer.testing

from mixpanel_headless.cli.main import app
from mixpanel_headless.exceptions import ServerError
from mixpanel_headless.types import SavedBehavior
from tests.unit._saved_metric_fixtures import saved_behavior_json

runner = typer.testing.CliRunner()


def _behaviors() -> list[SavedBehavior]:
    """Return two typed saved behaviors: a funnel and a retention behavior.

    Returns:
        SavedBehavior objects built from the shared fixtures.
    """
    return [
        SavedBehavior.model_validate(saved_behavior_json(1, "Checkout")),
        SavedBehavior.model_validate(
            saved_behavior_json(2, "Return visits", behavior_type="retention")
        ),
    ]


class TestBehaviorsList:
    """Tests for mp behaviors list."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_returns_json_list(self, mock_get_ws: MagicMock) -> None:
        """A plain list prints every behavior as JSON with the default filters."""
        mock_ws = MagicMock()
        mock_ws.list_behaviors.return_value = _behaviors()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "list"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert [b["type"] for b in data] == ["funnel", "retention"]
        mock_ws.list_behaviors.assert_called_once_with(
            behavior_type=None, name_contains=None
        )

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_passes_filters(self, mock_get_ws: MagicMock) -> None:
        """--type and --name-contains map to their list_behaviors arguments."""
        mock_ws = MagicMock()
        mock_ws.list_behaviors.return_value = []
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app, ["behaviors", "list", "--type", "funnel", "--name-contains", "check"]
        )
        assert result.exit_code == 0, result.output
        mock_ws.list_behaviors.assert_called_once_with(
            behavior_type="funnel", name_contains="check"
        )

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_table_shows_can_view(self, mock_get_ws: MagicMock) -> None:
        """The table view has a CAN VIEW column and leaves out the definition."""
        mock_ws = MagicMock()
        mock_ws.list_behaviors.return_value = _behaviors()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "list", "--format", "table"])
        assert result.exit_code == 0, result.output
        assert "CAN VIEW" in result.stdout
        assert "Return visits" in result.stdout
        assert "DEFINITION" not in result.stdout


class TestBehaviorsGet:
    """Tests for mp behaviors get."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_returns_json(self, mock_get_ws: MagicMock) -> None:
        """get prints the full behavior, definition included."""
        mock_ws = MagicMock()
        mock_ws.get_behavior.return_value = _behaviors()[0]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "get", "1"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["definition"]["behavior"]["type"] == "funnel"
        mock_ws.get_behavior.assert_called_once_with(1)

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_jq_filter(self, mock_get_ws: MagicMock) -> None:
        """--jq filters the JSON output."""
        mock_ws = MagicMock()
        mock_ws.get_behavior.return_value = _behaviors()[1]
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "get", "2", "--jq", ".name"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == "Return visits"


class TestBehaviorsDelete:
    """Tests for mp behaviors delete."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_one_id_uses_checked_delete(self, mock_get_ws: MagicMock) -> None:
        """One ID goes through delete_behavior (existence check) with a stderr message."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "delete", "3001"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_behavior.assert_called_once_with(3001, force=False)
        mock_ws.delete_behaviors.assert_not_called()
        assert result.stdout == ""
        assert "Deleted saved behavior 3001" in result.stderr

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_several_ids_use_one_bulk_delete(self, mock_get_ws: MagicMock) -> None:
        """Several IDs go through one delete_behaviors call; stderr names the skip rule."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "delete", "7", "8"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_behaviors.assert_called_once_with([7, 8], force=False)
        mock_ws.delete_behavior.assert_not_called()
        assert "7, 8" in result.stderr
        assert "skips" in result.stderr

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_unknown_id_exits_nonzero(self, mock_get_ws: MagicMock) -> None:
        """The server error on the pre-read of an unknown ID exits non-zero."""
        mock_ws = MagicMock()
        mock_ws.delete_behavior.side_effect = ServerError(
            "Internal Server Error", status_code=500
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "delete", "999"])
        assert result.exit_code != 0
        assert "Server error (500)" in result.stderr


class TestBehaviorsDeleteForce:
    """Tests for the --force flag of mp behaviors delete."""

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_force_passes_through(self, mock_get_ws: MagicMock) -> None:
        """--force reaches both the single and the bulk delete."""
        mock_ws = MagicMock()
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "delete", "3001", "--force"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_behavior.assert_called_once_with(3001, force=True)

        result = runner.invoke(app, ["behaviors", "delete", "1", "2", "--force"])
        assert result.exit_code == 0, result.output
        mock_ws.delete_behaviors.assert_called_once_with([1, 2], force=True)

    @patch("mixpanel_headless.cli.commands.behaviors.get_workspace")
    def test_permission_refusal_exits_nonzero(self, mock_get_ws: MagicMock) -> None:
        """A delete guard refusal exits non-zero with the message on stderr."""
        from mixpanel_headless.exceptions import ParamValidationError

        mock_ws = MagicMock()
        mock_ws.delete_behavior.side_effect = ParamValidationError(
            "This account cannot edit saved behavior 3001. Pass force=True "
            "(CLI: --force) to delete it anyway.",
            code="BH4_DELETE_NOT_PERMITTED",
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(app, ["behaviors", "delete", "3001"])
        assert result.exit_code != 0
        assert "--force" in result.stderr

    def test_help_explains_the_guard(self) -> None:
        """The delete help names --force and the superadmin hazard."""
        result = runner.invoke(app, ["behaviors", "delete", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.stdout
        assert "superadmin" in result.stdout
