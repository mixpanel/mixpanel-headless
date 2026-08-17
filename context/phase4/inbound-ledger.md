# Phase-4 inbound ledger — the SINGLE collection point Phase-4 planning reads

**Status**: v1.0 · 2026-08-16 · Written by the B9 gate (task B9-GATE, Phase-3
TERMINAL gate) per `context/phase3/design/b9-packets.md` §5.5 (as amended by
the §10 errata) and the gate dispatch. Every row was re-verified against its
source of record before writing (the mechanical sweep covered every
`context/phase3/notes/B*-notes.md` outbound section — B0–B4 gate notes carry
none; B5's outbound ledger was closed at B6, B7's at B8, B8's at B9, each
closure audited by the successor gate — plus the B9 shard/spike notes and all
four B9 review resolutions).

Ground state Phase 4 inherits: TypeScript repo `main`, full conformance
corpus **3,251 PASS / 0 FAIL / 0 UNPORTED** @ corpus pin `70c904dc`
(terminal gate report `context/phase3/reports/2026-08-16-b9-gate.json`);
Python repo branch `ts-port/phase2-contract-support`; oracle surface 55
families, differential regression clean at 10 seeds (fresh + all nine prior
gate seeds); Phase-3 summary block in `context/phase3/notes/B9-notes.md`.

## 1. O1 — OAuth error details carry the full 200 token payload (ESCALATED to the R10.7 fix queue)

RE-SCOPED at B9 (packet §10 erratum 5 — the original `flow.ts:898` citation
is stale post-hoist): core `packages/core/src/auth/oauth-http.ts`
`postTokenRequest` missing-required-fields branch (`oauth-http.ts:245`
region) puts `response_data` — the FULL 200 token payload, potentially
including an `access_token` — into refresh/exchange error details. This is
verbatim `flow.py:596-605` parity (Python does the same), shared by node
refresh AND browser exchange. Pair-B FB-3 escalated it from "re-examine" to
the **R10.7 Python-first fix queue** — it is item (d) of row 2. Bug report:
`context/phase3/bug-reports/python-oauth-error-details-token-payload.md`.
README/JSDoc caveats landed at B9 (TS `de08f1f`). Sources:
`b8-reviewB-resolution.md` O1 → `b9-reviewB-resolution.md` FB-3 →
`b9-packets.md` §10.5.

## 2. The R10.7 Python-fix queue (Python-first fix → re-record → re-pin → TS follows)

NONE fixed during Phase 3 by design (R10.7 bug-compatibility: TS ports the
buggy behavior verbatim until Python fixes land). Queue:

| # | Bug | Source of record |
|---|---|---|
| (a) | Frequency-filter clause shape (the 2 standing referee-(b) deep REJECTs — true positives, disclosed since Phase 1) | `context/phase1/addendum/frequency-filter-probe.md` |
| (b) | `dataGroupId` int-vs-string threading (the pinned expected-and-disclosed referee-(a) REJECT set) | `context/phase3/bug-reports/mixpanel-headless-datagroupid-int-clause.md` |
| (c) | `_handle_response` 403 `TypeError` on truthy non-dict/non-str JSON bodies | `context/phase3/bug-reports/python-handle-response-403-typeerror.md` |
| (d) | OAuth error details carry the full 200 token payload (row 1 above) | `context/phase3/bug-reports/python-oauth-error-details-token-payload.md` |

**Re-pin choreography per fix (playbook P3-7 trigger 3, normative)**: fix on
the Python support branch → re-record/re-extract the affected vectors →
re-pin the corpus (`scripts/sync-corpus.sh` re-sync + D8/D9 drift check —
UNAFFECTED vectors must be byte-identical, only stamps move) → re-run the
P3-0 vector-count measurement and update expectations → TS follows (remove
the bug-compat twin, tests + vectors flip to the fixed behavior in the same
change) → referee re-runs where the fix touches bookmark payloads ((a) and
(b) retire the standing disclosed REJECT sets — after them, both referees
must run fully clean). Batch the four fixes into as few re-pin events as
practical; each re-pin re-establishes 3,251+Δ / 0 / 0 before burn-in nights
count.

## 3. The JsonNumber facade round-trip gap

In the LIBRARY result path a >2^53 integer token collapses at
`JsonNumber.toNumber()` before any consumer sees it (TS imprecise/±Infinity
where CPython keeps the exact int) — the sanctioned Discrepancy #6/#7 class,
disclosed at `B6-notes.md:190` region (the `pythonFloatCoerce` domain notes).
Re-examine if Phase-4 burn-in ever sees live event counts or ids beyond
2^53. A code fix would require a `JsonNumber`-preserving (or bigint) result
surface — a public-API decision, not a port-fidelity one. Sources:
`B6-notes.md:190`; playbook discrepancies #6/#7.

## 4. Live-parity Layer-4 setup (plan §6 Phase 4 / Layer 4 — the burn-in gate)

- **Corpus + fuzz nightly**: full corpus replay (BOTH languages), fresh-seed
  differential fuzz (≥500/family over the 55 families), referee checks;
  **≥4 consecutive green nights**; failure clusters → upstream fixes →
  regenerate → reset the counter (plan "Phase 4 — Burn-in").
- **Live suite**: parameterize the 503 live-test scenarios; run against a
  dedicated demo project from BOTH implementations nightly;
  **rate-limit-aware: the 60 q/hr per-project budget requires sharding
  across nights or across projects**; responses cached and diffed after
  canonicalization (plan "Layer 4" — the anti-ScanCode layer).
