"""Property-based tests for Lexicon metadata write serialization (PR2).

Invariants:
- ``model_dump(by_alias=True)`` never emits the snake_case forms of the
  metadata fields (the API only understands camelCase).
- ``exclude_none=True`` omits unset fields entirely.
- snake_case construction round-trips through the camelCase dump.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless.types import (
    UpdateEventDefinitionParams,
    UpdatePropertyDefinitionParams,
)

_text = st.text(min_size=1, max_size=20)


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
    resource_type=st.none() | st.sampled_from(["Event", "User"]),
)
def test_property_update_emits_only_camel(
    display_name: str | None,
    example_value: str | None,
    resource_type: str | None,
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
