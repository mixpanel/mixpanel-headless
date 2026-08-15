"""Minimal value codecs for record mode (design D4.4 — PR-2 generic subset).

PR-3 owns the full per-type ``$type`` codec table (Filter, FunnelStep,
RetentionEvent, ...). This module ships the GENERIC encoders the PR-2 pilot
needs:

- ``call.input`` values: JSON natives pass through; ``datetime``/``date``,
  ``SecretStr``, ``bytes``, Pydantic models, dataclasses, and callables are
  ``$type``-tagged per the vector-schema ``taggedValue`` convention.
- ``expect.result``/``expect.output`` values: same, except Pydantic models
  and dataclasses serialize to their plain to-dict shape (schema ``result``
  comment) while ``datetime`` and ``bytes`` stay ``$type``-tagged (design
  D4.2 item 4 / D6 rule 11).

Anything unencodable raises :class:`UnencodableValueError`, which the plugin
maps to the manifest ``unserializable_input`` bucket (design D10) — never a
silent drop. Lone surrogates and non-finite floats are rejected here at
record time per design D6 rules 2 and 5.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as _dt
import math
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel, SecretStr

_MAX_DEPTH = 64
"""Recursion guard for pathological self-referencing structures."""


class UnencodableValueError(Exception):
    """Raised when a captured value cannot be encoded into vector JSON.

    The record plugin catches this and logs the capture under the manifest
    ``unserializable_input`` category (design D10) instead of emitting a
    vector.
    """


def _reject_bad_string(value: str) -> str:
    """Return ``value`` unchanged after rejecting lone surrogates.

    Design D6 rule 2: lone surrogates are illegal in vectors because the
    canonical form is UTF-8, which cannot encode an unpaired surrogate.

    Args:
        value: Candidate string for vector JSON.

    Returns:
        The same string when it is valid UTF-8-encodable text.

    Raises:
        UnencodableValueError: If the string contains a lone surrogate.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise UnencodableValueError(
            f"string contains a lone surrogate: {value!r}"
        ) from exc
    return value


def _reject_bad_float(value: float) -> float:
    """Return ``value`` unchanged after rejecting non-finite floats.

    Design D6 rule 5: ``NaN``/``Infinity`` are illegal in vectors and the
    encoder rejects them at record time.

    Args:
        value: Candidate float for vector JSON.

    Returns:
        The same float when finite.

    Raises:
        UnencodableValueError: If the float is NaN or infinite.
    """
    if not math.isfinite(value):
        raise UnencodableValueError(f"non-finite float in captured value: {value!r}")
    return value


def _encode_bytes(value: bytes) -> dict[str, str]:
    """Encode raw bytes as the ``$type: bytes`` tagged object (design D4.4).

    Args:
        value: Raw byte payload (e.g. ``upload_to_signed_url`` csv_bytes).

    Returns:
        ``{"$type": "bytes", "encoding": "base64", "data": <b64>}``.
    """
    return {
        "$type": "bytes",
        "encoding": "base64",
        "data": base64.b64encode(value).decode("ascii"),
    }


