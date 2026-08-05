"""Tests for writing Lexicon metadata: display_name, example_value, resource_type.

The Mixpanel data-definitions API reads and writes these fields in camelCase
(``displayName``, ``exampleValue``, ``resourceType``). Before this change the
update parameter models lacked the fields and the facade dumped snake_case, so
``display_name`` writes were silently dropped. These tests lock the payload format
end to end:

- the parameter models emit camelCase under ``model_dump(by_alias=True)`` while
  leaving existing single-word fields untouched;
- the read model parses the camelCase fields back;
- the Workspace facade sends camelCase bodies for events and for event / user
  properties, single and bulk (group properties are a follow-up, see the PR);
- the CLI exposes ``--display-name`` / ``--example-value`` / ``--resource-type``.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from unittest.mock import MagicMock, patch

import httpx
import typer.testing
from pydantic import SecretStr

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless.cli.main import app
from mixpanel_headless.types import (
    BulkEventUpdate,
    BulkPropertyUpdate,
    BulkUpdateEventsParams,
    BulkUpdatePropertiesParams,
    EventDefinition,
    PropertyDefinition,
    UpdateEventDefinitionParams,
    UpdatePropertyDefinitionParams,
)
from mixpanel_headless.workspace import Workspace

runner = typer.testing.CliRunner()

_SESSION = Session(
    account=ServiceAccount(
        name="t",
        region="us",
        username="u",
        secret=SecretStr("s"),
        default_project="12345",
    ),
    project=Project(id="12345"),
)


class TestParamSerialization:
    """``model_dump(by_alias=True)`` emits the camelCase the API expects."""

    def test_event_update_emits_camel_display_name(self) -> None:
        """``display_name`` serializes to ``displayName``."""
        params = UpdateEventDefinitionParams(
            display_name="App Open", description="user opened the app"
        )
        body = params.model_dump(exclude_none=True, by_alias=True)
        assert body == {"displayName": "App Open", "description": "user opened the app"}

    def test_event_update_single_word_fields_unchanged(self) -> None:
        """Single-word fields are unchanged by aliasing."""
        body = UpdateEventDefinitionParams(hidden=True, verified=True).model_dump(
            exclude_none=True, by_alias=True
        )
        assert body == {"hidden": True, "verified": True}

    def test_property_update_emits_camel(self) -> None:
        """Property updates emit ``displayName``/``exampleValue``/``resourceType``."""
        params = UpdatePropertyDefinitionParams(
            display_name="Plan Type", example_value="free, pro", resource_type="User"
        )
        body = params.model_dump(exclude_none=True, by_alias=True)
        assert body == {
            "displayName": "Plan Type",
            "exampleValue": "free, pro",
            "resourceType": "User",
        }

    def test_resource_type_passes_through_verbatim(self) -> None:
        """Each accepted ``resource_type`` reaches the body as ``resourceType``.

        The field is constrained to the capitalized ``"Event"`` / ``"User"`` the
        data-definitions API accepts (also what mixpanel-power-tools sends); the
        chosen value is forwarded to the payload key unchanged.
        """
        values: tuple[Literal["Event", "User"], ...] = ("Event", "User")
        for value in values:
            body = UpdatePropertyDefinitionParams(resource_type=value).model_dump(
                exclude_none=True, by_alias=True
            )
            assert body == {"resourceType": value}

    def test_bulk_event_update_aliases_display_name_only(self) -> None:
        """Bulk event display_name aliases without re-casing existing fields."""
        entry = BulkEventUpdate(
            name="purchase", display_name="Purchase", team_contacts=["t@x.io"]
        )
        body = entry.model_dump(exclude_none=True, by_alias=True)
        assert body["displayName"] == "Purchase"
        assert body["name"] == "purchase"
        # Existing fields keep their established payload shape (not silently re-cased).
        assert body["team_contacts"] == ["t@x.io"]
        assert "displayName" in body and "display_name" not in body

    def test_bulk_property_update_emits_camel(self) -> None:
        """Bulk property updates emit camelCase for the new fields."""
        entry = BulkPropertyUpdate(
            name="plan",
            resource_type="Event",
            display_name="Plan",
            example_value="free, pro",
        )
        body = entry.model_dump(exclude_none=True, by_alias=True)
        assert body["displayName"] == "Plan"
        assert body["exampleValue"] == "free, pro"
        assert body["resourceType"] == "Event"

    def test_snake_kwargs_still_construct(self) -> None:
        """Construction by snake_case field name still works."""
        assert UpdatePropertyDefinitionParams(display_name="x").display_name == "x"
        assert UpdateEventDefinitionParams(display_name="y").display_name == "y"

    def test_camel_input_validates(self) -> None:
        """camelCase input also validates for the single-update models.

        Guards the ``alias_generator``: a camelCase payload (the shape the API
        and reads use) populates the snake_case attribute.
        """
        prop = UpdatePropertyDefinitionParams.model_validate({"displayName": "x"})
        assert prop.display_name == "x"
        event = UpdateEventDefinitionParams.model_validate({"displayName": "y"})
        assert event.display_name == "y"

    def test_bulk_event_update_accepts_camel_input(self) -> None:
        """camelCase ``displayName`` input round-trips (the events bulk-update path).

        ``mp lexicon events bulk-update --data`` feeds camelCase JSON (the shape
        the API and ``events get`` return). Before the validation alias was added
        this was silently dropped, sending an empty update.
        """
        parsed: dict[str, Any] = json.loads(
            '{"events": [{"name": "purchase", "displayName": "Purchase"}]}'
        )
        params = BulkUpdateEventsParams(**parsed)
        assert params.events[0].display_name == "Purchase"
        # dump (camelCase) -> revalidate preserves the field
        redumped: dict[str, Any] = params.model_dump(exclude_none=True, by_alias=True)
        assert BulkUpdateEventsParams(**redumped).events[0].display_name == "Purchase"


class TestReadModelParsing:
    """The read model parses the camelCase metadata fields."""

    def test_property_definition_parses_display_and_example(self) -> None:
        """``displayName``/``exampleValue`` populate the snake_case attributes."""
        prop = PropertyDefinition.model_validate(
            {
                "name": "$city",
                "displayName": "City",
                "exampleValue": "San Francisco",
                "resourceType": "Event",
            }
        )
        assert prop.display_name == "City"
        assert prop.example_value == "San Francisco"
        assert prop.resource_type == "Event"

    def test_event_definition_parses_camel_display_name(self) -> None:
        """``EventDefinition`` reads back camelCase ``displayName`` from the API."""
        ev = EventDefinition.model_validate(
            {"id": 1, "name": "purchase", "displayName": "Purchase"}
        )
        assert ev.display_name == "Purchase"


def _capture_workspace(captured: dict[str, Any], response: Any) -> Workspace:
    """Build a Workspace whose transport records the last request body."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.content:
            captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=response)

    client = MixpanelAPIClient(
        session=_SESSION, _transport=httpx.MockTransport(handler)
    )
    return Workspace(session=_SESSION, _api_client=client)


