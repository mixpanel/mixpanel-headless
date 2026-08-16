# B4-C1 notes — client core + wire-enablement seam

**Status**: IN PROGRESS (skeleton) · 2026-08-15 · fable ≤ high · packet: `context/phase3/design/b4-packets.md` §Packet C1

## Plan of record

1. Read Python sources (api_client.py C1 ranges, me.py pure half) + B0 TS modules.
2. Layer-3 translation (R10.1/R10.2): test_api_client_session.py (ALL), test_api_client.py
   (construction/close/ctx-mgr + TestPublicRequest), test_query_workspace_scoping.py
   (client-side classes), test_workspace_resolution.py (TestSelectWorkspaceId /
   TestResolveWorkspaceIdWithResolver / TestProjectsMetadataIndex), test_me.py (pure half),
   test_api_client_pbt.py (TestAuthHeaderProperties + the three B0-module PBT classes),
   test_workspace_resolution_pbt.py, test_app_api_client.py B0 deferrals.
3. Implement `packages/core/src/client/client.ts` (createMixpanelClient) + `client/me.ts`.
4. b′ inline: `clientFromSession` + memoization in bindings.ts; register 11 C1 names; replay.
5. R10.9 harness `throwaway/b4-c1/`; RUN record below.

## Progress log

- [x] Notes skeleton committed
- [ ] Sources read
- [ ] Layer-3 tests translated
- [ ] client.ts + me.ts green
- [ ] Bindings + vector replay (+80 expected)
- [ ] R10.9 RUN record
- [ ] npm run check green; commits

## Findings / TODO(port) log

(populated as work proceeds)

## R10.9 RUN record

(pending)
