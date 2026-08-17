# Pair-A Lens-1 review: fix fidelity + cross-language twin exactness (four-bug R10.7 batch)

Reviewer: Pair A, Lens 1 (adversarial). Date: 2026-08-17.
Scope reviewed: Python `ts-port/python-bugfix-batch` (bddc576, 95d16e2, 57c5e16, 700db99,
a1d43a5, 2ea6442) vs `ts-port/phase2-contract-support`; TS `main` (a382687, 2b72ce1) vs 8fa150d.
Bar: the four fix-of-record docs + `context/phase4/inbound-ledger.md` row 2.
Method: everything below was verified EMPIRICALLY (probes run, oracles re-run, corpora
re-run) — not taken from `bugfix-batch-notes.md` on trust.

## Verdict summary

| Check | Result |
|---|---|
| (a) fix vs fix-of-record | MATCH (native fixture `analytics/api/version_2_0/insights/test.py:4111` key-for-key; deep oracle re-probed ACCEPT on all 4 actual builder outputs incl. windowed dateRange + event filters) |
| (b) fix vs fix-of-record | MATCH (clause `str()` coercion = doc option 2; sections `globalDataGroupId` = B5 addendum resolution; interior cohort `data_group_id` also coerced — required for ajv-clean, disclosed in notes) |
| (c) fix vs fix-of-record | MATCH VERBATIM (report's suggested expression; full 10-body matrix probed — outcomes exactly the report's post-fix table) |
| (d) fix vs fix-of-record | MATCHES the doc's suggested snippet — but the snippet's own flaw shipped: see FINDING F1 |
| Red-first | Test classes/counts named in the notes' red runs all exist (`TestSensitiveData403BodyShapes` :206, `TestTokenPayloadRedaction` :490, rewritten `TestBuildFrequencyFilterEntry` incl. new `test_no_custom_property_nesting` :750); red-run records are notes-based (single-commit TDD batches), internally consistent with the pre-fix/post-fix pass splits |
| TS twin shape exactness | 7/7 probe cases BYTE-IDENTICAL incl. key order (freq basic/window/filters+label/empty-filters; group cpr/cohort/freq-group with dgid 5/7/3) — probe harness run in both languages, JSON insertion-order compared |
| Corpora | Python runner 3,262/3,262 exit 0 re-run; TS `npm run conformance` 3,262/0/0 @ 700db996cc95 re-run; synced bundles hash-identical across repos (5/5 spot hashes incl. manifest); unaffected bundles stamp-only (3/3 spot diffs) |
| Referees | (a) ajv: `npm run referee:bookmark` re-run 9/9 green, 0 REJECT, `EXPECTED_DATAGROUPID_REJECTS` map DELETED (no allowlist kept); (b) deep: committed `last-run-deep.json` = 125 ACCEPT / 0 REJECT / 189 SKIP, README expected-REJECT section removed; independently re-probed the deep oracle myself (recipe env) — 4/4 ACCEPT |
| Bug-compat residue | NONE found: no freq `customProperty`/`eventFilters`/top-level `behaviorType` in either impl; no `sections["dataGroupId"]`; internals.ts local `pyTruthy` + TypeError branch deleted (the surviving `pyTruthy` hits are the UNRELATED result-base/discovery/replays helpers, legitimate); `@throws TypeError` JSDoc removed; browser README leak caveat flipped to redaction wording |
| R10.2 | NO weakening. Every removed assertion (both languages, diffed line sets side-by-side) is an old-shape lock replaced by a strictly-equal-or-stronger new-shape lock (full-dict equality, added `Object.hasOwn(..., "dataGroupId") === false` absence checks, added statusCode checks, byte-exact redaction string pin, key-order lock re-pointed at both levels in builders.test.ts:916-937) |

## FINDINGS

### F1 (MAJOR, bug (d)) — the Python redaction fix introduces an uncoded `AttributeError`
on non-dict 200 JSON bodies, and the TS twin deliberately diverges there

`flow.py:620-624` (post-fix): `redacted = {k: ... for k, v in data.items()}`. `data` comes
from `response.json()` whose runtime range is ANY JSON value (the annotation
`dict[str, object]` is aspirational — same class of lie bug (c) just fixed in
`_handle_response`). Empirically verified on the branch:

```
200 body b'[1, 2]'   -> AttributeError 'list' object has no attribute 'items'
200 body b'"hello"'  -> AttributeError 'str' object has no attribute 'items'
200 body b'42'       -> AttributeError 'int' object has no attribute 'items'
```

