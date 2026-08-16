# B8-N1 — config + io_utils + env wiring + readFile seam (shard notes)

Packet: `context/phase3/design/b8-packets.md` §2 (v1.0). Spec of record:
`phase3-playbook.md` v1.1 + user-ratifications.md.

## Scope adjustment recorded up front

The §0.3.1 core touch (org-ordering Map fix) landed BEFORE this shard as the
standalone B8-MAPFIX task (TS `597ef7d`, notes `B8-MAPFIX-notes.md`),
including the §2.3 `naming-order.test.ts` lock (9 tests) and the §2.5 row-6
harness row (fast-check 1000 + CPython differential 1000, 0 divergences,
`throwaway/b8-mapfix` RUN). N1 therefore does NOT re-touch core for ordering;
this shard verifies the lock is present and green and covers the remaining
§2.1 rows (all `packages/node`).

## Status log (incremental, R10.13)

- [x] Python sources re-read at HEAD (io_utils.py 1-545, config.py 1-1061,
      test_io_utils.py, test_config.py, test_settings_headers.py N1 classes,
      test_042_edge_cases.py::TestConfigManagerEdgeCases, fixtures)
- [x] Core consumer signatures re-read (resolver.ts ResolverEnv/
      ResolverConfigSource, auth-effects.ts ConfigWrites/AddAccountParams/
      SetActiveUpdate/ApplySessionUpdate, workspace.ts readFile seam :560/:1156,
      fake-auth-effects.ts reference semantics, accounts.py:472-489 promotion)
- [x] TOML library pinned + recorded: **smol-toml 1.7.1** (exact pin in
      packages/node/package.json + root lockfile) — TS-native, MIT, zero-dep,
      TOML 1.0 parse+stringify; config schema round-trips (strings/ints/bools/
      nested tables); no datetime needed. Serialization formatting is out of
      contract (packet §0.4); read-side locks carry the Python fixtures verbatim.
- [x] Layer-3 tests translated (RED first): io-utils, config, settings-headers
      (N1 classes), 042 TestConfigManagerEdgeCases, secret-roundtrip
      (RED state verified on resume: config/settings-headers/secret-roundtrip
      fail on missing ../src/config.js + ../src/config-writes.js; 52 io-utils/
      env/fs-seams tests already green)
- [x] io-utils.ts implemented to green
- [x] config.ts + config-writes.ts implemented to green (112/112 node
      package tests pass incl. config 55, io-utils 46, settings-headers 3,
      secret-roundtrip 2, node-seams 5)
- [x] env.ts + fs-seams.ts implemented to green
- [x] B7 fake-backed swap-in run (accounts-namespace over real ConfigWrites)
- [x] R10.9 harness `throwaway/b8-n1/` + RUN record below
- [x] npm run check green (see RUN record)
- [x] Local commits (TS main; Python support branch)

