"""Signature, field, and class-section extraction for the built-in help.

Pure introspection over already-imported objects: no I/O, no network, no
``Workspace`` construction. Every function here returns the frozen models
from :mod:`.models` or plain strings and tuples.

Two rules shape this module:

- **Display the source annotation.** ``format_type`` keeps the text that
  ``inspect.signature`` returns (a string under ``from __future__ import
  annotations``), so alias names such as ``MathType`` stay visible. Resolved
  hints from ``typing.get_type_hints`` feed only the inline allowed values.
- **Private members hidden, constructors shown.** Field and member names
  that start with ``_`` are omitted. Classmethods and staticmethods whose
  return annotation names the class itself (or ``Self``) form the
  *construction* section.

``resolved_hints`` never raises: ``typing.get_type_hints`` fails with
``NameError`` on classes whose annotations name ``TYPE_CHECKING``-only
imports (``FlowQueryResult``, ``SchemaGraphResult``), and the module then
degrades to the string form.
"""

from __future__ import annotations

import dataclasses
import enum
import inspect
import re
import typing
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from .docstrings import first_line, parse_docstring
from .models import FieldDoc, MemberDoc, ParamDoc, ParamKind, SignatureDoc

_PREFIX_RE = re.compile(
    r"\b(?:typing_extensions|typing|collections\.abc|builtins|"
    r"mixpanel_headless(?:\.\w+)*)\."
)
"""Module prefixes removed from display strings."""

_CLASS_REPR_RE = re.compile(r"<class '([^']*)'>")
"""Matches ``<class 'pkg.Name'>`` and captures the dotted name."""

_FORWARD_REF_RE = re.compile(r"ForwardRef\('([^']*)'\)")
"""Matches ``ForwardRef('Name')`` and captures the name."""

_QUOTED_RE = re.compile(r"""^(['"])(.*)\1$""")
"""Matches a whole string wrapped in one pair of quotes (a quoted forward reference)."""

_UNION_KEYWORDS = ("Optional", "Union")
"""Subscript names rewritten to ``|`` form by ``_rewrite_unions``."""

_CONSTRAINT_ATTRS = (
    "max_length",
    "min_length",
    "ge",
    "gt",
    "le",
    "lt",
    "multiple_of",
    "pattern",
    "max_digits",
    "decimal_places",
)
"""Attributes read from Pydantic field metadata objects, in display order."""

_CONFIG_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("frozen", False),
    ("extra", "ignore"),
    ("populate_by_name", False),
)
"""Model config keys reported by ``model_config_doc`` when they differ from these."""

_HINTS_CACHE: dict[int, tuple[object, dict[str, object]]] = {}
"""Per-process cache for ``resolved_hints``: ``id(obj) -> (obj, hints)``.

The object is stored with its hints so its ``id`` cannot be recycled while the
entry is alive.
"""

_PARAM_KIND_NAMES: dict[inspect._ParameterKind, ParamKind] = {
    inspect.Parameter.POSITIONAL_ONLY: "positional_only",
    inspect.Parameter.POSITIONAL_OR_KEYWORD: "positional_or_keyword",
    inspect.Parameter.VAR_POSITIONAL: "var_positional",
    inspect.Parameter.KEYWORD_ONLY: "keyword_only",
    inspect.Parameter.VAR_KEYWORD: "var_keyword",
}
"""``inspect.Parameter.kind`` to the ``ParamDoc.kind`` literal it is recorded as."""

_Sections = tuple[tuple[MemberDoc, ...], tuple[MemberDoc, ...], tuple[MemberDoc, ...]]
"""Return type of ``class_sections``: ``(construction, properties, methods)``."""


# =============================================================================
# Annotation display
# =============================================================================


