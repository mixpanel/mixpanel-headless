# B8-MAPFIX — user-ratified org-ordering fix (shard notes)

Task: execute the 2026-08-16 user ratification
(`context/phase3/design/user-ratifications.md:14-22`) — `MeResponse`
container maps parse into an insertion-order-preserving `ReadonlyMap`
sourced from the lossless JSON layer, so `defaultAccountName`'s
first-org pick matches Python dict insertion order exactly. Supersedes
the B7-ARB-A R2 exclusion (`b7-reviewA-resolution.md` ruling R2 /
playbook Discrepancy #13). Packet references: `b8-packets.md` §0.3.1,
§2.2 (org-ordering lock), §2.3 (naming-order test row), §2.5 row 6.

## Status log (incremental, R10.13)

- [x] Red test written + red run recorded
- [x] Ordered-entries capability in lossless layer
- [x] MeResponse ReadonlyMap fields + model-base ordered-dict container
- [x] naming.ts / lifecycle.ts / login-unified.ts / accounts-ops.ts /
      services/me.ts consumers updated (tsc sweep + grep sweep clean)
- [x] Exclusion comments removed (naming.ts JSDoc rewritten to cite the
      ratification; naming.test.ts fixture note updated)
- [x] R10.9 harness: fast-check out-of-order fuzz + CPython differential
- [x] npm run check green; conformance 3,244/0/7 unchanged
- [x] Commits (TS main; Python support branch)

## Mechanism (files touched, TS repo)

1. `packages/core/src/client/json-value.ts` — `LOSSLESS_KEY_ORDER`
   symbol sidecar (non-enumerable; invisible to `Object.keys` /
   `JSON.stringify` / spread) + `attachKeyOrder` / `orderedKeys` /
   `orderedEntries`; `toNativeJson` propagates the sidecar.
2. `packages/core/src/client/lossless-json.ts` — `parseObject` records
   first-occurrence source key order (duplicates: first position, last
   value — the `json.loads` dict rule) and attaches the sidecar ONLY
   when JS enumeration diverges from source order (out-of-order
   integer-like keys); in-order objects carry nothing.
3. `packages/core/src/types/entities/model-base.ts` — new
   `container: "ordered-dict"` field kind → reconstructs into
   `ReadonlyMap<string, Model>` from `orderedEntries` (plain-object
   input) or Map input (caller-supplied order); `serializeValue` /
   `dumpValue` gained Map arms (Map → plain record in map order — the
   one boundary where order narrows back to JS enumeration; recorder
   shape unchanged). The existing `container: "dict"` semantics are
   untouched (the three `composed_properties` sites keep Records).
4. `packages/core/src/client/me.ts` — the three `MeResponse` container
   fields are `ordered-dict` (`ReadonlyMap`, defaults `new Map()`);
   init types accept `Record | ReadonlyMap`. Decision per packet
   §0.3.1: ALL THREE maps get the uniform treatment (one mechanism;
   R4.8), covering the result-affecting first-org pick AND the two
   sibling #13 sites (projects listing order, picker tie order) plus
   the `resolveWorkspace` tie-breaks.
5. Consumers: `accounts/naming.ts` (first-entry via Map iterator;
   disclosure comment rewritten to cite the ratification),
   `workspace-members/lifecycle.ts` (`resolveOrganizationId` /
   `cachedOrganizationId`), `accounts/login-unified.ts`
   (`resolveProjectForLogin` listings + picker sort + `summaryWithMe`;
   `sortKey` org lookup), `accounts/accounts-ops.ts` (`ProjectPicker`
   type, `assertProjectRegionMatches`, test/count/key sites),
   `services/me.ts` (`listProjects` / `findProject` /
   `listWorkspaces` / `resolveWorkspace`).

## Red run record

`npx vitest run packages/core/test/accounts/naming-order.test.ts` at
TS `main` 9fb09ef (pre-fix): **8 failed / 1 passed** — every
order-sensitive assertion reproduces the #13 divergence (ascending
integer-key hoisting wins over insertion order in `defaultAccountName`,
`MeService.resolveWorkspace` tie-break, and the Map shape asserts); the
single pass is the order-insensitive `toJSON` content check.

## R10.9 RUN record (mirror of `throwaway/b8-mapfix/RUN.md`)

