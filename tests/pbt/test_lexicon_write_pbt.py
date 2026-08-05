"""Property-based tests for Lexicon metadata write serialization (PR2).

Invariants:
- ``model_dump(by_alias=True)`` never emits the snake_case forms of the
  metadata fields (the API only understands camelCase).
- ``exclude_none=True`` omits unset fields entirely.
- snake_case construction round-trips through the camelCase dump.
"""

from __future__ import annotations

from typing import Literal

from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless.types import (
    BulkEventUpdate,
    BulkPropertyUpdate,
    UpdateEventDefinitionParams,
    UpdatePropertyDefinitionParams,
)

_text = st.text(min_size=1, max_size=20)
# Typed so the pydantic mypy plugin sees the Literal the write models require.
_RESOURCE_TYPES: list[Literal["Event", "User"]] = ["Event", "User"]


@given(display_name=st.none() | _text, description=st.none() | _text)
def test_event_update_never_emits_snake(
    display_name: str | None, description: str | None
) -> None:
    """Event update dumps never contain ``display_name`` (snake)."""
    params = UpdateEventDefinitionParams(
        display_name=display_name, description=description
    )
    body = params.model_dump(exclude_none=True, by_alias=True)
    assert "display_name" not in body
    if display_name is not None:
        assert body["displayName"] == display_name
    else:
        assert "displayName" not in body


@given(
    display_name=st.none() | _text,
    example_value=st.none() | _text,
    resource_type=st.none() | st.sampled_from(_RESOURCE_TYPES),
)
def test_property_update_emits_only_camel(
    display_name: str | None,
    example_value: str | None,
    resource_type: Literal["Event", "User"] | None,
) -> None:
    """Property update dumps emit camelCase metadata keys and no snake forms."""
    params = UpdatePropertyDefinitionParams(
        display_name=display_name,
        example_value=example_value,
        resource_type=resource_type,
    )
    body = params.model_dump(exclude_none=True, by_alias=True)
    for snake in ("display_name", "example_value", "resource_type"):
        assert snake not in body
    if display_name is not None:
        assert body["displayName"] == display_name
    if example_value is not None:
        assert body["exampleValue"] == example_value
    if resource_type is not None:
        assert body["resourceType"] == resource_type


@given(
    resource_type=st.sampled_from(_RESOURCE_TYPES),
    display_name=st.none() | _text,
    example_value=st.none() | _text,
)
def test_bulk_property_update_emits_only_camel(
    resource_type: Literal["Event", "User"],
    display_name: str | None,
    example_value: str | None,
) -> None:
    """Bulk property entries dump camelCase keys and never the snake forms."""
    entry = BulkPropertyUpdate(
        name="p",
        resource_type=resource_type,
        display_name=display_name,
        example_value=example_value,
    )
    body = entry.model_dump(exclude_none=True, by_alias=True)
    for snake in ("display_name", "example_value", "resource_type"):
        assert snake not in body
    assert body["resourceType"] == resource_type
    if display_name is not None:
        assert body["displayName"] == display_name
    if example_value is not None:
        assert body["exampleValue"] == example_value


@given(
    display_name=st.none() | _text,
    team_contacts=st.none() | st.lists(_text, max_size=3),
    contacts=st.none() | st.lists(_text, max_size=3),
)
def test_bulk_event_update_keeps_contacts_snake(
    display_name: str | None,
    team_contacts: list[str] | None,
    contacts: list[str] | None,
) -> None:
    """Bulk event entries camelCase only ``display_name``; contact lists stay snake.

    This is the exact invariant the per-field-alias strategy on
    ``BulkEventUpdate`` exists to protect: ``display_name`` must reach the payload
    as ``displayName`` while ``team_contacts`` / ``contacts`` keep their
    established snake_case shape in the same payload.
    """
    entry = BulkEventUpdate(
        name="e",
        display_name=display_name,
        team_contacts=team_contacts,
        contacts=contacts,
    )
    body = entry.model_dump(exclude_none=True, by_alias=True)
    assert "display_name" not in body
    if display_name is not None:
        assert body["displayName"] == display_name
    if team_contacts is not None:
        assert body["team_contacts"] == team_contacts
        assert "teamContacts" not in body
    if contacts is not None:
        assert body["contacts"] == contacts
