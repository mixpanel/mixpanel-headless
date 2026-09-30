"""Wire definitions and pre-send checks for saved metrics and saved behaviors.

Pure functions that the ``Workspace`` write methods (``create_metric``,
``update_metric``, ``bulk_update_metrics``, ``create_behavior``,
``update_behavior``) call before any request. They do no I/O.

- :func:`metric_wire_parts` and :func:`behavior_wire_definition` turn a
  definition value into the kind, the wire ``definition`` dict, and (for a
  warehouse metric) the warehouse source that the App API expects.
- :func:`display_to_wire`, :func:`goal_to_wire`, and
  :func:`apply_presentation` write the presentation values.
- The ``check_*`` functions raise :class:`ParamValidationError` with a
  registry code. The server checks a POST against its JSON Schema but
  stores a PATCH as sent, so the client runs the same checks on both.

A behavior metric definition is the ``behavior`` and ``measurement`` of the
show clause that ``Workspace.query`` writes for the same inline value, so a
saved metric queries the same way as its inline twin.

These are internal helpers. Import them from
``mixpanel_headless._internal.saved_definitions``.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Final, cast, get_args, get_origin

from pydantic import BaseModel
from pydantic.json_schema import SkipJsonSchema

from mixpanel_headless._internal.bookmark_schema import (
    SAVED_METRIC_DEFINITION_MODELS,
    SavedBehaviorDefinition,
    validate_with_pydantic,
)
from mixpanel_headless._internal.bookmark_schema import Goal as _GoalSchema
from mixpanel_headless._internal.bookmark_schema import (
    MetricDisplay as _MetricDisplaySchema,
)
from mixpanel_headless._internal.query.metric_builders import (
    build_behavior_definition,
    build_formula_definition,
    build_metric_definition,
)
from mixpanel_headless.exceptions import ParamValidationError
from mixpanel_headless.types import (
    BehaviorDefinition,
    CohortMetric,
    Formula,
    FunnelMetric,
    Metric,
    MetricDefinition,
    MetricDisplay,
    MetricGoal,
    RawBehaviorDefinition,
    RetentionMetric,
    SavedMetric,
    WarehouseMetric,
)

MAX_TEXT_LENGTH: Final[int] = 255
"""Longest name or description the server stores; a longer one gives a 500."""

_DEPRECATED_GOAL_KEYS: Final[frozenset[str]] = frozenset({"unit", "direction"})
"""Goal keys that stored rows still carry and the client never writes."""

_OPERAND_ATTRIBUTION_KEYS: Final[tuple[str, ...]] = (
    "segmentMethod",
    "multiAttribution",
)
"""Operand measurement keys that a saved formula cannot use."""


@dataclass(frozen=True)
class MetricWireParts:
    """The wire pieces of a saved metric definition.

    Attributes:
        kind: The wire ``type``: ``"metric"``, ``"formula"``, or
            ``"warehouse"``.
        definition: A new wire ``definition`` dict that the caller may
            change.
        warehouse_source_id: The warehouse source of a warehouse metric,
            or ``None``.
    """

    kind: str
    """The wire ``type`` of the saved metric."""

    definition: dict[str, Any]
    """A new wire ``definition`` dict."""

    warehouse_source_id: int | None
    """The warehouse source of a warehouse metric, or ``None``."""


# =============================================================================
# Wire definitions
# =============================================================================


def metric_wire_parts(definition: MetricDefinition) -> MetricWireParts:
    """Turn a saved metric definition value into its wire pieces.

    A behavior metric definition is the ``behavior`` and ``measurement`` of
    the show clause that ``Workspace.query`` writes for the same value, and
    a saved formula holds its operands the way a query formula with its own
    operands does. So a saved metric queries the same way as its inline
    twin.

    Args:
        definition: A ``Metric``, ``CohortMetric``, ``FunnelMetric``, or
            ``RetentionMetric`` (a behavior metric); a ``Formula`` with its
            own operands (a saved formula); a ``WarehouseMetric``; or a
            ``RawMetricDefinition``.

    Returns:
        The kind, a new definition dict, and the warehouse source.

    Raises:
        ParamValidationError: A ``Formula`` without operands, whose letters
            name the other metrics of a query and so mean nothing on their
            own (``SM7_FORMULA_WITHOUT_OPERANDS``); a ``MetricRef`` operand
            with overrides (``MR2_OPERAND_OVERRIDE``).

    Example:
        ```python
        parts = metric_wire_parts(Metric("Login", math="unique"))
        parts.kind        # "metric"
        parts.definition  # {"behavior": {...}, "measurement": {"math": "unique"}}
        ```
    """
    if isinstance(definition, (Metric, CohortMetric, FunnelMetric, RetentionMetric)):
        return MetricWireParts(
            kind="metric",
            definition=build_metric_definition(definition),
            warehouse_source_id=None,
        )
    if isinstance(definition, Formula):
        if definition.metrics is None:
            raise ParamValidationError(
                f"Formula {definition.expression!r} names the other metrics of a "
                f"query by letter, so it has no meaning as a saved formula. Give "
                f"the formula its own operands: Formula(expression, "
                f"metrics=[...]).",
                code="SM7_FORMULA_WITHOUT_OPERANDS",
                details={"expression": definition.expression},
            )
        return MetricWireParts(
            kind="formula",
            definition=build_formula_definition(definition),
            warehouse_source_id=None,
        )
    if isinstance(definition, WarehouseMetric):
        wire: dict[str, Any] = {
            "query": definition.sql,
            "metricType": definition.metric_type,
            "aggregation": definition.aggregation,
            "syncInterval": definition.sync_interval,
        }
        if definition.time_column is not None:
            wire["timeColumn"] = definition.time_column
        if definition.value_column is not None:
            wire["valueColumn"] = definition.value_column
        return MetricWireParts(
            kind="warehouse",
            definition=wire,
            warehouse_source_id=definition.source_id,
        )
    return MetricWireParts(
        kind=definition.type,
        definition=_copy_mapping(definition.definition),
        warehouse_source_id=definition.warehouse_source_id,
    )


def behavior_wire_definition(behavior: BehaviorDefinition) -> dict[str, Any]:
    """Turn a saved behavior definition value into its wire definition.

    Args:
        behavior: A ``SimpleBehavior``, ``FunnelBehavior``, or
            ``RetentionBehavior`` (compiled with the same builders as the
            behavior of a query metric, without a name), or a
            ``RawBehaviorDefinition`` (copied as given).

    Returns:
        A new ``{"behavior": {...}}`` dict that the caller may change.

    Example:
        ```python
        behavior_wire_definition(FunnelBehavior(["View Cart", "Purchase"]))
        # {"behavior": {"type": "funnel", "resourceType": "events", ...}}
        ```
    """
    if isinstance(behavior, RawBehaviorDefinition):
        return _copy_mapping(behavior.definition)
    return build_behavior_definition(behavior)


def _copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-copy a mapping into a plain dict.

    Args:
        value: The mapping to copy.

    Returns:
        A new dict whose nested values do not share state with ``value``.
    """
    return copy.deepcopy(dict(value))


