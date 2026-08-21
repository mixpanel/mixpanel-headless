"""Unit tests for the response-model validation seam (E2 coding pass §1.7).

Covers ``validate_response_model`` / ``validate_response_models``: success
passthrough, the ``ResponseValidationError`` wrap with the generic
``RESPONSE_VALIDATION_ERROR`` code, structured details, and exception
chaining. Assertions never touch message text (R5.4).
"""

from __future__ import annotations

import pydantic
import pytest

from mixpanel_headless._internal.response_validation import (
    validate_response_model,
    validate_response_models,
)
from mixpanel_headless.exceptions import (
    MixpanelHeadlessError,
    ResponseValidationError,
)


class _Widget(pydantic.BaseModel):
    """Minimal response model for seam tests."""

    id: int
    name: str


class TestValidateResponseModel:
    """Tests for the single-payload seam helper."""

    def test_valid_payload_returns_model(self) -> None:
        """A conforming payload passes through as a model instance."""
        widget = validate_response_model(
            _Widget, {"id": 1, "name": "w"}, endpoint="get_widget"
        )
        assert widget == _Widget(id=1, name="w")

    def test_invalid_payload_raises_coded_error(self) -> None:
        """A non-conforming payload raises the generic coded wrap."""
        with pytest.raises(ResponseValidationError) as excinfo:
            validate_response_model(_Widget, {}, endpoint="get_widget")
        assert excinfo.value.code == "RESPONSE_VALIDATION_ERROR"

    def test_details_carry_model_and_errors(self) -> None:
        """The wrap's details are structured: model name + pydantic errors."""
        with pytest.raises(ResponseValidationError) as excinfo:
            validate_response_model(_Widget, {"id": "x"}, endpoint="get_widget")
        details = excinfo.value.details
        assert details["model"] == "_Widget"
        assert isinstance(details["errors"], list)
        assert len(details["errors"]) > 0

    def test_pydantic_cause_is_chained(self) -> None:
        """The original pydantic error stays chained via __cause__."""
        with pytest.raises(ResponseValidationError) as excinfo:
            validate_response_model(_Widget, {}, endpoint="get_widget")
        assert isinstance(excinfo.value.__cause__, pydantic.ValidationError)

    def test_wrap_is_hierarchy_error_not_value_error(self) -> None:
        """The wrap is a MixpanelHeadlessError and deliberately NOT a ValueError.

        Unlike ``pydantic.ValidationError``, ``ResponseValidationError``
        does not impersonate ``ValueError`` — the E2-sanctioned behavior
        change at response seams.
        """
        with pytest.raises(MixpanelHeadlessError) as excinfo:
            validate_response_model(_Widget, {}, endpoint="get_widget")
        assert not isinstance(excinfo.value, ValueError)


class TestValidateResponseModels:
    """Tests for the list-payload seam helper."""

    def test_all_valid_payloads_return_models(self) -> None:
        """A list of conforming payloads maps to model instances in order."""
        widgets = validate_response_models(
            _Widget,
            [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
            endpoint="list_widgets",
        )
        assert widgets == [_Widget(id=1, name="a"), _Widget(id=2, name="b")]

    def test_any_invalid_payload_raises_coded_error(self) -> None:
        """One bad item is enough to trigger the coded wrap."""
        with pytest.raises(ResponseValidationError) as excinfo:
            validate_response_models(
                _Widget,
                [{"id": 1, "name": "a"}, {}],
                endpoint="list_widgets",
            )
        assert excinfo.value.code == "RESPONSE_VALIDATION_ERROR"

    def test_empty_payload_list_returns_empty_list(self) -> None:
        """An empty payload list validates to an empty model list."""
        assert validate_response_models(_Widget, [], endpoint="list_widgets") == []