class TestFacadeSendsCamelCase:
    """The Workspace facade sends camelCase bodies to the API."""

    def test_update_event_definition_body(self) -> None:
        """Event update sends ``displayName`` in the PATCH body."""
        captured: dict[str, Any] = {}
        ws = _capture_workspace(captured, {"results": {"id": 1, "name": "purchase"}})
        result = ws.update_event_definition(
            "purchase", UpdateEventDefinitionParams(display_name="Purchase")
        )
        assert isinstance(result, EventDefinition)
        assert captured["body"]["displayName"] == "Purchase"
        assert captured["body"]["name"] == "purchase"

    def test_update_property_definition_body(self) -> None:
        """Property update sends displayName/exampleValue/resourceType and reads it back."""
        captured: dict[str, Any] = {}
        ws = _capture_workspace(
            captured, {"results": {"id": 1, "name": "plan", "resourceType": "User"}}
        )
        result = ws.update_property_definition(
            "plan",
            UpdatePropertyDefinitionParams(
                display_name="Plan", example_value="free, pro", resource_type="User"
            ),
        )
        body = captured["body"]
        assert body["displayName"] == "Plan"
        assert body["exampleValue"] == "free, pro"
        assert body["resourceType"] == "User"
        assert body["name"] == "plan"
        # read-back: the API echoes the capitalized form into the parsed model
        assert result.resource_type == "User"

    def test_update_property_definition_user_scoped_body(self) -> None:
        """A user-property update sends resourceType=User to disambiguate.

        ``resourceType`` lets the PATCH target a user property that shares a name
        with an event property (the common Lexicon collision).
        """
        captured: dict[str, Any] = {}
        ws = _capture_workspace(captured, {"results": {"id": 1, "name": "tier"}})
        ws.update_property_definition(
            "tier",
            UpdatePropertyDefinitionParams(display_name="Tier", resource_type="User"),
        )
        assert captured["body"]["resourceType"] == "User"
        assert captured["body"]["displayName"] == "Tier"

    def test_update_custom_event_sends_camel(self) -> None:
        """Custom-event update (shares the event param model) sends displayName."""
        captured: dict[str, Any] = {}
        ws = _capture_workspace(
            captured, {"results": {"id": 1, "name": "ce", "customEventId": 7}}
        )
        ws.update_custom_event(
            7, UpdateEventDefinitionParams(display_name="Metric Tree Opened")
        )
        assert captured["body"]["displayName"] == "Metric Tree Opened"

    def test_bulk_update_event_definitions_body(self) -> None:
        """Bulk event update sends ``displayName`` per entry."""
        captured: dict[str, Any] = {}
        ws = _capture_workspace(captured, {"results": [{"id": 1, "name": "e"}]})
        ws.bulk_update_event_definitions(
            BulkUpdateEventsParams(events=[BulkEventUpdate(name="e", display_name="E")])
        )
        assert captured["body"]["events"][0]["displayName"] == "E"

    def test_bulk_update_property_definitions_body(self) -> None:
        """Bulk property update sends displayName/exampleValue per entry."""
        captured: dict[str, Any] = {}
        ws = _capture_workspace(captured, {"results": [{"id": 1, "name": "p"}]})
        ws.bulk_update_property_definitions(
            BulkUpdatePropertiesParams(
                properties=[
                    BulkPropertyUpdate(
                        name="p",
                        resource_type="Event",
                        display_name="P",
                        example_value="x",
                    )
                ]
            )
        )
        entry = captured["body"]["properties"][0]
        assert entry["displayName"] == "P"
        assert entry["exampleValue"] == "x"

    def test_bulk_update_property_definitions_user_scoped(self) -> None:
        """Bulk property update carries resourceType=User for user properties."""
        captured: dict[str, Any] = {}
        ws = _capture_workspace(captured, {"results": [{"id": 1, "name": "plan"}]})
        ws.bulk_update_property_definitions(
            BulkUpdatePropertiesParams(
                properties=[
                    BulkPropertyUpdate(
                        name="plan", resource_type="User", display_name="Plan"
                    )
                ]
            )
        )
        entry = captured["body"]["properties"][0]
        assert entry["resourceType"] == "User"
        assert entry["displayName"] == "Plan"