# =============================================================================
# Presentation values
# =============================================================================


def display_to_wire(display: MetricDisplay) -> dict[str, Any]:
    """Write a ``MetricDisplay`` as the wire ``display`` dict.

    Args:
        display: The presentation settings.

    Returns:
        The set fields under their camelCase wire keys, plus any unknown key
        the model holds, so the schema check can refuse it.
    """
    return display.model_dump(by_alias=True, exclude_none=True)


def goal_to_wire(goal: MetricGoal) -> dict[str, Any]:
    """Write a ``MetricGoal`` as a wire goal dict.

    A goal without an id gets a new UUID. Each ``date`` or ``datetime``
    checkpoint becomes a naive ISO timestamp, the form the web app stores;
    an aware ``datetime`` is converted to UTC first. The deprecated keys
    ``unit`` and ``direction`` are never written.

    Args:
        goal: The goal.

    Returns:
        The goal dict: ``id``, ``label``, ``checkpoints``, ``target_type``,
        ``target_input`` when set, then any other unknown key.
    """
    wire: dict[str, Any] = {
        "id": goal.id if goal.id is not None else str(uuid.uuid4()),
        "label": goal.label,
        "checkpoints": [
            [_checkpoint_time(when), float(value)] for when, value in goal.checkpoints
        ],
        "target_type": goal.target_type,
    }
    if goal.target_input is not None:
        wire["target_input"] = goal.target_input
    for key, value in (goal.model_extra or {}).items():
        if key not in _DEPRECATED_GOAL_KEYS:
            wire[key] = value
    return wire


