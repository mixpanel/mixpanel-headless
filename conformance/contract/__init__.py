"""Phase-2 contract-artifact generation (phase2-design C2/C3/C5/C8).

This package hosts ``generate_contract``, the introspection-driven generator
that emits the four Phase-2 contract artifacts consumed by the TypeScript
port's vector-lock tests:

- ``error-codes.json`` — exception hierarchy, default codes, and the coded
  guard registry (C3).
- ``literal-aliases.json`` — Literal alias members, Enum tables, and NewType
  supertypes (C2).
- ``tag-universe.json`` — the JSON-aware ``$type`` tag census over the
  committed corpus plus the codec-table built-ins (C8a).
- ``model-coverage.json`` — per-Pydantic-model lock evidence: corpus tags
  and entity-golden wire vectors (C5 item 5).

Artifacts are byte-deterministic for a fixed ``--generated-from`` stamp and
corpus state; regeneration is a deliberate act mirroring the D3 vector
regeneration story.
"""