```
npx vite-node throwaway/b8-mapfix/org-order-fuzz.ts
org-order-fuzz: examples 1000 (>=500 budget) divergences 0 seed 20260816

npx vite-node throwaway/b8-mapfix/org-order-py-diff.ts > /tmp/b8-mapfix-cases.jsonl
org-order-py-diff: emitted 1000 cases (naming 600, workspace 400) seed 20260816
uv run python throwaway/b8-mapfix/py_driver.py < /tmp/b8-mapfix-cases.jsonl
py-diff: naming 600 workspace 400 divergences 0
```

The ascending-id fuzz exclusion is REMOVED — both runs draw shuffled
integer-like + non-integer key orders. Part 1 is packet §2.5 row 6
verbatim (fast-check vs insertion-order mini-model). Part 2 goes
beyond the packet: naming has no oracle bridge surface (auth posture,
playbook Risk 7), so instead of a mini-model-only proof the harness
runs a direct CPython differential — 1,000 seeded cases through the
real TS wire path vs the real `default_account_name` /
`select_workspace_id` on the support branch (@ fd91a81), zero
divergences. Edge-set members exercised: `""`, `"---"`, unicode `é`,
non-BMP `"𝒳 labs"`, whitespace-wrapped names, empty org maps,
collision-suffix arms.

## Checkpoint numbers (2026-08-16)

- `npm run check`: green (typecheck ×5, eslint, prettier, **9,403**
  vitest tests / 213 files + the 7 standing UNPORTED oauth_flow corpus
  skips, browser-bundle smoke).
- `npm run conformance`: **3,251 — 3,244 PASS / 0 FAIL / 7 UNPORTED**
  (unchanged; this task owns 0 vectors — the ratification site is not
  vector-observable, order divergence needed out-of-ascending `/me`
  fixtures which no recorded vector carries).

## Decisions / disclosures (review-pair + arbiter input)

1. **Sidecar mechanism, not a parser return-type change**: making
   `parseLossless` return Maps would ripple through every wire body
   consumer; the non-enumerable symbol sidecar preserves the plain
   `JsonValue` object shape (zero behavior change for every existing
   consumer — attached ONLY when order actually diverges) and the
   ordered-dict container reads it at exactly the model boundary that
   needs Python-dict order.
2. **All three MeResponse maps converted** (packet §0.3.1 asked for a
   decision): uniform `ReadonlyMap` — one mechanism, closes all three
   Discrepancy #13 sites and the `resolveWorkspace` /
   `list_workspaces` iteration-order surfaces at once.
3. **Serialization boundary disclosure**: `toJSON` /
   `toVectorPayload` / `modelDump*` convert the Map back to a plain
   record (recorder shape). A plain record cannot hold out-of-order
   integer-like keys, so JSON-serialized output re-hoists ascending —
   identical to pre-fix behavior and to what `JSON.parse` does on the
   Python-emitted text. **B8-N2 note**: the on-disk me.json cache must
   RE-HYDRATE through the ordered path (`parseLossless` →
   `toNativeJson` → `fromDict`, which it gets for free), but a cache
   WRITE through `JSON.stringify(toJSON())` narrows key order for
   out-of-order integer-like keys (Python's `json.dump` keeps dict
   order). First-org identity survives only if the write preserves
   order — N2 should either serialize from the Maps directly
   (order-preserving writer) or record the narrowing as a disclosed
   cache-shape deviation. Flagged for the N2 packet executor.
4. **py_driver.py workspace arm** reproduces the `me.py:905-915`
   3-line view comprehension verbatim instead of instantiating
   MeService/MeCache (I/O scaffolding with no effect on the pick);
   the naming arm calls the real `default_account_name` end-to-end.
5. **`ProjectPicker` type spelling changed** (`accounts-ops.ts:57`):
   the indexed-access type `MeResponse["projects"][string]` has no
   Map analog; now `readonly [string, MeProjectInfo]` — same type,
   direct spelling.
6. **Gate duty reminder** (playbook §5.6 / b8-packets §7): update
   playbook Discrepancy #13 with the closure note (fixed at B8-MAPFIX
   per the 2026-08-16 ratification) and delete `throwaway/b8-mapfix/`
   after arbiter sign-off.
