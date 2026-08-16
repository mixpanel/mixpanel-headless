# B4 arbiter resolution (P3-2d) — review pair `b4-review-wire.md` × `b4-review-assertions.md`

**Status**: COMPLETE · 2026-08-16 · Arbiter (fable tier, per plan mandate)
**Inputs**: wire-semantics review (GO-WITH-FIXES: 2 major + 3 minor + 1 nit, commit
`cb432d9`) · assertions review (GO-conditional: 1 major + 2 minor, commit `0e2b44d`).
Nine distinct findings total; no overlap between the lenses. Every verdict below was
re-verified against Python source and/or an executed probe by the arbiter before
ruling — nothing accepted on reviewer authority alone.

**Outcome: ALL NINE FINDINGS CONFIRMED. Eight fixed (six in code, red-first; two by
documentation), one resolved by arbiter ruling (the W-F6 blessing), with one
sanctioned deviation (D-B4ARB-1) inside the W-F2 fix. Nothing REJECTED. Post-fix
verdict: GO for the B4 gate.**

---

## Findings ledger

| # | Finding (reviewer) | Verdict | Disposition |
|---|---|---|---|
| W-F1 | exportEvents mid-stream body-read failures escape raw — no retry, no HTTP_ERROR wrap (wire, MAJOR) | **CONFIRMED** (red probe: `TypeError: terminated` escaped, 1 fetch call, no code) | FIXED red-first — `guardedByteSource` normalizes producer-side stream errors to `MixpanelHttpError` (§W-F1) |
| W-F2 | `timeoutSeconds` dead at the fetch adapter — no request timeout enforced anywhere (wire, MAJOR) | **CONFIRMED** (red probe: hung fetch stalls past any budget; grep confirms no timer/race pre-fix) | FIXED red-first — per-request timeout clock in `rawFetch` + sanctioned deviation **D-B4ARB-1** for streaming-body reads (§W-F2) |
| W-F3 | custom abort reason (`controller.abort("user-stop")`) escapes the request point un-normalized (wire, minor) | **CONFIRMED** (red probe: raw string `"user-stop"` rethrown bare) | FIXED red-first — `signal?.aborted` checked FIRST in the `rawFetch` catch, `normalizedAbortError(signal.reason)` thrown (§W-F3) |
| W-F4 | pagination body-parse catch narrower than Python's `except Exception`; comment mis-cites B0-ARB F3 (wire, minor) | **CONFIRMED** (`pagination.py:248` is `except Exception`; red probe: 200k-deep nesting → raw `RangeError` pre-fix) | FIXED red-first — catch-all wrap as `INVALID_RESPONSE`; mis-citation corrected in the comment (§W-F4) |
| W-F5 | exportProfiles `String()`-coerces `session_id` — a JsonNumber becomes `"[object Object]"` (wire, minor/PLAUSIBLE) | **CONFIRMED** (red probe: numeric `session_id: 123` → `"[object Object]"` in the page-1 body pre-fix) | FIXED red-first — raw `JsonValue` threaded, `toNativeJson` fold at insertion; residual disclosed (§W-F5) |
| W-F6 | real 1ms timers / no `vi.useFakeTimers` in the async suites vs risk-register #4 wording (wire, nit) | **CONFIRMED** as a wording deviation | RULED: injected-sleep-seam pattern **BLESSED** as satisfying the mandate's intent; no code change (§W-F6) |
| A-F1 | three whole `test_api_client.py` classes (23 tests) silently untranslated; ported `withProject` had ZERO locks (assertions, MAJOR) | **CONFIRMED** (arbiter grep re-run: zero hits for all 23 test names across `packages/core/test/` + `throwaway/` pre-fix) | FIXED — all 23 tests translated in `client-authenticated-requests.test.ts`, 23/23 green (§A-F1) |
| A-F2 | packet C1 §Layer-3 under-enumerates `test_api_client.py`, leaving three classes unassigned (assertions, minor) | **CONFIRMED** (packet row vs the 36-class `grep '^class '` list) | FIXED — full class→owner table appended to `b4-packets.md` §Addendum; B5/B6 instruction recorded (§A-F2) |
| A-F3 | four B4 `TODO(port)` markers carry disclosures but no recorded owner (assertions, minor) | **CONFIRMED** (grep re-run matches the four cited markers) | FIXED — owners recorded in this document (§A-F3); no code change needed |