- **Live-auth scenarios with no Phase-3 oracle** (playbook Risk 7
  compensating control): real IdP refresh, real browser login (callback
  server + paste fallback), real DCR, and the **browser PKCE e2e triple**
  (`b9-packets.md` §4.5 / `B9-spike.md` §4): (1) authorize-time
  `redirect_uri_allowed` enforcement for the registered third-party URI;
  (2) the consent screen issuing a code to that redirect; (3) a
  browser-origin `token/` POST succeeding cross-origin (token-endpoint CORS
  was never probed).
- **Implementer cautions carried forward**: `/api/app/me` is minutes-slow
  live — never on an interactive path (plan §4.3 note); one observed
  HTTP/2 flake against `/api/app`.

## 5. Sanctioned TOCTOU residue of the R9.2 fd-hardening drop

`packages/node/src/io-utils.ts` header documents the residual
symlink-swap window left by dropping Python's fd-flag hardening (R9.2
sanctioned drop; symlink refusal kept). Re-examine only if burn-in surfaces
a practical exploit path. Source: `B8-notes.md` Phase-4 ledger line 2 +
`B8-N1-notes.md`.

## 6. Standing discrepancy-class re-examine triggers

Playbook discrepancy log, classes with live-observability triggers:
**#6/#7** (>2^53 Retry-After / `safeInt` — re-examine on a live >2^53
header or count), **#11** (gmtime overflow band OSError-vs-ValueError —
live timestamp in the band), **#12** (integral-float spelling narrowing —
a wire body where the spelling is contract), **#14** (`\d` ASCII narrowing
at the B8 bridge `project` twins — a live Nd-digit bridge artifact),
**#15** (config default path import-time vs call-time — a scenario
depending on the frozen path). Plus the **#9/#10 residual-site
HUMAN-CALL** (order-insensitive comparison for integer-like-key emission
ordering) — still open, OPTIONAL, non-blocking (#13 was CLOSED-FIXED at B8
by user ratification; the remaining #9/#10 mechanism sites are unaffected).

## 7. D2 spike posture + residue

**CLASSIFICATION: ACCEPTED** (2026-08-16, `B9-spike.md` — budget: creds
1/1, DCR 1/2, Query-API 0/2). DCR accepts third-party https redirect URIs;
**Tier C ships PKCE-in-browser ENABLED** alongside first-class
`oauth_token`. Docs carry the ARB-A-corrected wording ("…consent/exchange
**to be verified** in Phase-4 live burn-in") — never a completed-e2e claim.
Residue for Phase 4:

- Registered client residue: `client_id
  ClI8BeFoFjq1Vn1SbdpiufvxvRvCwAbFtaMaXRvo` (redirect
  `https://spike-b9.example.com/oauth/callback`, no management fields
  returned) — **clean up if a DCR management API ever exists**; the client
  is public-metadata-only and unusable without the unverified consent path.
- Regional posture (eu/in) ASSUMED uniform — only us was probed; verify
  opportunistically during burn-in DCR scenarios.
- Free signal (recorded, NOT evidence about `token/`): the DCR endpoint
  answered a third-party `Origin` with `access-control-allow-origin: *`.
- The e2e triple itself is row 4's browser-PKCE scenario.

## 8. Browser refresh surface (deferred out of v1 — now on the D2-ACCEPTED branch)

`refreshTokens`-over-`CredentialStore` (Python twin `flow.py:442-498`, TS
core `postTokenRequest` already hoisted and shared) deferred out of browser
v1 (`b9-packets.md` §2.2/§3.4 disposition). Precondition: the row-4/row-7
browser-PKCE e2e lands green in burn-in. Until then browser sessions
re-login on expiry (`createBrowserWorkspaceFromStore` refuses
expired-with-no-refresh with `OAUTH_TOKEN_ERROR`).

## 9. Packaging + awareness items (accumulated, non-blocking)

- **`exports` asymmetry** (B9-ARB-A ASR-O4, LEAVE-AS-IS ruling):
  `packages/browser/package.json` carries `"exports"`, core/node carry
  none; functionally inert today (all cross-package imports are relative).
  Phase-4/5 packaging (entry-point maps, types conditions, ESM
  conditional exports per plan Phase 5) starts from this known asymmetry.
- **Arbiter judgment-call defaults, trivially adjustable** (B9-ARB-B,
  flagged for awareness, not decision): `completeLogin` pending-record TTL
  default 30 min (`DEFAULT_MAX_PENDING_AGE_MS`); `beginLogin` redirectUri
  gate allows http on loopback per RFC 8252 §7.3.
- **Cross-tab `completeLogin` races are a documented non-goal** (FB-6
  disposition: same-realm in-flight dedup only; no atomic ops exist on the
  3-method `CredentialStore` interface). Re-examine if a real multi-tab
  consumer workflow needs it.
- **`repros/` state**: exactly the two RESOLVED P2-9 triage records —
  historical, non-blocking.
- **SA-refusal path table** now has 7 enumerated rows (packet §2.3 + §10.1
  paths 6–7); if Phase 4 surfaces a third gate-bypass shape, pair-B's
  arbiter recommends promoting the browser guard into a core seam rather
  than extending the wrapper (`b9-reviewB-resolution.md`).
