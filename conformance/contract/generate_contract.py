"""Phase-2 contract-artifact generator (phase2-design C2/C3/C5/C8, packet P2-1).

Pure introspection over the live library plus a JSON-aware walk of the
committed vector corpus — no source parsing, no hand transcription. Emits
four artifacts under ``conformance/contract/``:

- ``error-codes.json`` (C3): the 28 exported exception classes with their
  parent edges, per-class default codes, and the full
  ``CODED_GUARD_REGISTRY`` / ``CODED_GUARD_TWIN_CODES`` sets.
- ``literal-aliases.json`` (C2): every exported ``Literal`` alias with its
  member tuple, every exported ``enum.Enum`` class with kind + members,
  and the auth ``NewType`` identifiers with their supertypes.
- ``tag-universe.json`` (C8a): the distinct ``$type`` tag census over every
  corpus JSONL line (recursive ``$type``-key walk — NEVER grep: escaped
  ``\\"$type\\"`` text inside string payloads yields pseudo-tags for text
  scanners) plus the codec-table built-ins, zero-filled when unexercised
  (``date``).
- ``model-coverage.json`` (C5 item 5): for each exported Pydantic model,
  its corpus-tag occurrence count and the wire-vector ids whose
  ``expect.result`` payloads golden-lock it (via return-annotation
  mapping of the registered wire entry points).

Determinism: the ``generated_from`` stamp is injected externally (mirroring
the D3 manifest discipline — never ``git rev-parse``); for a fixed stamp and
corpus state a re-run is byte-identical.

Usage:
    ```bash
    uv run python -m conformance.contract.generate_contract \
        --generated-from <full 40-char source SHA>
    ```
"""

from __future__ import annotations

import argparse
import enum
import inspect
import json
import re
import typing
from collections import Counter
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from conformance.record.emit import canonical_json
from conformance.record.registry import KIND_WIRE_API, REGISTRY, resolve_callable

BUILTIN_TAGS: tuple[str, ...] = (
    "SecretStr",
    "bytes",
    "callback",
    "date",
    "datetime",
    "float",
)
"""The six codec-table built-in ``$type`` tags (conformance/record/codecs.py).

``date`` has zero corpus occurrences today but stays in the universe:
it is registered on both sides and the C8(a) sweep reports (not fails)
zero-occurrence tags. A behavioral cross-check against the live codec
module lives in ``conformance/tests/test_generate_contract.py``.
"""

DEFAULT_VECTORS_DIR: Path = Path(__file__).resolve().parents[1] / "vectors"
"""The committed corpus root scanned by the tag/model walks."""

DEFAULT_OUT_DIR: Path = Path(__file__).resolve().parent
"""Where the four artifacts land (``conformance/contract/``)."""

ARTIFACT_NAMES: tuple[str, ...] = (
    "error-codes.json",
    "literal-aliases.json",
    "tag-universe.json",
    "model-coverage.json",
)
"""The artifact file names, in emission order."""

_LITERAL_MEMBER_RE = re.compile(r"'([^']*)'")
"""First-quoted-member extractor for stringified ``Literal[...]`` annotations."""


def _distinct_public_names() -> list[str]:
    """Return ``mixpanel_headless.__all__`` deduplicated in first-seen order.

    Ten Literal-alias strings appear twice in ``__all__`` (Discrepancy Log
    #9); every artifact keys on the 274 DISTINCT names.

    Returns:
        The distinct export names, first occurrence order preserved.
    """
    import mixpanel_headless as mp

    return list(dict.fromkeys(mp.__all__))


def _public_object(name: str) -> Any:
    """Resolve one exported name to its runtime object.

    Args:
        name: A ``mixpanel_headless.__all__`` entry.

    Returns:
        The exported object.

    Raises:
        AttributeError: If the export is missing (broken ``__all__``).
    """
    import mixpanel_headless as mp

    return getattr(mp, name)


# ---------------------------------------------------------------------------
# error-codes.json (C3)
# ---------------------------------------------------------------------------


def _dummy_for_annotation(annotation: str) -> Any:
    """Build a type-appropriate dummy value for a constructor annotation.

    Used only to instantiate exception classes whose default code is set
    inside the constructor body (no ``code=`` signature default). The
    annotation is the stringified form (PEP 563 — the library uses
    ``from __future__ import annotations``).

    Args:
        annotation: The parameter's stringified annotation.

    Returns:
        A dummy value: first ``Literal`` member, empty list for
        sequence-ish annotations, ``1`` for ints, ``"x"`` otherwise.
    """
    if "Literal[" in annotation:
        match = _LITERAL_MEMBER_RE.search(annotation)
        if match is not None:
            return match.group(1)
    if "Sequence" in annotation or "list" in annotation or "tuple" in annotation:
        return []
    if "int" in annotation:
        return 1
    return "x"


