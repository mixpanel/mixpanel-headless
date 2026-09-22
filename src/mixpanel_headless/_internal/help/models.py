"""Structured result model for the built-in API reference.

Every type here is a frozen ``slots=True`` dataclass built from tuples, so
instances are hashable and safe to cache per process. Each type exposes
``to_dict()``, which converts nested models recursively and turns every tuple
into a list, so the result is JSON-serializable with ``json.dumps``.

``HelpEntry`` is the structured output of ``reference.describe()``;
``SearchResult`` is the output of ``reference.search()``. Renderers in
``render.py`` are pure functions from these models to text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

ExportKind = Literal[
    "module",
    "exception",
    "enum",
    "model",
    "dataclass",
    "class",
    "literal",
    "alias",
    "function",
    "constant",
]
"""Classification of a package export: exactly what ``inventory.classify()`` returns.

The order follows the classification rules, so a module wins over a class
and an exception over an enum.
"""

MemberKind = Literal[ExportKind, "method", "property"]
"""Classification of a listing row or search hit.

Every ``ExportKind`` plus the two kinds that only exist as class members:
``method`` (instance, class, and static methods alike) and ``property``.
"""

HelpKind = Literal[MemberKind, "overview", "listing", "parameter"]
"""Classification of a help entry (what kind of object the query resolved to).

Every ``MemberKind`` plus the three kinds that only exist as whole entries:
the package ``overview``, a ``listing`` (``Workspace``, ``types``,
``exceptions``), and a single ``parameter`` of a callable. A search result
is a ``SearchResult``, not a ``HelpEntry``, and has no kind.
"""

HelpFormat = Literal["text", "markdown", "json"]
"""Output format accepted by the renderers and the CLI ``--format`` option."""

EXPORT_KINDS: tuple[ExportKind, ...] = get_args(ExportKind)
"""Runtime tuple of every ``ExportKind`` value, in classification-rule order."""

MEMBER_KINDS: tuple[MemberKind, ...] = get_args(MemberKind)
"""Runtime tuple of every ``MemberKind`` value: ``EXPORT_KINDS`` then ``method``, ``property``."""

HELP_KINDS: tuple[HelpKind, ...] = get_args(HelpKind)
"""Runtime tuple of every ``HelpKind`` value: ``MEMBER_KINDS`` then the entry-only kinds."""

HELP_FORMATS: tuple[HelpFormat, ...] = get_args(HelpFormat)
"""Runtime tuple of every ``HelpFormat`` value, for validation of ``--format``."""

MatchedOn = Literal["name", "doc", "member"]
"""Where a search hit matched: the name, the docstring summary, or a member.

The ``member`` tier covers enum members (``NAME = repr(value)``) and the
values of ``Literal`` aliases.
"""

ParamKind = Literal[
    "positional_only",
    "positional_or_keyword",
    "var_positional",
    "keyword_only",
    "var_keyword",
]
"""How a parameter may be passed; the lower-cased ``inspect.Parameter.kind`` names."""

PARAM_KINDS: tuple[ParamKind, ...] = get_args(ParamKind)
"""Runtime tuple of every ``ParamKind`` value, in ``inspect`` declaration order."""

_CALLABLE_MEMBER_KINDS: frozenset[str] = frozenset({"method", "function"})
"""The member kinds that carry a signature; every other kind must not."""


def _pairs_to_lists(pairs: tuple[tuple[str, str], ...]) -> list[list[str]]:
    """Convert a tuple of two-string pairs into a list of two-item lists.

    Args:
        pairs: Pairs such as ``(("events", "Event names."),)``.

    Returns:
        ``[["events", "Event names."]]`` — JSON-friendly and order-preserving.
    """
    return [[first, second] for first, second in pairs]


@dataclass(frozen=True, slots=True)
class Hint:
    """Pointer to a hosted documentation page.

    Attributes:
        title: Short human-readable label, for example ``"Entity management guide"``.
        url: Absolute URL of the page.
    """

    title: str
    url: str

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Returns:
            ``{"title": ..., "url": ...}``.
        """
        return {"title": self.title, "url": self.url}


