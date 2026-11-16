"""Integration tests for inspect CLI commands."""

from __future__ import annotations

import json
import warnings
from unittest.mock import MagicMock, patch

import httpx
import pytest
from typer.testing import CliRunner

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless.cli.main import app
from mixpanel_headless.exceptions import QueryError
from mixpanel_headless.types import (
    FunnelInfo,
    LexiconDefinition,
    LexiconProperty,
    LexiconSchema,
    SavedCohort,
    TopEvent,
)
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session


class TestInspectEvents:
    """Tests for mp inspect events command."""

    def test_events_json_format(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test listing events in JSON format."""
        mock_workspace.events.return_value = ["Event A", "Event B", "Event C"]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(app, ["inspect", "events", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data == ["Event A", "Event B", "Event C"]

    def test_events_plain_format(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test listing events in plain format."""
        mock_workspace.events.return_value = ["Event A", "Event B"]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(app, ["inspect", "events", "--format", "plain"])

        assert result.exit_code == 0
        assert "Event A" in result.stdout
        assert "Event B" in result.stdout


class TestInspectProperties:
    """Tests for mp inspect properties command."""

    def test_properties_for_event(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test listing properties for an event."""
        mock_workspace.properties.return_value = ["prop1", "prop2", "prop3"]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app, ["inspect", "properties", "--event", "Sign Up", "--format", "json"]
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data == ["prop1", "prop2", "prop3"]
        mock_workspace.properties.assert_called_once_with("Sign Up")

    def test_classified_properties_are_left_out_with_a_warning(
        self, cli_runner: CliRunner
    ) -> None:
        """Classified properties do not fail the command: it lists the rest.

        Runs the real client and discovery service on a mock transport that
        answers ``toptypes`` the way the server answers an account without
        classified-data access.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Answer the toptypes request with one classified property.

            Args:
                request: The properties request.

            Returns:
                The property map.
            """
            assert request.url.path == "/api/query/events/properties/toptypes"
            return httpx.Response(
                200,
                json={
                    "plan": {"count": 50, "type": "string"},
                    "amount": {"count": 9, "type": "number"},
                    "email": {"count": 0, "type": "string", "sensitive": True},
                },
            )

        session = make_session(project_id="12345", region="us", oauth_token="t")
        client = MixpanelAPIClient(
            session=session, _transport=httpx.MockTransport(handler)
        )
        workspace = Workspace(session=session, _api_client=client)

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=workspace,
        ):
            result = cli_runner.invoke(
                app,
                ["inspect", "properties", "--event", "Purchase", "--format", "json"],
            )

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == ["amount", "plan"]
        stderr = " ".join(result.stderr.split())
        assert "Warning: 1 property of event 'Purchase' is classified" in stderr
        assert "left out: email." in stderr
        assert "UserWarning" not in stderr

    def test_no_warning_prints_no_warning_line(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A call that warns about nothing prints no ``Warning:`` line."""
        mock_workspace.properties.return_value = ["plan"]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app, ["inspect", "properties", "--event", "Purchase"]
            )

        assert result.exit_code == 0, result.output
        assert "Warning" not in result.stderr

    @pytest.mark.parametrize("fmt", ["json", "jsonl", "table", "csv", "plain"])
    def test_each_user_warning_is_one_warning_line(
        self, cli_runner: CliRunner, mock_workspace: MagicMock, fmt: str
    ) -> None:
        """Every ``UserWarning`` of the call prints, in every output format.

        Args:
            cli_runner: CLI runner fixture.
            mock_workspace: Mock workspace fixture.
            fmt: The ``--format`` value.
        """

        class _SubWarning(UserWarning):
            """A subclass, to show that the category check accepts subclasses."""

        def properties(event: str) -> list[str]:
            """Warn twice, then return one property.

            Args:
                event: The event name.

            Returns:
                The property names.
            """
            warnings.warn("first notice", UserWarning, stacklevel=1)
            warnings.warn("second notice", _SubWarning, stacklevel=1)
            return ["plan"]

        mock_workspace.properties.side_effect = properties

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app, ["inspect", "properties", "--event", "Purchase", "--format", fmt]
            )

        assert result.exit_code == 0, result.output
        stderr = " ".join(result.stderr.split())
        assert "Warning: first notice" in stderr
        assert "Warning: second notice" in stderr
        assert "plan" in result.stdout
        assert "notice" not in result.stdout

    def test_warning_line_prints_under_an_ignore_filter(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """The left-out names print even when a filter ignores warnings.

        The warning is the only signal for the properties that the command
        leaves out, so the command shows it under every warning filter.
        """

        def properties(event: str) -> list[str]:
            """Warn once, then return one property.

            Args:
                event: The event name.

            Returns:
                The property names.
            """
            warnings.warn("left out: email", UserWarning, stacklevel=1)
            return ["plan"]

        mock_workspace.properties.side_effect = properties

        with (
            warnings.catch_warnings(),
            patch(
                "mixpanel_headless.cli.commands.inspect.get_workspace",
                return_value=mock_workspace,
            ),
        ):
            warnings.simplefilter("ignore")
            result = cli_runner.invoke(
                app, ["inspect", "properties", "--event", "Purchase"]
            )

        assert result.exit_code == 0, result.output
        assert "Warning: left out: email" in " ".join(result.stderr.split())

    def test_rich_markup_in_a_warning_prints_as_text(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A property name with square brackets prints as it is.

        Without the escape, Rich reads ``[email]`` as a style tag and drops
        it, and ``[/x]`` stops the command with a markup error.
        """

        def properties(event: str) -> list[str]:
            """Warn about names that look like Rich markup.

            Args:
                event: The event name.

            Returns:
                The property names.
            """
            warnings.warn("left out: meta[email], [/x]", UserWarning, stacklevel=1)
            return ["plan"]

        mock_workspace.properties.side_effect = properties

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app, ["inspect", "properties", "--event", "Purchase"]
            )

        assert result.exit_code == 0, result.output
        assert "Warning: left out: meta[email], [/x]" in " ".join(result.stderr.split())

    def test_emoji_code_in_a_warning_prints_as_text(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A property name with a ``:word:`` part prints as it is.

        Rich replaces an emoji code such as ``:email:`` with a glyph. The
        warning is the only place that names the left-out properties, so
        the name must not change.
        """

        def properties(event: str) -> list[str]:
            """Warn about names that hold emoji codes.

            Args:
                event: The event name.

            Returns:
                The property names.
            """
            warnings.warn(
                "left out: contact:email:primary, account:id:hash",
                UserWarning,
                stacklevel=1,
            )
            return ["plan"]

        mock_workspace.properties.side_effect = properties

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app, ["inspect", "properties", "--event", "Purchase"]
            )

        assert result.exit_code == 0, result.output
        assert "Warning: left out: contact:email:primary, account:id:hash" in " ".join(
            result.stderr.split()
        )

    def test_warning_of_another_category_is_passed_on(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A warning that is not a ``UserWarning`` leaves the command's capture.

        The command records warnings to print the left-out names. It must
        not swallow the other categories: it hands each one back to Python's
        own display. Here a recorder around the command takes that display,
        so the warning arrives in the recorder and not as a ``Warning:``
        line.
        """

        def properties(event: str) -> list[str]:
            """Raise one warning of each kind, then return one property.

            Args:
                event: The event name.

            Returns:
                The property names.
            """
            warnings.warn("old option", FutureWarning, stacklevel=1)
            warnings.warn("left out: email", UserWarning, stacklevel=1)
            return ["plan"]

        mock_workspace.properties.side_effect = properties

        with (
            warnings.catch_warnings(record=True) as passed_on,
            patch(
                "mixpanel_headless.cli.commands.inspect.get_workspace",
                return_value=mock_workspace,
            ),
        ):
            warnings.simplefilter("always")
            result = cli_runner.invoke(
                app, ["inspect", "properties", "--event", "Purchase"]
            )

        assert result.exit_code == 0, result.output
        assert [(w.category, str(w.message)) for w in passed_on] == [
            (FutureWarning, "old option")
        ]
        stderr = " ".join(result.stderr.split())
        assert "Warning: left out: email" in stderr
        assert "old option" not in stderr

    def test_warnings_print_when_the_call_fails(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """A failed call still shows the warnings that came before the error."""

        def properties(event: str) -> list[str]:
            """Warn, then fail.

            Args:
                event: The event name.

            Raises:
                QueryError: Always.
            """
            warnings.warn("left out: email", UserWarning, stacklevel=1)
            raise QueryError("Bad event selector", status_code=400)

        mock_workspace.properties.side_effect = properties

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app, ["inspect", "properties", "--event", "Purchase"]
            )

        assert result.exit_code != 0
        stderr = " ".join(result.stderr.split())
        assert "Warning: left out: email" in stderr
        assert "Bad event selector" in stderr


class TestInspectValues:
    """Tests for mp inspect values command."""

    def test_values_with_all_options(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test listing values with event and limit options."""
        mock_workspace.property_values.return_value = ["value1", "value2"]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app,
                [
                    "inspect",
                    "values",
                    "--property",
                    "country",
                    "--event",
                    "Purchase",
                    "--limit",
                    "50",
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data == ["value1", "value2"]
        mock_workspace.property_values.assert_called_once_with(
            property_name="country", event="Purchase", limit=50
        )

    def test_values_without_event(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test listing values without event filter."""
        mock_workspace.property_values.return_value = ["US", "EU", "APAC"]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app,
                ["inspect", "values", "--property", "region", "--format", "json"],
            )

        assert result.exit_code == 0
        mock_workspace.property_values.assert_called_once_with(
            property_name="region", event=None, limit=100
        )


class TestInspectFunnels:
    """Tests for mp inspect funnels command."""

    def test_funnels_json_format(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test listing funnels in JSON format."""
        mock_workspace.funnels.return_value = [
            FunnelInfo(funnel_id=123, name="Checkout Funnel"),
            FunnelInfo(funnel_id=456, name="Signup Flow"),
        ]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(app, ["inspect", "funnels", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["funnel_id"] == 123
        assert data[0]["name"] == "Checkout Funnel"


class TestInspectCohorts:
    """Tests for mp inspect cohorts command."""

    def test_cohorts_json_format(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test listing cohorts in JSON format."""
        mock_workspace.cohorts.return_value = [
            SavedCohort(
                id=1,
                name="Power Users",
                count=1000,
                description="Active users",
                created="2024-01-01 12:00:00",
                is_visible=True,
            ),
            SavedCohort(
                id=2,
                name="New Users",
                count=500,
                description="Recent signups",
                created="2024-01-15 10:00:00",
                is_visible=True,
            ),
        ]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(app, ["inspect", "cohorts", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[0]["name"] == "Power Users"
        assert data[0]["count"] == 1000


class TestInspectTopEvents:
    """Tests for mp inspect top-events command."""

    def test_top_events_default_options(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test listing top events with default options."""
        mock_workspace.top_events.return_value = [
            TopEvent(event="Page View", count=10000, percent_change=5.2),
            TopEvent(event="Sign Up", count=500, percent_change=-2.1),
        ]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app, ["inspect", "top-events", "--format", "json"]
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["event"] == "Page View"
        assert data[0]["count"] == 10000
        mock_workspace.top_events.assert_called_once_with(type="general", limit=10)

    def test_top_events_with_type_and_limit(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test listing top events with custom type and limit."""
        mock_workspace.top_events.return_value = []

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app,
                [
                    "inspect",
                    "top-events",
                    "--type",
                    "unique",
                    "--limit",
                    "5",
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 0
        mock_workspace.top_events.assert_called_once_with(type="unique", limit=5)


class TestInspectLexiconSchemas:
    """Tests for mp inspect lexicon-schemas command."""

    def test_lexicon_schemas_json_format(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test listing Lexicon schemas in JSON format."""
        mock_workspace.lexicon_schemas.return_value = [
            LexiconSchema(
                entity_type="event",
                name="Purchase",
                schema_json=LexiconDefinition(
                    description="User made a purchase",
                    properties={
                        "amount": LexiconProperty(
                            type="number", description="Amount", metadata=None
                        ),
                    },
                    metadata=None,
                ),
            ),
            LexiconSchema(
                entity_type="profile",
                name="Plan Type",
                schema_json=LexiconDefinition(
                    description="User subscription plan",
                    properties={},
                    metadata=None,
                ),
            ),
        ]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app, ["inspect", "lexicon-schemas", "--format", "json"]
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data) == 2
        assert data[0]["entity_type"] == "event"
        assert data[0]["name"] == "Purchase"
        assert data[0]["property_count"] == 1
        assert data[1]["entity_type"] == "profile"

    def test_lexicon_schemas_with_type_filter(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test filtering Lexicon schemas by entity type."""
        mock_workspace.lexicon_schemas.return_value = [
            LexiconSchema(
                entity_type="event",
                name="Login",
                schema_json=LexiconDefinition(
                    description="User logged in",
                    properties={},
                    metadata=None,
                ),
            ),
        ]

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app,
                ["inspect", "lexicon-schemas", "--type", "event", "--format", "json"],
            )

        assert result.exit_code == 0
        mock_workspace.lexicon_schemas.assert_called_once_with(entity_type="event")

    def test_lexicon_schemas_invalid_type(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test invalid entity type returns error."""
        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app, ["inspect", "lexicon-schemas", "--type", "invalid"]
            )

        assert result.exit_code == 3  # INVALID_ARGS


class TestInspectLexiconSchema:
    """Tests for mp inspect lexicon-schema command."""

    def test_lexicon_schema_json_format(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test getting single Lexicon schema in JSON format."""
        mock_workspace.lexicon_schema.return_value = LexiconSchema(
            entity_type="event",
            name="Purchase",
            schema_json=LexiconDefinition(
                description="User made a purchase",
                properties={
                    "amount": LexiconProperty(
                        type="number", description="Purchase amount", metadata=None
                    ),
                    "currency": LexiconProperty(
                        type="string", description="Currency code", metadata=None
                    ),
                },
                metadata=None,
            ),
        )

        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app,
                [
                    "inspect",
                    "lexicon-schema",
                    "--type",
                    "event",
                    "--name",
                    "Purchase",
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["entity_type"] == "event"
        assert data["name"] == "Purchase"
        assert "amount" in data["schema_json"]["properties"]
        assert "currency" in data["schema_json"]["properties"]
        mock_workspace.lexicon_schema.assert_called_once_with("event", "Purchase")

    def test_lexicon_schema_invalid_type(
        self, cli_runner: CliRunner, mock_workspace: MagicMock
    ) -> None:
        """Test invalid entity type returns error."""
        with patch(
            "mixpanel_headless.cli.commands.inspect.get_workspace",
            return_value=mock_workspace,
        ):
            result = cli_runner.invoke(
                app,
                [
                    "inspect",
                    "lexicon-schema",
                    "--type",
                    "invalid",
                    "--name",
                    "Test",
                ],
            )

        assert result.exit_code == 3  # INVALID_ARGS