def _checkpoint_time(when: str | datetime | date) -> str:
    """Write a goal checkpoint time as a naive ISO timestamp string.

    Args:
        when: An ISO string (kept as is), a ``datetime``, or a ``date``.

    Returns:
        The timestamp string, for example ``"2026-12-31T00:00:00"``.
    """
    if isinstance(when, datetime):
        if when.tzinfo is not None:
            when = when.astimezone(timezone.utc).replace(tzinfo=None)
        return when.isoformat()
    if isinstance(when, date):
        return f"{when.isoformat()}T00:00:00"
    return when


def apply_presentation(
    definition: dict[str, Any],
    *,
    display: MetricDisplay | None,
    goals: Sequence[MetricGoal] | None,
) -> None:
    """Write display and goals into a wire definition, in place.

    Args:
        definition: The wire definition to change.
        display: New presentation settings; ``None`` leaves the
            ``display`` key as it is.
        goals: New goals; ``None`` leaves the ``goals`` key as it is, and
            an empty sequence writes an empty list.
    """
    if display is not None:
        definition["display"] = display_to_wire(display)
    if goals is not None:
        definition["goals"] = [goal_to_wire(goal) for goal in goals]


# =============================================================================
# Coded checks
# =============================================================================


def check_name(name: str | None, *, entity: str) -> None:
    """Check a saved metric or saved behavior name.

    Args:
        name: The stripped name, or ``None`` for no change.
        entity: ``"saved metric"`` or ``"saved behavior"``, for the message.

    Raises:
        ParamValidationError: The name is empty (``SM1_EMPTY_NAME``), or
            longer than 255 characters (``SM2_NAME_TOO_LONG``).
    """
    if name is None:
        return
    if not name.strip():
        raise ParamValidationError(
            f"A {entity} name must not be empty.",
            code="SM1_EMPTY_NAME",
        )
    _check_length(name, field="name", entity=entity)


def check_description(description: str | None, *, entity: str) -> None:
    """Check a saved metric or saved behavior description.

    Args:
        description: The description, or ``None`` for no change.
        entity: ``"saved metric"`` or ``"saved behavior"``, for the message.

    Raises:
        ParamValidationError: The description is longer than 255
            characters (``SM2_NAME_TOO_LONG``).
    """
    if description is not None:
        _check_length(description, field="description", entity=entity)


def _check_length(text: str, *, field: str, entity: str) -> None:
    """Refuse a name or description that the server cannot store.

    Args:
        text: The name or description.
        field: ``"name"`` or ``"description"``.
        entity: ``"saved metric"`` or ``"saved behavior"``, for the message.

    Raises:
        ParamValidationError: ``text`` is longer than 255 characters
            (``SM2_NAME_TOO_LONG``).
    """
    if len(text) > MAX_TEXT_LENGTH:
        raise ParamValidationError(
            f"A {entity} {field} can have at most {MAX_TEXT_LENGTH} characters; "
            f"this one has {len(text)}. The server fails with a 500 on a longer "
            f"value.",
            code="SM2_NAME_TOO_LONG",
            details={"field": field, "length": len(text), "max": MAX_TEXT_LENGTH},
        )


