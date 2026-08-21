"""Response-model validation seam for App API payloads (E2 coding pass §1.7).

Wraps ``pydantic.ValidationError`` raised while parsing Mixpanel API
responses into the domain :class:`~mixpanel_headless.exceptions.ResponseValidationError`
carrying the generic ``RESPONSE_VALIDATION_ERROR`` registry code. Every
response-side ``model_validate`` call in ``workspace.py`` and
``api_client.py`` routes through these helpers so malformed server payloads
surface as coded, hierarchy-catchable errors instead of raw pydantic ones.

Functions:
    validate_response_model: Validate one payload against a response model.
    validate_response_models: Validate a sequence of payloads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import pydantic

from mixpanel_headless.exceptions import ResponseValidationError

if TYPE_CHECKING:
    from collections.abc import Iterable

_ModelT = TypeVar("_ModelT", bound=pydantic.BaseModel)


def validate_response_model(
    model: type[_ModelT],
    payload: object,
    *,
    endpoint: str,
) -> _ModelT:
    """Validate an API response payload against a Pydantic response model.

    Args:
        model: The Pydantic response model class to validate against.
        payload: The raw (already JSON-decoded) response payload.
        endpoint: Name of the calling method (e.g. ``"create_dashboard"``),
            used for the error message and debugging context.

    Returns:
        The validated model instance.

    Raises:
        ResponseValidationError: The payload does not conform to *model*
            (code ``RESPONSE_VALIDATION_ERROR``); the original
            ``pydantic.ValidationError`` is chained via ``__cause__`` and
            its structured error list is carried in ``details``.

    Example:
        ```python
        dashboard = validate_response_model(
            Dashboard, raw, endpoint="get_dashboard"
        )
        ```
    """
    try:
        return model.model_validate(payload)
    except pydantic.ValidationError as exc:
        raise ResponseValidationError(
            f"{endpoint}: API response failed {model.__name__} validation",
            details={
                "model": model.__name__,
                "errors": exc.errors(include_url=False),
            },
        ) from exc


def validate_response_models(
    model: type[_ModelT],
    payloads: Iterable[object],
    *,
    endpoint: str,
) -> list[_ModelT]:
    """Validate a sequence of API response payloads against a response model.

    Args:
        model: The Pydantic response model class to validate against.
        payloads: Iterable of raw (already JSON-decoded) payload items.
        endpoint: Name of the calling method (e.g. ``"list_dashboards"``),
            used for the error message and debugging context.

    Returns:
        List of validated model instances, in input order.

    Raises:
        ResponseValidationError: Any item does not conform to *model*
            (code ``RESPONSE_VALIDATION_ERROR``); the original
            ``pydantic.ValidationError`` is chained via ``__cause__``.

    Example:
        ```python
        dashboards = validate_response_models(
            Dashboard, raw, endpoint="list_dashboards"
        )
        ```
    """
    return [
        validate_response_model(model, payload, endpoint=endpoint)
        for payload in payloads
    ]
