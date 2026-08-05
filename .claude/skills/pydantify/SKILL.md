---
name: pydantify
description: Use when adding or changing any Pydantic model, field, union, validator, discriminator, or JSON-schema behaviour in this repo — including anything in types.py, query_models.py, _internal/pydantic_utils.py, or the generated model_json_schema() output. Covers how to express a rule (field type vs validator vs documented residual), how to choose and wire a discriminated union, the schema/runtime parity contract other repositories depend on, and the mypy --strict constraints that shape all of it.
user-invocable: true
---

# Pydantic in this repo

## Step 0 — read the upstream docs first

**Before writing anything**, fetch <https://pydantic.dev/docs/validation/latest/get-started/> and follow it to the sections your change touches. Pydantic moves; what you remember is probably a version or two stale, and it gains features that make hand-rolled work unnecessary.

Start points:

| doing | read |
|---|---|
| a model, fields, config | [concepts/models](https://pydantic.dev/docs/validation/latest/concepts/models/), [concepts/fields](https://pydantic.dev/docs/validation/latest/concepts/fields/) |
| a union or discriminator | [concepts/unions](https://pydantic.dev/docs/validation/latest/concepts/unions/) |
| a validator or coercion | [concepts/validators](https://pydantic.dev/docs/validation/latest/concepts/validators/) |
| anything schema-shaped | [concepts/json_schema](https://pydantic.dev/docs/validation/latest/concepts/json_schema/) |
| error shape or `loc` | [errors/errors](https://pydantic.dev/docs/validation/latest/errors/errors/) |

**If the request is anything non-standard, consult the docs before designing.** Say what you read and what it said. Several designs in this repo were rejected outright by one paragraph of upstream documentation, and one restriction we worked around for weeks turned out to be self-imposed.

Then: prefer a built-in mechanism over hand-rolled logic, always. If the answer is not built in, it does not belong in the model — it goes in a rules module as a plain function.

---

## The contract

`model_json_schema()` is **published**. Other repositories import these models and drive an LLM/MCP request schema off the generated schema. A payload one layer accepts and the other rejects is the defect class this whole area exists to close.

Everything below serves that. Read [references/verified-behaviour.md](references/verified-behaviour.md) before asserting how Pydantic behaves — it records what was observed, not what seems likely. Read [references/discriminated-unions.md](references/discriminated-unions.md) before touching a union.

[references/worked_example.py](references/worked_example.py) is the shape, end to end: base, shape models, rules module, a residual, a composite, and the union. It runs and self-checks — `uv run python .claude/skills/pydantify/references/worked_example.py`. Read it rather than reinventing the layout.

---

## 1. Parity is the invariant

Schema and runtime must accept the same payloads. Every divergence is a **documented residual**, and the direction decides how bad it is.

| direction | meaning | verdict |
|---|---|---|
| **schema ⊃ runtime** | schema blesses a payload the runtime rejects | tolerable — but a generator *will* emit it, so surface the runtime error rather than assuming it cannot happen |
| **runtime ⊃ schema** | the runtime accepts what the schema forbids | **eliminate** — the library's own output becomes schema-invalid |

`SkipJsonSchema` manufactures the second direction. Reach for it only when a shape genuinely must not be public, and record it as a residual.

Never claim a residual is "the safe direction" without saying which direction it is. Both phrasings are true of *different* residuals; conflating them hides the one that matters.

## 2. Express a rule at the highest level that can hold it

Work down this list. Stop at the first that fits.

**1 — A field type.** Most rules are shapes, and a shape belongs in the annotation where both the validator and the schema can see it.

```python
value: Annotated[list[str], Field(min_length=1, max_length=_MAX_FILTER_VALUES)]
value: StrictInt | StrictFloat                       # rejects True and "5"
operator: Literal["is greater than", "is less than"] # closed set, in the schema
quantity: Annotated[StrictInt, Field(gt=0)]          # exclusiveMinimum: 0
```

Prefer `StringConstraints(pattern=…)` over a hand-written `WithJsonSchema` blob: it renders the same schema natively *and* splits a pattern failure (`string_pattern_mismatch`, catchable schema-side) from a semantic one (`value_error`, runtime-only). One caveat — it takes the shape rejection over, so a hand-written message for it becomes unreachable; when the message matters more than the split, declare the pattern in `json_schema_extra` instead. Same schema either way. See [references/verified-behaviour.md](references/verified-behaviour.md).

**2 — A `model_validator`, when the rule spans fields.** Field types cannot see siblings. Keep the hook to one line and put the body in a rules module.

```python
@model_validator(mode="after")
def _check_order(self) -> DateRangeFilter:
    """Endpoint ordering; no JSON Schema form exists."""
    check_dates_ordered(self.value)     # body lives in the rules module
    return self
```

If JSON Schema *can* state the rule, also declare it with `json_schema_extra` (`if`/`then`/`else` for a cross-field pairing) so the schema stays in parity. Note the cost in a comment: `json_schema_extra` is **inert at runtime**, so the rule then exists twice and nothing keeps the halves in sync.

**3 — A documented residual.** Some rules have no JSON Schema form: comparing two elements of one array, calendar validity, `int` versus integral `float`. Say so where the type is defined, and name the direction.

## 3. Model layout

**One model per shape, not per value.** A value earns its own model only when it needs a different field or a different rule. Four numeric comparison operators share one model; equality needs its own because its `value` is tied to `property_type`.

Grouping is free at the routing layer — `MarkedDiscriminator` maps every literal a model claims onto that model.

**Public field names.** `property`, not `_property` + `validation_alias`. `BaseModel` rejects leading-underscore field names outright, so the underscore convention is what forces a model to stay a pydantic dataclass. Public names also fix serialization: with only a `validation_alias`, `model_dump(by_alias=True)` emits the *field name*, so such models do not round-trip through their own schema.

**Validation logic out of the models.** A model is field declarations, `model_config`, and at most a one-line validator hook. Rules are plain functions over primitives in a module that imports **no model** — that is what keeps the import acyclic.

**Serialization logic belongs on the model.** The rule above is about *validation*, and its whole justification is that acyclicity constraint: a rule needs helpers, and helpers must not import models. Rendering a model into a wire format only reads `self`, so it has no such problem — and pushing it outside means a builder re-deriving, from the outside, groupings the models already encode. That is how this repo ended up with four hand-written operator frozensets restating the filter member split, one of which had silently drifted out of sync.

So: give the base an overridable renderer, and let each model override only where its shape differs.

```python
class AbstractMixpanelModel(BaseModel):
    def mixpanel_model_dump(self, fmt: WireFormat = "default") -> dict[str, Any]:
        if fmt == "bookmark":
            return self._dump_bookmark()          # one typed ladder, in the base
        return self.model_dump()

    def _dump_bookmark(self) -> dict[str, Any]:
        return self.model_dump()                  # subclasses override as needed
```

Two things this buys, both of which the outside-in version cannot: "which operators behave this way" becomes "which class overrides the hook", so it cannot drift; and a member that *cannot* be expressed in a dialect says so itself rather than being caught by an `isinstance` check in someone else's loop.

Dispatch in the base, not `getattr(self, f"_dump_{fmt}")` — stringly-typed lookup is unverifiable under `mypy --strict` — and not a `fmt` switch inside every subclass, which repeats the ladder once per member. Where the rendering needs data (operator tables, format helpers), move that next to the models too; a model cannot import the builder module that imports it.

Anything a caller supplies that the model cannot know — a list index for an error path, a fallback from a sibling object — stays with the caller. Raise a small carrier exception and let it attach the position.

**Naming.** `AbstractX` for a base that is not a union member. `XFilter` / `XCriterion` for members. The short, unqualified name for the union annotation, because that is what appears in signatures:

```python
class AbstractFilter(BaseModel): ...      # base: shared fields, config, factories
class PresenceFilter(AbstractFilter): ... # member
Filter = Annotated[PresenceFilter | ..., MarkedDiscriminator("operator", ...)]
```

A base cannot share the union's name: a union is an `Annotated` alias and carries neither classmethods nor `isinstance`.

## 4. Choosing a union

| approach | routing code | error on a bad branch | OpenAPI `discriminator` | error `loc` |
|---|---|---|---|---|
| plain `Union` | none | **~N errors**, one per member | no | pydantic internals leak |
| `Field(discriminator=…)` | one line | 1–2 | yes | **tag leaks** |
| `Discriminator` + `Tag` | one callable | 1–2 | no | tag leaks |
| **`MarkedDiscriminator`** | one line | 1–2 | yes | **clean** |

**Default to `MarkedDiscriminator`.** It is the house convention, it is the only option that gets both a clean `loc` and the OpenAPI block, and its string form needs no callable:

```python
Filter = Annotated[
    PresenceFilter | EqualityFilter | ...,
    MarkedDiscriminator("operator", error_type="invalid_filter_operator"),
]
```

Two things to get right:

**Pass `error_type`.** Without it an unroutable value reports `"Unable to extract tag using discriminator by_field_operator()"`. With it, the marker generates `"operator must be one of 'is set', 'is not set', …"` from the members.

**Never invent a tag field.** `members={"Name": Target}` supplies a tag for a member that cannot name itself. A field added only to satisfy routing would also appear in the schema as a phantom property.

Details, the anti-patterns, and why a plain discriminator leaks: [references/discriminated-unions.md](references/discriminated-unions.md).

## 5. `mypy --strict` constraints

Four that will bite. All are checker limits, not style.

**A type alias must be assigned a type expression directly.** A helper that *returns* `Annotated[...]` produces `Variable "X" is not valid as a type`. So unions are written out literally, even when that repeats member names.

```python
Filter = Annotated[A | B | C, MarkedDiscriminator("kind")]   # ok
def spec(members): return Annotated[...]                      # not a type alias
```

**A function call cannot be an annotation.** `value: _bounded(str)` fails with `Invalid type comment or annotation`. Declare `StrList = Annotated[list[str], …]` and use that.

**An `Annotated` union cannot be composed into another.** `AtomicFilter | CompoundFilter` hands `MarkedDiscriminator` an alias with no `model_fields`. Two unions over overlapping members each list their members.

**`isinstance(x, Sequence)` re-admits `str`** even after an earlier branch excluded it, because `str` *is* a `Sequence`. Narrow on `is not None` instead:

```python
if isinstance(where, str):
    ...
elif where is not None:          # not `isinstance(where, Sequence)`
    items: Sequence[Filter] = [where] if isinstance(where, Filter) else where
```

Related: consumers of a model list take `Sequence[Model]`, not `list[Model]`. Factories return narrow subclasses, so `list` invariance rejects `[Filter.equals(...)]` against `list[Filter]`.

## 6. Verify

Schema changes are the deliverable, so check them explicitly. `just check` covers lint, `mypy --strict`, tests and build; it does **not** tell you whether the schema moved.

Dump it sorted, so regenerating gives a reviewable diff rather than reordering churn:

```python
import json
from pathlib import Path
from pydantic import TypeAdapter

Path("schema.json").write_text(
    json.dumps(TypeAdapter(X).json_schema(), indent=2, sort_keys=True) + "\n"
)
```

For a change that should be schema-neutral, compare a hash before and after:

```python
import hashlib, json
from pydantic import TypeAdapter
hashlib.sha256(json.dumps(TypeAdapter(X).json_schema(), sort_keys=True).encode()).hexdigest()
```

A docstring edit moves the hash — model docstrings become `description`. Strip every `description` key before comparing when only prose changed.

For anything touching a union, confirm all four:

1. **Parity** — for each payload, schema-valid `==` runtime-valid, or it is a named residual.
2. **Totality** — every declared value routes. Derive the list from the source of truth (`get_args(SomeLiteral)`), never from a hand-written set; a guard built from a hand-written set silently stops guarding.
3. **`loc` cleanliness** — every tag is stripped by `is_meta_key`: `tuple(x for x in err["loc"] if not is_meta_key(x))`.
4. **Metaschema** — `jsonschema.Draft202012Validator.check_schema(schema)`.

Two failure modes worth naming, both hit during this work:

- A simplification can **silently degrade an error** while every test still passes. A discriminator that never returns `None` cannot produce a union-level error; it routes to a member which then complains about its own narrow subset.
- Touching `pydantic_utils.py` affects **24 unions**. Run the full suite, not the file you edited.
