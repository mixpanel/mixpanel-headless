# Verified Pydantic behaviour

Observed against **Pydantic 2.13.3**, Python 3.10, `jsonschema` Draft 2020-12.
Each entry records what was actually run. Re-verify if the pydantic floor moves;
`pyproject.toml` pins `pydantic>=2.0`.

Several of these overturned a design. Where an obvious-looking assumption is
wrong, the wrong version is stated too, because it is the one you will reach for.

---

## Models and fields

### `BaseModel` rejects leading-underscore field names

```python
class M(BaseModel):
    _property: str = Field(validation_alias="property")
```
```
NameError: Fields must not use names with leading underscores;
           e.g., use 'property' instead of '_property'.
```

Raised at **class definition**, not validation. Pydantic reserves `_x` on a
`BaseModel` for private attributes (`ModelPrivateAttr`) — excluded from fields,
validation, serialization and the schema.

**Pydantic dataclasses have no such reservation.** That asymmetry is the only
reason a model in this repo would still be a `@pydantic_dataclass`.

### `property` is a legal field name

Shadowing the builtin inside a class body is fine, and the builtin stays usable
in the same class. `ruff`'s `A003` would flag it, but flake8-builtins (`A`) is
not in this repo's `select` list.

### `model_dump(by_alias=True)` ignores a `validation_alias`

From the docs: *"if only `validation_alias` is set, `model_dump(by_alias=True)`
emits the field name, not the validation alias."*

Consequence: a model using the `_field` + `validation_alias` convention
serializes under its **private** names and does not round-trip through its own
published schema. Only `alias` or `serialization_alias` affect output.

### A base-class `model_validator` is inherited

Declared once on a plain base, collected by every subclass — including
`@pydantic_dataclass` subclasses of an *undecorated* base. Lets one guard cover
a family, with a `ClassVar` flag for per-member opt-out.

### `ClassVar` stays out of the schema

Usable as a per-model switch (`_ALLOWS_COHORT: ClassVar[bool] = False`) without
appearing as a property. It does show in `__dataclass_fields__` as
`_FIELD_CLASSVAR`.

### `ABC` + `@abstractmethod` blocks base construction

```python
class Base(BaseModel, ABC):
    @abstractmethod
    def _member(self) -> None: ...
```
```
TypeError: Can't instantiate abstract class Base with abstract method _member
```

No metaclass conflict — `ModelMetaclass` already derives from `ABCMeta`. Cost is
an artificial method existing only to block construction, so weigh it against
simply leaving the base concrete.

---

## Field types and their schema

### Bounded `list` vs `tuple` — different schema *and* different runtime type

```python
v: Annotated[list[int], Field(min_length=2, max_length=2)]
v: tuple[int, int]
```
```
list : {"items": {"type": "integer"}, "maxItems": 2, "minItems": 2, "type": "array"}
tuple: {"maxItems": 2, "minItems": 2, "prefixItems": [{...}, {...}], "type": "array"}

one-element input:  list -> too_short      tuple -> missing
runtime type:       list -> list           tuple -> tuple
```

The runtime type matters when downstream code gates on `isinstance(v, list)`.

### `StringConstraints` replaces a hand-written `WithJsonSchema`

```python
DateStr = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    AfterValidator(_is_a_real_date),
    Field(json_schema_extra={"format": "date"}),
]
```
```
{"format": "date", "pattern": "^\\d{4}-\\d{2}-\\d{2}$", "type": "string"}
```

Identical to the hand-written blob, generated natively — and the docs recommend
it over `WithJsonSchema` for a field carrying validators.

It also **splits the failure modes**, which a single hand-rolled check cannot:

| input | error | catchable schema-side |
|---|---|---|
| `"01/01/2025"` | `string_pattern_mismatch` | yes |
| `"2025-02-30"` | `value_error` | no — calendar validity has no JSON Schema form |

**Caveat — it costs the message.** `StringConstraints` owns the shape
rejection, so a domain message is no longer reachable for it:

| | message for `"01/01/2025"` |
|---|---|
| `StringConstraints(pattern=…)` | `String should match pattern '^\d{4}-\d{2}-\d{2}$'` |
| `json_schema_extra` + one `AfterValidator` | `Date must be YYYY-MM-DD format (got '01/01/2025')` |

