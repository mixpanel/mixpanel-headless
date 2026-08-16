# B6-W6 notes — lexicon data definitions + tracking & history (15 members)

Packet: `context/phase3/design/b6-packets.md` §8 (W6). Spec of record:
`phase3-playbook.md` v1.1. Python arbiter: `workspace.py:7197-7581`
(Data Definitions / Lexicon, Phase 027) and `workspace.py:8526-8648`
(Tracking & History + Export, Phase 027), re-read line-by-line at HEAD
2026-08-16.

Status: DONE. `npm run check` green; one local commit on TS `main`.

## 1 Scope

15 members / 33 measured vectors, zero zero-vector members.

| #   | member                             | py def | vec | shape                                     |
| --- | ---------------------------------- | ------ | --- | ----------------------------------------- |
| 1   | `get_event_definitions`            | :7201  | 4   | kwonly `names` (REQUIRED); models         |
| 2   | `update_event_definition`          | :7235  | 2   | `by_alias` dump; model                    |
| 3   | `delete_event_definition`          | :7272  | 1   | void forward                              |
| 4   | `bulk_update_event_definitions`    | :7293  | 2   | `by_alias` dump; models                   |
| 5   | `get_property_definitions`         | :7331  | 4   | kwonly `names` (REQUIRED), `resource_type`|
| 6   | `update_property_definition`       | :7375  | 3   | `by_alias` dump; model                    |
| 7   | `bulk_update_property_definitions` | :7412  | 3   | `by_alias` dump; models                   |
| 8   | `list_lexicon_tags`                | :7460  | 3   | **str-vs-dict branch** (id=0 sentinel)    |
| 9   | `create_lexicon_tag`               | :7502  | 2   | PLAIN dump; model                         |
| 10  | `update_lexicon_tag`               | :7530  | 1   | PLAIN dump; model                         |
| 11  | `delete_lexicon_tag`               | :7561  | 1   | void forward (BY NAME)                    |
| 12  | `get_tracking_metadata`            | :8530  | 1   | verbatim dict                             |
| 13  | `get_event_history`                | :8558  | 2   | verbatim list                             |
| 14  | `get_property_history`             | :8585  | 1   | verbatim list                             |
| 15  | `export_lexicon`                   | :8618  | 3   | kwonly `export_types`; verbatim dict      |

Deliverables (TS repo, branch `main`):

- `packages/core/src/workspace-members/lexicon-tracking.ts` (member module)
- `packages/core/src/workspace.ts` — the `// === B6-W6 lexicon +
  tracking/history members (W6 owns; append-only) ===` section (15
  one-line delegations) + the import/re-export block for the three
  options interfaces
- `packages/core/test/workspace/lexicon-tracking.test.ts` (Layer-3, 39
  tests: 24 translated + 15 additive delegation contracts)
- `throwaway/b6-w6/{wire-edges.ts,probe-strip.ts}` (R10.9; deleted at the gate)

## 2 Findings from the Python re-read (arbiter-visible)

