# Data Model: Behaviors, Metrics & Formulas semantic layer

**Feature**: 047-behaviors-metrics-formulas
**Date**: 2026-06-28

This feature adds three saved-entity families to the public surface: **behaviors**, **metrics**, **formulas**. Each family gets a result type plus `Create*`/`Update*` Pydantic v2 param models, plus two shared value types (`MeasurementProperty`, `BehaviorStep`) and one enum (`MeasurementMath`). No new on-disk persistence: these are remote App API entities. This document is the entity ledger plus the validator table.

All types are defined in `mixpanel_headless.types` and exported from `mixpanel_headless.__init__`. Provisional shapes; the response envelopes are confirmed by the live call in research.md R-1 before freeze.

---

## 1. Reused entities (no changes)

| Entity | Source | Notes |
|--------|--------|-------|
| `Workspace` | `workspace.py` | Gains 15 new methods (5 per entity family). No schema change. |
| `MixpanelAPIClient` | `_internal/api_client.py` | Gains 15 App API methods via `maybe_scoped_path` + `app_request` + pagination, mirroring `list_cohorts_app` / `create_cohort` / etc. |
| pagination helper | `_internal/pagination.py` | Reused by the three `list_*` methods (cursor-based). |
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

Property-aggregation maths (require a `MeasurementProperty`): `average, median, min, max, sum, p25, p75, p90, p99, unique_values`.
Plain-count maths (MUST omit property): `total, unique, dau, wau, mau`.

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
    description: str | None = None
    type: Literal["simple", "funnel", "retention"]
    definition: dict[str, Any]      # round-tripped definition.behavior
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

`UpdateBehaviorParams` mirrors with all fields optional (PATCH semantics).

---

## 4. Metrics

### 4.1 `Metric` (result)

```python
class Metric(BaseModel):
    """A saved KPI: an embedded behavior plus a measurement."""
    id: int
    name: str
    description: str | None = None
    definition: dict[str, Any]      # round-tripped {behavior, measurement}
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

`UpdateMetricParams` mirrors with optional fields.

---

## 5. Formulas

### 5.1 `Formula` (result)

```python
class Formula(BaseModel):
    """A saved derived KPI over named metric variables."""
    id: int
    name: str
    description: str | None = None
    definition: str                 # e.g. "(A / B) * 100"
    referenced_metrics: list[dict[str, Any]]   # round-tripped
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

`ReferencedMetric` carries a complete metric shape (behavior + measurement) plus a `display` object restricted to the allowed keys (`abbrev, axis, direction, hideTrendline, precision, prefix, suffix, trendline`). `UpdateFormulaParams` mirrors with optional fields.

---

## 6. Validator table (the authoritative guards)

| Type | Validator | Failure mode prevented |
|------|-----------|------------------------|
| `CreateMetricParams` / `UpdateMetricParams` | `math` is the `MeasurementMath` Literal | bad math (`avg`, `unique_group`) → whole-entity 400 |
| `CreateMetricParams` | property-aggregation math REQUIRES `property`; plain count OMITS it | missing aggregand or stray property on a count → corrupt metric |
| `MeasurementProperty` | property is an object, not a string | bare-string property → webapp crash |
| emitted `measurement` | only keys `math, property, cumulative, dataGroupId, perUserAggregation, rolling, segmentMethod, multiAttribution` | unknown key → 400 |
| `BehaviorStep` | `name` non-empty | nameless step → webapp crash on load |
| `CreateBehaviorParams` | step counts: simple>=1, funnel>=2, retention==2; `behaviors` never empty | short/empty steps → webapp crash on load |
| `CreateBehaviorParams` / `BehaviorStep` | `funnel_order` ∈ {loose, any} | `strict` → 400 |
| `CreateFormulaParams` | variables in `definition` contiguous from A and count == len(referenced_metrics) | variable/metric mismatch → broken formula |
| `ReferencedMetric.display` | only the allowed display keys | `label` key → 400 |

All validators run at construction time (Pydantic v2 `@model_validator` / `@field_validator`), BEFORE any HTTP call. Construction-time failures raise Pydantic `ValidationError`.

---

## 7. State transitions

### 7.1 Create pipeline (per entity family)

```
Create*Params(...)                 # construction-time validation (Pydantic)
    │  ValidationError ─► caller (no HTTP)
    ▼
params.model_dump(exclude_none=True, by_alias=True)   # camelCase payload
    ▼
client.create_*(body)              # 1 RTT, POST maybe_scoped_path(...)
    │  400 ─► QueryError    5xx ─► ServerError    401 ─► AuthenticationError
    ▼
Model.model_validate(raw)          # decode server response → result type
    ▼
Metric | Behavior | Formula        # with server-assigned id
```

### 7.2 Read / update / delete

```
get_*(id)    → GET    maybe_scoped_path("<entity>/{id}")   → Model.model_validate(raw)
update_*(id) → PATCH  maybe_scoped_path("<entity>/{id}")   → Model.model_validate(raw)
delete_*(id) → DELETE maybe_scoped_path("<entity>/{id}")   → None
list_*()     → GET    maybe_scoped_path("<entity>")  (paginated) → list[Model]
```

(Exact entity path segments confirmed by research.md R-1 before freeze.)

---

## 8. Invariants (verified by PBT)

Tested via Hypothesis in `tests/pbt/test_metric_math_pbt.py`, `test_behavior_steps_pbt.py`, `test_formula_variables_pbt.py`:

- **Math enum closure**: any string NOT in `MeasurementMath` raises `ValidationError`; every member constructs.
- **Property presence**: for any property-aggregation math, omitting `property` raises; for any plain-count math, supplying `property` raises (or is normalized away per the chosen rule — fixed by the contract).
- **Step counts**: for randomly generated step lists, `funnel` validates iff len>=2, `retention` iff len==2, `simple` iff len>=1.
- **funnel_order closure**: only `loose` / `any` validate.
- **Formula mapping**: for a definition referencing variables S (a set of uppercase tokens), the params validate iff S == {A..A+n-1} and n == len(referenced_metrics).
- **Round-trip**: `Model.model_validate(params_dump)` preserves every set field (where the server echoes it).
