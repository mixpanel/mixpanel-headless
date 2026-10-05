"""Shared hand-built App API payloads for saved metric and saved behavior tests.

Each builder returns one entity dict in the shape that
``GET /api/app/projects/{pid}/metrics`` and ``.../behaviors`` return per
row: ``id``, ``name``, ``type``, ``description``, ``definition``, the
visibility flags, ``created_by``, naive UTC timestamps, and the permission
keys computed for the caller. :func:`id_map` wraps rows in the id-keyed
``results`` map that every list, get, create, and update response uses.

Imported by the types, API client, workspace, CLI, and property tests for
saved metrics. Lives in a private module (leading underscore) so pytest
doesn't try to collect it as a test file.
"""

from __future__ import annotations

from typing import Any

CREATOR: dict[str, Any] = {"id": 7, "email": "ana@example.com", "name": "Ana Analyst"}
"""The ``created_by`` user of every fixture row."""

OWNER: dict[str, Any] = {"id": 8, "email": "olu@example.com", "name": "Olu Owner"}
"""The ``owned_by`` and ``last_verified_by`` user of the verified fixture rows."""


def behavior_metric_json(
    metric_id: int = 104700,
    name: str = "Weekly signups",
    *,
    verified: bool = False,
    can_view: bool = True,
) -> dict[str, Any]:
    """Return a saved behavior metric (kind ``metric``) as the App API sends it.

    Args:
        metric_id: The metric id.
        name: The metric name.
        verified: Add the ``verified``, ``last_verified``, ``last_verified_by``,
            ``owned_by``, and ``contacts`` keys, as the server does for a
            verified metric with an owner.
        can_view: The per-user ``can_view`` flag.

    Returns:
        One saved metric dict with a simple behavior, a display block, and a goal.
    """
    row: dict[str, Any] = {
        "id": metric_id,
        "name": name,
        "type": "metric",
        "description": "Unique users who signed up.",
        "definition": {
            "behavior": {
                "type": "simple",
                "behaviors": [
                    {"type": "event", "name": "Signup", "filters": []},
                    {"type": "event", "name": "Account Created", "filters": []},
                ],
            },
            "measurement": {"math": "unique"},
            "display": {"prefix": "", "suffix": " users", "precision": 0},
            "goals": [
                {
                    "id": "0f7c4e5e-2b1f-4a4e-9a51-3f7d3c0f9b10",
                    "label": "Q4 target",
                    "checkpoints": [["2026-12-31T00:00:00", 5000.0]],
                    "target_type": "absolute",
                }
            ],
        },
        "is_visible": can_view,
        "is_locked": False,
        "created_by": dict(CREATOR),
        "contacts": [],
        "created": "2026-03-01T12:00:00",
        "modified": "2026-09-01T08:30:00",
        "can_view": can_view,
        "can_update_basic": can_view,
        "can_share": can_view,
        "allow_staff_override": False,
        "is_superadmin": False,
    }
    if verified:
        row.update(
            {
                "verified": True,
                "last_verified": "2026-09-02T10:00:00",
                "last_verified_by": dict(OWNER),
                "owned_by": dict(OWNER),
                "contacts": [OWNER["email"]],
            }
        )
    return row


def formula_metric_json(
    metric_id: int = 118228,
    name: str = "Signup conversion",
) -> dict[str, Any]:
    """Return a saved formula (kind ``formula``) whose operands include references.

    The first two operands refer to saved metrics by id, with the string
    ``metric_id`` that the server adds in responses only; the third operand
    is an inline behavior metric with no id.

    Args:
        metric_id: The metric id.
        name: The metric name.

    Returns:
        One saved formula dict.
    """
    return {
        "id": metric_id,
        "name": name,
        "type": "formula",
        "description": "",
        "definition": {
            "formula": {
                "definition": "A / B * 100",
                "referencedMetrics": [
                    {"type": "metric", "id": 104700, "metric_id": "104700"},
                    {"type": "metric", "id": 104701, "metric_id": "104701"},
                    {
                        "type": "metric",
                        "behavior": {"type": "event", "name": "Visit"},
                        "measurement": {"math": "total"},
                    },
                ],
            },
            "display": {"suffix": "%", "precision": 1},
        },
        "is_visible": True,
        "is_locked": False,
        "created_by": dict(CREATOR),
        "contacts": [],
        "created": "2026-04-01T00:00:00",
        "modified": "2026-04-02T00:00:00",
        "can_view": True,
        "can_update_basic": True,
        "can_share": True,
    }


def warehouse_metric_json(
    metric_id: int = 120001,
    name: str = "Daily revenue (warehouse)",
) -> dict[str, Any]:
    """Return a saved warehouse metric (kind ``warehouse``) as the App API sends it.

    Args:
        metric_id: The metric id.
        name: The metric name.

    Returns:
        One saved warehouse metric dict with ``warehouse_source_id``.
    """
    return {
        "id": metric_id,
        "name": name,
        "type": "warehouse",
        "description": "Synced from the warehouse.",
        "definition": {
            "query": "SELECT day, revenue FROM finance.daily_revenue",
            "metricType": "timeseries",
            "aggregation": "last_value",
            "syncInterval": "daily",
        },
        "warehouse_source_id": 55,
        "is_visible": True,
        "is_locked": False,
        "created_by": dict(CREATOR),
        "contacts": [],
        "created": "2026-05-01T00:00:00",
        "modified": "2026-05-01T00:00:00",
        "can_view": False,
        "can_update_basic": False,
        "can_share": False,
    }


