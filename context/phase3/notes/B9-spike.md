# B9-D2-SPIKE notes — browser-origin PKCE verification (DCR redirect-URI acceptance for third-party origins)

**Status**: DONE · executed 2026-08-16 (local) / 2026-08-17 UTC · task
B9-D2-SPIKE per `b9-packets.md` §4. Closes plan §8 open-question 3 / plan
§4.3 "Remaining unverified: browser-origin PKCE end-to-end (DCR client
registration + redirect-URI acceptance for third-party origins)".

**CLASSIFICATION: ACCEPTED** (attempt 1 → 2xx with a `client_id`,
§4.3 row 1). Tier C ships PKCE-in-browser ENABLED.

Filename note: the dispatch names this file `B9-spike.md`; the packet §4
header says `B9-D2-SPIKE-notes.md`. The dispatch-named file is the file of
record; `B9-D2-SPIKE-notes.md` is a one-line pointer here.

## Budget ledger (HARD caps, §4.1) — FINAL

| Item | Cap | Used |
|---|---|---|
| Credentials check (`uv run mp account test mixpanel-2`) | 1 (mandatory first) | 1 — PASSED |
| DCR registration attempts (POST `mcp/register/`) | 2 | **1** (attempt 1 → 201; the localhost control is CONDITIONAL on a non-2xx attempt 1 and therefore did not run) |
| Query-API calls (contingency only, arbiter-triggered) | 2 | **0** (no arbiter question raised; default zero honored) |
| §4.3(b) optional authorize-URL well-formedness GET (unauthenticated, sanctioned inside the ACCEPTED follow-through) | 1 optional | 1 |
| Other live calls anywhere in B9 | 0 | 0 |

All live traffic used raw `curl -sS` one-shots (§4.1.5) — the library
paths were never run live; the only library use was OFFLINE authorize-URL
construction via the shipped `buildAuthorizeUrl` (§4.3(a), no network).
stderr was never suppressed on any call.

## Pre-flight local-state snapshot (§4.6 duty 1)

`~/.mp/oauth/` before any live call:

```
/Users/jaredmcfarland/.mp/oauth/client_us.json  mtime 1784236054 (Jul 16 14:07:34 2026)  (only file present)
```

## 1. Credentials check (mandated first, §4.1.1)

Command: `uv run mp account test mixpanel-2` (stdout+stderr merged, exit 0).
Output (verbatim, ANSI stripped):

```json
{
  "account_name": "mixpanel-2",
  "ok": true,
  "user": { "id": 1428693, "email": "jared@mixpanel.com" },
  "accessible_project_count": 90,
  "error": null,
  "error_code": null,
  "error_details": null
}
```

PASSED → live half proceeds.

## 2. DCR attempt 1 (the unknown) — third-party https origin → **201**

Request: `POST https://mixpanel.com/oauth/mcp/register/` (us region only,
per §4.2 — regional posture ASSUMED uniform, recorded as an assumption).
Raw `curl -sS -D <headers> -o <body>`; headers sent:

- `Content-Type: application/json`
- `Origin: https://spike-b9.example.com` (browser-realistic)

Body — byte-identical to `ensure_client_registered`
(`client_registration.py:106-112`; same body in core `registerClient`,
`packages/core/src/auth/oauth-http.ts:308-314`, locked by the R2
`registration.test.ts` byte-compare):

```json
{"redirect_uris": ["https://spike-b9.example.com/oauth/callback"], "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "token_endpoint_auth_method": "none", "scope": "projects analysis events insights segmentation retention data:read funnels flows data_definitions dashboard_reports bookmarks"}
```

`redirect_uris[0]` is a third-party **https** origin on an RFC 2606
reserved domain (provably not attacker-usable, provably not localhost).