@dataclass(frozen=True, slots=True)
class ParamDoc:
    """One parameter of a callable signature.

    Attributes:
        name: Parameter name without ``self``; ``*args`` and ``**kwargs`` keep
            their prefixes.
        annotation: Display form of the annotation (already cleaned).
        default: ``repr`` of the default, or ``None`` when the parameter is required.
        description: Description from the ``Args:`` docstring section, or ``""``.
        values: Literal or enum member values accepted by the parameter, if any.
        kind: How the parameter may be passed. Renderers print a bare ``*``
            before the first ``keyword_only`` parameter (unless a
            ``var_positional`` one precedes it) and a ``/`` after the last
            ``positional_only`` parameter.
    """

    name: str
    annotation: str
    default: str | None = None
    description: str = ""
    values: tuple[str, ...] = ()
    kind: ParamKind = "positional_or_keyword"

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Returns:
            A dict with every field; ``values`` becomes a list.
        """
        return {
            "name": self.name,
            "annotation": self.annotation,
            "default": self.default,
            "description": self.description,
            "values": list(self.values),
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class SignatureDoc:
    """A callable signature with per-parameter documentation.

    Attributes:
        name: Callable name (unqualified).
        params: Parameters in declaration order.
        returns: Display form of the return annotation, or ``None`` when absent.
    """

    name: str
    params: tuple[ParamDoc, ...] = ()
    returns: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Returns:
            A dict with ``params`` converted recursively.
        """
        return {
            "name": self.name,
            "params": [param.to_dict() for param in self.params],
            "returns": self.returns,
        }


@dataclass(frozen=True, slots=True)
class FieldDoc:
    """One public field of a dataclass or Pydantic model.

    Attributes:
        name: Python attribute name.
        annotation: Display form of the annotation.
        default: Display form of the default (``repr`` or ``<factory name>``), or ``None``.
        required: ``True`` when the field has no default.
        constraints: Pydantic constraints such as ``"max_length=255"``.
        alias: JSON alias when it differs from ``name``, else ``None``.
        values: Enum member names or literal values accepted by the field, if any.
        description: Field description from ``Field(description=...)`` or the docstring.
    """

    name: str
    annotation: str
    default: str | None = None
    required: bool = False
    constraints: tuple[str, ...] = ()
    alias: str | None = None
    values: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        """Reject a required field that also carries a default.

        Raises:
            ValueError: When ``required`` is ``True`` and ``default`` is not
                ``None``; a field with a default is by definition optional.
        """
        if self.required and self.default is not None:
            raise ValueError(
                f"FieldDoc {self.name!r} is required but has default {self.default!r}"
            )

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Returns:
            A dict with every field; tuples become lists.
        """
        return {
            "name": self.name,
            "annotation": self.annotation,
            "default": self.default,
            "required": self.required,
            "constraints": list(self.constraints),
            "alias": self.alias,
            "values": list(self.values),
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class MemberDoc:
    """One member in a listing (method, property, classmethod, module export).

    Attributes:
        name: Member name, never indented; nesting is carried by ``depth``.
        kind: Member classification, one of ``MEMBER_KINDS``.
        summary: First docstring line, or ``""``.
        signature: Signature for ``method`` / ``function`` members (always
            present for those kinds), ``None`` for every other kind.
        depth: Nesting level inside a tree-shaped group, ``0`` for a flat
            row. The exception tree uses it: each level is one subclass step
            below the group's root. The text renderer indents two spaces per
            level; markdown and JSON keep the bare name and expose ``depth``.
    """

    name: str
    kind: MemberKind
    summary: str = ""
    signature: SignatureDoc | None = None
    depth: int = 0

    def __post_init__(self) -> None:
        """Validate the kind, its agreement with ``signature``, and ``depth``.

        Raises:
            ValueError: When ``kind`` is not one of ``MEMBER_KINDS``, when a
                ``method`` / ``function`` member has no signature, when any
                other kind carries one, or when ``depth`` is negative.
        """
        if self.depth < 0:
            raise ValueError(f"MemberDoc depth must be >= 0, got {self.depth}")
        if self.kind not in MEMBER_KINDS:
            allowed = ", ".join(MEMBER_KINDS)
            raise ValueError(
                f"Unknown member kind {self.kind!r}; expected one of: {allowed}"
            )
        callable_kind = self.kind in _CALLABLE_MEMBER_KINDS
        if callable_kind and self.signature is None:
            raise ValueError(
                f"MemberDoc {self.name!r} of kind {self.kind!r} requires a signature"
            )
        if not callable_kind and self.signature is not None:
            raise ValueError(
                f"MemberDoc {self.name!r} of kind {self.kind!r} "
                "must not carry a signature"
            )

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Returns:
            A dict with ``signature`` converted recursively or ``None``, and
            ``depth`` as an integer.
        """
        return {
            "name": self.name,
            "kind": self.kind,
            "summary": self.summary,
            "signature": None if self.signature is None else self.signature.to_dict(),
            "depth": self.depth,
        }


