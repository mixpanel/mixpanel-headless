# Data Model: Behaviors, Metrics & Formulas semantic layer

**Feature**: 047-behaviors-metrics-formulas
**Date**: 2026-06-28

This feature adds three saved-entity families to the public surface: **behaviors**, **metrics**, **formulas**. Each family gets a result type plus `Create*`/`Update*` Pydantic v2 param models, plus two shared value types (`MeasurementProperty`, `BehaviorStep`) and one enum (`MeasurementMath`). No new on-disk persistence: these are remote App API entities. This document is the entity ledger plus the validator table.

All types are defined in `mixpanel_headless.types` and exported from `mixpanel_headless.__init__`. Both the body shapes and the transport (project-scoped paths, the object-map list envelope, the two-endpoint mapping, bulk delete) are confirmed against the Mixpanel backend App API (research.md R-1, CONFIRMED).

---

## 1. Reused entities (no changes)

| Entity | Source | Notes |
|--------|--------|-------|
| `Workspace` | `workspace.py` | Gains 15 new public methods (5 per entity family). No schema change. The metric and formula families share the `/metrics/` client methods, discriminated by `type`. |
| `MixpanelAPIClient` | `_internal/api_client.py` | Gains App API methods on **two project-scoped endpoints** (`/behaviors/` and the shared `/metrics/` for metrics + formulas) via `app_request`. Project-scoped only (no `maybe_scoped_path` workspace scoping); `list_*` parses the object-map envelope; metric/formula delete uses the bulk DELETE (single-item metric DELETE returns 501). |
| pagination helper | `_internal/pagination.py` | NOT used by these entities — the list-response envelope is an object map keyed by string ID with no cursor pagination. `list_*` parses `results.values()` into a list directly. |
| `Cohort` / `CreateCohortParams` | `types.py` | The shape mirror — every new param/result type follows this Pydantic v2 model convention. |
| `APIError`, `QueryError`, `ServerError` | `exceptions.py` | Server-side failures map here; the library adds no new exception classes (validation failures are Pydantic `ValidationError`). |

### 1.1 `Metric` / `Behavior` naming-collision reconciliation (FR-018)

Spec 036-cohort-behaviors already exports query-layer shapes named `Metric` / `CohortMetric` (the `behavior.type` / `measurement.math` show-entry vocabulary used to build queries). The saved-entity result types this feature adds — also conceptually "a metric" and "a behavior" — collide by name on `mixpanel_headless.__init__` export (FR-018, research.md R-8).

**Reconciliation decision**: the existing query-layer `Metric` / `CohortMetric` stay exactly where they are with their current names (callers already import them). The new saved-entity result + param types are exported under unambiguous names that read as "the saved entity": `Behavior`, `Metric`, `Formula` as the in-module class names, but the build session MUST verify against the live `__init__.py` whether `Metric` is already a public export from 036; if it is, the saved-entity type is exported as `SavedMetric` (and correspondingly `SavedBehavior`) to avoid shadowing, and the `Create*Params` / `Update*Params` names — which do not collide — stay as written throughout this spec. The final exported names are locked at FR-018 / T018 / T036 time once the live `__all__` is inspected; whichever choice is made, no export may shadow an existing public symbol.

---

## 2. Shared value types

### 2.1 `MeasurementMath` (enum)

```python
MeasurementMath = Literal[
    "total", "unique", "dau", "wau", "mau",
    "average", "median", "min", "max", "sum",
    "p25", "p75", "p90", "p99", "unique_values",
    "conversion_rate_unique", "conversion_rate_total", "conversion_rate_session",
    "retention_rate",
]
```

Three branches by property-presence, confirmed against the Mixpanel backend:

- **Property-aggregation maths** (REQUIRE a `MeasurementProperty`): `average, median, min, max, sum, p25, p75, p90, p99, unique_values`.
- **Plain-count maths** (MUST omit property): `total, unique, dau, wau, mau`.
- **Rate maths** (MUST omit property; REQUIRE a specific behavior shape): `conversion_rate_unique, conversion_rate_total, conversion_rate_session` require a `funnel` behavior with >= 2 steps; `retention_rate` requires a `retention` behavior with EXACTLY 2 steps (born + return). Real backend payloads emit `"property": null` for all four; the library omits the key (the validators forbid a property on these maths).

### 2.2 `MeasurementProperty`

The aggregand object. Never a bare string.

```python
class MeasurementProperty(BaseModel):
    """Property aggregand for a property-aggregation metric.

    SECURITY/CORRECTNESS: a bare string here corrupts the metric and crashes
    the Mixpanel webapp query builder. This is an object so that form is
    unrepresentable.
    """
    name: str                       # exact property name
    type: Literal["number", "string", "datetime", "boolean", "list"] = "number"
    resource_type: Literal["events", "people"] = "events"  # serialized as resourceType
```

