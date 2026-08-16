# B4-C3 notes — entity CRUD wire methods: dashboards (+blueprints/RCA) + bookmarks-v2 + cohorts-app

**Status**: in progress · 2026-08-15 · fable ≤ high · packet: `context/phase3/design/b4-packets.md` §Packet C3.
Scope: 38 api-index names, 78 vectors, Python `api_client.py:3650-4937`.

## Progress log

- 2026-08-15: task start. Inventory: NO prior C3 work in the TS repo
  (`packages/core/src/services/entities/` absent; no C3 bindings; no
  `throwaway/b4-c3/`). C1 (99ba862^) and C2 (99ba862) landed — factory
  seams (`ClientCore`, `clientFromSession`, `runWire`/`coreToVectorJson`,
  `kwargBag` pattern) all present and binding.
- Read: packet C3 + Cautions; Python source :3650-4937 in full; the three
  Layer-3 sources in full (`test_api_client_crud.py` 1,059,
  `test_api_client_crud_edge.py` 605, `test_api_client_bookmarks.py` 548);
  C1 `client.ts`, C2 `engage.ts`/`query-host.ts` (pattern), `wire-client.ts`
  + `wire-queries.ts` (binding pattern), `client-test-helpers.ts`.

## Design decisions

(to be filled as work lands)

## Findings / discrepancies

(none yet)

## R10.9 RUN record

(pending)
