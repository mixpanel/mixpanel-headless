"""Value codecs for record mode and replay (design D4.4 full ``$type`` table).

One codec table, two directions:

- **Encode** (record time / oracle requests): ``call.input`` values pass
  JSON natives through; ``datetime``/``date``, ``SecretStr``, ``bytes``,
  Pydantic models, dataclasses, and callables are ``$type``-tagged per the
  vector-schema ``taggedValue`` convention. ``expect.result`` /
  ``expect.output`` values are the same, except Pydantic models and
  dataclasses serialize to their plain to-dict shape (schema ``result``
  comment) while ``datetime`` and ``bytes`` stay ``$type``-tagged (design
  D4.2 item 4 / D6 rule 11).
- **Decode** (Python corpus runner, design D7; oracle-py, design D14):
  ``$type``-tagged objects reconstruct the original rich values through the
  :data:`DATACLASS_CODECS` table — the design D4.4 set (``Filter``,
  ``FunnelStep``, ``RetentionEvent``, ``FlowStep``, ``Metric``,
  ``CohortMetric``, ``Formula``, ``GroupBy``, ``CohortBreakdown``,
  ``FrequencyBreakdown``, ``FrequencyFilter``, ``TimeComparison``,
  ``CohortDefinition``, ``UserAction``) plus the nested types those carry
  (``CohortCriteria``, ``CustomPropertyRef``, ``InlineCustomProperty``,
  ``PropertyInput``) and the non-dataclass codecs (``datetime``, ``date``,
  ``SecretStr``, ``bytes``, ``callback`` — replayed as a
  :class:`RecordingCallback` stub whose call log is diffed against
  ``expect.callback_calls``).

Registry entries additionally name an OUTPUT codec (design D4.4);
:func:`encode_output` dispatches it (``json`` / ``validation_errors`` per
D4.3 / ``model_name`` per D4.2 item 7 / ``selector_str``).

Anything unencodable raises :class:`UnencodableValueError`, which the plugin
maps to the manifest ``unserializable_input`` bucket (design D10) — never a
silent drop. Lone surrogates and non-finite floats are rejected here at
record time per design D6 rules 2 and 5. Decode failures raise
:class:`UndecodableValueError` (a runner/vector bug — always loud).

One decode-only tag exists for AUTHORED vectors: ``{"$type": "float",
"value": "Infinity" | "-Infinity" | "NaN"}``. Design D6 rule 5 bans
non-finite JSON NUMBER TOKENS from vectors (and the encoder keeps
rejecting them), but the design D4.3 seed vector for
``B20B_FILTER_VALUE_NOT_FINITE`` must pass a non-finite float INTO the
validator under test — the tag carries it as data without ever putting a
bare ``Infinity`` token in the JSON. Finite floats must stay raw number
tokens (the D6 rule 3 raw-token contract); the decoder rejects finite
spellings of this tag.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as _dt
import functools
import math
import types as _types
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, SecretStr

_MAX_DEPTH = 64
"""Recursion guard for pathological self-referencing structures."""


class UnencodableValueError(Exception):
    """Raised when a captured value cannot be encoded into vector JSON.

    The record plugin catches this and logs the capture under the manifest
    ``unserializable_input`` category (design D10) instead of emitting a
    vector.
    """


class UndecodableValueError(Exception):
    """Raised when a vector value cannot be decoded back to Python.

    Unlike :class:`UnencodableValueError` this is never an exclusion
    bucket: a committed vector that fails decode is a codec-table or
    vector bug and must fail the replay run loudly (design D7).
    """


class RecordingCallback:
    """Replay stub injected for ``$type: callback`` kwargs (design D4.4).

    Both runners inject one of these per callback-tagged kwarg; the stub's
    call log (positional args, canonicalized via the expect encoder) is
    diffed against ``expect.callback_calls[<kwarg>]``.

    Attributes:
        name: The kwarg name the stub replaces (from the tagged object).
        calls: Ordered list of encoded positional-argument lists.

    Example:
        ```python
        stub = RecordingCallback("on_batch")
        stub([{"event": "Login"}])
        stub.calls
        # [[[{"event": "Login"}]]]
        ```
    """

    def __init__(self, name: str) -> None:
        """Create an empty recording stub.

        Args:
            name: The kwarg name this stub stands in for.
        """
        self.name = name
        self.calls: list[list[Any]] = []

    def __call__(self, *args: Any) -> None:
        """Record one invocation's positional arguments, encoded.

        Args:
            *args: The positional arguments the library passed.

        Raises:
            UnencodableValueError: If an argument has no codec (the design
                D4.4 ``unserializable_input`` backstop — none known today).
        """
        self.calls.append([encode_expect_value(arg) for arg in args])


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
        # Field-level encoding (NOT model_dump): pydantic's JSON mode masks
        # ``SecretStr`` fields to ``"**********"``, destroying the D5.5
        # revealed-literal contract inside models (``OAuthTokens`` results
        # were unreplayable). Attribute access hands each field value to
        # the scalar branches above, so SecretStr reveals, datetime/date
        # tag per the codec table, and nested models recurse. Computed
        # fields are included in expect position only (they are part of
        # the library's public to-dict contract but must never reach a
        # constructor at decode time).
        field_names = list(type(value).model_fields)
        if not tagged_models:
            field_names.extend(type(value).model_computed_fields)
        try:
            encoded = {
                str(name): _encode_common(
                    getattr(value, name), depth + 1, tagged_models=tagged_models
                )
                for name in field_names
            }
        except AttributeError as exc:  # defensive: exotic descriptors
            raise UnencodableValueError(
                f"pydantic model {type(value).__name__} field access failed: {exc}"
            ) from exc
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
    import unittest.mock as _umock

    encoded: dict[str, Any] = {}
    for name, value in arguments.items():
        if isinstance(value, _umock.NonCallableMock):
            # A unittest.mock test double is NOT a callback: encoding it
            # as one would bake a false contract into the vector (PR-5
            # audit: MagicMock(spec=CohortDefinition) with a raising
            # to_dict became ``$type: callback`` and replayed as a valid
            # cohort). Mock-dependent captures are unserializable.
            raise UnencodableValueError(
                f"argument {name!r} is a unittest.mock object — the test "
                "contract lives in the mock's behavior, which vectors "
                "cannot encode (excluded as unserializable_input)"
            )
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


# ---------------------------------------------------------------------------
# Decode side — the design D4.4 $type table (runner/oracle consumers)
# ---------------------------------------------------------------------------


@functools.cache
def _dataclass_codecs() -> Mapping[str, type]:
    """Build the ``$type`` name -> dataclass table (design D4.4).

    Imported lazily (and cached) so merely importing this module stays
    cheap; the table is the D4.4 set plus the nested types those
    dataclasses carry in their fields.

    Returns:
        Mapping from tag name to the frozen dataclass it reconstructs.
    """
    from mixpanel_headless import types as mp_types

    names = (
        "Filter",
        "FunnelStep",
        "RetentionEvent",
        "FlowStep",
        "Metric",
        "CohortMetric",
        "Formula",
        "GroupBy",
        "CohortBreakdown",
        "FrequencyBreakdown",
        "FrequencyFilter",
        "TimeComparison",
        "UserAction",
        # Nested types reachable from the D4.4 set's fields:
        "CohortCriteria",
        "CustomPropertyRef",
        "InlineCustomProperty",
        "PropertyInput",
    )
    return {name: getattr(mp_types, name) for name in names}


@functools.cache
def _tuple_fields(cls: type) -> frozenset[str]:
    """Return the field names of ``cls`` annotated as tuples (possibly optional).

    Vector JSON has no tuple type; decoded lists must be coerced back to
    tuples where the dataclass declares one (``Filter._list_item_filters``)
    or reconstructed instances would compare unequal to the originals.

    Args:
        cls: A dataclass from the codec table.

    Returns:
        Names of fields whose annotation is ``tuple[...]`` or a union
        containing one.
    """

    def is_tuple_hint(hint: Any) -> bool:
        """Return whether ``hint`` is (or contains) a tuple annotation.

        Args:
            hint: A resolved type annotation.

        Returns:
            True for ``tuple[...]`` and unions with a tuple member.
        """
        origin = get_origin(hint)
        if origin is tuple:
            return True
        if origin in (Union, _types.UnionType):
            return any(is_tuple_hint(arg) for arg in get_args(hint))
        return False

    hints = get_type_hints(cls)
    return frozenset(
        field.name
        for field in dataclasses.fields(cls)
        if is_tuple_hint(hints.get(field.name))
    )


def _decode_dataclass(cls: type, payload: Mapping[str, Any]) -> Any:
    """Reconstruct a frozen dataclass from its tagged-object fields.

    Args:
        cls: The dataclass named by the payload's ``$type``.
        payload: The tagged object (``$type`` plus field values).

    Returns:
        A new ``cls`` instance equal to the encoded original.

    Raises:
        UndecodableValueError: If the payload carries unknown fields or the
            constructor rejects the decoded values.
    """
    field_names = {field.name for field in dataclasses.fields(cls)}
    extra = set(payload) - field_names - {"$type"}
    if extra:
        raise UndecodableValueError(
            f"unknown fields {sorted(extra)} for $type {cls.__name__}"
        )
    tuple_fields = _tuple_fields(cls)
    kwargs: dict[str, Any] = {}
    for name in field_names & set(payload):
        decoded = decode_value(payload[name])
        if name in tuple_fields and isinstance(decoded, list):
            decoded = tuple(decoded)
        kwargs[name] = decoded
    try:
        return cls(**kwargs)
    except Exception as exc:
        raise UndecodableValueError(
            f"could not reconstruct {cls.__name__} from vector fields: {exc}"
        ) from exc


def _decode_cohort_definition(payload: Mapping[str, Any]) -> Any:
    """Reconstruct a ``CohortDefinition`` (``init=False`` — design D4.4).

    ``CohortDefinition`` hides its fields behind ``all_of``/``any_of``
    classmethods, so the generic dataclass path cannot rebuild it.

    Args:
        payload: The tagged object with ``_criteria`` and ``_operator``.

    Returns:
        The reconstructed ``CohortDefinition``.

    Raises:
        UndecodableValueError: If the operator is unknown or the criteria
            list is empty/invalid.
    """
    from mixpanel_headless.types import CohortDefinition

    criteria = [decode_value(item) for item in payload.get("_criteria", [])]
    operator = payload.get("_operator")
    try:
        if operator == "or":
            return CohortDefinition.any_of(*criteria)
        if operator == "and":
            return CohortDefinition.all_of(*criteria)
    except Exception as exc:
        raise UndecodableValueError(
            f"could not reconstruct CohortDefinition: {exc}"
        ) from exc
    raise UndecodableValueError(
        f"unknown CohortDefinition operator {operator!r} in vector input"
    )


@functools.cache
def _public_type_codecs() -> Mapping[str, type]:
    """Mechanical ``$type`` fallback table over the public types module.

    The hand-audited :func:`_dataclass_codecs` table covers the D4.4
    builder set; wire entry points additionally take dozens of public
    Params models (``CreateAnnotationParams``, ``UpdateCohortParams``, …)
    and ``OAuthTokens``. Enumerating them by hand would rot, so every
    public BaseModel/dataclass exported by ``mixpanel_headless.types``
    (plus ``OAuthTokens``) resolves mechanically — the PR-5 audit found
    61 wire-input tags this closes.

    Returns:
        Mapping from class name to the class it reconstructs.
    """
    from mixpanel_headless import types as mp_types
    from mixpanel_headless._internal.auth.token import OAuthTokens

    table: dict[str, type] = {}
    for name in dir(mp_types):
        if name.startswith("_"):
            continue
        candidate = getattr(mp_types, name)
        if not isinstance(candidate, type):
            continue
        if issubclass(candidate, BaseModel) or dataclasses.is_dataclass(candidate):
            table[name] = candidate
    table["OAuthTokens"] = OAuthTokens
    return table


def _decode_model(cls: type[BaseModel], payload: Mapping[str, Any]) -> Any:
    """Reconstruct a Pydantic model from its tagged-object fields.

    Args:
        cls: The BaseModel subclass named by the payload's ``$type``.
        payload: The tagged object (``$type`` plus field values).

    Returns:
        A new ``cls`` instance equal to the encoded original.

    Raises:
        UndecodableValueError: If the payload carries unknown fields or
            validation rejects the decoded values.
    """
    field_names = set(cls.model_fields)
    extra = set(payload) - field_names - {"$type"}
    if extra:
        raise UndecodableValueError(
            f"unknown fields {sorted(extra)} for $type {cls.__name__}"
        )
    kwargs = {name: decode_value(payload[name]) for name in field_names & set(payload)}
    try:
        return cls(**kwargs)
    except Exception as exc:
        raise UndecodableValueError(
            f"could not reconstruct {cls.__name__} from vector fields: {exc}"
        ) from exc


def _decode_tagged(payload: Mapping[str, Any]) -> Any:
    """Decode one ``$type``-tagged object (design D4.4 table dispatch).

    Args:
        payload: A mapping carrying a ``$type`` key.

    Returns:
        The reconstructed Python value.

    Raises:
        UndecodableValueError: If the tag is unknown or the payload is
            malformed for its tag.
    """
    tag = payload["$type"]
    try:
        if tag == "datetime":
            return _dt.datetime.fromisoformat(str(payload["iso"]))
        if tag == "date":
            return _dt.date.fromisoformat(str(payload["iso"]))
        if tag == "SecretStr":
            return SecretStr(str(payload["value"]))
        if tag == "bytes":
            if payload.get("encoding") != "base64":
                raise UndecodableValueError(
                    f"unknown bytes encoding {payload.get('encoding')!r}"
                )
            return base64.b64decode(str(payload["data"]), validate=True)
        if tag == "callback":
            return RecordingCallback(str(payload["name"]))
        if tag == "float":
            spelling = str(payload["value"])
            if spelling not in ("Infinity", "-Infinity", "NaN"):
                raise UndecodableValueError(
                    f"$type float carries non-canonical spelling {spelling!r} "
                    "(finite floats must be raw JSON number tokens — design "
                    "D6 rule 3; only Infinity/-Infinity/NaN are taggable)"
                )
            return float(spelling)
        if tag == "CohortDefinition":
            return _decode_cohort_definition(payload)
    except (KeyError, ValueError) as exc:
        raise UndecodableValueError(f"malformed $type {tag!r} payload: {exc}") from exc
    cls = _dataclass_codecs().get(str(tag)) or _public_type_codecs().get(str(tag))
    if cls is None:
        raise UndecodableValueError(
            f"no codec for $type {tag!r} (extend conformance/record/codecs.py "
            "and its TS mirror together — design D4.4)"
        )
    if isinstance(cls, type) and issubclass(cls, BaseModel):
        return _decode_model(cls, payload)
    return _decode_dataclass(cls, payload)


def decode_value(value: Any) -> Any:
    """Decode one vector JSON value back to Python (design D7 replay side).

    Plain JSON passes through; ``$type``-tagged objects reconstruct rich
    values via the codec table; containers decode recursively.

    Args:
        value: A value loaded from a vector's ``call.input``.

    Returns:
        The Python value to pass to the registry target.

    Raises:
        UndecodableValueError: If any nested tag is unknown or malformed.
    """
    if isinstance(value, Mapping):
        if "$type" in value:
            return _decode_tagged(value)
        return {str(key): decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_value(item) for item in value]
    return value


def decode_input_kwargs(encoded: Mapping[str, Any]) -> dict[str, Any]:
    """Decode a vector ``call.input`` object into call kwargs (design D7).

    Args:
        encoded: The vector's ``call.input`` mapping.

    Returns:
        Keyword arguments for the registry target; ``callback``-tagged
        values arrive as :class:`RecordingCallback` stubs.

    Raises:
        UndecodableValueError: If any value fails to decode.
    """
    return {name: decode_value(value) for name, value in encoded.items()}


# ---------------------------------------------------------------------------
# Output codecs (registry ``output_codec`` dispatch — design D4.4)
# ---------------------------------------------------------------------------


def _encode_validation_errors(value: object) -> list[dict[str, str]]:
    """Serialize ``list[ValidationError]`` structurally (design D4.3).

    The contract is ``path`` + ``code`` + ``severity``, order preserved;
    ``message``/``suggestion``/``fix`` never enter vectors (R5.3/R5.4).

    Args:
        value: The validator's return value.

    Returns:
        One ``{path, code, severity}`` object per error, in emission order.

    Raises:
        UnencodableValueError: If the value is not a list of
            ``ValidationError`` instances.
    """
    from mixpanel_headless.exceptions import ValidationError

    if not isinstance(value, list) or not all(
        isinstance(item, ValidationError) for item in value
    ):
        raise UnencodableValueError(
            "validation_errors codec expects list[ValidationError], got "
            f"{type(value).__name__}"
        )
    return [
        {"path": item.path, "code": item.code, "severity": item.severity}
        for item in value
    ]


def encode_output(codec: str, value: object) -> Any:
    """Encode a return value per the registry entry's output codec (D4.4).

    Args:
        codec: The registry ``output_codec`` name.
        value: The raw return value.

    Returns:
        The vector-JSON representation:

        - ``json`` — generic :func:`encode_expect_value`;
        - ``validation_errors`` — structural ``[{path, code, severity}]``
          (design D4.3);
        - ``model_name`` — the returned model CLASS as its name string
          (design D4.2 item 7);
        - ``selector_str`` — the selector string verbatim (design D4.2
          item 1; escaping is contract char-for-char).

    Raises:
        UnencodableValueError: If the value does not fit the named codec,
            or the codec name is unknown (a registry bug — loud, never a
            silent fallback).
    """
    if codec == "json":
        return encode_expect_value(value)
    if codec == "validation_errors":
        return _encode_validation_errors(value)
    if codec == "model_name":
        if not isinstance(value, type):
            raise UnencodableValueError(
                f"model_name codec expects a class, got {type(value).__name__}"
            )
        return value.__name__
    if codec == "selector_str":
        if not isinstance(value, str):
            raise UnencodableValueError(
                f"selector_str codec expects str, got {type(value).__name__}"
            )
        return _reject_bad_string(value)
    raise UnencodableValueError(
        f"unknown output codec {codec!r} (conformance/record/registry.py and "
        "codecs.py must agree)"
    )