Serialized shape: `{"name": "amount", "type": "number", "resourceType": "events"}`.

### 2.3 `BehaviorStep`

One event step. The atomic unit step-count validators count.

```python
class BehaviorStep(BaseModel):
    """One event step in a behavior definition."""
    name: str                       # exact event name; MUST be non-empty
    type: Literal["event"] = "event"
    filters: list[dict[str, Any]] = []
    filters_determiner: Literal["all", "any"] = "all"   # serialized filtersDeterminer
    funnel_order: Literal["loose", "any"] | None = None  # per-step; serialized funnelOrder
```

**Validation**: `name` MUST be non-empty (whitespace-only rejected).

---

## 3. Behaviors

### 3.1 `Behavior` (result)

```python
class Behavior(BaseModel):
    """A saved user-action definition (simple / funnel / retention)."""
    id: int
    name: str
    type: Literal["simple", "funnel", "retention"]
    definition: dict[str, Any]      # round-tripped definition.behavior
    description: str | None = None
    # Confirmed response entity fields (echoed by the App API):
    is_visible: bool | None = None
    is_locked: bool | None = None
    created: str | None = None
    modified: str | None = None
    created_by: dict[str, Any] | None = None   # {id, email, name}
    verified: bool | None = None
    owned_by: dict[str, Any] | None = None      # {id}
    # .df / .to_dict() per the result-type contract
```

### 3.2 `CreateBehaviorParams`

```python
class CreateBehaviorParams(BaseModel):
    """Parameters to create a behavior. Validators refuse webapp-crashing shapes."""
    name: str
    description: str | None = None
    type: Literal["simple", "funnel", "retention"]
    steps: list[BehaviorStep]
    resource_type: Literal["events"] = "events"
    funnel_order: Literal["loose", "any"] = "loose"           # funnel only
    conversion_window_unit: Literal["second","minute","hour","day","week","month"] = "day"
    conversion_window_duration: int = 7                         # funnel only
    retention_unit: Literal["day", "week", "month"] = "day"     # retention only
    retention_type: Literal["birth"] = "birth"                  # retention only
```

`UpdateBehaviorParams` mirrors with all fields optional (PATCH semantics), plus the two PATCH-only keys `verified: bool | None` and `owned_by: dict | None` (`{id}`) that the create model does not carry.

---

## 4. Metrics

### 4.1 `Metric` (result)

```python
class Metric(BaseModel):
    """A saved KPI: an embedded behavior plus a measurement.

    Served by the /metrics/ endpoint with type="metric". A formula is the same
    endpoint with type="formula" (see §5).
    """
    id: int
    name: str
    type: Literal["metric", "formula"] = "metric"
    definition: dict[str, Any]      # round-tripped {behavior, measurement}
    description: str | None = None
    # Confirmed response entity fields (echoed by the App API):
    is_visible: bool | None = None
    is_locked: bool | None = None
    created: str | None = None
    modified: str | None = None
    created_by: dict[str, Any] | None = None   # {id, email, name}
    verified: bool | None = None
    owned_by: dict[str, Any] | None = None      # {id}
    # .df / .to_dict()
```

### 4.2 `CreateMetricParams`

```python
class CreateMetricParams(BaseModel):
    """Parameters to create a metric. The measurement validators are the guard."""
    name: str
    description: str | None = None
    math: MeasurementMath
    property: MeasurementProperty | None = None    # required iff math is property-aggregation
    steps: list[BehaviorStep]                       # the embedded behavior
    behavior_type: Literal["simple", "funnel", "retention"] = "simple"
    cumulative: bool = False
    data_group_id: int | None = None               # serialized dataGroupId
    per_user_aggregation: str | None = None         # serialized perUserAggregation
    rolling: int | None = None
```

`UpdateMetricParams` mirrors with optional fields, plus the two PATCH-only keys `verified: bool | None` and `owned_by: dict | None` (`{id}`).

---

## 5. Formulas

### 5.1 `Formula` (result)

```python
class Formula(BaseModel):
    """A saved derived KPI over named metric variables.

    A formula is a metric with type="formula"; it is created, listed, updated,
    and deleted through the SAME /metrics/ endpoint as a behavior-backed metric,
    discriminated by the top-level type field. The expression and the referenced
    metrics live under definition.formula in the wire shape (payload-shapes.md §6).
    """
    id: int
    name: str
    type: Literal["formula"] = "formula"
    definition: str                 # e.g. "(A / B) * 100"
    referenced_metrics: list[dict[str, Any]]   # round-tripped
    description: str | None = None
    # Confirmed response entity fields (echoed by the App API):
    is_visible: bool | None = None
    is_locked: bool | None = None
    created: str | None = None
    modified: str | None = None
    created_by: dict[str, Any] | None = None   # {id, email, name}
    verified: bool | None = None
    owned_by: dict[str, Any] | None = None      # {id}
    # .df / .to_dict()
```