Pre-fix, all three raised `OAuthError` (code `OAUTH_TOKEN_ERROR`/`OAUTH_REFRESH_ERROR`,
`response_data: str(data)`), because `from_token_response`'s `data["expires_in"]` raises
TypeError (caught) and `str(data)` accepts anything. So this is a BEHAVIORAL REGRESSION
introduced by the batch, not pre-existing. The fix-of-record's suggested snippet carries
the same `.items()` call — the batch implemented the suggestion verbatim without
generalizing it, while the TS twin (`oauth-http.ts:275-282`) DID add an `isPlainRecord`
guard (non-record → old unredacted `pythonStr(data)` rendering inside a proper
`OAuthError`). Result post-fix, same input, different languages:

- Python: uncoded `AttributeError` crash (violates the R5.4 codes-only spirit — caller
  gets no `MixpanelHeadlessError` at all);
- TS: `OAuthError` with `response_data` (no leak — a non-record body has no token-bearing
  keys).

Reachability is the SAME misbehaving-IdP threat class that motivated bug (d) itself, so
"unreachable in practice" is not available as a dismissal. No corpus vector locks either
side of this edge (the new redaction vector uses a dict body), which is why both corpora
run 3,262/0/0 over the divergence.

Suggested repair (Python-first, one line): guard the comprehension —
`redacted = {...} if isinstance(data, dict) else data` (mirroring the TS twin exactly),
plus a red-first test for a list/scalar 200 body; no re-pin impact unless a vector is
added (recommended: add one, so the edge is corpus-locked in both languages).

### F2 (MINOR, bug (b)) — live-API spelling confirmation deliberately skipped

The fix-of-record says "probe the live App API first to confirm which spelling saved
bookmarks actually store". The batch ground rules forbid live calls, so the evidence base
is: ajv contract (`DataGroupId = string|null`, `Sections.additionalProperties: false` +
`globalDataGroupId`), deep validator (`Any(None, str)` at every clause level), and the
analytics fixture `test_behaviors.py:15109` (`"globalDataGroupId": str(...)`). That is
two independent static oracles + a platform fixture — strong, but the live saved-bookmark
round-trip remains unverified until Phase-4 burn-in. Carry as a burn-in check item, not a
defect.

### F3 (MINOR, process/scope) — TS main carries an out-of-batch commit in the review window

`a382687` ("README: consumer-facing rewrite") sits between the 8fa150d ground state and
the batch commit `2b72ce1`. Docs-only, no code, no vectors; but it is not part of the
four-bug mandate and rode into the reviewed range. Flag for the orchestrator's ledger;
no action needed from the batch executors.

### Observations (no action)

- O1: TS-FOLLOW notes' record-guard comment says "Python has no such branch — data.items()
  presumes a dict there" — i.e. the executors SAW the F1 edge and shipped the divergence
  anyway rather than routing it back into the Python fix. The R10.7 flip discipline (twin
  retires in the same change, no window with two live behaviors) argues the guard should
  have been a Python-first amendment inside this same batch.
- O2: bug (c) bare-`Infinity` flip verified consistent: Python `json.dumps(inf)` →
  `"Infinity"` (no flag → QueryError) ≡ TS `jsonDumpsLike` JsonNumber raw-token rendering;
  Layer-3 locked in internals.test.ts (not vector-locked — acceptable, matches Python
  which also has no such vector).
- O3: the (d) redaction vector byte-locks `str(dict)` rendering
  (`{'access_token': '<redacted>', ...}`) and the TS refresh test pins the identical
  string; node ≡ browser ≡ Python confirmed via the vector + the executors' 17/0 spot
  harness (their step-6 record; redaction leg independently re-verified here via the
  Python probe's `leak check: False`).
- O4: interior cohort `data_group_id` coercion (deep validator would ALSO accept int
  there, `Any(int, str, None)`) is a defensible over-coercion: ajv `GroupByCohort`
  requires string|null, and the notes disclose the reasoning. Both oracles accept the
  emitted str.

## RUN RECORD (this review)

- Python probe shapes: `/tmp/probe_shapes.py` → `/tmp/py_shapes.json`; TS twin probe via
  throwaway vitest file (deleted after run) → `/tmp/ts_shapes.json`; comparator
  `/tmp/cmp.py` → 7/7 byte-identical incl. key order.
- 403 matrix probe `/tmp/probe_403.py` → exactly the fix-of-record post-fix table.
- OAuth probe `/tmp/probe_oauth2.py` → redaction correct + F1 AttributeError repro.
- Deep-oracle probe `/tmp/probe_deep2.py` (recipe env: voluptuous==0.16.0,
  protobuf==7.35.1, pandas==3.0.5, pytz==2026.3.post1, PYTHONPATH=/Users/jaredmcfarland/
  Developer, analytics READ-ONLY) → 4/4 ACCEPT.
- `uv run python -m conformance.runner` → 3,262 ok; TS `npm run conformance` → 3,262/0/0;
  `npm run referee:bookmark` → 9/9, 0 REJECT.
- Touched Python unit files re-run: 381 passed.