@dataclass(frozen=True, slots=True)
class Group:
    """A titled group of members, used for ``Workspace`` domain grouping.

    Attributes:
        title: Group title, for example ``"Discovery"``.
        items: Members in the group.
    """

    title: str
    items: tuple[MemberDoc, ...]

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Returns:
            ``{"title": ..., "items": [member dicts]}``.
        """
        return {"title": self.title, "items": [item.to_dict() for item in self.items]}


@dataclass(frozen=True, slots=True)
class UsageDoc:
    """One ``Workspace`` method that accepts a given type ("Used by Workspace").

    Attributes:
        method: Method name on ``Workspace``.
        params: Names of the parameters whose annotation references the type.
    """

    method: str
    params: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Returns:
            ``{"method": ..., "params": [...]}``.
        """
        return {"method": self.method, "params": list(self.params)}


@dataclass(frozen=True, slots=True)
class DocSections:
    """Parsed Google-style docstring.

    Attributes:
        summary: First paragraph before the first section header, lines joined
            with single spaces.
        body: Everything before the first section header, dedented, newlines kept.
        args: ``(name, description)`` pairs from ``Args:``.
        returns: Text of ``Returns:`` (and ``Yields:``).
        raises: ``(exception_name, description)`` pairs from ``Raises:``.
        example: Text of ``Example:`` / ``Examples:``, dedented, fences kept.
        notes: Text of ``Note:`` / ``Notes:``.
    """

    summary: str = ""
    body: str = ""
    args: tuple[tuple[str, str], ...] = ()
    returns: str = ""
    raises: tuple[tuple[str, str], ...] = ()
    example: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Returns:
            A dict with ``args`` and ``raises`` as lists of two-item lists.
        """
        return {
            "summary": self.summary,
            "body": self.body,
            "args": _pairs_to_lists(self.args),
            "returns": self.returns,
            "raises": _pairs_to_lists(self.raises),
            "example": self.example,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class HelpEntry:
    """Structured description of one resolved help query.

    ``kind``, ``name``, ``qualname``, ``summary``, and ``doc`` are required.
    Every collection defaults to an empty tuple and every scalar extra to
    ``None``, so builders can construct partial entries for kinds that lack
    a section. Which fields a kind populates is fixed by the conventions
    below; ``reference.describe()`` follows them and the renderers rely on
    them. A consumer of ``to_dict()`` can too.

    Per-kind field conventions:

    - ``method`` / ``function``: ``signature`` holds the callable and
      ``name`` is the display name (``Workspace.query``, ``accounts.add``).
      ``referenced_types`` lists the library types in the signature. For a
      ``Workspace`` method, ``domain`` is the registry domain title and
      ``see_also`` names the other ``Workspace`` methods of that domain;
      both are empty for every other callable. ``groups`` is unused.
    - ``property``: ``signature`` has no params; its ``returns`` is the
      property type or ``None``.
    - ``parameter``: ``signature.params`` holds exactly one ``ParamDoc`` and
      ``signature.name`` is the owning callable's bare name; ``values``
      repeats the parameter's allowed values; ``summary`` and ``doc`` carry
      the parameter description.
    - ``class`` / ``model`` / ``dataclass``: ``bases``, ``config`` (models
      only), ``construction``, ``fields`` (models and dataclasses),
      ``properties``, ``methods``, and ``used_by`` map one-to-one to the
      rendered sections.
    - ``enum``: ``values`` holds the member names in definition order and
      ``fields`` reuses ``FieldDoc`` for the members: ``name`` is the member
      name, ``annotation`` the type name of the member value, ``default``
      its ``repr``, ``required`` always ``False``. ``bases`` lists the enum's
      bases.
    - ``literal``: ``values`` holds the allowed values in declaration order.
    - ``alias``: ``values`` holds the member display names of the union and
      ``referenced_types`` the ``(name, summary)`` rows for the members that
      are library types.
    - ``exception``: ``bases[0]`` is the direct base. ``groups`` is empty for
      a leaf or one group titled ``Subclasses`` whose items carry their
      nesting in ``MemberDoc.depth`` (a direct subclass is depth ``0``).
      ``used_by`` lists the ``Workspace`` methods whose ``Raises:`` names it.
    - ``module``: one group titled ``Members`` with every ``__all__`` name.
    - ``constant``: ``value`` is the ``repr`` of the value and ``bases``
      holds one name, the value's type (the enum class for an enum member
      such as ``FeatureFlagStatus.ENABLED``). ``values`` is unused.
    - ``listing``: ``groups`` carries the rows (``Workspace`` domains, the
      ``types`` kinds, or the one ``Exceptions`` tree whose items carry
      ``depth``). ``summary`` is a count line or the facade's summary.
    - ``overview``: ``summary`` is the package version and ``doc.body`` the
      query grammar; ``groups`` is empty.

    Attributes:
        kind: What the query resolved to.
        name: Display name, for example ``"Workspace.query"`` or ``"Filter"``.
        qualname: Canonical help query for this entry, for example
            ``"Workspace.query"`` or ``"Filter"``; passing it back to
            ``describe()`` returns the same entry. Not an import path.
        summary: First docstring line (or generated summary for aliases).
        doc: Parsed docstring sections.
        signature: Signature for callables, else ``None``.
        bases: Names of public base classes (the value's type for a constant).
        config: Non-default Pydantic model config as ``(key, value)`` pairs.
        construction: Public constructors and factory classmethods.
        fields: Public dataclass or model fields; enum members for an enum.
        properties: Public properties.
        methods: Public methods (instance, class, static).
        values: Enum member names, literal values, or alias member names.
        value: Display form of a constant's value (``repr``), else ``None``.
        groups: Titled member groups for listings, modules, and exception trees.
        referenced_types: ``(type_name, summary)`` pairs referenced by a callable.
        used_by: ``Workspace`` methods that accept (or raise) this type.
        domain: Registry domain title of a ``Workspace`` method, else ``None``.
        see_also: Other ``Workspace`` methods in the same registry domain.
        hints: Hosted-documentation pointers.
    """

    kind: HelpKind
    name: str
    qualname: str
    summary: str
    doc: DocSections
    signature: SignatureDoc | None = None
    bases: tuple[str, ...] = ()
    config: tuple[tuple[str, str], ...] = ()
    construction: tuple[MemberDoc, ...] = ()
    fields: tuple[FieldDoc, ...] = ()
    properties: tuple[MemberDoc, ...] = ()
    methods: tuple[MemberDoc, ...] = ()
    values: tuple[str, ...] = ()
    value: str | None = None
    groups: tuple[Group, ...] = ()
    referenced_types: tuple[tuple[str, str], ...] = ()
    used_by: tuple[UsageDoc, ...] = ()
    domain: str | None = None
    see_also: tuple[str, ...] = ()
    hints: tuple[Hint, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Nested models convert recursively; tuples become lists; pair tuples
        become two-item lists. Keys follow the dataclass field order.

        Returns:
            A dict suitable for ``json.dumps``.
        """
        return {
            "kind": self.kind,
            "name": self.name,
            "qualname": self.qualname,
            "summary": self.summary,
            "doc": self.doc.to_dict(),
            "signature": None if self.signature is None else self.signature.to_dict(),
            "bases": list(self.bases),
            "config": _pairs_to_lists(self.config),
            "construction": [member.to_dict() for member in self.construction],
            "fields": [field.to_dict() for field in self.fields],
            "properties": [member.to_dict() for member in self.properties],
            "methods": [member.to_dict() for member in self.methods],
            "values": list(self.values),
            "value": self.value,
            "groups": [group.to_dict() for group in self.groups],
            "referenced_types": _pairs_to_lists(self.referenced_types),
            "used_by": [usage.to_dict() for usage in self.used_by],
            "domain": self.domain,
            "see_also": list(self.see_also),
            "hints": [hint.to_dict() for hint in self.hints],
        }


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search result row.

    Attributes:
        category: Display category: the ``ExportKind`` of an export or
            module member (``exception``, ``enum``, ``model``, ``dataclass``,
            ``class``, ``literal``, ``alias``, ``function``, ``module``,
            ``constant``), or ``method`` / ``property`` for ``Workspace``
            members.
        name: Matched name, qualified for ``Workspace`` members.
        summary: First docstring line, or ``""``.
        matched_on: Which part of the entry matched the term.
    """

    category: MemberKind
    name: str
    summary: str
    matched_on: MatchedOn

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Returns:
            A dict with the four scalar fields.
        """
        return {
            "category": self.category,
            "name": self.name,
            "summary": self.summary,
            "matched_on": self.matched_on,
        }


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Result of ``reference.search(term)``.

    Attributes:
        term: The search term as given.
        hits: Matching entries in display order, duplicates removed.
        suggestions: "Did you mean?" names when there are no hits.
    """

    term: str
    hits: tuple[SearchHit, ...] = ()
    suggestions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Convert to a JSON-serializable dict.

        Returns:
            ``{"term": ..., "hits": [hit dicts], "suggestions": [...]}``.
        """
        return {
            "term": self.term,
            "hits": [hit.to_dict() for hit in self.hits],
            "suggestions": list(self.suggestions),
        }


__all__ = [
    "EXPORT_KINDS",
    "HELP_FORMATS",
    "HELP_KINDS",
    "MEMBER_KINDS",
    "PARAM_KINDS",
    "DocSections",
    "ExportKind",
    "FieldDoc",
    "Group",
    "HelpEntry",
    "HelpFormat",
    "HelpKind",
    "Hint",
    "MatchedOn",
    "MemberDoc",
    "MemberKind",
    "ParamDoc",
    "ParamKind",
    "SearchHit",
    "SearchResult",
    "SignatureDoc",
    "UsageDoc",
]