### 5.2 `CreateFormulaParams`

```python
class CreateFormulaParams(BaseModel):
    """Parameters to create a formula. Variables map 1:1 to referenced_metrics by order."""
    name: str
    description: str | None = None
    definition: str                              # "(A / B) * 100"
    referenced_metrics: list[ReferencedMetric]    # A, B, ... by array order
```

`ReferencedMetric` carries a complete metric shape (behavior + measurement) plus a `display` object restricted to the allowed keys (`abbrev, axis, direction, hideTrendline, precision, prefix, suffix, trendline`). `UpdateFormulaParams` mirrors with optional fields, plus the two PATCH-only keys `verified: bool | None` and `owned_by: dict | None` (`{id}`).

`CreateFormulaParams` sets the wire `type="formula"` and routes through the metrics client methods (formulas have no separate endpoint); `create_formula` / `list_formulas` / `update_formula` / `delete_formula` are the `/metrics/` operations discriminated by `type`. `delete_formula(id)` uses the bulk DELETE on `/metrics/` (single-item metric DELETE returns 501).

---

## 6. Validator table (the authoritative guards)

| Rule | Type | Validator | Failure mode prevented |
|------|------|-----------|------------------------|
| **M1** | `CreateMetricParams` / `UpdateMetricParams` | `math` is the `MeasurementMath` Literal | bad math (`avg`, `unique_group`) → whole-entity 400 |
| **M2** | `CreateMetricParams` | property-aggregation math REQUIRES `property`; plain count OMITS it (a stray property on a count is normalized away — dropped from the emitted payload, not rejected) | missing aggregand on an aggregation, or a stray property on a count, → corrupt metric |
| **M3** | `MeasurementProperty` | property is an object, not a string | bare-string property → webapp crash |
| **M4** | emitted `measurement` | only keys `math, property, cumulative, dataGroupId, perUserAggregation, rolling, segmentMethod, multiAttribution` | unknown key → 400 |
| **M5** | `CreateMetricParams` | rate maths (`conversion_rate_unique`, `conversion_rate_total`, `conversion_rate_session`, `retention_rate`) FORBID a `property` (property omitted from the emitted payload) | stray property on a rate math → corrupt metric |
| **M6** | `CreateMetricParams` | rate-math behavior shape: the three `conversion_rate_*` require `behavior_type="funnel"` with >= 2 steps; `retention_rate` requires `behavior_type="retention"` with EXACTLY 2 steps | rate math over the wrong behavior shape → broken metric / query-builder crash |
| **B1** | `BehaviorStep` | `name` non-empty | nameless step → webapp crash on load |
| **B2** | `CreateBehaviorParams` | step counts: simple>=1, funnel>=2, retention==2; `behaviors` never empty | short/empty steps → webapp crash on load |
| **B3** | `CreateBehaviorParams` / `BehaviorStep` | `funnel_order` ∈ {loose, any} | `strict` → 400 |
| **F1** | `CreateFormulaParams` | variables in `definition` contiguous from A and count == len(referenced_metrics) | variable/metric mismatch → broken formula |
| **F2** | `ReferencedMetric.display` | only the allowed display keys | `label` key → 400 |

All validators run at construction time (Pydantic v2 `@model_validator` / `@field_validator`), BEFORE any HTTP call. Construction-time failures raise Pydantic `ValidationError`. The one exception is M2's stray-property-on-a-count case, which is a silent normalization (the property is dropped from the emitted payload, matching the backend, which itself strips the property on count maths) rather than a raised error; every other rule fails fast.

---

## 7. State transitions

### 7.1 Create pipeline (per entity family)

```
Create*Params(...)                 # construction-time validation (Pydantic)
    │  ValidationError ─► caller (no HTTP)
    ▼
params.model_dump(exclude_none=True, by_alias=True)   # camelCase payload
    │  (EXCEPTION: ReferencedMetric — see §7.3 — keeps explicit nulls)
    │  create_formula sets type="formula"; create_metric sets type="metric"
    ▼
client.create_*(body)              # 1 RTT, POST /api/app/projects/{pid}/{behaviors|metrics}/
    │  (behaviors → /behaviors/; metrics AND formulas → /metrics/)
    │  400 ─► QueryError    5xx ─► ServerError    401 ─► AuthenticationError
    ▼
Model.model_validate(raw)          # decode server response → result type
    ▼
Metric | Behavior | Formula        # with server-assigned id
```

