# Discriminated unions

Everything here was observed against Pydantic 2.13.3. The infrastructure lives in `src/mixpanel_headless/_internal/pydantic_utils.py`; the shape it produces is in [worked_example.py](worked_example.py).

Check the upstream page before relying on any of it — <https://pydantic.dev/docs/validation/latest/concepts/unions/> — since this records one version's behaviour.

---

## Why not a plain `Union`

A `Union` of models with disjoint `Literal`s **routes correctly** — pydantic's smart mode finds the one that matches. It costs nothing to write. It costs a great deal to debug:

| union | errors for one bad payload | first `loc` |
|---|---|---|
| discriminated | **2** | `('#list_contains', 'list_item_filters', 0)` |
| plain | **47** | `('list_item_filters', 0, 'function-after[_guard_cohort_property(), IsSet]', 'operator')` |

Every member reports its own complaint, and internal validator names surface in the path. On a 25-member union one typo produces ~20 errors, the first pointing at a member the caller never meant.

That is the entire reason `pydantic_utils.py` exists.

## Where native `Field(discriminator=…)` actually fails

Get this boundary right — the obvious guess is wrong in both directions.

| case | native | note |
|---|---|---|
| one model, `Literal["a","b","c","d"]` | **builds** | routes, and emits all four mapping entries |
| two models both claiming `"equals"` | **fails** | `Value 'equals' for discriminator 'operator' mapped to multiple choices` |

So a *multi-valued* literal is fine; a *shared* value is not. Grouping four operators into one model works natively. Splitting equality into a string variant and a numeric variant does not, because both would claim `"equals"`.

Native's real cost is elsewhere: **it copies the matched tag into the error `loc`.**

```
loc: ('is at most', 'value')
```

`is at most` is not a key the caller sent. Stripping it by name is unsafe, because a tag can equal a real field name — this repo has a criterion whose `kind` value is `"property"` sitting beside a `property` field.

## `MarkedTag`: strippable by shape

Every tag this package builds is `#`-prefixed. `#` cannot occur in a Python identifier or an alias, so a tag is recognisable **by shape** — no registry, no collision:

```python
loc = ('#NumericComparisonFilter', 'value', 'int')
tuple(x for x in loc if not is_meta_key(x))     # ('value', 'int')
```

`is_meta_key` also matches pydantic's own labels for undiscriminated unions (`list[str]`, `constrained-int`) heuristically — those have brackets or a `constrained-` prefix, which no field name has.

## `MarkedDiscriminator`

Wraps `Discriminator` + `Tag` — the pure-pydantic pairing — and adds three things: the `#` prefix, the `Tag` wrappers written for you, and an OpenAPI block pydantic will not emit for a callable.

```python
Filter = Annotated[
    PresenceFilter | EqualityFilter | ...,
    MarkedDiscriminator("operator", error_type="invalid_filter_operator"),
]
```

### The string form needs no callable

Given a field name, the marker reads each member's `Literal` and builds the map itself. Adding a value to a member's `Literal` makes it routable with no second edit. Prefer this to a callable whenever members share a discriminator field.

### Multi-valued literals, and the value→tag map

A model claiming several literals cannot be named after any one of them, so `alternative_name` falls back to the **type name**, and the tag stops doubling as the payload value. Routing then goes value → tag through a map:

```python
# one model, four operators
class NumericComparisonFilter(AbstractFilter):
    operator: Literal["is greater than", "is less than", "is at least", "is at most"]
```
```
tag:     '#NumericComparisonFilter'
mapping: {"is greater than": "#/$defs/NumericComparisonFilter",
          "is less than":    "#/$defs/NumericComparisonFilter", ...}
```

Single-valued members are unaffected — their tag is still the literal itself, so existing unions keep their exact error paths.

### `error_type` is load-bearing

| | unroutable-value message |
|---|---|
| without | `Unable to extract tag using discriminator by_field_operator()` |
| with | `operator must be one of 'is set', 'is not set', 'equals', …` |

The generated list names the **values a payload may carry**, not the model names. Omitting `error_type` degrades the message silently.

### The OpenAPI block

Pydantic emits `discriminator` only for `Field(discriminator=…)`, because it cannot know what a callable routes on. This marker always routes through a callable — that is how the tag gets marked — so it supplies the block itself from the map it already built:

```json
"discriminator": {"propertyName": "operator",
                  "mapping": {"equals": "#/$defs/EqualityFilter", ...}}
```

Keyed on the **unmarked** values a payload carries; no `#` tag reaches the schema. Skipped in three cases where it could not be stated truthfully: routing by shape (no property to name), a branch count that has drifted from the tag list, and any branch that is not a plain `$ref`.

It is a hint, not information — the `oneOf` is already decidable because each member pins the field to its own literal.

### `members=` for a member that cannot name itself

```python
Step = Annotated[
    str | FlowStep,
    MarkedDiscriminator(_str_or("FlowStep"),
                        members={"str": NonEmptyStr, "FlowStep": FlowStep},
                        error_type="invalid_flow_step"),
]
```

Use it for constrained aliases, hidden schema wrappers, or a `str` alternative. **Never add a field to the model just to give the discriminator something to read** — that field would appear in the schema as a phantom property callers must not set.

---

## Anti-patterns

Each was tried during this work and rejected for the stated reason.

### `RootModel` to name a nested union

A nested union renders as an inline `{"oneOf": [...]}`, not a `$ref`, so an outer `mapping` has nothing to point at. `RootModel` gives it a name and fixes the `$ref` — but it **wraps the instance**: `isinstance(f, Base)` becomes false and `f.value` becomes `f.root.value`. Disqualifying for a union member.

### Nesting one marked union inside another

Works — correct routing, no `skipped-discriminator` warning, both tags marked. But it renders inline (above), splits the error vocabulary in two, and makes one branch structurally unlike its siblings. Prefer one flat union.

### A discriminator that never returns `None`

```python
def route(v):                                        # wrong
    return "NumberVariant" if pt == "number" else "StringVariant"
```

An unknown value falls through to the fallback member, which then complains about **its own narrow subset** — losing the union-level message that would have named every legal value. Return `None` for anything unclaimed so the union reports it.

This degrades silently: every test still passes.

### Hand-maintained routing or vocabulary tables

Derive from the annotations (`get_args(Model.model_fields[f].annotation)`) or from the declared source of truth (`get_args(SomeLiteral)`). A guard built from a hand-written set stops guarding the moment the two drift, and it fails by *skipping* a case rather than by erroring.

### `object.__setattr__` to normalize on a frozen model

Bypasses `frozen=True` from inside an after-validator. Use a `BeforeValidator`. Note the declared type then describes the *input*, not the output, unless `json_schema_input_type` is available.

### `json_schema_extra` alone for a cross-field rule

`if`/`then`/`else` states the rule in the schema, and it **does nothing at runtime**. Paired with a `model_validator` it achieves parity — at the cost of the rule existing twice with nothing keeping the halves in sync. Prefer splitting the model when the discriminator allows it; accept the duplication only when it does not.