def check_metric_definition(
    kind: str, definition: Mapping[str, Any], *, for_create: bool = False
) -> None:
    """Check a saved metric definition with the mirror of the server POST schema.

    Args:
        kind: The metric kind: ``"metric"``, ``"formula"``, or
            ``"warehouse"``.
        definition: The wire definition.
        for_create: Also refuse the legacy keys that the server's create
            schema leaves out (see :func:`find_server_skipped_keys`). An
            update does not refuse them, because the server stores an
            update as sent and stored definitions carry them.

    Raises:
        ParamValidationError: The definition fails the mirror
            (``SM4_SCHEMA``). The message and ``details["path"]`` name the
            first failing field; ``details["errors"]`` lists every failure.
    """
    model = SAVED_METRIC_DEFINITION_MODELS[kind]
    errors = validate_with_pydantic(model, definition, path_prefix="definition")
    if errors:
        _raise_schema_error(f"saved {kind} definition", errors)
    if for_create:
        _refuse_skipped_keys(f"saved {kind} definition", kind, definition)


def check_behavior_definition(
    definition: Mapping[str, Any], *, for_create: bool = False
) -> None:
    """Check a saved behavior definition with the mirror of the server POST schema.

    Args:
        definition: The wire definition, ``{"behavior": {...}}``.
        for_create: Also refuse the legacy keys that the server's create
            schema leaves out.

    Raises:
        ParamValidationError: The definition fails the mirror
            (``SM4_SCHEMA``). The message and ``details["path"]`` name the
            first failing field.
    """
    errors = validate_with_pydantic(
        SavedBehaviorDefinition, definition, path_prefix="definition"
    )
    if errors:
        _raise_schema_error("saved behavior definition", errors)
    if for_create:
        _refuse_skipped_keys("saved behavior definition", "behavior", definition)


# =============================================================================
# Legacy keys that the server's create schema leaves out
# =============================================================================
# The server generates its POST JSON Schema from its Pydantic models, and a
# field declared ``Ignore[...]`` there (``SkipJsonSchema``) is absent from
# that schema, whose objects forbid extra keys. So such a key is read past at
# query time but rejects a create. The mirror declares the same fields with
# the same marker, and these helpers find them in a definition. A create
# refuses them in every definition, raw or compiled from a typed value; an
# update sends a definition as given, because stored definitions carry them.

_SKIPPED_KEY_ROOTS: Final[dict[str, type[BaseModel]]] = {
    **SAVED_METRIC_DEFINITION_MODELS,
    "behavior": SavedBehaviorDefinition,
}
"""Definition mirror per metric kind, plus ``behavior`` for saved behaviors."""


_SKIP_JSON_SCHEMA: Final[type] = cast(type, SkipJsonSchema)
"""The runtime class of pydantic's ``SkipJsonSchema`` marker."""