def saved_behavior_json(
    behavior_id: int = 3001,
    name: str = "Checkout",
    *,
    behavior_type: str = "funnel",
    description: str | None = None,
    verified: bool = False,
) -> dict[str, Any]:
    """Return a saved behavior as the App API sends it.

    Args:
        behavior_id: The behavior id.
        name: The behavior name.
        behavior_type: The wire ``type`` (``simple``, ``funnel``, or ``retention``).
        description: The description; the server can send ``null``.
        verified: Add the ``verified``, ``last_verified``, and
            ``last_verified_by`` keys.

    Returns:
        One saved behavior dict. It has no ``owned_by``, ``contacts``, or
        ``warehouse_source_id``.
    """
    row: dict[str, Any] = {
        "id": behavior_id,
        "name": name,
        "type": behavior_type,
        "description": description,
        "definition": {
            "behavior": {
                "type": behavior_type,
                "behaviors": [
                    {"type": "event", "name": "View Cart"},
                    {"type": "event", "name": "Purchase"},
                ],
                "conversionWindowDuration": 7,
                "conversionWindowUnit": "day",
            }
        },
        "is_visible": True,
        "is_locked": False,
        "created_by": dict(CREATOR),
        "created": "2026-06-01T00:00:00",
        "modified": "2026-06-02T00:00:00",
        "can_view": True,
        "can_update_basic": True,
        "can_share": True,
    }
    if verified:
        row.update(
            {
                "verified": True,
                "last_verified": "2026-06-03T00:00:00",
                "last_verified_by": dict(OWNER),
            }
        )
    return row


LEGACY_KEY_PATHS: dict[str, list[str]] = {
    "metric": [
        "definition.behavior.filter",
        "definition.behavior.exclusions[0].dropdown_tab_index",
        "definition.behavior.exclusions[0].type",
        "definition.measurement.id",
        "definition.measurement.type",
    ],
    "formula": [
        "definition.formula.referencedMetrics[1].behavior.filter",
        "definition.formula.referencedMetrics[1].measurement.type",
    ],
    "behavior": [
        "definition.behavior.filter",
        "definition.behavior.exclusions[0].selected_property_type",
    ],
}
"""The legacy key paths of each ``legacy_*_json`` row, per definition kind."""


def legacy_funnel_metric_json(metric_id: int = 104900) -> dict[str, Any]:
    """Return a stored funnel metric whose definition still has legacy keys.

    The server's create schema leaves these keys out, and its query engine
    reads past them: ``behavior.filter``, the funnel step keys
    ``dropdown_tab_index`` and ``type`` of an exclusion, and the
    measurement keys ``id`` and ``type`` (see ``LEGACY_KEY_PATHS``).

    Args:
        metric_id: The metric id.

    Returns:
        One saved metric dict of kind ``metric``.
    """
    row = behavior_metric_json(metric_id, "Cart to purchase")
    row["definition"] = {
        "behavior": {
            "type": "funnel",
            "resourceType": "events",
            "filter": [],
            "behaviors": [
                {"type": "event", "name": "View Cart", "filters": []},
                {"type": "event", "name": "Purchase", "filters": []},
            ],
            "conversionWindowDuration": 7,
            "conversionWindowUnit": "day",
            "exclusions": [
                {
                    "event": "Refund",
                    "steps": {"from": 0, "to": 1},
                    "dropdown_tab_index": 0,
                    "type": "event",
                }
            ],
        },
        "measurement": {"math": "conversion_rate_unique", "id": 3, "type": "metric"},
        "display": {"suffix": "%", "precision": 1},
    }
    return row


def legacy_formula_metric_json(metric_id: int = 118900) -> dict[str, Any]:
    """Return a stored formula whose inline operand still has legacy keys.

    The first operand refers to a saved metric with the string ``metric_id``
    that the server adds in responses; its create schema accepts that key.
    The second operand is an inline metric with ``behavior.filter`` and a
    measurement ``type`` (see ``LEGACY_KEY_PATHS``).

    Args:
        metric_id: The metric id.

    Returns:
        One saved metric dict of kind ``formula``.
    """
    row = formula_metric_json(metric_id, "Visits per signup")
    row["definition"] = {
        "formula": {
            "definition": "A / B",
            "referencedMetrics": [
                {"type": "metric", "id": 104700, "metric_id": "104700"},
                {
                    "type": "metric",
                    "behavior": {"type": "event", "name": "Visit", "filter": []},
                    "measurement": {"math": "total", "type": "metric"},
                },
            ],
        }
    }
    return row


def legacy_behavior_json(behavior_id: int = 3900) -> dict[str, Any]:
    """Return a stored funnel behavior whose definition still has legacy keys.

    The keys are ``behavior.filter`` and the funnel step key
    ``selected_property_type`` of an exclusion (see ``LEGACY_KEY_PATHS``).

    Args:
        behavior_id: The behavior id.

    Returns:
        One saved behavior dict of type ``funnel``.
    """
    row = saved_behavior_json(behavior_id, "Checkout (legacy)")
    behavior = row["definition"]["behavior"]
    behavior["filter"] = []
    behavior["exclusions"] = [
        {
            "event": "Refund",
            "steps": {"from": 0, "to": 1},
            "selected_property_type": "string",
        }
    ]
    return row


def id_map(*rows: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Wrap entity rows in the id-keyed map of an App API ``results`` field.

    Args:
        *rows: Entity dicts, each with an integer ``id``.

    Returns:
        A dict keyed by the string form of each row id, in argument order.
    """
    return {str(row["id"]): row for row in rows}


def envelope(*rows: dict[str, Any]) -> dict[str, Any]:
    """Return a full App API response body for the given rows.

    Args:
        *rows: Entity dicts, each with an integer ``id``.

    Returns:
        ``{"status": "ok", "results": {<id>: <row>, ...}}``.
    """
    return {"status": "ok", "results": id_map(*rows)}