### 7.2 Read / update / delete / list

Project-scoped paths (`{pid}` = project_id); `<entity>` is `behaviors` or `metrics` (formulas use `metrics`). No workspace scoping, no `maybe_scoped_path`.

```
get_*(id)    → GET    /api/app/projects/{pid}/<entity>/{id}/   → Model.model_validate(raw)
update_*(id) → PATCH  /api/app/projects/{pid}/<entity>/{id}/   → Model.model_validate(raw)
list_*()     → GET    /api/app/projects/{pid}/<entity>/        → parse object-map results → list[Model]

# delete — diverges by family:
delete_behavior(id) → DELETE /api/app/projects/{pid}/behaviors/{id}/   → None   # single-item OK
delete_metric(id)   → DELETE /api/app/projects/{pid}/metrics/          → None   # BULK, body {"metrics":[{id}]}
delete_formula(id)  → DELETE /api/app/projects/{pid}/metrics/          → None   # BULK (formula = metric), body {"metrics":[{id}]}
```

The single-item metric DELETE returns 501 NOT IMPLEMENTED (confirmed), so `delete_metric` / `delete_formula` MUST use the bulk DELETE with a single-entry body. `list_metrics()` and `list_formulas()` both read the `/metrics/` collection and partition `results.values()` by `type` (`"metric"` vs `"formula"`). The object-map list envelope is parsed by reading `results.values()` — there is no cursor pagination.

### 7.2a Wire body top-level keys (confirmed)

The `Create*Params` / `Update*Params` models above are the ergonomic layer; their validators assemble the confirmed wire body, whose top-level keys are:

- **create (POST)**: `name` (str, max 255), `type`, `definition`, `description` (optional). `create_metric` sets `type="metric"`, `create_formula` sets `type="formula"`, `create_behavior` sets `type` ∈ {`simple`, `funnel`, `retention`}.
- **update (PATCH)**: the same keys, all optional, PLUS two PATCH-only keys — `verified` (bool) and `owned_by` (`{id}`). These two are accepted only on PATCH (the `Update*Params` models carry them; the `Create*Params` models do not).

### 7.3 `ReferencedMetric` serialization — the `exclude_none` exception

The universal serialization rule for this feature is `model_dump(exclude_none=True, by_alias=True)` (§7.1): nullable keys are OMITTED, not emitted as `null`. `ReferencedMetric` is the one documented exception.

Confirmed against the Mixpanel backend: a saved FORMULA stores each `referencedMetrics[i]` measurement block with its nullable keys (`property`, `rolling`, `perUserAggregation`) present as EXPLICIT NULLS, and `cumulative` present as an explicit boolean (defaults to `false`). These are not omitted in the stored payload. To round-trip a formula the library MUST emit those explicit nulls inside each referenced metric.

Therefore `ReferencedMetric` (and the measurement block it carries) MUST NOT be serialized with `exclude_none=True`. It carries its own serialization — a custom Pydantic v2 `@model_serializer` (or a per-call `model_dump(by_alias=True)` without `exclude_none`) — that keeps `property: null`, `rolling: null`, `perUserAggregation: null`, and `cumulative: false` in the wire shape. The enclosing `CreateFormulaParams` still uses `exclude_none=True` for its own top-level keys; only the `referenced_metrics` entries opt out. The matching wire shape is in [contracts/payload-shapes.md §6](contracts/payload-shapes.md).

---

## 8. Invariants (verified by PBT)

Tested via Hypothesis in `tests/pbt/test_metric_math_pbt.py`, `test_behavior_steps_pbt.py`, `test_formula_variables_pbt.py`:

- **Math enum closure**: any string NOT in `MeasurementMath` raises `ValidationError`; every member constructs.
- **Property presence (three branches)**: for any property-aggregation math, omitting `property` raises (M2); for any plain-count math, supplying `property` is normalized away — the emitted payload omits the key (M2); for any rate math, supplying `property` is forbidden — omitted from the emitted payload (M5), and the rate-math behavior shape (M6) holds (conversion_rate_* ⇒ funnel >= 2 steps, retention_rate ⇒ retention == 2 steps).
- **Step counts**: for randomly generated step lists, `funnel` validates iff len>=2, `retention` iff len==2, `simple` iff len>=1.
- **funnel_order closure**: only `loose` / `any` validate.
- **Formula mapping**: for a definition referencing variables S (a set of uppercase tokens), the params validate iff S == {A..A+n-1} and n == len(referenced_metrics).
- **Round-trip**: `Model.model_validate(params_dump)` preserves every set field (where the server echoes it).