Response: **HTTP/2 201**, `content-type: application/json`. Notable
headers (full set retained in this transcript's source run):

```
HTTP/2 201
access-control-allow-origin: *          ← CORS free signal: the Origin header
vary: Authorization, Cookie                was answered with ACAO *, i.e. the
x-server-elapsed: 0.609                    DCR endpoint itself is CORS-open
strict-transport-security: max-age=63072000; includeSubDomains; preload
date: Mon, 17 Aug 2026 04:01:57 GMT
```

Response body (verbatim — DCR is unauthenticated; no secret material
present to redact: `token_endpoint_auth_method: none`, no `client_secret`,
no `registration_access_token`, no `registration_client_uri`):

```json
{"client_id": "ClI8BeFoFjq1Vn1SbdpiufvxvRvCwAbFtaMaXRvo", "client_id_issued_at": 1786939317, "client_secret_expires_at": 0, "redirect_uris": ["https://spike-b9.example.com/oauth/callback"], "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "client_name": "MCP Client - 1786939316", "token_endpoint_auth_method": "none", "scope": "projects analysis events insights segmentation retention data:read funnels flows data_definitions dashboard_reports bookmarks"}
```

The registered `redirect_uris` echo the third-party https URI verbatim.
**DCR redirect-URI policy for third-party https origins: ACCEPTED (stored
without modification, 201, no warning field).**

Attempt 2 (localhost control): NOT RUN — §4.2 makes it conditional on
attempt 1 returning non-2xx. Budget remaining: 1 DCR attempt (unspent).

## 3. Classification + follow-through (§4.3 row ACCEPTED)

### (a) Authorize URL via the SHIPPED `buildAuthorizeUrl` (offline)

Script bundled from the shipped sources (esbuild, platform-neutral;
`packages/core/src/auth/oauth-http.ts` `buildAuthorizeUrl` +
`packages/core/src/auth/pkce.ts` `PkceChallenge.generate()` /
`base64UrlEncodeBytes` + `OAUTH_BASE_URLS.us`), with the live
`client_id` and the third-party redirect:

```
https://mixpanel.com/oauth/authorize/?response_type=code&client_id=ClI8BeFoFjq1Vn1SbdpiufvxvRvCwAbFtaMaXRvo&redirect_uri=https%3A%2F%2Fspike-b9.example.com%2Foauth%2Fcallback&state=ieaRKVoZrMqEinIVaipQJ1Xw830gad6SI1Ylk6LBOXw&code_challenge=Bn8nmE9IJKYhQr7bXQZ2fGqfTAsWzvrojPjA8M_zbV8&code_challenge_method=S256
```

Param order `response_type, client_id, redirect_uri, state,
code_challenge, code_challenge_method` and the INTENTIONAL absence of
`scope` (`flow.py:625-627`) both hold — §3.3 contract shape confirmed on
the live-registered client id.

### (b) Optional well-formedness probe (ONE unauthenticated GET, no follow)

`curl -sS -o /dev/null -w '%{http_code} %{redirect_url}'` on the URL above:

```
HTTP=302
REDIRECT=https://mixpanel.com/login/?next=/oauth/authorize/%3Fresponse_type%3Dcode%26client_id%3DClI8BeFoFjq1Vn1SbdpiufvxvRvCwAbFtaMaXRvo%26redirect_uri%3Dhttps%253A%252F%252Fspike-b9.example.com%252Foauth%252Fcallback%26state%3D...%26code_challenge%3D...%26code_challenge_method%3DS256
```

A login-redirect that preserves the FULL authorize URL (client_id +
third-party redirect_uri included) as `next`. Per §4.3(b) this proves
**only URL well-formedness** — recorded as exactly that, no more. It does
NOT prove `redirect_uri_allowed` acceptance at authorize time (that check
runs post-login, `flow.py:55-58`).

### Verdict (Tier-C shipping posture per plan §4.3)

**PKCE-in-browser is VIABLE — Tier C ships PKCE-in-browser ENABLED**,
labeled: "DCR accepts third-party https redirect URIs (verified
2026-08-16); end-to-end browser consent/exchange verified in Phase-4 live
burn-in." The plan-§4.3 fallback ("oauth_token first-class; PKCE stays
Node-only until resolved") is NOT triggered; `oauth_token` mode remains
first-class and README-leading regardless (R9.3 / D2 Tier-C table).

Recorded assumption: regional posture (eu/in `mcp/register/`) assumed
uniform with us — only the us endpoint was probed (§4.2 budget rule).

## 4. Residual gap (§4.5 — verbatim structure, stated honestly)

Even under ACCEPTED, three things remain unverified without a real
browser session:

1. **Authorize-time `redirect_uri_allowed` enforcement** for the
   registered third-party URI — DCR storing it ≠ authorize honoring it;
   the `flow.py:55-58` docstring proves the check is a distinct code path.
2. **The consent screen issuing a code** to that redirect.
3. **A browser-origin `token/` POST succeeding cross-origin** — the token
   endpoint's CORS posture was NOT in the Phase-0 spike table. (The DCR
   endpoint answered `access-control-allow-origin: *` in §2 above — a
   favorable adjacent signal, but NOT evidence about `token/`.)

