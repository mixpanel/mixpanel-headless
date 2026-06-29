# Contract: Payload Shapes (behaviors / metrics / formulas)

**Feature**: 047-behaviors-metrics-formulas
**Surface**: App API request/response bodies for the three saved-entity families
**Audience**: The build session wiring `MixpanelAPIClient`; reviewers verifying the validators emit exactly these shapes
**Source of truth**: [mixpanel/mixpanel-power-tools](https://github.com/mixpanel/mixpanel-power-tools), `templates/prompts/ai-behaviors-metrics-system.txt`, for the BODY shapes; the ENDPOINT PATHS + LIST ENVELOPE are CONFIRMED against the Mixpanel backend App API (see [research.md R-1](../research.md)) and recorded in §0 below.

The param-model validators MUST refuse to emit anything that violates the constraints in this document. Changing a documented constraint requires a power-tools reference update and a CHANGELOG entry.

---

## 0. Endpoint paths — CONFIRMED

CONFIRMED against the Mixpanel backend App API (see [research.md R-1](../research.md)). All paths are **project-scoped** — there is **NO workspace scoping** for these entities (unlike cohorts). Two endpoints back the three public method families: `/behaviors/` and `/metrics/` (formulas ride `/metrics/`, discriminated by `type`).

### Behaviors — `/api/app/projects/{project_id}/behaviors/`

| Operation | Method | Path | Body |
|-----------|--------|------|------|
| list | GET | `/api/app/projects/{project_id}/behaviors/` | — |
| create | POST | `/api/app/projects/{project_id}/behaviors/` | a single behavior OR `{"behaviors": [...]}` |
| bulk update | PATCH | `/api/app/projects/{project_id}/behaviors/` | `{"behaviors": [{id, ...}]}` |
| bulk delete | DELETE | `/api/app/projects/{project_id}/behaviors/` | `{"behaviors": [{id}]}` |
| get | GET | `/api/app/projects/{project_id}/behaviors/{behavior_id}/` | — |
| update | PATCH | `/api/app/projects/{project_id}/behaviors/{behavior_id}/` | behavior fields |
| delete | DELETE | `/api/app/projects/{project_id}/behaviors/{behavior_id}/` | — |

### Metrics AND formulas — `/api/app/projects/{project_id}/metrics/`

A formula is a metric with `type="formula"`; metrics (`type="metric"`) and formulas (`type="formula"`) share this one endpoint, discriminated by the top-level `type` field.

| Operation | Method | Path | Body |
|-----------|--------|------|------|
| list | GET | `/api/app/projects/{project_id}/metrics/` | — |
| create | POST | `/api/app/projects/{project_id}/metrics/` | a single metric/formula (`type` discriminates) |
| bulk update | PATCH | `/api/app/projects/{project_id}/metrics/` | `{"metrics": [{id, ...}]}` |
| bulk delete | DELETE | `/api/app/projects/{project_id}/metrics/` | `{"metrics": [{id}]}` |
| get | GET | `/api/app/projects/{project_id}/metrics/{metric_id}/` | — |
| update | PATCH | `/api/app/projects/{project_id}/metrics/{metric_id}/` | metric/formula fields |
| delete (single) | DELETE | `/api/app/projects/{project_id}/metrics/{metric_id}/` | **returns 501 NOT IMPLEMENTED** |

**Metric/formula deletion MUST go through the bulk DELETE** on the collection path — single-item DELETE returns 501. (Behaviors support single-item DELETE; metrics/formulas do not.)

### List-response envelope (CONFIRMED)

```json
{ "status": "ok", "results": { "<id>": { /* entity */ }, "<id2>": { /* entity */ } } }
```

`results` is an **OBJECT MAP KEYED BY STRING ID**, NOT an array, with **NO cursor pagination / `page_info`**. The `list_*` methods parse the map's values into a list of typed objects — no pagination helper needed (this differs from cohorts).

### Create/update body — top-level keys

`name` (str, max 255), `type`, `definition`, `description` (optional). PATCH additionally accepts `verified` (bool) and `owned_by` (`{id}`). Behavior `type` ∈ {`simple`, `funnel`, `retention`}; metric `type` ∈ {`metric`, `formula`}.

### Response entity fields

`id`, `name`, `type`, `description`, `definition`, `is_visible`, `is_locked`, `created`, `modified`, `created_by` (`{id, email, name}`), `verified` (optional), `owned_by` (optional).

The BODY shapes in §1–§6 below are confirmed against the Mixpanel backend (math property-presence branches, rate-math behavior shapes, the saved measurement-object shape, and the formula `referencedMetrics` explicit nulls).

---

## 1. Measurement object (shared by metrics + referenced metrics)

Allowed keys ONLY (omit unset): `math, property, cumulative, dataGroupId, perUserAggregation, rolling, segmentMethod, multiAttribution`. Any other key 400s.

`math` strict enum: `total, unique, dau, wau, mau, average, median, min, max, sum, p25, p75, p90, p99, unique_values, conversion_rate_unique, conversion_rate_total, conversion_rate_session, retention_rate`.

`property` (ONLY for property-aggregation math) MUST be an object:

```json
{ "name": "amount", "type": "number", "resourceType": "events" }
```

Property presence has THREE branches (confirmed against the Mixpanel backend):
- **property-aggregation** (`average`/`median`/`min`/`max`/`sum`/`p25`/`p75`/`p90`/`p99`/`unique_values`): `property` REQUIRED.
- **plain count** (`total`/`unique`/`dau`/`wau`/`mau`): `property` MUST be OMITTED (a stray property is silently stripped, not rejected — the backend strips it on count maths).
- **rate** (`conversion_rate_unique`/`conversion_rate_total`/`conversion_rate_session`/`retention_rate`): `property` FORBIDDEN (omitted; real backend payloads carry `"property": null`), AND a behavior shape is REQUIRED — the three `conversion_rate_*` need a `funnel` behavior with >= 2 steps, `retention_rate` needs a `retention` behavior with EXACTLY 2 steps (born + return).

There is NO `avg`, NO `unique_group`, NO `groupKey`. To count distinct groups use `math: "unique"` + a numeric `dataGroupId`.

---

## 2. Simple behavior

```json
{
  "type": "behavior",
  "name": "Shopping Activity",
  "description": "All shopping-related user actions",
  "definition": {
    "behavior": {
      "type": "simple",
      "resourceType": "events",
      "filters": [],
      "filtersDeterminer": "all",
      "behaviors": [
        { "type": "event", "name": "view product", "filters": [], "filtersDeterminer": "all" },
        { "type": "event", "name": "add to cart", "filters": [], "filtersDeterminer": "all" }
      ]
    }
  }
}
```

Rule: `definition.behavior.behaviors` non-empty (>= 1 for simple). Every step has a non-empty `name` and a `type`.

---

## 3. Funnel behavior

```json
{
  "type": "behavior",
  "name": "Checkout Funnel",
  "definition": {
    "behavior": {
      "type": "funnel",
      "resourceType": "events",
      "behaviors": [
        { "name": "view cart", "type": "event", "filters": [], "funnelOrder": "loose", "filtersDeterminer": "all" },
        { "name": "checkout",  "type": "event", "filters": [], "funnelOrder": "loose", "filtersDeterminer": "all" },
        { "name": "purchase",  "type": "event", "filters": [], "funnelOrder": "loose", "filtersDeterminer": "all" }
      ],
      "exclusions": [],
      "aggregateBy": [],
      "funnelOrder": "loose",
      "conversionWindowUnit": "day",
      "conversionWindowDuration": 7
    }
  }
}
```

Rules: >= 2 steps. `funnelOrder` (top-level AND per-step) ∈ {`loose`, `any`} — NO `strict`. `aggregateBy` is an array of full property objects or `[]` (never bare strings).

---

## 4. Retention behavior

```json
{
  "type": "behavior",
  "name": "Weekly Retention",
  "definition": {
    "behavior": {
      "type": "retention",
      "dataset": "$mixpanel",
      "resourceType": "events",
      "behaviors": [
        { "name": "$mp_anything_event", "type": "event", "filters": [], "filtersDeterminer": "all" },
        { "name": "$mp_anything_event", "type": "event", "filters": [], "filtersDeterminer": "all" }
      ],
      "retentionType": "birth",
      "retentionUnit": "day",
      "retentionAlignmentType": "birth",
      "retentionUnboundedMode": "none"
    }
  }
}
```

Rule: EXACTLY 2 steps (born + return). Fewer crashes the query builder.

---

## 5. Metric (embedded behavior + measurement)

```json
{
  "type": "metric",
  "name": "Daily Active Users",
  "definition": {
    "behavior": {
      "type": "simple",
      "resourceType": "events",
      "filters": [],
      "filtersDeterminer": "all",
      "behaviors": [
        { "name": "$mp_anything_event", "type": "event", "filters": [], "filtersDeterminer": "all" }
      ]
    },
    "measurement": { "math": "unique", "cumulative": false }
  }
}
```

Property-aggregation example (`measurement` carries the property object):

```json
"measurement": {
  "math": "average",
  "property": { "name": "amount", "type": "number", "resourceType": "events" },
  "cumulative": false
}
```

---

## 6. Formula (referencedMetrics map 1:1 to variables by order)

```json
{
  "type": "formula",
  "name": "Engagement Rate",
  "definition": {
    "formula": {
      "definition": "(A / B) * 100",
      "referencedMetrics": [
        {
          "type": "metric",
          "display": {},
          "behavior": { "name": "user session", "type": "event", "search": "", "dataset": "$mixpanel",
                        "filters": [], "dataGroupId": null, "profileType": null, "resourceType": "events" },
          "measurement": { "math": "unique", "rolling": null, "property": null, "cumulative": false, "perUserAggregation": null }
        },
        {
          "type": "metric",
          "display": {},
          "behavior": { "name": "signup", "type": "event", "search": "", "dataset": "$mixpanel",
                        "filters": [], "dataGroupId": null, "profileType": null, "resourceType": "events" },
          "measurement": { "math": "unique", "rolling": null, "property": null, "cumulative": false, "perUserAggregation": null }
        }
      ]
    },
    "measurement": {}
  }
}
```

Rules:
- distinct variables in `definition` contiguous from `A`; count == `referencedMetrics.length`.
- `referencedMetrics[0]` → `A`, `[1]` → `B`, ...
- each `display` object: ONLY `abbrev, axis, direction, hideTrendline, precision, prefix, suffix, trendline`. NO `label`. Empty `{}` is fine.
- formula expressions: simple `+ - * /` only (per the reference; nested-metric formulas are out of scope).
- **Explicit nulls inside each referenced metric** (confirmed against the Mixpanel backend): the `measurement` block of each `referencedMetrics[i]` carries its nullable keys as EXPLICIT NULLS — `property: null`, `rolling: null`, `perUserAggregation: null` — and `cumulative` as an explicit boolean (`false`). These are NOT omitted (see the example above). This is the one place the feature-wide `exclude_none=True` rule does NOT apply: `ReferencedMetric` uses a custom serializer that keeps the nulls so the formula round-trips. See [data-model.md §7.3](../data-model.md) and [research.md R-6](../research.md).

---

## 7. Forward compatibility

- Adding a new optional measurement key (within the allowed set) is backward-compatible.
- Changing the `math` enum members is a major change (callers pattern-match on validation).
- The confirmed endpoint paths (§0) are locked at freeze; a server-side path change is a client-plumbing-only update (param models unchanged).
