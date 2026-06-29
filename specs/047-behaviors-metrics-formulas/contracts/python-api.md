# Contract: Python API

**Feature**: 047-behaviors-metrics-formulas
**Surface**: `mixpanel_headless` public exports
**Audience**: Developers using `mixpanel-headless` as a Python library

This contract enumerates every new public symbol and its signature. `data-model.md` documents the shape of types; `payload-shapes.md` documents the wire format; `error-messages.md` documents stable errors.

---

## 1. `Workspace` methods

All added to `mixpanel_headless.workspace.Workspace`, mirroring the cohort CRUD shape.

### Behaviors

```python
def list_behaviors(self) -> list[Behavior]:
    """List saved behaviors via the App API (cursor-paginated).

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
    """Delete a behavior. Raises QueryError on 404."""
```

### Metrics

```python
def list_metrics(self) -> list[Metric]: ...
def get_metric(self, metric_id: int) -> Metric: ...
def create_metric(self, params: CreateMetricParams) -> Metric: ...
def update_metric(self, metric_id: int, params: UpdateMetricParams) -> Metric: ...
def delete_metric(self, metric_id: int) -> None: ...
```

Docstrings mirror the behavior family. `create_metric` / `update_metric` emit a `measurement` object containing only the allowed keys; the property is included iff `math` is a property-aggregation math.

### Formulas

```python
def list_formulas(self) -> list[Formula]: ...
def get_formula(self, formula_id: int) -> Formula: ...
def create_formula(self, params: CreateFormulaParams) -> Formula: ...
def update_formula(self, formula_id: int, params: UpdateFormulaParams) -> Formula: ...
def delete_formula(self, formula_id: int) -> None: ...
```

`create_formula` / `update_formula` emit `referencedMetrics` in `A, B, ...` array order matching the variables in `definition`.

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