def _default_code_for(cls: type[BaseException]) -> str:
    """Derive one exception class's default ``code`` value.

    Preference order: the ``code`` parameter's signature default when it is
    a string (pure introspection); otherwise a dummy instantiation built
    from the constructor signature, reading ``.code`` off the instance.

    Args:
        cls: The exception class.

    Returns:
        The default code string.

    Raises:
        TypeError: If the dummy instantiation does not satisfy the
            constructor (a new constructor shape needs a new dummy rule),
            or if the class is not a ``MixpanelHeadlessError`` subclass
            (every exported exception carries ``.code``).
    """
    from mixpanel_headless.exceptions import MixpanelHeadlessError

    signature = inspect.signature(cls.__init__)
    code_param = signature.parameters.get("code")
    if code_param is not None and isinstance(code_param.default, str):
        return code_param.default
    kwargs: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        if name == "self" or param.default is not inspect.Parameter.empty:
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        kwargs[name] = _dummy_for_annotation(str(param.annotation))
    instance = cls(**kwargs)
    if not isinstance(instance, MixpanelHeadlessError):
        raise TypeError(f"{cls.__name__} does not carry the .code contract")
    return str(instance.code)


def build_error_codes(generated_from: str) -> dict[str, Any]:
    """Build the ``error-codes.json`` artifact body (design C3).

    Sources: the exported exception class objects themselves (MRO walk for
    parent edges) and ``exceptions.CODED_GUARD_REGISTRY`` /
    ``CODED_GUARD_TWIN_CODES`` — no parsing.

    Args:
        generated_from: The externally-injected provenance SHA.

    Returns:
        The artifact body with ``exception_classes`` (name -> parent name
        or None), ``default_codes``, and the two sorted code lists.
    """
    from mixpanel_headless import exceptions as exceptions_module

    classes: dict[str, type[BaseException]] = {}
    for name in _distinct_public_names():
        obj = _public_object(name)
        if isinstance(obj, type) and issubclass(obj, BaseException):
            classes[name] = obj
    exception_classes: dict[str, str | None] = {}
    default_codes: dict[str, str] = {}
    for name in sorted(classes):
        cls = classes[name]
        parent = next(
            (base.__name__ for base in cls.__mro__[1:] if base.__name__ in classes),
            None,
        )
        exception_classes[name] = parent
        default_codes[name] = _default_code_for(cls)
    return {
        "generated_from": generated_from,
        "exception_classes": exception_classes,
        "default_codes": default_codes,
        "coded_guard_registry": sorted(exceptions_module.CODED_GUARD_REGISTRY),
        "coded_guard_twin_codes": sorted(exceptions_module.CODED_GUARD_TWIN_CODES),
    }


# ---------------------------------------------------------------------------
# literal-aliases.json (C2)
# ---------------------------------------------------------------------------


def build_literal_aliases(generated_from: str) -> dict[str, Any]:
    """Build the ``literal-aliases.json`` artifact body (design C2).

    Selects every distinct export where ``typing.get_origin(obj) is
    Literal`` (members in declaration order) or ``issubclass(obj,
    enum.Enum)`` (kind ``str``/``int`` + members in declaration order),
    plus the auth ``NewType`` identifiers with their supertype names.
    ``mixpanel_headless.auth_types.__all__`` is unioned in so auth-only
    aliases are covered even when not re-exported at top level.

    Args:
        generated_from: The externally-injected provenance SHA.

    Returns:
        The artifact body with ``literal_aliases``, ``enums`` and
        ``newtypes`` maps.
    """
    import mixpanel_headless.auth_types as auth_types

    literal_aliases: dict[str, list[Any]] = {}
    enums: dict[str, dict[str, Any]] = {}
    newtypes: dict[str, str] = {}
    seen: set[str] = set()
    sources: list[tuple[str, Any]] = [
        (name, _public_object(name)) for name in _distinct_public_names()
    ]
    for name in auth_types.__all__:
        sources.append((name, getattr(auth_types, name)))
    for name, obj in sources:
        if name in seen:
            continue
        seen.add(name)
        if typing.get_origin(obj) is typing.Literal:
            literal_aliases[name] = list(typing.get_args(obj))
        elif isinstance(obj, type) and issubclass(obj, enum.Enum):
            kind = "int" if issubclass(obj, int) else "str"
            enums[name] = {
                "kind": kind,
                "members": {member.name: member.value for member in obj},
            }
        elif hasattr(obj, "__supertype__"):
            newtypes[name] = obj.__supertype__.__name__
    return {
        "generated_from": generated_from,
        "literal_aliases": dict(sorted(literal_aliases.items())),
        "enums": dict(sorted(enums.items())),
        "newtypes": dict(sorted(newtypes.items())),
    }