**Shard commit**: TS `main` `44fc912` ("B8-N1: node config + io_utils +
env wiring + readFile seam"), on top of `597ef7d` (B8-MAPFIX). 0 vectors
owned; conformance untouched (3,244 PASS / 0 FAIL / 7 UNPORTED holds).

## Decisions / substitutions (header-cited in code)

1. **Tmp-name substitution** (`io-utils.ts` header; packet §2.2 / §7 caution
   10): Python's `<name>.tmp.<pid>.<tid>` becomes `<name>.tmp.<pid>.<counter>`
   (monotonic per-process counter) — JS has no OS thread id in the main
   thread (`worker_threads.threadId` is 0). EEXIST stale-tmp branch leaves
   the FOREIGN tmp in place (harness row 1a locks it).
2. **R9.2 fd-hardening drop** (`io-utils.ts` header; plan §4.2): the
   `_open_credential_fd` `O_NOFOLLOW`/`O_CLOEXEC`/dirfd-walk layer
   (`io_utils.py:236-435`) is substituted with lstat-based symlink refusal +
   stat-based regular-file/mode/size checks. The retained layer probes the
   LEAF only — a file under a symlinked PARENT still reads (harness row 3
   documents this; parity with Python's retained `reject_if_symlink` layer;
   parent traversal was the dropped hardening). Sanctioned TOCTOU residue →
   Phase-4 burn-in (packet §8 outbound row 3).
3. **`mode & 0o077` guard** → `ParamValidationError`/`VALIDATION_ERROR`
   (Python bare ValueError; R5 codes-not-messages, no new code minted).
   `apply_session` workspace-XOR-clear_workspace ValueError → same twin
   (fake-auth-effects precedent over `config.py:826-829`).
4. **`CredentialPathError`** — coded `MixpanelHeadlessError` subclass with
   the OSError fields (`errno`, `filename`) mirrored in `details`;
   `CREDENTIAL_PATH_ERROR` code is node-package-local (never reaches a
   contract boundary — every call site wraps into `ConfigError`/`OAuthError`).
   N1 defines it ONCE in `io-utils.ts`; N2 must import BY NAME (R10.8).
5. **CRED-F3 reveal-site enumeration (config.ts)**: the ONE on-disk reveal
   site is `accountToBlock` (`_account_to_block` twin, `config.py:92-125`).
   Unlike Python (which also unwraps at `config.py:366/455/466` to build
   validation payloads), the TS add/update paths pass `Secret` INSTANCES
   into `parseAccount` (which accepts them), so revealed text exists only
   in the block `accountToBlock` produced for the TOML serializer. The
   module-local `credentialText` helper unwraps only inside
   `applyUpdateAccount`/`applyAddAccount` block-building for string params
   (transaction-local, never serialized directly). Locked by
   `secret-roundtrip.test.ts` (SA + OT write→read reveal equality, real
   values on disk, no `**********` mask).
6. **FR-045 promotion layering** (B-E2E-N1): `ConfigManager.addAccount`
   NON-promoting (test_config lock + harness probe); promotion exactly once
   in `createNodeConfigSource().addAccount` transaction
   (`accounts.py:472-489` twin: `is_first` evaluated BEFORE the insert).
7. **Duplicate add** → PLAIN `ConfigError`/`CONFIG_ERROR` (B-E2E-F1;
   `config.py:446`), never `AccountExistsError` — harness row 4 asserts.
8. **`_validate_workspace_id`** → `Number.isInteger(w) && w > 0` VALUE check
   (§7 caution 1 — no parse, no `pythonInt`, never `!w`); harness confirms
   `2**53` is accepted on BOTH sides (Python int / JS safe-boundary integer).
9. **MP_CONFIG_PATH read at CONSTRUCTION** (`config.py:150-151` parity);
   `createNodeEnv` members read `process.env` at CALL time (§0.4).
10. **smol-toml 1.7.1** pinned (packages/node/package.json + root lockfile).
    Serialization formatting out of contract (§0.4); a trailing newline is
    appended for tomli_w cosmetic parity. Read-side locks: `TestFixtureLoad`
    over the VERBATIM Python fixtures (diff-verified byte-identical against
    `tests/fixtures/configs/{simple,multi}.toml`).
11. **`isPythonDict`** (core `compat/python-dict.ts`) is the ONE dict guard
    at every `isinstance(x, dict)` site (watchlist #13): `_validate_raw`,
    `list_accounts`/`get_account` block guards, target block guards,
    `get_custom_header`, `apply_target`, `remove_account` ref scan.
12. **`getActive`** parses through core `parseActiveSession` and wraps any
    validation error in `ConfigError` ("Invalid [active] block: …",
    `config.py:706-711`); `_read_raw` boundary wraps CredentialPathError /
    errno errors / `TomlError` into `ConfigError` ("Could not parse config
    at …") while letting the strict-decode `TypeError` (UnicodeDecodeError
    twin) propagate, exactly per Python's `except (TOMLDecodeError, OSError)`.

## Harness findings (fake-model corrections — no product-code defects)

- **F-N1-1 (model)**: the B7 in-memory `fakeConfig().applySession` is NOT
  transactional on failure — e.g. `applySession({project, workspace})` with
  no active account sets `active.workspace` and THEN throws, leaving the
  partial mutation. Python's `_mutate()` (and the real on-disk port) roll
  the whole op back. Fake-only divergence, never reached by the B7 suites;
  the fuzz driver snapshots/restores the fake state on error (documented in
  `config-model-fuzz.ts`). Flagged for the B8 review pairs — candidate
  drive-by fix to the fake if the arbiter wants it.
- **F-N1-2 (model)**: `fakeConfig().applySession`'s project branch calls
  `parseAccount` UNWRAPPED, so an invalid project surfaces as
  `ResponseValidationError`; Python wraps every ValidationError in
  `ConfigError` (`config.py:395-401`) and the real port matches Python.
  Driver normalizes this one case (documented in `config-model-fuzz.ts`).

## RUN record (R10.9) — `throwaway/b8-n1/`

All runs on TS `main` working tree (this shard), node v24.18.0, corpus pin
untouched (N1 owns 0 vectors).

```
npx vitest run packages/node/test
6 files, 112 tests — ALL PASS (config 55 incl. TestConfigManagerEdgeCases,
io-utils 46, settings-headers 3, secret-roundtrip 2, node-seams 5, index 1)

npx vitest run packages/core/test/accounts/naming-order.test.ts
9 tests PASS (§0.3.1 org-ordering lock — landed at B8-MAPFIX, verified here)

# Swap-in run (§2.6 done-criteria): the B7 fake-backed suite copied with
# ONLY the effects import rewritten to a shim that swaps `config` for the
# REAL on-disk createNodeConfigSource in a tmp dir (real-effects.ts).
npx vitest run -c throwaway/b8-n1/vitest.config.ts
throwaway/b8-n1/accounts-namespace-real.test.ts — 48/48 PASS

npx vite-node throwaway/b8-n1/io-config-probes.ts
io-config-probes: 74 checks, 0 failures
  row 1: crash-window fault injection (EEXIST foreign-tmp survives; fchmod/
         mid-loop-write/rename failures → original byte-identical + tmp
         cleaned + error propagated; short-write loop retried; post-success
         mode 0600 and 0400-on-request)
  row 2: 0600 on config writes; created parent dir 0700; mode-guard rows
         0o644/0o640/0o601 → ParamValidationError with ZERO FS touch
  row 3: symlinked config (read + write entry), dangling symlink (config +
         readCredentialBytes), symlinked-PARENT allowed at the retained
         lstat layer (documented R9.2 drop)
  row 4 (deterministic): unknown account/target ×5, duplicate add (plain
         ConfigError, not AccountInUseError), remove-referenced ±force,
         apply_session no-account, workspace XOR clear_workspace,
         workspace 0/-1/1.5 rejected + 2^53 accepted, malformed TOML,
         unknown account type, failing-op file byte-identical
  row 5: edge set — invalid names ""/"18.0"/"1.5"/"bad name"/"𝒳"/"[]"
         refused; "true"/"null" pattern-valid and accepted; invalid
         default_project members refused; NFC/NFD distinct + preserved
         VERBATIM through TOML; "𝒳" in header name + secret round-trip
  + FR-045 probes: adapter promotes first account only; manager never

npx vite-node throwaway/b8-n1/config-model-fuzz.ts
config-model-fuzz: runs 500 (>=500 budget) ops 2994 error-agreements 2220
divergences 0 seed 20260816
  (differential vs the B7 in-memory fake as mini-model; per-op error-class
  agreement + full observable-state agreement + REAL-side transaction
  atomicity (file byte-identical after every throwing op) + active-refs-
  existing-account and sorted-list invariants; model corrections F-N1-1/
  F-N1-2 above)

npx vite-node throwaway/b8-n1/io-fuzz.ts
io-fuzz: surfaceA(atomic-write) 500 examples, surfaceB(toml-round-trip) 500
examples, divergences 0, seed 20260816
  (A: random payload/mode round-trips vs in-memory map model, bytes + mode
  bits; B: random grapheme strings through setCustomHeader → fresh-manager
  getCustomHeader, verbatim)

§2.5 row 6 (org-ordering): executed at B8-MAPFIX (`throwaway/b8-mapfix`
RUN — fast-check 1000 + CPython differential 1000, 0 divergences); this
shard re-verified the Layer-3 lock only (9/9 above).

npm run check → GREEN (typecheck all workspaces, eslint 0 problems,
prettier clean, vitest full suite, browser smoke).
```

## Seam closure (§4.4 N1 rows)

- `config.*` → `createNodeConfigSource` (`packages/node/src/config-writes.ts`)
- `env` → `createNodeEnv` (`packages/node/src/env.ts`)
- `readSecretStdin` → `readCappedSecretFromStdin` (`packages/node/src/io-utils.ts`)
- `UNPORTED_FILE_READ_SEAM` → `nodeReadFile` (`packages/node/src/fs-seams.ts`)
- Downstream N2 imports BY NAME: `atomicWriteBytes`, `rejectIfSymlink`,
  `readCredentialBytes`/`readCredentialText`, `CredentialPathError` (R10.8).
