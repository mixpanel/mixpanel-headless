# Contract: Python API

**Feature**: 047-behaviors-metrics-formulas
**Surface**: `mixpanel_headless` public exports
**Audience**: Developers using `mixpanel-headless` as a Python library

This contract enumerates every new public symbol and its signature. `data-model.md` documents the shape of types; `payload-shapes.md` documents the wire format; `error-messages.md` documents stable errors.

---

## 1. `Workspace` methods

All added to `mixpanel_headless.workspace.Workspace`, mirroring the cohort CRUD *naming* shape. The three public method families map onto **two project-scoped App API endpoints** (confirmed; research.md R-1): behaviors → `/api/app/projects/{pid}/behaviors/`, and BOTH metrics and formulas → `/api/app/projects/{pid}/metrics/` (a formula is a metric with `type="formula"`, so the formula methods are the metrics client operations discriminated by `type`). These entities are project-scoped only — no workspace scoping. `list_*` parses the object-map list envelope (`{"status":"ok","results":{"<id>":{...}}}`) into a typed list; there is no cursor pagination.

### Behaviors

```python
def list_behaviors(self) -> list[Behavior]:
    """List saved behaviors via the App API.

    Parses the object-map list envelope (results keyed by string ID) into a
    typed list; no cursor pagination.

    Returns:
        List of Behavior, possibly empty.

    Raises:
        AuthenticationError, QueryError, ServerError.
    """

def get_behavior(self, behavior_id: int) -> Behavior:
    """Get a single behavior by ID. Raises QueryError on 404."""

def create_behavior(self, params: CreateBehaviorParams) -> Behavior:
    """Create a behavior. params is validated at construction time; this call
    issues one POST. Raises QueryError on a server-side 400."""

def update_behavior(self, behavior_id: int, params: UpdateBehaviorParams) -> Behavior:
    """Update a behavior (PATCH semantics; unset fields untouched)."""

def delete_behavior(self, behavior_id: int) -> None:
    """Delete a behavior via single-item DELETE on /behaviors/{id}/.
    Raises QueryError on 404."""
```

### Metrics

```python
def list_metrics(self) -> list[Metric]: ...        # /metrics/ results filtered to type="metric"
def get_metric(self, metric_id: int) -> Metric: ...
def create_metric(self, params: CreateMetricParams) -> Metric: ...   # POST /metrics/ with type="metric"
def update_metric(self, metric_id: int, params: UpdateMetricParams) -> Metric: ...
def delete_metric(self, metric_id: int) -> None: ...   # BULK DELETE on /metrics/ ({"metrics":[{id}]})
```

Docstrings mirror the behavior family. `create_metric` / `update_metric` emit a `measurement` object containing only the allowed keys; the property is included iff `math` is a property-aggregation math. `list_metrics` reads the `/metrics/` collection and returns only entries with `type="metric"` (formulas are filtered out — see `list_formulas`). `delete_metric` MUST use the **bulk DELETE** on the `/metrics/` collection path (the single-item metric DELETE returns 501 NOT IMPLEMENTED); it sends `{"metrics":[{"id": metric_id}]}`.

### Formulas

Formulas have no separate endpoint: each method below is the corresponding `/metrics/` operation with `type="formula"`.

```python
def list_formulas(self) -> list[Formula]: ...      # /metrics/ results filtered to type="formula"
def get_formula(self, formula_id: int) -> Formula: ...
def create_formula(self, params: CreateFormulaParams) -> Formula: ...   # POST /metrics/ with type="formula"
def update_formula(self, formula_id: int, params: UpdateFormulaParams) -> Formula: ...
def delete_formula(self, formula_id: int) -> None: ...   # BULK DELETE on /metrics/ ({"metrics":[{id}]})
```

`create_formula` / `update_formula` POST to the **metrics** endpoint with `type="formula"` and emit `referencedMetrics` in `A, B, ...` array order matching the variables in `definition`. `list_formulas` reads the `/metrics/` collection and returns only entries with `type="formula"`. `delete_formula` MUST use the **bulk DELETE** on the `/metrics/` collection path (single-item metric DELETE returns 501); it sends `{"metrics":[{"id": formula_id}]}`.

**Public 3-family / 2-endpoint mapping**: `*_behavior` → `/behaviors/`; `*_metric` and `*_formula` → `/metrics/`, discriminated by the wire `type` field (`"metric"` vs `"formula"`). The three public families stay distinct for typed ergonomics, but only two endpoints are wired.

---

## 2. Param + result types

Documented in detail in [data-model.md](../data-model.md). Quick reference:

| Type | Returned by / used by | Key feature |
|------|-----------------------|-------------|
| `Behavior` | `*_behavior` reads/writes | simple/funnel/retention saved action |
| `CreateBehaviorParams` / `UpdateBehaviorParams` | `create/update_behavior` | step-count + funnel_order validators |
| `Metric` | `*_metric` reads/writes | embedded behavior + measurement |
| `CreateMetricParams` / `UpdateMetricParams` | `create/update_metric` | math enum + property-object validators |
| `Formula` | `*_formula` reads/writes | derived KPI over metric variables |
| `CreateFormulaParams` / `UpdateFormulaParams` | `create/update_formula` | variable↔referencedMetrics 1:1 validator |
| `MeasurementProperty` | metric / referenced-metric aggregand | object, never bare string |
| `BehaviorStep` | behavior / metric step | non-empty name |
| `ReferencedMetric` | formula `referenced_metrics[i]` | complete metric shape + allowed display keys |
| `MeasurementMath` | `math` field | strict Literal enum |

---

## 3. Errors

Validation failures are Pydantic `ValidationError` raised at construction time (zero HTTP). Server-side failures map to the existing hierarchy:

```text
APIError
├── AuthenticationError   # 401
├── QueryError            # 400 / 404
└── ServerError           # 5xx
```

No new exception classes. See [error-messages.md](error-messages.md) for stable messages.

---

## 4. Public exports (`__init__.py`)

```python
# Added to mixpanel_headless.__all__:
"Behavior",
"CreateBehaviorParams",
"UpdateBehaviorParams",
"Metric",
"CreateMetricParams",
"UpdateMetricParams",
"Formula",
"CreateFormulaParams",
"UpdateFormulaParams",
"MeasurementProperty",
"BehaviorStep",
"ReferencedMetric",
"MeasurementMath",
```

---

## 5. Consumers

| Consumer | Relationship |
|----------|--------------|
| Any Python script using `mixpanel-headless` | Direct user of the 15 `Workspace` methods + param/result types. The surface is independently useful. |
| metric-maker skill (feature 048) | First skill consumer; calls `create_behavior` / `create_metric` / `create_formula` plus the existing custom-event/property/cohort CRUD to assemble starter kits. Adds no library code. Ships as a separate PR after this feature. |