This repo's `_DateStr` takes the second form for that reason — the split
is worth less here than a message naming the format. Prefer
`StringConstraints` when no hand-written message is at stake; when one
is, declare the pattern in `json_schema_extra` and let a single
`AfterValidator` cover both shape and semantics. The schema is identical
either way.

### `SkipJsonSchema` hides without weakening

```python
v: str | SkipJsonSchema[int]
```
```
schema: {"type": "string"}       runtime accepts int? 5
```

Manufactures **runtime ⊃ schema** — the library can emit a value its own schema
rejects. Use only when a shape must not be public, and record it as a residual.

### Strict numbers vs JSON's single number type

```python
v: StrictInt
```
```
schema: {"type": "integer"}
schema accepts 1.0 ?  True        schema accepts True ?  False
runtime 1.0 -> int_type
```

`"type": "integer"` matches any number with a zero fractional part. No keyword
expresses "an `int`, not a `float`". Unreachable from JSON text (which parses `1`
to an `int`) — only a caller passing Python objects hits it. Permanent residual.

### `json_schema_input_type` — the right answer for coercion, unused here

On `BeforeValidator` / `PlainValidator` / `WrapValidator`. Declares the widened
accepted input so the model can keep the strict post-validation type:

```python
value: Annotated[list[str], BeforeValidator(to_list, json_schema_input_type=str | list[str])]
```
```
mode="validation"   : {"anyOf": [{"type": "string"}, {"items": {...}, "type": "array"}]}
mode="serialization": {"items": {"type": "string"}, "type": "array"}
```

Docs recommend it over `WithJsonSchema` for fields with validators. **Not used in
this repo** — it postdates 2.0 and the floor stays there. Without it, a coercing
field must declare the wide union, leaving the serialization schema imprecise.
Revisit if the floor ever moves.

---

## Schema semantics

### `discriminator` validates nothing; `oneOf` does

```
discriminator alone, garbage accepted?  True
oneOf alone,         garbage accepted?  False
```

`discriminator` is an annotation — a Draft 2020-12 validator ignores it. OpenAPI
requires it *alongside* `oneOf`/`anyOf`/`allOf`. So the `$ref`s appearing in both
is mandated by the spec, not duplication to remove.

`mapping` is itself optional; omitted, the implicit rule is "the property value
is the schema name". Values like `"is greater than"` cannot be class names, so an
explicit mapping is required here.

### `mapping` may point several values at one `$ref`

```json
{"is set": "#/$defs/PresenceFilter", "is not set": "#/$defs/PresenceFilter"}
```

Metaschema-valid. This is what lets one model claim several literals while the
schema still names every value.

---

## Known pydantic issues

### `PydanticJsonSchemaWarning … [skipped-discriminator]`

pydantic **#11039** / **#11573**. A `validation_alias` forces an Input/Output
schema split; a *string*-discriminated union nested under a *callable*
discriminated union loses its mapping and warns.

Not hit by the current design (public field names, no nesting of that shape), but
it is why a warning-free schema build is worth asserting when the shape changes.

---

## mypy `--strict`

### A type alias must be assigned a type expression directly

```python
Spec = Annotated[A | B, MarkedDiscriminator("kind")]   # ok
def spec(members): return Annotated[...]               # -> "not valid as a type"
```

A helper that *returns* an alias makes the name a **variable**. Any annotation
referencing it fails. This is why unions are written out literally.

### A function call cannot be an annotation

```python
value: _bounded(str)
```
```
error: Invalid type comment or annotation
note: Suggestion: use _bounded[...] instead of _bounded(...)
```

Declare named `Annotated` aliases instead.

### `isinstance(x, Sequence)` re-admits `str`

```python
def g(where: F | Sequence[F] | str | None) -> None:
    if isinstance(where, str):
        pass
    elif isinstance(where, (F, Sequence)):
        reveal_type(where)     # F | Sequence[F] | str   <-- str is back
```

The positive test overrides the earlier exclusion, because `str` *is* a
`Sequence`. Narrowing on `where is not None` gives `F | Sequence[F]`.

### `list` is invariant, `Sequence` is covariant

A factory returning a narrow subclass makes `[Factory.make()]` infer
`list[Subclass]`, which is **not** assignable to `list[Base]`. Consumers should
take `Sequence[Base]`. mypy names the fix in the error text.