def format_type(annotation: object) -> str:
    """Return the display string for an annotation.

    Cleanup rules: strip ``typing.`` / ``typing_extensions.`` /
    ``collections.abc.`` and every ``mixpanel_headless...`` module prefix,
    unwrap ``<class '...'>`` and ``ForwardRef('...')``, replace ``NoneType``
    with ``None``, and rewrite ``Optional[X]`` / ``Union[A, B]`` to ``X | None``
    / ``A | B``. String annotations are cleaned but otherwise kept as written,
    so alias names such as ``MathType`` survive. The result is a fixed
    point: ``format_type(format_type(x)) == format_type(x)``.

    Args:
        annotation: A class, a typing construct, a string annotation, or ``None``.

    Returns:
        The cleaned display string. ``None`` and ``NoneType`` give ``"None"``.

    Example:
        ```python
        format_type(Optional[int])                      # "int | None"
        format_type("mixpanel_headless.types.Filter")   # "Filter"
        format_type("MathType")                         # "MathType"
        ```
    """
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, str):
        text = annotation
    elif isinstance(annotation, typing.ForwardRef):
        text = annotation.__forward_arg__
    elif hasattr(annotation, "__name__") and not hasattr(annotation, "__args__"):
        text = str(annotation.__name__)
    else:
        text = str(annotation)
    while True:
        cleaned = _clean_once(text)
        if cleaned == text:
            return cleaned
        text = cleaned


def _clean_once(text: str) -> str:
    """Apply every cleanup rule to ``text`` one time.

    ``format_type`` loops this function to a fixed point, because one rule can
    expose input for another (for example a prefix removal that joins two
    fragments into ``NoneType``).

    Args:
        text: An annotation string.

    Returns:
        The text after one pass of prefix, class-repr, forward-ref, quote,
        ``NoneType``, and union rewriting.
    """
    text = _PREFIX_RE.sub("", text)
    text = _CLASS_REPR_RE.sub(r"\1", text)
    text = _FORWARD_REF_RE.sub(r"\1", text)
    text = _QUOTED_RE.sub(r"\2", text)
    text = text.replace("NoneType", "None")
    return _rewrite_unions(text)