1. **14 of 15 members are pure forwards.** The single exception is
   `list_lexicon_tags` (`:7488-7500`): it loops the raw list and
   branches on `isinstance(x, str)` — a plain tag-name STRING becomes
   `LexiconTag(id=0, name=x)` (the id=0 sentinel documented in the
   member's own docstring Note, `:7481-7486`), everything else goes
   through `validate_response_model`. That `isinstance` is a STRING
   discrimination, **not** watchlist #13's `isinstance(x, dict)`, so
   `isPlainRecord` has no site in this shard; the twin is a plain
   `typeof entry === "string"` over the raw (lossless) entry, which is
   a JS string for any JSON string token.
2. **TWO dump spellings, deliberately preserved.** The four definition
   writers use `model_dump(exclude_none=True, by_alias=True)`
   (`:7266`, `:7325`, `:7406`, `:7452`) because
   `UpdateEventDefinitionParams` / `UpdatePropertyDefinitionParams` /
   `BulkEventUpdate` / `BulkPropertyUpdate` carry `to_camel` aliases
   the App API requires (`displayName`, `exampleValue`,
   `resourceType`). The two TAG writers use a PLAIN
   `model_dump(exclude_none=True)` (`:7526`, `:7557`). `by_alias`
   would be a no-op on their single `name` field, but the port mirrors
   the source spelling rather than harmonizing — the W1-D4
   `modelDumpExcludeNone({ byAlias })` option carries it.
3. **ZERO empty-response guards** in either range (grep-verified: no
   `if raw is None` / `API returned empty response` in
   `workspace.py:7197-7581` or `:8526-8648`). The shared
   `requireResponse` helper (`workspace-members/shared.ts`) is
   therefore deliberately UNUSED here — the W5 precedent. Inventing the
   guard would add a branch Python does not have.
4. **Four opaque passthroughs** (`get_tracking_metadata`,
   `get_event_history`, `get_property_history`, `export_lexicon`)
   return the client payload verbatim under `dict[str, Any]` /
   `list[dict[str, Any]]` with no model validation (`:8556`, `:8583`,
   `:8614`, `:8648`) — the W4 `list_erf_experiments` / W5 `test_alert`
   precedent (`native(raw) as …`).
5. **The packet's member table understates two required kwargs.**
   §8's api-map rows list `names` under "kwonly" for
   `get_event_definitions` / `get_property_definitions`; at HEAD both
   are keyword-only AND **required** (no default, `:7201`,
   `:7331-7334`). The TS options bags are therefore non-optional
   parameters (`WorkspaceGetEventDefinitionsOptions` /
   `WorkspaceGetPropertyDefinitionsOptions` have a required `names`),
   unlike every other W-shard options bag which defaults to `{}`.
   Not a discrepancy in the Python — a precision note for the binder.
6. **`resource_type` canonicalization is the CLIENT's** (B4-C5
   `canonicalResourceType`, `api_client.py:266-284`): the facade
   forwards the caller's spelling verbatim (`"event"` → the client
   sends `resourceType=Event`). R10.8 — the facade must not
   pre-canonicalize, and the Layer-3 additive probe locks the verbatim
   forward while the wire probe locks the `Event` on the URL.
7. **`export_lexicon`'s default type list and pending-wrapper live in
   the client too** (`lexicon.ts:596-611`): Python's facade passes
   `export_types=None` straight down (`:8648`), so the TS facade
   forwards `?? null`. The `{status: "pending", message}` wrapper for a
   plain-string async response is never facade-visible.
8. **No `int(str)`, no `.strip()`, no truthiness guard, no date
   construction** anywhere in the two ranges — R11.7 / watchlist #5 /
   watchlist #6 have no site to bite inside W6's own code. (They DID
   bite an inherited test file — see §4.)
9. **Discrepancy #10 has no W6 site.** No W6 surface exposes an
   `extra_forbidden` warning list; both response models with
   `extra='allow'` (`EventDefinition`, `PropertyDefinition`) spill
   unknown keys into `__extras` without emitting an ordered warning
   list. Integer-like unknown keys stayed out of every fuzz domain
   the shard added (§3 (iii-b)).

## 3 R10.9 harness RUN record — `throwaway/b6-w6/`

Throwaway. The B6 gate (`b6-packets.md` §12) deletes
`throwaway/b6-w6/`; this record survives here.

| file             | role                                                          |
| ---------------- | ------------------------------------------------------------- |
| `wire-edges.ts`  | delegation equivalence + status branches + edge set + branches |
| `probe-strip.ts` | one-shot `pythonStrip` vs `trim` probe feeding §4              |

Run: `npx vite-node throwaway/b6-w6/wire-edges.ts`

Deterministic (no RNG, no seed): every case is a hand-built canned
interaction over the injected-fetch seam.

```
checks 55   failures 0
```