These three are the "browser PKCE e2e" live-auth scenario for the Phase-4
burn-in ledger (plan §6; `B8-notes.md` outbound "live auth scenarios";
`b9-packets.md` §5.5 row 4). The docs never claim e2e verification — the
landed wording (§7 below) says so explicitly.

## 5. Registered clients (residue) — §4.6 duty 2

| client_id | redirect_uri | management URI |
|---|---|---|
| `ClI8BeFoFjq1Vn1SbdpiufvxvRvCwAbFtaMaXRvo` | `https://spike-b9.example.com/oauth/callback` | none returned (no `registration_client_uri` / `registration_access_token` in the 201 body) |

Disposition: deletion NOT attempted — Mixpanel DCR exposes no documented
delete in our Python source, and the response carried no RFC 7591
management fields; budget forbids exploratory calls. The Phase-4 ledger
(`b9-packets.md` §5.5 row 7) carries "clean up spike DCR clients if a
management API exists". The client is public-metadata-only
(`token_endpoint_auth_method: none`, no secret) and unusable without
passing the (unverified) authorize/consent path.

## 6. Cleanup verification (§4.6 duty 1) — PASSED

After all live calls:

```
/Users/jaredmcfarland/.mp/oauth/client_us.json  mtime 1784236054 (Jul 16 14:07:34 2026)  — UNCHANGED, still the only file
```

No repo file outside `context/phase3/notes/` + the packet addendum
(`context/phase3/design/b9-packets.md` §9, dispatch-required) was touched
in the Python repo; TS repo changes are exactly the docs commit (browser
README + `redirect-flow.ts` JSDoc). Scratch material lived in `/tmp` only
(`/tmp/b9-spike-attempt1.*`, `/tmp/b9-authurl.*`).

## 7. Docs wording as landed (TS repo, one commit)

- `packages/browser/README.md` (NEW — no package README existed; created
  as the docs home the done-criterion names): leads with `oauth_token`
  first-class (R9.3/§8 map), then the "PKCE-in-browser status" section
  carrying the ACCEPTED label verbatim — "**PKCE-in-browser ships
  ENABLED.** DCR accepts third-party https redirect URIs (verified
  2026-08-16); end-to-end browser consent/exchange verified in Phase-4
  live burn-in." — followed by the three-item residual-gap list and the
  no-e2e-claim sentence; plus the localStorage security-warning pointer
  and the Export-Node-only section (plan §4.3 cite).
- `packages/browser/src/redirect-flow.ts` module JSDoc: additive "D2
  spike outcome (b9-packets.md §4.3: ACCEPTED)" paragraph with the same
  label, the residual-gap triple, the explicit "Nothing here claims e2e
  verification", and a pointer to this notes file.
- Packet addendum: `b9-packets.md` §9 (Python repo) records the outcome +
  the docs-facing wording for the gate/reviewers.

Commit hashes: recorded in §8 after the commits land.

## 8. Commits

- TS docs commit (`mixpanel-headless-ts`, `main`): `f6f298b` —
  "B9-D2-SPIKE docs (b9-packets.md §4.3 ACCEPTED): PKCE-in-browser ships
  ENABLED" (README + redirect-flow.ts JSDoc; `npm run check` green with
  the edits: 243 files / 9,934 tests + two-entry browser smoke OK).
- Python notes + addendum commit (`mixpanel-headless`,
  `ts-port/phase2-contract-support`): hash recorded in the finalization
  amendment commit that follows it (a commit cannot contain its own
  hash); both hashes are also in the orchestrator's task record.
  → landed as `3005bc9` (this line added by the finalization amendment
  commit, §4.6 duty 3).

Checks: `npm run check` green (above). `just check` green on the Python
side — note: a first run under the agent harness shell failed 14 CLI
string-assertion tests solely because the harness exports `FORCE_COLOR=3`
(Rich then embeds ANSI codes inside captured output); with the ambient
color-forcing vars neutralized (`env -u FORCE_COLOR NO_COLOR=1`) the same
tree passes. Environment artifact, not a repo regression — the spike's
Python changes are markdown-only (this notes file, the pointer file, the
`b9-packets.md` §9 addendum). Recorded for the gate task in case its
shell inherits the same variable.