def _rewrite_unions(text: str) -> str:
    """Rewrite ``Optional[X]`` and ``Union[A, B]`` subscripts to pipe form.

    Brackets are matched, so nested forms such as
    ``Optional[Dict[str, int]]`` become ``Dict[str, int] | None``. A name that
    merely ends in ``Optional`` or ``Union`` (``MyUnion[int]``) is left alone.

    Args:
        text: An annotation string.

    Returns:
        The text with every matched subscript rewritten.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        keyword = _union_keyword_at(text, index)
        if keyword is None:
            out.append(text[index])
            index += 1
            continue
        open_at = index + len(keyword)
        close_at = _matching_bracket(text, open_at)
        if close_at < 0:
            out.append(text[index])
            index += 1
            continue
        inner = _rewrite_unions(text[open_at + 1 : close_at])
        parts = [part.strip() for part in _split_top_level(inner)]
        if keyword == "Optional":
            parts.append("None")
        out.append(" | ".join(parts))
        index = close_at + 1
    return "".join(out)


def _union_keyword_at(text: str, index: int) -> str | None:
    """Return ``"Optional"`` or ``"Union"`` when a whole-word subscript starts here.

    Args:
        text: The annotation string.
        index: Position to test.

    Returns:
        The keyword when ``text[index:]`` starts with ``Keyword[`` and the
        previous character is not part of an identifier; otherwise ``None``.
    """
    if index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_"):
        return None
    for keyword in _UNION_KEYWORDS:
        if text.startswith(keyword + "[", index):
            return keyword
    return None


def _matching_bracket(text: str, open_at: int) -> int:
    """Find the ``]`` that closes the ``[`` at ``open_at``.

    Args:
        text: The annotation string.
        open_at: Index of an opening bracket.

    Returns:
        Index of the matching closing bracket, or ``-1`` when unbalanced.
    """
    depth = 0
    for index in range(open_at, len(text)):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not nested inside brackets or parentheses.

    Args:
        text: The inside of a subscript, for example ``"str, Dict[str, int]"``.

    Returns:
        The top-level comma-separated parts, unstripped.
    """
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


# =============================================================================
# Resolved hints and allowed values
# =============================================================================


def resolved_hints(obj: object) -> dict[str, object]:
    """Return ``typing.get_type_hints(obj, include_extras=True)`` or ``{}``.

    Any exception (``NameError`` for ``TYPE_CHECKING``-only names, ``TypeError``
    for objects without annotations) degrades to an empty dict so callers fall
    back to the string annotation. Results are cached per object;
    ``clear_cache`` empties the cache.

    Args:
        obj: A class, function, method, or module.

    Returns:
        A fresh copy of the resolved hints keyed by parameter or field name,
        with ``"return"`` for callables; ``{}`` when resolution fails.

    Example:
        ```python
        resolved_hints(Workspace.query)["mode"]   # Literal['timeseries', 'total', 'table']
        resolved_hints(FlowQueryResult)           # {} — networkx is TYPE_CHECKING-only
        ```
    """
    key = id(obj)
    cached = _HINTS_CACHE.get(key)
    if cached is not None and cached[0] is obj:
        return dict(cached[1])
    try:
        hints: dict[str, object] = dict(typing.get_type_hints(obj, include_extras=True))
    except Exception:  # noqa: BLE001 - any failure means "no resolved hints"
        hints = {}
    _HINTS_CACHE[key] = (obj, hints)
    return dict(hints)


def clear_cache() -> None:
    """Empty the ``resolved_hints`` cache.

    Returns:
        ``None``.
    """
    _HINTS_CACHE.clear()


def allowed_values(hint: object) -> tuple[str, ...]:
    """Return the values a resolved hint accepts, for inline display.

    ``Literal`` arguments give their values (strings as-is, other objects via
    ``repr``); ``Enum`` classes give their member names. Unions, ``Annotated``,
    and generic containers such as ``list[Color]`` are searched recursively and
    the values are joined in order without duplicates. Anything else gives
    ``()``. String annotations are never parsed; pass a resolved hint.

    Args:
        hint: A resolved type hint.

    Returns:
        The accepted values in declaration order, or ``()``.

    Example:
        ```python
        allowed_values(Literal["a", "b"])                # ("a", "b")
        allowed_values(FeatureFlagStatus | None)         # ("ENABLED", "DISABLED", ...)
        allowed_values(str)                              # ()
        ```
    """
    origin = typing.get_origin(hint)
    if origin is Literal:
        return tuple(
            arg if isinstance(arg, str) else repr(arg) for arg in typing.get_args(hint)
        )
    if origin is Annotated:
        return allowed_values(typing.get_args(hint)[0])
    if isinstance(hint, type) and issubclass(hint, enum.Enum):
        return enum_values(hint)
    if origin is None:
        return ()
    values: list[str] = []
    for arg in typing.get_args(hint):
        if isinstance(arg, list):  # ``Callable[[...], R]`` parameter list
            continue
        for value in allowed_values(arg):
            if value not in values:
                values.append(value)
    return tuple(values)


# =============================================================================
# Signatures
# =============================================================================


def signature_doc(
    func: object,
    *,
    name: str | None = None,
    owner: type | None = None,
) -> SignatureDoc:
    """Build a ``SignatureDoc`` for a callable.

    One ``ParamDoc`` per parameter: a leading ``self`` / ``cls`` is dropped;
    ``*args`` and ``**kwargs`` keep their prefixes in ``name``; ``annotation``
    is the source annotation through ``format_type`` (``""`` when absent);
    ``default`` is ``repr(default)`` or ``None``; ``values`` come from
    ``resolved_hints`` when available; ``description`` comes from the
    ``Args:`` section of the docstring.

    Args:
        func: A function, bound or unbound method, class, or callable object.
            A raw ``classmethod`` / ``staticmethod`` descriptor is accepted when
            ``owner`` is given.
        name: Display name; defaults to ``func.__name__``.
        owner: Class that defines ``func``; used only to unwrap descriptors.

    Returns:
        The signature. When ``inspect.signature`` raises (builtins without a
        text signature, objects with a bogus ``__signature__``), the result has
        ``params=()`` and ``returns=None``.

    Example:
        ```python
        doc = signature_doc(Workspace.query)
        doc.params[0].name                 # "events"
        [p for p in doc.params if p.name == "math"][0].values   # 22 MathType values
        doc.returns                        # "QueryResult"
        ```
    """
    if owner is not None and isinstance(func, (classmethod, staticmethod)):
        func = func.__get__(None, owner)
    display = name if name is not None else _callable_name(func)
    try:
        signature = inspect.signature(func)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return SignatureDoc(name=display)
    hints = resolved_hints(func)
    descriptions = dict(parse_docstring(inspect.getdoc(func)).args)
    params: list[ParamDoc] = []
    for position, (pname, param) in enumerate(signature.parameters.items()):
        if position == 0 and pname in ("self", "cls"):
            continue
        params.append(_param_doc(pname, param, hints, descriptions))
    returns: str | None = None
    if signature.return_annotation is not inspect.Signature.empty:
        returns = format_type(signature.return_annotation)
    return SignatureDoc(name=display, params=tuple(params), returns=returns)


def _callable_name(func: object) -> str:
    """Return the best display name for a callable.

    Args:
        func: Any object.

    Returns:
        ``func.__name__`` when present, else the name of its type.
    """
    own = getattr(func, "__name__", None)
    return own if isinstance(own, str) else type(func).__name__


def _param_doc(
    pname: str,
    param: inspect.Parameter,
    hints: dict[str, object],
    descriptions: dict[str, str],
) -> ParamDoc:
    """Build one ``ParamDoc`` from an ``inspect.Parameter``.

    Args:
        pname: Parameter name as declared.
        param: The parameter object.
        hints: Resolved hints for the callable (may be empty).
        descriptions: ``Args:`` descriptions keyed by name (with or without
            ``*`` / ``**`` prefixes).

    Returns:
        The parameter documentation, with ``kind`` taken from ``param.kind``
        (``keyword_only`` for parameters after a bare ``*`` or ``*args``,
        ``positional_only`` for parameters before ``/``).
    """
    if param.kind is inspect.Parameter.VAR_POSITIONAL:
        display = f"*{pname}"
    elif param.kind is inspect.Parameter.VAR_KEYWORD:
        display = f"**{pname}"
    else:
        display = pname
    annotation = ""
    if param.annotation is not inspect.Parameter.empty:
        annotation = format_type(param.annotation)
    default = None
    if param.default is not inspect.Parameter.empty:
        default = repr(param.default)
    values = allowed_values(hints[pname]) if pname in hints else ()
    description = descriptions.get(display) or descriptions.get(pname, "")
    return ParamDoc(
        name=display,
        annotation=annotation,
        default=default,
        description=description,
        values=values,
        kind=_PARAM_KIND_NAMES[param.kind],
    )


# =============================================================================
# Fields
# =============================================================================


def dataclass_fields_doc(cls: type) -> tuple[FieldDoc, ...]:
    """Document the public fields of a dataclass.

    Fields are kept in definition order. Names that start with ``_`` are
    omitted. ``default`` is ``repr(default)``, ``<factory_name>`` for a
    ``default_factory`` (for example ``<list>``), or ``None`` when required.
    ``annotation`` is the source annotation through ``format_type``;
    ``values`` come from resolved hints; ``description`` comes from the
    ``Args:`` section of the class docstring when present.

    Args:
        cls: Any class; a non-dataclass yields ``()``.

    Returns:
        One ``FieldDoc`` per public field.

    Example:
        ```python
        [f.name for f in dataclass_fields_doc(Replay)][:2]   # ["replay_id", "distinct_id"]
        dataclass_fields_doc(Filter)                        # () — every field is private
        ```
    """
    if not dataclasses.is_dataclass(cls):
        return ()
    hints = resolved_hints(cls)
    descriptions = dict(parse_docstring(inspect.getdoc(cls)).args)
    docs: list[FieldDoc] = []
    for field in dataclasses.fields(cls):
        if field.name.startswith("_"):
            continue
        default: str | None
        required = False
        if field.default is not dataclasses.MISSING:
            default = repr(field.default)
        elif field.default_factory is not dataclasses.MISSING:
            default = _factory_display(field.default_factory)
        else:
            default = None
            required = True
        docs.append(
            FieldDoc(
                name=field.name,
                annotation=format_type(field.type),
                default=default,
                required=required,
                values=allowed_values(hints[field.name]) if field.name in hints else (),
                description=descriptions.get(field.name, ""),
            )
        )
    return tuple(docs)


def _factory_display(factory: object) -> str:
    """Return the ``<factory_name>`` display for a default factory.

    Args:
        factory: The factory callable (zero-argument, or Pydantic's
            one-argument form that receives validated data).

    Returns:
        ``"<list>"`` for ``list``, ``"<dict>"`` for ``dict``, and so on; falls
        back to the ``repr`` of the factory inside angle brackets.
    """
    return f"<{getattr(factory, '__name__', repr(factory))}>"


def pydantic_fields_doc(cls: type[BaseModel]) -> tuple[FieldDoc, ...]:
    """Document the public fields of a Pydantic model.

    Rules: a required field has ``required=True`` and ``default=None``; a
    ``default_factory`` shows as ``<factory_name>``; a literal ``None``
    default gives ``default=None, required=False`` (the renderer elides it);
    any other default is its ``repr``. ``constraints`` are read from the
    field metadata (``max_length=50``, ``ge=0``, ``pattern=...``). ``alias``
    is the JSON alias when it differs from the name, whether set explicitly
    or produced by ``alias_generator``. ``annotation`` prefers the source
    annotation text and falls back to the resolved ``FieldInfo``
    annotation. ``values`` are inline enum member names or Literal values.
    ``description`` is ``Field(description=...)`` or the class docstring
    ``Args:`` entry. Underscore-prefixed names never reach ``model_fields``
    (Pydantic treats them as private attributes), so no filter is needed.

    Args:
        cls: A ``BaseModel`` subclass; any other class yields ``()``.

    Returns:
        One ``FieldDoc`` per public field in definition order.

    Example:
        ```python
        docs = pydantic_fields_doc(CreateDashboardParams)
        docs[0].name, docs[0].required   # ("title", True)
        ```
    """
    if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
        return ()
    source = _source_annotations(cls)
    descriptions = dict(parse_docstring(inspect.getdoc(cls)).args)
    alias_generator = _alias_callable(cls.model_config.get("alias_generator"))
    docs: list[FieldDoc] = []
    for fname, info in cls.model_fields.items():
        default, required = _pydantic_default(info)
        docs.append(
            FieldDoc(
                name=fname,
                annotation=_pydantic_annotation(fname, info, source),
                default=default,
                required=required,
                constraints=_pydantic_constraints(info),
                alias=_pydantic_alias(fname, info, alias_generator),
                values=allowed_values(info.annotation),
                description=info.description or descriptions.get(fname, ""),
            )
        )
    return tuple(docs)


def _source_annotations(cls: type) -> dict[str, object]:
    """Collect source annotations across the MRO, subclass entries winning.

    Args:
        cls: The class to inspect.

    Returns:
        ``name -> annotation`` as written (strings under ``from __future__
        import annotations``). Classes whose annotations cannot be read
        contribute nothing.
    """
    merged: dict[str, object] = {}
    for klass in reversed(cls.__mro__):
        try:
            merged.update(inspect.get_annotations(klass))
        except Exception:  # noqa: BLE001 - lazy annotations may fail to evaluate
            continue
    return merged


def _pydantic_annotation(fname: str, info: FieldInfo, source: dict[str, object]) -> str:
    """Pick the display annotation for a Pydantic field.

    Args:
        fname: Field name.
        info: The field's ``FieldInfo``.
        source: Source annotations from ``_source_annotations``.

    Returns:
        The source annotation through ``format_type`` when it exists and is not
        an ``Annotated[...]`` wrapper; otherwise ``format_type(info.annotation)``.
    """
    raw = source.get(fname)
    if raw is not None:
        text = format_type(raw)
        if text and not text.startswith("Annotated["):
            return text
    return format_type(info.annotation)


def _pydantic_default(info: FieldInfo) -> tuple[str | None, bool]:
    """Return ``(default_display, required)`` for a Pydantic field.

    Args:
        info: The field's ``FieldInfo``.

    Returns:
        ``(None, True)`` when required; ``("<factory>", False)`` for a
        factory; ``(None, False)`` for a literal ``None`` default; otherwise
        ``(repr(default), False)``.
    """
    if info.is_required():
        return None, True
    if info.default_factory is not None:
        return _factory_display(info.default_factory), False
    if info.default is None:
        return None, False
    return repr(info.default), False


def _pydantic_constraints(info: FieldInfo) -> tuple[str, ...]:
    """Read constraint attributes from a field's metadata objects.

    Args:
        info: The field's ``FieldInfo``.

    Returns:
        Strings such as ``"max_length=50"`` in metadata order, then attribute
        order within one metadata object.
    """
    parts: list[str] = []
    for meta in info.metadata:
        for attr in _CONSTRAINT_ATTRS:
            value = getattr(meta, attr, None)
            if value is not None:
                parts.append(f"{attr}={value}")
    return tuple(parts)


def _alias_callable(generator: object) -> Callable[[str], object] | None:
    """Normalize a ``model_config["alias_generator"]`` value to a callable.

    Args:
        generator: A function, a ``pydantic.AliasGenerator``, or ``None``.

    Returns:
        The callable that maps a field name to its alias, or ``None``.
    """
    if generator is None:
        return None
    candidate = getattr(generator, "alias", generator)
    if callable(candidate):
        return typing.cast("Callable[[str], object]", candidate)
    return None


def _pydantic_alias(
    fname: str, info: FieldInfo, generator: Callable[[str], object] | None
) -> str | None:
    """Return the JSON alias of a field when it differs from the Python name.

    Args:
        fname: Field name.
        info: The field's ``FieldInfo``.
        generator: Callable from ``_alias_callable`` (may be ``None``).

    Returns:
        The alias string, or ``None`` when there is none or it equals ``fname``.
    """
    alias: object = info.alias
    if alias is None and generator is not None:
        try:
            alias = generator(fname)
        except Exception:  # noqa: BLE001 - a broken generator must not break help
            alias = None
    if isinstance(alias, str) and alias != fname:
        return alias
    return None


def model_config_doc(cls: type[BaseModel]) -> tuple[tuple[str, str], ...]:
    """Return non-default Pydantic model config entries.

    Tracked keys: ``frozen`` (default ``False``), ``extra`` (default
    ``"ignore"``), ``populate_by_name`` (default ``False``), and
    ``alias_generator`` (reported by function name when set).

    Args:
        cls: A ``BaseModel`` subclass.

    Returns:
        ``(key, value)`` pairs in that fixed order, values as display strings
        (``"True"``, ``"forbid"``, ``"to_camel"``). ``()`` when every key is
        at its default.

    Example:
        ```python
        model_config_doc(CamelModel)
        # (("frozen", "True"), ("extra", "forbid"), ("populate_by_name", "True"),
        #  ("alias_generator", "to_camel"))
        ```
    """
    config = getattr(cls, "model_config", None)
    if not isinstance(config, dict):
        return ()
    pairs: list[tuple[str, str]] = []
    for key, default in _CONFIG_DEFAULTS:
        value = config.get(key)
        if value is not None and value != default:
            pairs.append((key, value if isinstance(value, str) else repr(value)))
    generator = config.get("alias_generator")
    if generator is not None:
        target = getattr(generator, "alias", generator)
        pairs.append(("alias_generator", getattr(target, "__name__", str(target))))
    return tuple(pairs)


# =============================================================================
# Enums
# =============================================================================


def enum_values(cls: type[enum.Enum]) -> tuple[str, ...]:
    """Return enum member names in definition order.

    Args:
        cls: An ``Enum`` subclass.

    Returns:
        The member names.
    """
    return tuple(member.name for member in cls)


def enum_members(cls: type[enum.Enum]) -> tuple[tuple[str, str], ...]:
    """Return ``(name, repr(value))`` pairs for an enum member table.

    Args:
        cls: An ``Enum`` subclass.

    Returns:
        The pairs in definition order.

    Example:
        ```python
        enum_members(FeatureFlagStatus)[0]   # ("ENABLED", "'enabled'")
        ```
    """
    return tuple((member.name, repr(member.value)) for member in cls)


# =============================================================================
# Class sections and bases
# =============================================================================


def class_sections(cls: type) -> _Sections:
    """Split the public members of a class into three sorted sections.

    Only members defined on classes in the same top-level package as ``cls``
    (``mixpanel_headless`` for library classes) are considered, so ``object``,
    ``BaseModel``, and ``Enum`` machinery never appear. Names
    that start with ``_``, Pydantic validators and serializers, nested
    classes, and plain data attributes are skipped. A subclass definition
    shadows a base definition of the same name.

    - **construction**: classmethods and staticmethods whose return annotation
      names the class itself or ``Self``.
    - **properties**: ``property`` and ``cached_property`` objects.
    - **methods**: every other public callable.

    Args:
        cls: The class to inspect.

    Returns:
        ``(construction, properties, methods)``, each sorted by name. Callable
        members carry a ``SignatureDoc``; properties carry ``None``.

    Example:
        ```python
        construction, properties, methods = class_sections(Filter)
        len(construction), properties, methods   # (28, (), ())
        ```
    """
    construction: list[MemberDoc] = []
    properties: list[MemberDoc] = []
    methods: list[MemberDoc] = []
    excluded = _pydantic_decorated_names(cls)
    owner_names = _owner_names(cls)
    seen: set[str] = set()
    for klass in cls.__mro__:
        if not _same_package(klass, cls):
            continue
        for name, raw in vars(klass).items():
            if name in seen or name.startswith("_") or name in excluded:
                continue
            seen.add(name)
            member = _classify_member(cls, name, raw, owner_names)
            if member is None:
                continue
            section, doc = member
            {
                "construction": construction,
                "properties": properties,
                "methods": methods,
            }[section].append(doc)
    return (
        tuple(sorted(construction, key=_member_name)),
        tuple(sorted(properties, key=_member_name)),
        tuple(sorted(methods, key=_member_name)),
    )


def _member_name(doc: MemberDoc) -> str:
    """Sort key for member listings.

    Args:
        doc: A member entry.

    Returns:
        The member name.
    """
    return doc.name


def _same_package(klass: type, cls: type) -> bool:
    """Tell whether ``klass`` lives in the same top-level package as ``cls``.

    For library classes this means "defined inside ``mixpanel_headless``";
    framework bases (``object``, ``pydantic.BaseModel``, ``enum.Enum``,
    ``str``) never share the package and are therefore skipped.

    Args:
        klass: A class from the MRO of ``cls``.
        cls: The class being documented.

    Returns:
        ``True`` when both ``__module__`` values share their first segment.
    """
    return _top_package(klass) == _top_package(cls)


def _top_package(klass: type) -> str:
    """Return the first segment of a class's ``__module__``.

    Args:
        klass: Any class.

    Returns:
        ``"mixpanel_headless"`` for library classes, ``"builtins"`` for
        ``object`` and ``str``, and so on.
    """
    module = getattr(klass, "__module__", "") or ""
    return module.split(".", 1)[0]


def _pydantic_decorated_names(cls: type) -> frozenset[str]:
    """Names registered as Pydantic validators or serializers on ``cls``.

    Args:
        cls: Any class; non-models yield an empty set.

    Returns:
        The decorated member names, which must not appear as methods.
    """
    decorators = getattr(cls, "__pydantic_decorators__", None)
    if decorators is None:
        return frozenset()
    names: set[str] = set()
    for group in (
        "validators",
        "field_validators",
        "root_validators",
        "model_validators",
        "field_serializers",
        "model_serializers",
    ):
        registry = getattr(decorators, group, None)
        if isinstance(registry, dict):
            names.update(registry)
    return frozenset(names)


def _owner_names(cls: type) -> frozenset[str]:
    """Names that a constructor's return annotation may use for ``cls``.

    Args:
        cls: The class being documented.

    Returns:
        ``Self`` plus the ``__name__`` and ``__qualname__`` of ``cls`` and of
        every in-package class in its MRO, so an inherited factory annotated
        with the base class still counts as construction for the subclass.
    """
    names = {"Self"}
    for klass in cls.__mro__:
        if _same_package(klass, cls):
            names.update((klass.__name__, klass.__qualname__))
    return frozenset(names)


def _classify_member(
    cls: type, name: str, raw: object, owner_names: frozenset[str]
) -> tuple[Literal["construction", "properties", "methods"], MemberDoc] | None:
    """Classify one raw class-dict entry into a section with its ``MemberDoc``.

    Args:
        cls: The class being documented (used to bind descriptors).
        name: Attribute name.
        raw: The value from ``vars(klass)`` (descriptor or function).
        owner_names: Return-annotation names that mark a constructor.

    Returns:
        ``(section, member)`` or ``None`` when the entry is not a public
        property or callable.
    """
    if isinstance(raw, property) or type(raw).__name__ == "cached_property":
        summary = first_line(inspect.getdoc(raw))
        return "properties", MemberDoc(name=name, kind="property", summary=summary)
    if (
        isinstance(raw, type)
        or not callable(raw)
        and not isinstance(raw, (classmethod, staticmethod))
    ):
        return None
    bound = getattr(cls, name, None)
    if bound is None or not callable(bound):
        return None
    doc = signature_doc(bound, name=name)
    member = MemberDoc(
        name=name,
        kind="method",
        summary=first_line(inspect.getdoc(bound)),
        signature=doc,
    )
    if isinstance(raw, (classmethod, staticmethod)) and _returns_owner(
        doc, owner_names
    ):
        return "construction", member
    return "methods", member


def _returns_owner(doc: SignatureDoc, owner_names: frozenset[str]) -> bool:
    """Tell whether a signature's return annotation names the owner or ``Self``.

    Args:
        doc: The member's signature.
        owner_names: Names from ``_owner_names``.

    Returns:
        ``True`` for ``-> Filter``, ``-> "Filter"``, and ``-> Self`` on a
        class named ``Filter`` (or on one of its in-package subclasses).
    """
    if doc.returns is None:
        return False
    return doc.returns.strip().strip("'\"") in owner_names


def bases_doc(cls: type) -> tuple[str, ...]:
    """Return the names of a class's direct bases, minus framework roots.

    ``object``, ``BaseModel``, ``Generic``, and ``Protocol`` are dropped; the
    kind of a help entry already says "model" or "dataclass", so listing the
    framework base adds nothing.

    Args:
        cls: The class to inspect.

    Returns:
        Base class names in declaration order; ``()`` when only framework
        roots remain.

    Example:
        ```python
        bases_doc(QueryResult)   # ("ResultWithDataFrame",)
        bases_doc(Filter)        # ()
        ```
    """
    skipped = {"object", "BaseModel", "Generic", "Protocol"}
    return tuple(
        base.__name__ for base in cls.__bases__ if base.__name__ not in skipped
    )


__all__ = [
    "allowed_values",
    "bases_doc",
    "class_sections",
    "clear_cache",
    "dataclass_fields_doc",
    "enum_members",
    "enum_values",
    "format_type",
    "model_config_doc",
    "pydantic_fields_doc",
    "resolved_hints",
    "signature_doc",
]
