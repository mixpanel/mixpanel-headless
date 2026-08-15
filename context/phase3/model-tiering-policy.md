# Model-tiering policy for Phase 3+ (user-approved 2026-08-15)

Concretizes plan §6 Phase 3 ("volume translation on the fast/cheap tier; rulebook,
api_client, auth, and all review on the strongest tier") into fixed assignments for
workflow authoring. Binding on every workflow launched from Phase 3 onward. To be
folded into the rulebook as R10.14 at the next amendment pass.

Pricing snapshot at decision time (first-party API, per MTok in/out):
Fable 5 $10/$50 · Opus 5 $5/$25 · Sonnet 5 $3/$15 (intro $2/$10 through 2026-08-31).

## Tier assignments

| Work | Tier (`model` opt in agent()) | Rationale |
|---|---|---|
| B0 pythonCompat + shared client internals (`app_request`, `_handle_response`, retry/backoff, `maybe_scoped_path`, `_iter_jsonl_lines`) | **fable** (inherit) | R10.8: ported once, first; every later slice imports — highest blast radius |
| B2 validators (`validation.py`, `user_validators`) translation + Layer-3 tests | **sonnet** | Mechanical rule transcription, fully locked by validation-error vectors + code-registry equality |
| B3 builders (bookmark builders/schema/enums, segfilter, transforms, expressions, query builders) | **opus** | Volume work but the riskiest pure logic (selector-string escaping = watchlist #2); mid-tier + the mandatory heaviest-fuzz gate |
| B4 api_client + pagination | **fable** (inherit) | Plan-mandated strongest tier |
| B5 services (discovery, live_query, replays, rrweb analyzer) | **sonnet** | Wire/parse-vector-locked; rrweb has golden files |
| B6 workspace facade (205 members) | **sonnet** | The bulk of the queue; mechanical delegation + options mapping, delegation-equivalence PBT locks it |
| B7 accounts/session/targets + resolver core | **fable** (inherit) | Auth subsystem — no second oracle (plan §2.3 gap), doubled review |
| B8 node package (config, storage, callback server, bridge) | **fable** (inherit) | Auth-adjacent (token files, 0o600 writes, callback ports, bridge) |
| B9 browser package (PKCE, CredentialStore) | **fable** (inherit) | Auth |
| ALL design, adversarial review, arbitration, audits, gate verdicts, failure triage (R10.4) | **fable** (inherit) | Review quality is the safety net that makes cheap translation safe — never downgraded |
| Anything touching the conformance rig itself (recorder, emit, canonicalizers, codecs, runners, oracles, smoke) | **fable** (inherit) | The judge must be stronger than the judged |

## Rules

1. **Effort discipline unchanged**: R10.13 applies on every tier — effort ≤ high with the
   incremental work protocol; no xhigh workflow agents on any model.
2. **Escalation on failure**: a volume-tier (sonnet/opus) task that misses its
   done-criteria on attempt 1 retries on **fable** with the failure context. Two failures
   still aborts the chain per the standing contract.
3. **Review is always cross-tier**: every sonnet/opus translation gets Fable adversarial
   review with the R10.2 assertion-weakening check; the R10.9 throwaway differential
   harness and module vector gates are unchanged and tier-independent.
4. **Layer-3 test translation** runs at the same tier as its module's translation; the
   reviewer checking it is Fable.
5. **Sonnet intro pricing ends 2026-08-31** — after that date sonnet remains the volume
   tier at $3/$15 (still cheapest); no assignment change needed.
6. Phase 2 (in flight at decision time) completes on Fable as launched; this policy
   applies from the first Phase-3 workflow onward.

Projected effect: full-port estimate drops from ~$4–8K (all-Fable) to ~$2–4K, with
quality held by the verification stack (vectors, differential oracles, referees,
Fable-tier review/audit gates).