class TestCli:
    """The CLI exposes the new metadata flags."""

    @patch("mixpanel_headless.cli.commands.lexicon.get_workspace")
    def test_events_update_display_name_flag(self, mock_get_ws: MagicMock) -> None:
        """``--display-name`` reaches the update params."""
        mock_ws = MagicMock()
        mock_ws.update_event_definition.return_value = MagicMock(
            model_dump=MagicMock(
                return_value={"name": "purchase", "displayName": "Purchase"}
            )
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "lexicon",
                "events",
                "update",
                "--name",
                "purchase",
                "--display-name",
                "Purchase",
            ],
        )
        assert result.exit_code == 0
        params = mock_ws.update_event_definition.call_args[0][1]
        assert params.display_name == "Purchase"

    @patch("mixpanel_headless.cli.commands.lexicon.get_workspace")
    def test_properties_update_metadata_flags(self, mock_get_ws: MagicMock) -> None:
        """``--display-name``/``--example-value``/``--resource-type`` reach params."""
        mock_ws = MagicMock()
        mock_ws.update_property_definition.return_value = MagicMock(
            model_dump=MagicMock(return_value={"name": "plan"})
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            [
                "lexicon",
                "properties",
                "update",
                "--name",
                "plan",
                "--display-name",
                "Plan Type",
                "--example-value",
                "free, pro",
                "--resource-type",
                "User",
            ],
        )
        assert result.exit_code == 0
        params = mock_ws.update_property_definition.call_args[0][1]
        assert params.display_name == "Plan Type"
        assert params.example_value == "free, pro"
        assert params.resource_type == "User"

    @patch("mixpanel_headless.cli.commands.lexicon.get_workspace")
    def test_properties_update_omits_resource_type_by_default(
        self, mock_get_ws: MagicMock
    ) -> None:
        """Without --resource-type the param stays None (no always-send)."""
        mock_ws = MagicMock()
        mock_ws.update_property_definition.return_value = MagicMock(
            model_dump=MagicMock(return_value={"name": "plan"})
        )
        mock_get_ws.return_value = mock_ws

        result = runner.invoke(
            app,
            ["lexicon", "properties", "update", "--name", "plan", "--description", "x"],
        )
        assert result.exit_code == 0
        params = mock_ws.update_property_definition.call_args[0][1]
        assert params.resource_type is None
        # exclude_none keeps resourceType out of the payload body entirely
        assert "resourceType" not in params.model_dump(exclude_none=True, by_alias=True)

    @patch("mixpanel_headless.cli.commands.lexicon.get_workspace")
    def test_events_bulk_update_carries_display_name(
        self, mock_get_ws: MagicMock
    ) -> None:
        """`events bulk-update` JSON entries carry display_name through to params."""
        mock_ws = MagicMock()
        mock_ws.bulk_update_event_definitions.return_value = []
        mock_get_ws.return_value = mock_ws

        payload = json.dumps(
            {"events": [{"name": "purchase", "display_name": "Purchase"}]}
        )
        result = runner.invoke(
            app, ["lexicon", "events", "bulk-update", "--data", payload]
        )
        assert result.exit_code == 0
        params = mock_ws.bulk_update_event_definitions.call_args[0][0]
        assert params.events[0].display_name == "Purchase"
