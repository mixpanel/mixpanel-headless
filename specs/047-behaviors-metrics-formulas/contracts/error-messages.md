# Contract: Error Messages

**Feature**: 047-behaviors-metrics-formulas
**Surface**: Stable validator + API error catalog
**Audience**: Callers writing error-handling code

Validation errors are Pydantic `ValidationError` raised at CONSTRUCTION time (zero HTTP). Server-side errors map to the existing `APIError` hierarchy. Message wording changes require a minor version bump + CHANGELOG entry; stable identifiers (the exception class, the validated field) are stricter.

---

## 1. Bad `measurement.math`

**When**: `CreateMetricParams`/`UpdateMetricParams`/`ReferencedMetric` built with a `math` not in the enum.

```
ValidationError: math "avg" is not a valid measurement math. Valid values:
total, unique, dau, wau, mau, average, median, min, max, sum, p25, p75, p90, p99,
unique_values, conversion_rate_unique, conversion_rate_total,
conversion_rate_session, retention_rate. (Did you mean "average"?)
```

Special-case hints: `avg`→`average`; `unique_group`/`groupKey`→ use `unique` + a numeric `data_group_id`.

---

## 2. Bare-string property

**When**: `property` passed as a string instead of a `MeasurementProperty`.

```
ValidationError: measurement property must be a MeasurementProperty object
({name, type, resourceType}), not the bare string "amount". A bare string
corrupts the metric and crashes the Mixpanel webapp.
```

---

## 3. Property presence mismatch

**When**: property-aggregation math without a property, or plain count with a property.

```
ValidationError: math="sum" is a property aggregation and requires a property object.
```

A plain count (`total`/`unique`/`dau`/`wau`/`mau`) with a stray `property` is NOT an error: the property is silently dropped from the emitted payload (M2 normalization), matching the backend, which strips it on count maths. Likewise a rate math with a stray `property` is dropped, not rejected (M5 normalization). Neither raises.

---

## 3a. Rate-math behavior shape

**When**: a rate math is paired with the wrong behavior shape (rule M6).

```
ValidationError: math="conversion_rate_total" is a conversion rate and requires a funnel behavior with >= 2 steps; got behavior_type="simple".
```
```
ValidationError: math="retention_rate" requires a retention behavior with EXACTLY 2 steps (born + return); got behavior_type="simple".
```

---

## 4. Behavior step counts

**When**: wrong step count for the behavior type, or a nameless step.

```
ValidationError: funnel behaviors require >= 2 steps; got 1.
```
```
ValidationError: retention behaviors require EXACTLY 2 steps (born + return); got 3.
```
```
ValidationError: simple behaviors require >= 1 step; got 0.
```
```
ValidationError: every behavior step requires a non-empty name.
```

---

## 5. Bad `funnel_order`

**When**: `funnel_order` is anything other than `loose`/`any`.

```
ValidationError: funnel_order must be "loose" or "any"; "strict" is not valid.
```

---

## 6. Formula variable mapping

**When**: variables in `definition` do not map 1:1 to `referenced_metrics`.

```
ValidationError: definition "(A / B) * 100" uses 2 variables (A, B) but 1
referenced_metric was given; variables must map 1:1 to referenced_metrics by order.
```
```
ValidationError: variables must be contiguous from A; got A, C (B is missing).
```

---

## 7. Bad `display` key in a referenced metric

**When**: a `ReferencedMetric.display` carries a disallowed key.

```
ValidationError: display object may only contain abbrev, axis, direction,
hideTrendline, precision, prefix, suffix, trendline; got "label".
```

---

## 8. Server-side errors (passed through)

Errors from the App API that are not caught by construction-time validation map to the existing hierarchy:

| HTTP | Exception | Typical cause |
|------|-----------|---------------|
| 401 | `AuthenticationError` | bad / missing credentials |
| 400 | `QueryError` | a payload the validators did not catch (e.g. referenced metric ID does not exist), or a confirmed-shape drift |
| 404 | `QueryError` | get/update/delete of a non-existent entity ID |
| 5xx | `ServerError` | Mixpanel-side failure |

`details` carries the Mixpanel `error` field and request ID per the existing `_handle_response` behavior. The library invents no new exception classes for the semantic layer.

---

## 9. Forward compatibility

- Adding a new validator (a stricter guard) is a minor change; document it in CHANGELOG.
- Relaxing a validator (accepting a previously-rejected shape) is a minor change.
- Changing the exception TYPE a failure raises (e.g. `ValidationError` → a custom class) is a major change.
- Callers MUST NOT pattern-match on message strings; match on the field name in the `ValidationError` or the exception class.