| group                      | cases                                                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| (i) delegation equivalence | `get_event_definitions`, `get_property_definitions`, `list_lexicon_tags`, `get_tracking_metadata`, `get_event_history`, `get_property_history`, `export_lexicon`, `update_event_definition` — facade result === direct client result re-validated through the SAME model seam (8)                                                                                                                             |
| (ii) wire status branches  | `get_event_definitions` 200 / 404 (`QueryError/QUERY_FAILED`); `export_lexicon` 200 / 500 (`ServerError/SERVER_ERROR`) (4)                                                                                                                                                                                                                                                                                    |
| (iii) edge set             | (a) annotation-bounded (#8) through the definition-update payloads — `true`, `null`, `""`, `"𝒳"`, `[]` across `update_event_definition`, `update_property_definition`, both bulk writers, `create_lexicon_tag`, `get_event_definitions(names=[])`, `export_lexicon([""])` (7); (b) the FULL set incl. both floats through the four `dict[str, Any]` passthroughs + the `extra='allow'` spillover path (7)     |
| (iv) W6-local branches     | `list_lexicon_tags` all-string / all-object / mixed / empty arms (4); the two dump spellings incl. all-None-drops (4); the two `?? null` forwards in default + populated arms (4); the two void members × (return + arg) (4); `RESPONSE_VALIDATION_ERROR` from a malformed 200 for all nine validated members (9); the four verbatim passthroughs (4)                                                          |

Harness observations:

1. **Discrepancy #12 confirmed at the passthrough seam, recorded not
   "fixed".** A `18.0` wire token reaches `export_lexicon`'s caller as
   the JS number `18` (`JSON.stringify` → `"18"`), because the opaque
   members hand back the NATIVE tree. The lossless token survives only
   in the `JsonValue` tree the CLIENT returns. This is the ratified #12
   class (integral-float spelling narrowing in output text), and it
   mirrors Python, where `json.loads` yields a `float` whose `repr` is
   `18.0` — the spelling difference is a rendering concern for the
   vector comparator, not a facade branch. Locked as an explicit
   assertion rather than papered over.
2. **`BulkPropertyUpdate.resource_type` is REQUIRED** (unlike
   `BulkEventUpdate`, which has no such field) — the first harness
   draft omitted it and the Phase-2 model correctly raised
   `BulkPropertyUpdate.resource_type: field required`. Matches
   `types.py`; no port defect.
3. **The 404 branch reaches the facade as `QueryError/QUERY_FAILED`**
   (`internals.ts:493` — "Resource not found"), i.e. the same coded
   family as 400. Codes, not messages (R5): the harness asserts the
   code pair, never the sentence.

## 4 Inherited-file fix (arbiter-visible, cross-shard)

`packages/core/test/workspace/delegation-equivalence.pbt.test.ts` (a
**W3** deliverable) failed `npm run check` at W6 with the fast-check
counterexample `["", "\u001f", ""]` (prefix, ctrl, suffix — i.e. the
bare U+001F UNIT SEPARATOR as the whole event name). Root cause: the
skip guard was
translated as JS `name.trim() === ""` instead of Python's
`if not name.strip()` (`test_delegation_equivalence_pbt.py:364`) — an
**R11.7 violation** (bare `trim` forbidden).

Measured, not assumed:

| expression                    | result   |
| ----------------------------- | -------- |
| CPython `chr(0x1f).isspace()` | `True`   |
| CPython `chr(0x1f).strip()`   | `''`     |
| TS `pythonStrip("\x1f")`      | `""`     |
| JS `"\x1f".trim()`            | `"\x1f"` |

So for the single-`\x1f` name CPython skips the case, and the TS
validator likewise short-circuits on `V17_EMPTY_EVENT` before reaching
V22 (`validation-args.ts:1525-1546`) — but the `trim` guard let the
case through to a `V22_CONTROL_CHAR_EVENT` assertion that can never
hold. The port code was RIGHT; only the test guard was wrong.

Fix applied (one line + import + a cited comment): the guard now uses
`pythonStrip`. Verified with 6 consecutive clean runs of the PBT file
plus a full `npm run check`. Flagged here because W6 does not own that
file — the B6 review pair / arbiter should confirm the cross-shard
edit rather than treat it as scope creep, and W3 should be charged the
R11.7 finding.

## 5 Deferrals

None. W6 ships all 15 members with no `TODO(port)` markers.
Vector replay is the BIND task's exit (§11), charged back to W6 on
failure.