def _encode_common(value: object, depth: int, *, tagged_models: bool) -> Any:
    """Shared recursive encoder behind the input/expect entry points.

    Args:
        value: Arbitrary captured Python value.
        depth: Current recursion depth (guarded by ``_MAX_DEPTH``).
        tagged_models: When True (input position), Pydantic models and
            dataclasses become ``{"$type": <ClassName>, ...fields}`` tagged
            objects; when False (expect position), they serialize to their
            plain to-dict shape.

    Returns:
        A JSON-encodable structure.

    Raises:
        UnencodableValueError: If any nested value cannot be encoded.
    """
    if depth > _MAX_DEPTH:
        raise UnencodableValueError("value nesting exceeds the codec depth guard")
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return _reject_bad_float(value)
    if isinstance(value, str):
        return _reject_bad_string(value)
    if isinstance(value, bytes | bytearray):
        return _encode_bytes(bytes(value))
    if isinstance(value, _dt.datetime):
        return {"$type": "datetime", "iso": value.isoformat()}
    if isinstance(value, _dt.date):
        return {"$type": "date", "iso": value.isoformat()}
    if isinstance(value, SecretStr):
        # D5.5: SecretStr values are fake test values and serialize revealed;
        # the D5.4 redaction screen is the real-secret tripwire.
        return {
            "$type": "SecretStr",
            "value": _reject_bad_string(value.get_secret_value()),
        }
    if isinstance(value, Enum):
        return _encode_common(value.value, depth + 1, tagged_models=tagged_models)
    if isinstance(value, BaseModel):
        try:
            dumped = value.model_dump(mode="json")
        except Exception as exc:  # pydantic serialization is type-dependent
            raise UnencodableValueError(
                f"pydantic model {type(value).__name__} failed model_dump: {exc}"
            ) from exc
        encoded = {
            str(k): _encode_common(v, depth + 1, tagged_models=tagged_models)
            for k, v in dumped.items()
        }
        if tagged_models:
            return {"$type": type(value).__name__, **encoded}
        return encoded
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {
            f.name: _encode_common(
                getattr(value, f.name), depth + 1, tagged_models=tagged_models
            )
            for f in dataclasses.fields(value)
        }
        if tagged_models:
            return {"$type": type(value).__name__, **fields}
        return fields
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise UnencodableValueError(
                    f"non-string mapping key {k!r} cannot enter vector JSON"
                )
            out[_reject_bad_string(k)] = _encode_common(
                v, depth + 1, tagged_models=tagged_models
            )
        return out
    if isinstance(value, Sequence):
        return [
            _encode_common(v, depth + 1, tagged_models=tagged_models) for v in value
        ]
    if isinstance(value, set | frozenset):
        raise UnencodableValueError(
            "set values have no deterministic vector encoding (design D3 "
            "determinism); use the PR-3 per-type codec table instead"
        )
    raise UnencodableValueError(
        f"no codec for {type(value).__module__}.{type(value).__name__} "
        "(extend conformance/record/codecs.py — PR-3 owns the full table)"
    )


def encode_input_value(value: object) -> Any:
    """Encode a single ``call.input`` value (design D4.4 tagged convention).

    Args:
        value: The captured argument value.

    Returns:
        A JSON-encodable structure; rich types are ``$type``-tagged.

    Raises:
        UnencodableValueError: If the value has no codec.
    """
    return _encode_common(value, 0, tagged_models=True)


def encode_input_kwargs(arguments: Mapping[str, object]) -> dict[str, Any]:
    """Encode a bound-arguments mapping into a vector ``call.input`` object.

    Callable-valued arguments become ``{"$type": "callback", "name": <kwarg>}``
    per design D4.4 — their observed call logs are diffed via
    ``expect.callback_calls``, not their identity.

    Args:
        arguments: Explicitly-passed arguments keyed by parameter name
            (defaults must NOT be materialized here — design D1.2).

    Returns:
        The encoded ``call.input`` dictionary.

    Raises:
        UnencodableValueError: If any argument value has no codec.
    """
    encoded: dict[str, Any] = {}
    for name, value in arguments.items():
        if callable(value) and not isinstance(value, type):
            encoded[name] = {"$type": "callback", "name": name}
        else:
            encoded[name] = encode_input_value(value)
    return encoded


def encode_expect_value(value: object) -> Any:
    """Encode an ``expect.result``/``expect.output`` value (design D6/D4.2).

    Pydantic models and dataclasses serialize to their plain to-dict shape
    (the schema ``result`` comment); ``datetime`` and ``bytes`` values stay
    ``$type``-tagged (D6 rule 11 / expect.output encoding rules).

    Args:
        value: The value the library returned (or yielded).

    Returns:
        A JSON-encodable structure.

    Raises:
        UnencodableValueError: If the value has no codec.
    """
    return _encode_common(value, 0, tagged_models=False)