---

## W-F1 — exportEvents mid-stream body failures (MAJOR, fixed)

**Verified.** Python's `for line in _iter_jsonl_lines(response)` walk sits inside
the `try` guarded by `except httpx.HTTPError` (`api_client.py:1870-1953`);
`httpx.ReadError` during body consumption is an `httpx.HTTPError`, so Python
retries up to `max_retries` and then wraps as `HTTP_ERROR` (`"HTTP error during
export: ..."`). Pre-fix TS consumed `response.body` unguarded: arbiter red test
reproduced the reviewer's probe exactly (`TypeError: terminated` escaped raw,
1 fetch call, no retry, no code).

**Fix (TS, red-first).** `streaming.ts` gains `guardedByteSource(body, signal)`:
producer-side iteration errors normalize to `MixpanelHttpError` (mirroring
`createRequestExecutor`'s body-read wrap), caller aborts exit as normalized
`AbortError` (R6.7), and existing `MixpanelHttpError`s pass through untouched.
Consumer-side `return()` exits run the generator return path, not the catch.
Locks (`client-wire-arb.test.ts`, red pre-fix / green post-fix):

- `retries a body-read failure and re-streams (Python re-yields)` — asserts the
  Python-exact observable including the duplicate yield (`["A","A","B"]`),
  2 fetch calls, and the `_calculate_backoff(0)` sleep (`[1000]` ms).
- `wraps an exhausted mid-stream failure as HTTP_ERROR` — `maxRetries: 1`,
  body always dies: `MixpanelHeadlessError` code `HTTP_ERROR`, message
  `HTTP error during export: ...`, exactly 2 calls.

## W-F2 — request timeouts enforced at the adapter (MAJOR, fixed + deviation D-B4ARB-1)

**Verified.** Python passes `timeout=timeout or self._timeout` on every httpx
call (120s default, 600s export); `httpx.TimeoutException ⊂ httpx.HTTPError` →
retried → `HTTP_ERROR` (`NETWORK_ERROR` analog in pagination's own walk). Pre-fix
TS threaded `timeoutSeconds` everywhere and read it nowhere: a hung server
stalled forever. Undisclosed in any B4 notes file (arbiter grep re-run concurs).

**Fix (TS, red-first).** `rawFetch` now merges the caller signal and a timeout
clock into one internal `AbortController`:

- clock = `setTimeout(timeoutSeconds * 1000)` (single R2.12 conversion,
  Python-named `*Seconds` field preserved), aborting with a
  `DOMException(..., "TimeoutError")` whose rejection normalizes through the
  existing R2.10 arm to `MixpanelHttpError` — retried and then wrapped
  `HTTP_ERROR`, exactly the httpx.TimeoutException flow;
- `RawFetchResult` gains `stopTimeout()` (stop the clock, keep abort
  forwarding) and `release()` (stop clock + detach forwarding);
- buffered view (`createRequestExecutor`): the clock spans headers + body read
  (`response.text()` — httpx read-timeouts bound `response.read()` too),
  released in a `finally`;
- streaming view (`exportEvents`): `stopTimeout()` fires once headers arrive;
  the per-attempt `release()` runs in a `finally` so signal forwarding detaches
  when the attempt's body is done;
- the two `lookup-tables.ts` rawRequest sites release after their buffered
  body reads; Node timers are `unref()`d defensively (browser no-op).

**Deviation D-B4ARB-1 (SANCTIONED).** httpx timeouts are *per-operation*
(connect/read/write each get the budget; a healthy multi-hour export stream
never times out as long as individual reads stay under 600s). fetch has no
per-read primitive. TS semantics after this fix: (a) headers phase bounded by
`timeoutSeconds` — the hung-server failure mode now matches Python; (b) a
buffered request is bounded by ONE clock across headers + body (marginally
stricter than per-op for pathologically slow buffered bodies, marginally looser
never); (c) a streaming body after headers is NOT clock-bounded (Python would
fail on a single >600s read gap; TS will not — the alternative, a total clock,
would kill healthy long exports, which is the worse infidelity). Locked by
three Layer-3 tests including
`does NOT clock-bound a healthy streaming body (D-B4ARB-1)`.

## W-F3 — custom abort reasons normalized at the request point (minor, fixed)

**Verified.** Pre-fix catch arms: string reason is neither an
AbortError-DOMException nor TypeError/DOMException → rethrown bare (arbiter red
test concurs with the reviewer's probe). **Fix:** `signal?.aborted === true` is
checked FIRST in the `rawFetch` catch (and in the executor's body-read catch and
`guardedByteSource`) → `throw normalizedAbortError(signal.reason)`. A non-caller
AbortError (only possible source: the W-F2 clock) now falls to the R2.10
normalization arm instead of passing as a cancellation — which is the correct
taxonomy (it is httpx.TimeoutException, not a user abort). Lock:
`controller.abort('user-stop') rejects as DOMException AbortError`.

## W-F4 — pagination catch scope (minor, fixed)

**Verified.** `pagination.py:246-254` is `except Exception` (RecursionError ⊂
Exception in CPython), unlike the `except json.JSONDecodeError` sites B0-ARB F3
actually ruled on; the TS comment's "disclosed at B0" citation was wrong — no
design doc sanctioned this site. Arbiter red test: a 200,000-deep `[` body
escaped as raw `RangeError: Maximum call stack size exceeded`. **Fix:** the
guard `if (!(cause instanceof LosslessJsonError)) throw cause;` is removed at
THIS ONE SITE (every parse failure wraps as `INVALID_RESPONSE` with the
content-type detail, matching Python verbatim); the comment now cites W-F4 and
explains the contrast with the B0-ARB F3 sites. Lock (pagination.test.ts):
`wraps ANY body-parse failure as INVALID_RESPONSE (W-F4)`.

## W-F5 — session_id threads verbatim (minor, fixed + disclosed residual)

**Verified.** Python: `session_id = response.get("session_id")` →
`params["session_id"] = session_id` → `_request(..., data=params)` where
`data=` is the JSON body (`api_client.py:829/858` — the reviewer's "the page
body is JSON" reading is correct); an int stays an int on the wire. Pre-fix TS
`String(nextSession)` turned a lossless `JsonNumber` into `"[object Object]"`
(arbiter red test concurs). **Fix:** `sessionId` is typed `JsonValue`, assigned
raw, guarded by the same `pyTruthyJson` discipline (`if session_id:` on both
the insert and the break), and folded via `toNativeJson` only at the insertion
point (JSON.stringify cannot emit a raw token). **Disclosed residual:** an
UNSAFE-integer `session_id` (>2^53, no corpus instance; strictly narrower than
the pre-fix bug) would round through a JS double; Python would re-emit full
digits. Owner: B8 (node package) IF a runtime with `JSON.rawJSON` becomes the
floor; otherwise standing disclosure. Lock:
`a numeric session_id round-trips as a JSON number, not a string`.

## W-F6 — fake-timer mandate vs injected-sleep seam (nit, ruled)

**RULING: the injected-sleep-seam pattern is BLESSED as satisfying risk-register
#4 / the B4-row wording.** Rationale: every retry-WAIT assertion goes through
the injected `sleep(ms)` seam and asserts recorded millisecond durations
(`[5000]`, `[30000,30000,30000]`, `[1000]`) — deterministic in assertion
content and STRONGER for R2.12 than `advanceTimersByTimeAsync`, which cannot
distinguish a mis-scaled duration that the fake clock happily advances past.
The residual real timers (1ms chunk delays in `chunkedFetch`, and the
30ms/20ms pairs in the W-F2 locks, where real elapsed time IS the observable)
create only a theoretical flake surface on a pathologically loaded machine;
34 consecutive suite runs across this arbitration showed zero flakes. B5/B6
authors: use the seam for all retry timing; real short delays are acceptable
only where wall-clock passage is itself the behavior under test.

## A-F1 — the three dropped test classes (MAJOR, fixed)

**Verified.** Arbiter re-ran the reviewer's grep: zero hits for any of the 23
test names under `packages/core/test/` and `throwaway/`; no exclusion header in
`client-core.test.ts`/`client-request.test.ts`; no notes citation. `withProject`
(`client.ts:1166`) had zero locks of any kind (index-absent surface — Layer-3
is its ONLY lock class per the packet).

**Fix.** `packages/core/test/client/client-authenticated-requests.test.ts` —
all three classes translated 1:1 (R10.2), 23/23 green on first run (confirming
the C1 ports were faithful; the gap was lock coverage, not behavior):

- `TestAuthenticatedRequests` (7) — incl. the security lock
  `test_credentials_not_in_error_messages` (translated, NOT excluded: the
  arbiter declined the review's optional header-exclusion alternative);
- `TestWithProject` (9) — `withProject` now has its full Python lock set
  (project/auth/region/workspace/timeouts/maxRetries/transport-identity/OAuth);
- `TestClientIdentificationHeaders` (7) — with the autouse
  `_reset_entry_point` fixture as beforeEach/afterEach over
  `getEntryPoint`/`setEntryPoint`.

Documented substitutions (file header): `client._session` →
`client.core.session()`; `client._timeout`/`_export_timeout`/`_max_retries` →
`client.core.timeoutSeconds`/`.exportTimeoutSeconds`/`.maxRetries`;
`_transport is transport` → injected-fetch identity via
`client.core.http().fetchImpl`; `monkeypatch.setenv(MP_CUSTOM_HEADER_*)` → the
injected `getCustomHeaderEnv` provider (R9.1); UA runtime tag `python/<x.y>` →
`ts` (B0-notes decision 8).

## A-F2 — packet under-enumeration (minor, fixed)

Full 36-class `tests/unit/test_api_client.py` → TS-owner table appended to
`b4-packets.md` §Addendum (arbiter-generated by mechanical grep; every class
has exactly one primary owner; `_IterableByteStream` is a helper, not a test
class). **Instruction to B5/B6 packet authors (binding):** enumerate Layer-3
rows against each source file's COMPLETE `grep -n '^class '` list and assign
every class an owner or a cited exclusion — risk-register #3 is exactly this
failure mode at B6 volume.

## A-F3 — TODO(port) owners (minor, recorded)

| Marker | Owner / trigger |
|---|---|
| `pagination.ts:180` (exponent-form cursor spelling) | Standing disclosure — permanent unless a corpus refresh records an exponent-form cursor (re-check at each corpus re-pin). |
| `response-validation.ts:22` (non-missing pydantic type/msg wording) | **B6** (Workspace facade) — re-verify when B6 records/locks validation-error surfaces; else standing. |
| `py-dates.ts:14` (local-midnight clock disclosure) | **B8** (node package, env/clock seams) — final wording review at the B8 gate; else standing. |
| `services/entities/schemas.ts:76` (AttributeError vs TypeError stand-in) | Standing disclosure — same class as the exportProfiles non-dict arm; no lock reaches it by design. |

---

## Ripples chased

- **Full conformance replay** (post-fix): `3,251 = 2,370 PASS / 0 FAIL /
  881 UNPORTED` @ corpus `70c904dc598d` — byte-identical to the pre-arbitration
  baseline; zero vector movement from any fix (as predicted: all nine findings
  were vector-unreachable).
- **`npm run check`** green end-to-end: typecheck (5 packages), eslint,
  prettier, **6,083 tests passed / 881 skipped, 130 files** (was 6,052 — +31
  new locks: 23 translated + 7 in `client-wire-arb.test.ts` + 1 in
  `pagination.test.ts`), browser-bundle smoke OK.
- **R10.9 harness re-runs (all six shards)**: C1 39/0 · C2 52/52 · C3 65/0 ·
  C4 59 total, 0 failed · C5 75 passed, 0 failed · C6 56 ok, 0 fail.
- **Interface ripple**: `RawFetchResult` gained `stopTimeout`/`release` —
  all three `core.rawRequest` consumers updated (streaming ×1, lookup-tables
  ×2); `createRequestExecutor` releases in `finally`; destructuring callers of
  `{ response }` remain source-compatible.
- **Bindings/rig**: untouched — no API-name or serving changes; binding-honesty
  state from the assertions review carries forward unchanged.

## Commits

- TS repo (`mixpanel-headless-ts`, main): `a24a58d` — fixes W-F1..W-F5 +
  A-F1 locks + this arbitration's Layer-3 files (7 files, +864/−45).
- Python repo (`ts-port/phase2-contract-support`): this document +
  `b4-packets.md` §Addendum.
