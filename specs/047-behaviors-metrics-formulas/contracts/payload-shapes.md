# Contract: Payload Shapes (behaviors / metrics / formulas)

**Feature**: 047-behaviors-metrics-formulas
**Surface**: App API request/response bodies for the three saved-entity families
**Audience**: The build session wiring `MixpanelAPIClient`; reviewers verifying the validators emit exactly these shapes
**Source of truth**: [mixpanel/mixpanel-power-tools](https://github.com/mixpanel/mixpanel-power-tools), `templates/prompts/ai-behaviors-metrics-system.txt`, for the BODY shapes; the exact ENDPOINT PATHS + LIST ENVELOPE are NEEDS-CONFIRMATION (see [research.md R-1](../research.md)) and MUST be filled in from one live call before the binding surface freezes.

The param-model validators MUST refuse to emit anything that violates the constraints in this document. Changing a documented constraint requires a power-tools reference update and a CHANGELOG entry.

---

## 0. Endpoint paths — CONFIRM BEFORE FREEZE

Provisional (mirrors the cohort idiom; confirm against live):

| Operation | Method | Provisional path (via `maybe_scoped_path`) |
|-----------|--------|--------------------------------------------|
| list behaviors | GET | `/api/app/projects/{pid}/behaviors` |
| create behavior | POST | `/api/app/projects/{pid}/behaviors` |
| get / update / delete behavior | GET / PATCH / DELETE | `.../behaviors/{id}` |
| metrics | ... | `.../metrics` + `.../metrics/{id}` |
| formulas | ... | `.../formulas` + `.../formulas/{id}` |

The build session records the CONFIRMED paths, the list-response envelope (raw list vs `{results: [...]}` vs cursor-paginated), and the create-response shape here after the live call. Until then this section is provisional.

---

## 1. Measurement object (shared by metrics + referenced metrics)

Allowed keys ONLY (omit unset): `math, property, cumulative, dataGroupId, perUserAggregation, rolling, segmentMethod, multiAttribution`. Any other key 400s.

`math` strict enum: `total, unique, dau, wau, mau, average, median, min, max, sum, p25, p75, p90, p99, unique_values, conversion_rate_unique, conversion_rate_total, conversion_rate_session, retention_rate`.

`property` (ONLY for property-aggregation math) MUST be an object:

```json
{ "name": "amount", "type": "number", "resourceType": "events" }
```

For plain counts (`total`/`unique`/`dau`/`wau`/`mau`) `property` MUST be OMITTED.

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

---

## 7. Forward compatibility

- Adding a new optional measurement key (within the allowed set) is backward-compatible.
- Changing the `math` enum members is a major change (callers pattern-match on validation).
- The confirmed endpoint paths (§0) are locked at freeze; a server-side path change is a client-plumbing-only update (param models unchanged).