def _is_skipped(field: Any) -> bool:
    """Return whether a mirror field is absent from the server's JSON Schema.

    Args:
        field: A pydantic ``FieldInfo``.

    Returns:
        ``True`` when the field carries ``SkipJsonSchema``.
    """
    return any(isinstance(item, _SKIP_JSON_SCHEMA) for item in field.metadata)


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    """Return the model type inside a field annotation, if any.

    Args:
        annotation: A field annotation such as ``Behavior | None`` or
            ``list[SubBehavior] | None``.

    Returns:
        The first ``BaseModel`` subclass found in the annotation, looking
        through unions and list element types; ``None`` when there is none.
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = get_origin(annotation)
    if origin is None:
        return None
    for arg in get_args(annotation):
        found = _nested_model(arg)
        if found is not None:
            return found
    return None


def _walk_skipped(model: type[BaseModel], data: Any, path: str) -> list[str]:
    """Find the skipped keys of one mirror model in a value, recursively.

    Args:
        model: The mirror model that describes ``data``.
        data: The value to walk (mappings and lists are walked).
        path: The dotted path of ``data``.

    Returns:
        The dotted path of each skipped key, in walk order.
    """
    found: list[str] = []
    if isinstance(data, list):
        for index, item in enumerate(data):
            found += _walk_skipped(model, item, f"{path}[{index}]")
        return found
    if not isinstance(data, Mapping):
        return found
    fields = {(info.alias or name): info for name, info in model.model_fields.items()}
    for key, value in data.items():
        info = fields.get(key)
        if info is None:
            continue
        if _is_skipped(info):
            found.append(f"{path}.{key}")
            continue
        nested = _nested_model(info.annotation)
        if nested is not None:
            found += _walk_skipped(nested, value, f"{path}.{key}")
    return found


def find_server_skipped_keys(kind: str, definition: Mapping[str, Any]) -> list[str]:
    """Return the paths of legacy keys that a create of this definition would hit.

    Args:
        kind: ``"metric"``, ``"formula"``, ``"warehouse"``, or ``"behavior"``.
        definition: The wire definition.

    Returns:
        Dotted paths such as ``"definition.behavior.filter"``, in walk order.

    Example:
        ```python
        find_server_skipped_keys("metric", {"behavior": {"filter": []}})
        # ["definition.behavior.filter"]
        ```
    """
    return _walk_skipped(_SKIPPED_KEY_ROOTS[kind], definition, "definition")


def _refuse_skipped_keys(
    subject: str, kind: str, definition: Mapping[str, Any]
) -> None:
    """Raise ``SM4_SCHEMA`` when a definition carries a legacy key a create rejects.

    Args:
        subject: What is checked, for the message.
        kind: ``"metric"``, ``"formula"``, ``"warehouse"``, or ``"behavior"``.
        definition: The wire definition.

    Raises:
        ParamValidationError: A legacy key is present (``SM4_SCHEMA``).
    """
    paths = find_server_skipped_keys(kind, definition)
    if not paths:
        return
    more = f" (and {len(paths) - 1} more)" if len(paths) > 1 else ""
    raise ParamValidationError(
        f"The {subject} has a legacy key at {paths[0]}{more} that the server "
        f"reads past at query time but refuses on a create. Remove it.",
        code="SM4_SCHEMA",
        details={
            "path": paths[0],
            "errors": [
                {
                    "path": path,
                    "message": "Legacy key not allowed on create",
                    "code": "S3_UNKNOWN_FIELD",
                }
                for path in paths
            ],
        },
    )


def _raise_schema_error(subject: str, errors: Sequence[Any]) -> None:
    """Raise the ``SM4_SCHEMA`` refusal for a list of mirror errors.

    The server's own 400 message can name the wrong cause (its schema is a
    union, and it reports an error from another branch), so the client
    names the field path itself.

    Args:
        subject: What failed, for the message.
        errors: The package ``ValidationError`` items from the mirror.

    Raises:
        ParamValidationError: Always (``SM4_SCHEMA``).
    """
    first = errors[0]
    more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
    raise ParamValidationError(
        f"The {subject} does not match the server schema at {first.path}: "
        f"{first.message}{more}.",
        code="SM4_SCHEMA",
        details={"path": first.path, "errors": [e.to_dict() for e in errors]},
    )


def check_presentation(
    *,
    display: MetricDisplay | None,
    goals: Sequence[MetricGoal] | None,
) -> None:
    """Check new display and goals values with the mirror of the server schema.

    Used when an update changes the presentation but not the definition, so
    only the new pieces are checked, not the stored definition around them.

    Args:
        display: New presentation settings, or ``None``.
        goals: New goals, or ``None``.

    Raises:
        ParamValidationError: A value fails the mirror (``SM4_SCHEMA``).
            ``details["path"]`` starts with ``definition.display`` or
            ``definition.goals[i]``.
    """
    errors: list[Any] = []
    if display is not None:
        errors += validate_with_pydantic(
            _MetricDisplaySchema,
            display_to_wire(display),
            path_prefix="definition.display",
        )
    for index, goal in enumerate(goals or ()):
        errors += validate_with_pydantic(
            _GoalSchema, goal_to_wire(goal), path_prefix=f"definition.goals[{index}]"
        )
    if errors:
        _raise_schema_error("saved metric presentation", errors)


def check_formula_operands(definition: Mapping[str, Any]) -> None:
    """Refuse a saved formula whose operands use segment method or attribution.

    The web app refuses to save such a formula, and the query engine gives
    the reason: it replaces the measurement of a saved-metric operand with
    the saved one and does not merge operand overrides, and the formula's
    own attribution overwrites each operand's attribution. So the operand
    setting is dropped or makes every report fail. A null value is allowed;
    stored formulas carry ``"segmentMethod": null``.

    Args:
        definition: The wire definition of a saved formula. Shapes this
            check does not know are left to the schema check.

    Raises:
        ParamValidationError: An operand's ``measurement`` or
            ``overrides.measurement`` has a non-null ``segmentMethod`` or
            ``multiAttribution`` (``FM6_OPERAND_ATTRIBUTION``).
    """
    formula = definition.get("formula")
    operands = (
        formula.get("referencedMetrics") if isinstance(formula, Mapping) else None
    )
    if not isinstance(operands, list):
        return
    for index, operand in enumerate(operands):
        if not isinstance(operand, Mapping):
            continue
        overrides = operand.get("overrides")
        measurements = [
            operand.get("measurement"),
            overrides.get("measurement") if isinstance(overrides, Mapping) else None,
        ]
        for measurement in measurements:
            if not isinstance(measurement, Mapping):
                continue
            for key in _OPERAND_ATTRIBUTION_KEYS:
                if measurement.get(key):
                    raise ParamValidationError(
                        f"Saved formula operand {index} sets measurement.{key}. A "
                        f"saved formula cannot use operand segment method or "
                        f"attribution: the server drops or rejects them at query "
                        f"time. Set attribution on the formula's own measurement, "
                        f"or query the metrics inline.",
                        code="FM6_OPERAND_ATTRIBUTION",
                        details={"operand": index, "key": key},
                    )


def check_same_kind(
    *,
    entity: str,
    entity_id: int,
    stored_kind: str,
    new_kind: str,
    stored_source_id: int | None = None,
    new_source_id: int | None = None,
) -> None:
    """Refuse an update that would change the kind or warehouse source.

    The server ignores ``type`` and ``warehouse_source_id`` on an update but
    stores the new definition, so a kind change would leave a definition
    that does not match its kind. A legacy ``behavior`` kind counts as
    ``metric``.

    Args:
        entity: ``"saved metric"`` or ``"saved behavior"``, for the message.
        entity_id: The id of the stored entity.
        stored_kind: The kind (or behavior type) of the stored entity.
        new_kind: The kind (or behavior type) of the new definition.
        stored_source_id: The stored warehouse source, for a warehouse metric.
        new_source_id: The new warehouse source; ``None`` keeps the stored one.

    Raises:
        ParamValidationError: The kind or the warehouse source differs
            (``SM3_KIND_CHANGE``).
    """
    if _normal_kind(stored_kind) != _normal_kind(new_kind):
        raise ParamValidationError(
            f"The new definition is a {new_kind!r} definition, but {entity} "
            f"{entity_id} is a {stored_kind!r}. The server cannot change the kind "
            f"of a stored {entity}; create a new {entity} instead.",
            code="SM3_KIND_CHANGE",
            details={"id": entity_id, "stored": stored_kind, "new": new_kind},
        )
    if new_source_id is not None and new_source_id != stored_source_id:
        raise ParamValidationError(
            f"{entity.capitalize()} {entity_id} runs on warehouse source "
            f"{stored_source_id}; the server cannot move it to source "
            f"{new_source_id}. Create a new {entity} instead.",
            code="SM3_KIND_CHANGE",
            details={
                "id": entity_id,
                "stored_warehouse_source_id": stored_source_id,
                "new_warehouse_source_id": new_source_id,
            },
        )


def _normal_kind(kind: str) -> str:
    """Map the legacy ``behavior`` kind to ``metric``.

    Args:
        kind: A stored or new kind.

    Returns:
        ``"metric"`` for ``"behavior"``, otherwise ``kind``.
    """
    return "metric" if kind == "behavior" else kind


# =============================================================================
# Definition changes
# =============================================================================


@dataclass(frozen=True)
class MetricDefinitionChange:
    """A saved metric definition change that passed the local checks.

    Attributes:
        parts: The new definition with the params display and goals written
            in, or ``None`` when only the presentation changes.
        display: New presentation settings, or ``None``.
        goals: New goals, or ``None``.
    """

    parts: MetricWireParts | None
    """The new definition, or ``None`` when only the presentation changes."""

    display: MetricDisplay | None
    """New presentation settings, or ``None``."""

    goals: tuple[MetricGoal, ...] | None
    """New goals, or ``None``."""


def prepare_metric_change(
    definition: MetricDefinition | None,
    display: MetricDisplay | None,
    goals: Sequence[MetricGoal] | None,
    *,
    validate: bool,
) -> MetricDefinitionChange | None:
    """Run the local checks of a saved metric definition change.

    Runs before any request. A new definition gets the params display and
    goals written in, passes the saved formula operand rule, and (with
    ``validate``) passes the mirror of the server POST schema. Without a new
    definition, only the new display and goals are checked.

    Args:
        definition: The new definition, or ``None``.
        display: New presentation settings, or ``None``.
        goals: New goals, or ``None``.
        validate: Run the schema mirror. ``False`` skips it; the operand
            rule still runs.

    Returns:
        The checked change, or ``None`` when nothing in the definition
        changes.

    Raises:
        ParamValidationError: A saved formula operand uses segment method or
            attribution (``FM6_OPERAND_ATTRIBUTION``), or a value fails the
            schema mirror (``SM4_SCHEMA``).
    """
    if definition is None and display is None and goals is None:
        return None
    goal_tuple = tuple(goals) if goals is not None else None
    if definition is None:
        if validate:
            check_presentation(display=display, goals=goal_tuple)
        return MetricDefinitionChange(parts=None, display=display, goals=goal_tuple)
    parts = prepare_new_metric(definition, display, goal_tuple, validate=validate)
    return MetricDefinitionChange(parts=parts, display=display, goals=goal_tuple)


def prepare_new_metric(
    definition: MetricDefinition,
    display: MetricDisplay | None,
    goals: Sequence[MetricGoal] | None,
    *,
    validate: bool,
    for_create: bool = False,
) -> MetricWireParts:
    """Build a saved metric definition and run its local checks.

    The params display and goals are written into the definition. Then a
    saved formula passes the operand rule, and (with ``validate``) the
    definition passes the mirror of the server POST schema.

    Args:
        definition: The definition value.
        display: Presentation settings, or ``None``.
        goals: Goals, or ``None``.
        validate: Run the schema mirror. ``False`` skips it; the operand
            rule still runs.
        for_create: The definition goes into a create, so the mirror also
            refuses legacy keys that the server's create schema leaves out.

    Returns:
        The wire pieces, with display and goals written in.

    Raises:
        ParamValidationError: A saved formula operand uses segment method or
            attribution (``FM6_OPERAND_ATTRIBUTION``), or the definition
            fails the schema mirror (``SM4_SCHEMA``).
    """
    parts = metric_wire_parts(definition)
    apply_presentation(parts.definition, display=display, goals=goals)
    if parts.kind == "formula":
        check_formula_operands(parts.definition)
    if validate:
        check_metric_definition(parts.kind, parts.definition, for_create=for_create)
    return parts


def finish_metric_change(
    change: MetricDefinitionChange, stored: SavedMetric
) -> dict[str, Any]:
    """Merge a checked definition change with the stored metric.

    A new definition must have the stored kind and warehouse source. It
    keeps the stored ``display`` and ``goals`` unless it sets them itself
    (from the params or its own keys), because the server replaces a
    definition in full. A presentation-only change sends the stored
    definition back with the new display and goals.

    Args:
        change: The output of :func:`prepare_metric_change`.
        stored: The stored metric, read just before.

    Returns:
        The full wire definition to send.

    Raises:
        ParamValidationError: The new definition changes the kind or the
            warehouse source (``SM3_KIND_CHANGE``).
    """
    if change.parts is None:
        definition = copy.deepcopy(stored.definition)
        apply_presentation(definition, display=change.display, goals=change.goals)
        return definition
    check_same_kind(
        entity="saved metric",
        entity_id=stored.id,
        stored_kind=stored.type,
        new_kind=change.parts.kind,
        stored_source_id=stored.warehouse_source_id,
        new_source_id=change.parts.warehouse_source_id,
    )
    definition = copy.deepcopy(change.parts.definition)
    for key in ("display", "goals"):
        if key not in definition and key in stored.definition:
            definition[key] = copy.deepcopy(stored.definition[key])
    return definition