# ---------------------------------------------------------------------------
# tag-universe.json (C8a)
# ---------------------------------------------------------------------------


def iter_corpus_objects(vectors_dir: Path) -> Iterator[dict[str, Any]]:
    """Yield every parsed JSONL object in the corpus, deterministically.

    Files are visited in sorted path order; blank lines are skipped.
    Bundle headers (``$bundle`` records) are yielded too — they carry no
    ``$type`` keys but keeping the walk total keeps the census honest.

    Args:
        vectors_dir: The corpus root (``conformance/vectors``).

    Yields:
        Each parsed JSON object, one per non-blank line.

    Raises:
        json.JSONDecodeError: If a corpus line is not valid JSON.
    """
    for path in sorted(vectors_dir.rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parsed: dict[str, Any] = json.loads(line)
            yield parsed


def _walk_tags(node: Any, counts: Counter[str]) -> None:
    """Recursively tally ``$type`` string values under one JSON node.

    JSON-aware by construction: only DICT KEYS named ``$type`` with string
    values count — ``$type`` text embedded inside string payloads (the
    escaped ``\\"$type\\"`` pseudo-tag hazard) never registers.

    Args:
        node: A parsed JSON node (dict / list / scalar).
        counts: The mutable tag tally.
    """
    if isinstance(node, dict):
        tag = node.get("$type")
        if isinstance(tag, str):
            counts[tag] += 1
        for value in node.values():
            _walk_tags(value, counts)
    elif isinstance(node, list):
        for value in node:
            _walk_tags(value, counts)


def collect_tag_counts(vectors_dir: Path) -> dict[str, int]:
    """Tally every ``$type`` tag occurrence across the corpus.

    Args:
        vectors_dir: The corpus root.

    Returns:
        Tag -> occurrence count over all corpus lines.
    """
    counts: Counter[str] = Counter()
    for obj in iter_corpus_objects(vectors_dir):
        _walk_tags(obj, counts)
    return dict(counts)


def build_tag_universe(vectors_dir: Path, generated_from: str) -> dict[str, Any]:
    """Build the ``tag-universe.json`` artifact body (design C8a).

    The tag set is the corpus census UNION the codec-table built-ins
    (zero-filled when unexercised — ``date`` today). Rich tags are the
    observed non-built-in tags, each a Phase-2 type name.

    Args:
        vectors_dir: The corpus root.
        generated_from: The externally-injected provenance SHA.

    Returns:
        The artifact body with the per-tag counts and the
        built-in / rich partition.
    """
    counts = collect_tag_counts(vectors_dir)
    tags: dict[str, int] = dict.fromkeys(BUILTIN_TAGS, 0)
    tags.update(counts)
    rich_tags = sorted(tag for tag in counts if tag not in BUILTIN_TAGS)
    return {
        "generated_from": generated_from,
        "built_in_tags": sorted(BUILTIN_TAGS),
        "rich_tags": rich_tags,
        "tags": dict(sorted(tags.items())),
    }


# ---------------------------------------------------------------------------
# model-coverage.json (C5 item 5)
# ---------------------------------------------------------------------------


def _exported_models() -> dict[str, type[BaseModel]]:
    """Collect the exported Pydantic models (the 125 entity/param models).

    Returns:
        Model name -> class, over the distinct ``__all__`` names.
    """
    models: dict[str, type[BaseModel]] = {}
    for name in _distinct_public_names():
        obj = _public_object(name)
        if isinstance(obj, type) and issubclass(obj, BaseModel):
            models[name] = obj
    return models


def _collect_model_names(hint: Any, model_names: frozenset[str], out: set[str]) -> None:
    """Recursively collect exported-model names referenced by a type hint.

    Handles bare classes, generic containers (``list[X]``,
    ``PaginatedResponse[X]``), unions and nested parameterizations via
    ``typing.get_args`` / ``typing.get_origin``.

    Args:
        hint: A resolved type hint node.
        model_names: The exported model-name universe.
        out: Mutable sink for referenced model names.
    """
    if isinstance(hint, type):
        if issubclass(hint, BaseModel) and hint.__name__ in model_names:
            out.add(hint.__name__)
        return
    origin = typing.get_origin(hint)
    if (
        isinstance(origin, type)
        and issubclass(origin, BaseModel)
        and origin.__name__ in model_names
    ):
        out.add(origin.__name__)
    for argument in typing.get_args(hint):
        _collect_model_names(argument, model_names, out)


def _wire_api_model_map(
    model_names: frozenset[str],
) -> tuple[dict[str, list[str]], list[str]]:
    """Map each registered wire api to the exported models its return names.

    Args:
        model_names: The exported model-name universe.

    Returns:
        ``(api -> sorted model names, hint-resolution failures)`` — apis
        whose annotations cannot resolve (forward refs into ``TYPE_CHECKING``
        imports) are listed, never silently dropped.
    """
    api_models: dict[str, list[str]] = {}
    failures: list[str] = []
    for entry in REGISTRY:
        if entry.kind != KIND_WIRE_API:
            continue
        try:
            func = resolve_callable(entry)
            hints = typing.get_type_hints(func)
        except Exception:  # noqa: BLE001 - unresolvable hints are data here
            failures.append(entry.api)
            continue
        referenced: set[str] = set()
        _collect_model_names(hints.get("return"), model_names, referenced)
        if referenced:
            api_models[entry.api] = sorted(referenced)
    return api_models, sorted(failures)


def build_model_coverage(vectors_dir: Path, generated_from: str) -> dict[str, Any]:
    """Build the ``model-coverage.json`` artifact body (design C5 item 5).

    Per exported Pydantic model, the P2-1-mechanical lock evidence:

    - ``corpus_tag_occurrences``: how often the model appears as a
      ``$type`` tag anywhere in the corpus (codec round-trip lock, C8a).
    - ``entity_golden_vector_ids``: wire vectors carrying a plain
      ``expect.result`` whose api's return annotation references the
      model (entity-golden lock, C8b extension).
    - ``authored_fixture`` / ``deferral``: null here — P2-7 fills them for
      every ``status: "unresolved"`` model; a model with none of the four
      is a P2-7 failure.

    Args:
        vectors_dir: The corpus root.
        generated_from: The externally-injected provenance SHA.

    Returns:
        The artifact body keyed by model name, plus the hint-failure list.
    """
    models = _exported_models()
    model_names = frozenset(models)
    tag_counts = collect_tag_counts(vectors_dir)
    api_models, hint_failures = _wire_api_model_map(model_names)
    api_vector_ids: dict[str, list[str]] = {}
    for obj in iter_corpus_objects(vectors_dir):
        if obj.get("kind") != "wire":
            continue
        expect = obj.get("expect")
        if not isinstance(expect, dict) or "result" not in expect:
            continue
        call = obj.get("call")
        if not isinstance(call, dict):
            continue
        api = call.get("api")
        vector_id = obj.get("id")
        if isinstance(api, str) and isinstance(vector_id, str):
            api_vector_ids.setdefault(api, []).append(vector_id)
    coverage: dict[str, dict[str, Any]] = {}
    for name in sorted(models):
        golden_ids: set[str] = set()
        for api, referenced in api_models.items():
            if name in referenced:
                golden_ids.update(api_vector_ids.get(api, []))
        occurrences = tag_counts.get(name, 0)
        if occurrences > 0:
            status = "corpus_tag"
        elif golden_ids:
            status = "entity_golden"
        else:
            status = "unresolved"
        coverage[name] = {
            "corpus_tag_occurrences": occurrences,
            "entity_golden_vector_ids": sorted(golden_ids),
            "authored_fixture": None,
            "deferral": None,
            "status": status,
        }
    return {
        "generated_from": generated_from,
        "model_count": len(coverage),
        "hint_failures": hint_failures,
        "models": coverage,
    }


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


def write_artifacts(
    out_dir: Path, vectors_dir: Path, generated_from: str
) -> dict[str, Path]:
    """Generate and write all four artifacts (canonical JSON + newline).

    Args:
        out_dir: Destination directory (created if missing).
        vectors_dir: The corpus root for the tag/model walks.
        generated_from: The externally-injected provenance SHA.

    Returns:
        Artifact name -> written path.
    """
    bodies: dict[str, dict[str, Any]] = {
        "error-codes.json": build_error_codes(generated_from),
        "literal-aliases.json": build_literal_aliases(generated_from),
        "tag-universe.json": build_tag_universe(vectors_dir, generated_from),
        "model-coverage.json": build_model_coverage(vectors_dir, generated_from),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name in ARTIFACT_NAMES:
        path = out_dir / name
        path.write_text(canonical_json(bodies[name]) + "\n", encoding="utf-8")
        written[name] = path
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(
        description="Generate the Phase-2 contract artifacts (design C2/C3/C5/C8)."
    )
    parser.add_argument(
        "--generated-from",
        required=True,
        metavar="SHA",
        help="Provenance source SHA — injected externally, never git rev-parse "
        "(mirrors the D3 manifest stamp discipline).",
    )
    parser.add_argument(
        "--vectors",
        type=Path,
        default=DEFAULT_VECTORS_DIR,
        metavar="DIR",
        help="Corpus root to scan (default: conformance/vectors).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        metavar="DIR",
        help="Artifact output directory (default: conformance/contract).",
    )
    options = parser.parse_args(argv)
    written = write_artifacts(options.out, options.vectors, options.generated_from)
    for name in ARTIFACT_NAMES:
        print(f"[generate-contract] wrote {written[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
