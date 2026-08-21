"""Tests for the committed conformance-vector JSON Schema artifact.

The schema at ``conformance/schema/vector.schema.json`` is the single source
of truth for vector shape after PR-1 copies it from
``context/phase1/design/vector.schema.json`` (design D3). These tests lock
that the copy is present, parseable, and a structurally valid Draft 2020-12
JSON Schema, so later emit-time self-validation (D1/PR-2) has a sound anchor.
"""

import json
from pathlib import Path
from typing import Any

from jsonschema.validators import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "vector.schema.json"


def _load_schema() -> dict[str, Any]:
    """Load the committed vector schema from disk.

    Returns:
        The parsed JSON Schema document as a dictionary.

    Raises:
        FileNotFoundError: If the schema file is missing from
            ``conformance/schema/``.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)
    return schema


def test_vector_schema_file_exists() -> None:
    """The schema copy required by design D3/PR-1 exists on disk.

    Raises:
        AssertionError: If ``conformance/schema/vector.schema.json`` is
            missing.
    """
    assert SCHEMA_PATH.is_file(), f"missing schema copy at {SCHEMA_PATH}"


def test_vector_schema_declares_draft_2020_12() -> None:
    """The schema pins the Draft 2020-12 dialect explicitly.

    Both validators in the rig (Python ``jsonschema`` at emit time, ajv
    ``Ajv2020`` on the TS side per design D15a) assume 2020-12 semantics;
    an accidental dialect change must fail loudly here.

    Raises:
        AssertionError: If the ``$schema`` keyword is absent or names a
            different dialect.
    """
    schema = _load_schema()
    assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"


def test_vector_schema_is_valid_draft_2020_12() -> None:
    """The schema is itself valid against the Draft 2020-12 metaschema.

    Raises:
        jsonschema.exceptions.SchemaError: If the document violates the
            Draft 2020-12 metaschema.
    """
    Draft202012Validator.check_schema(_load_schema())


def test_vector_schema_requires_core_vector_fields() -> None:
    """The schema requires the four core vector fields from design D2/D3.

    Every vector must carry ``id``, ``kind``, ``call``, and ``expect``;
    this locks the top-level contract the record plugin and both runners
    build against.

    Raises:
        AssertionError: If any core field is missing from ``required``.
    """
    schema = _load_schema()
    assert set(schema["required"]) == {"id", "kind", "call", "expect"}
