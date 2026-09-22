# Copilot Instructions for mixpanel_headless

> Python library + CLI for Mixpanel analytics: discovery, live queries, streaming, and entity management.

`CLAUDE.md` at the repo root is the source of truth for conventions, architecture, and environment variables. This file is a short summary; where they disagree, `CLAUDE.md` wins.

## Quick Reference (Start Here)

```bash
# Setup (REQUIRED first)
uv sync --all-extras

# Verify changes — `just check` runs everything below plus docstring coverage and the build
just check

# Or individually
uv run ruff format src/ tests/                    # Format code
uv run ruff check src/ tests/                     # Lint code
uv run mypy src/ tests/                           # Type check
uv run pytest                                     # Run tests

# Run specific test
uv run pytest -k test_name

# Tests with coverage (must be ≥90%)
uv run pytest --cov=src/mixpanel_headless --cov-fail-under=90
```

## Tech Stack

- **Language**: Python 3.10+
- **CLI**: Typer + Rich
- **Validation**: Pydantic v2
- **HTTP**: httpx
- **Testing**: pytest, Hypothesis, mutmut, ruff, mypy, interrogate

## Project Structure

```
src/mixpanel_headless/
├── workspace.py        # Workspace facade (entry point for library)
├── auth_types.py       # Public auth surface (Account union, Session, Region, OAuthTokens, …)
├── accounts.py         # mp.accounts — add/list/use/login/test/…
├── session.py          # mp.session — show/use the persisted [active] block
├── targets.py          # mp.targets — saved (account, project, workspace?) cursors
├── exceptions.py       # Exception hierarchy
├── types.py            # Result types (frozen dataclasses)
├── reference.py        # Built-in API help (mp.help)
├── _internal/          # PRIVATE: never expose in public signatures
│   ├── config.py       # ConfigManager (TOML-backed)
│   ├── api_client.py   # MixpanelAPIClient
│   ├── auth/           # Account types, session resolver, OAuth flow, bridge file
│   ├── query/          # Query builders and validators
│   ├── replays/        # Session-replay analyzer (vendored rrweb)
│   └── services/       # Discovery, LiveQuery, Replays services
└── cli/
    ├── main.py         # Typer entry point + global flags (-a / -p / -w / -t)
    └── commands/       # account, project, workspace, target, session, query, inspect, entity CRUD, …

tests/
├── unit/              # Isolated tests (mocked deps)
├── integration/       # Component interaction tests
└── pbt/               # Property-based tests (Hypothesis)
```

## Architecture

```
CLI (Typer) → Public API (Workspace) → Services → Infrastructure (Config, API)
```

**Layer rules:**
- CLI never imports or constructs `MixpanelAPIClient`; API calls go through `Workspace`. CLI modules may use `_internal` config, auth, and helper modules (e.g., `ConfigManager`, the session resolver).
- Services call infrastructure only (no horizontal service calls)

## Code Requirements

### Types (STRICT)
- All code passes `mypy --strict`
- No `Any` without justification
- Use `X | None` (not `Optional[X]`)
- Use `Literal` for constrained strings

### Docstrings (REQUIRED)
Every class, method, and function has a docstring, including private helpers and tests (checked by interrogate in CI: every definition in `src/` and `conformance/`, 95% of `tests/`). Sections depend on the function (Google style):
- Summary: always
- Args: when it takes parameters (no types — those are in the annotations)
- Returns: when it returns a non-`None` value
- Raises: exceptions it raises deliberately
- Example: where behavior isn't obvious; use fenced code blocks, not `>>>`
- Tests and fixtures: a one-line summary of what the test proves, matching the file's convention

See the "Documentation (STRICT)" section of `CLAUDE.md` for the full rule.

### Testing (TDD)
- Write test FIRST, then implement
- Unit tests: `tests/unit/`
- Integration tests: `tests/integration/`
- Property-based tests: `*_pbt.py`
- Coverage minimum: 90%

### Patterns
- `frozen=True` on all dataclasses
- `model_config = ConfigDict(frozen=True)` on Pydantic models
- Use `Iterator[T]` not `list[T]` for streaming data
- Use `field(default_factory=list)` not `[]` for defaults

## Exceptions

Use the library hierarchy in `exceptions.py`, never bare `Exception`. Common classes:

- `MixpanelHeadlessError` (base)
- `ConfigError` → `AccountNotFoundError`, `AccountExistsError`, `AccountInUseError`, `ProjectNotFoundError`, `InvalidArgumentError`
- `APIError` → `AuthenticationError`, `RateLimitError`, `QueryError`, `ServerError`, `SessionReplayError`
- `OAuthError` → `RegionProbeError`
- `WorkspaceScopeError`, `ParamValidationError`, `BookmarkValidationError`, `ReportLinkError`, `HelpLookupError`

**Always chain:** `raise XError(...) from e`

## Security: Credentials

**NEVER expose secrets:**
- Account secrets and tokens are `SecretStr`; call `.get_secret_value()` only where the raw value is sent
- Don't interpolate secrets in f-strings
- Don't log accounts, sessions, or tokens in a way that bypasses their redacting `__repr__`

## Configuration

- Config file (TOML): `~/.mp/config.toml` (override with `MP_CONFIG_PATH`)
- Multiple named accounts (`service_account`, `oauth_browser`, `oauth_token`) with an `[active]` session block
- Environment variables override config (full table in `CLAUDE.md`):
  - `MP_USERNAME` + `MP_SECRET` (service account) or `MP_OAUTH_TOKEN` (static bearer)
  - `MP_PROJECT_ID`, `MP_REGION`, `MP_WORKSPACE_ID`
  - `MP_AUTH_FILE`, `MP_CONFIG_PATH`
  - `MP_API_BASE_URL`, `MP_APP_BASE_URL`

## Agent Task Guidelines

### Adding a Feature
1. Check `context/` for design specs
2. Write test in `tests/unit/` first
3. Implement minimal code to pass
4. Run all checks: `just check`

### Fixing a Bug
1. Write failing test reproducing bug
2. Fix implementation
3. Run all checks: `just check`

### Adding CLI Command
1. Add to `src/mixpanel_headless/cli/commands/`
2. Register in `main.py`
3. Follow existing patterns (formatters, error handling)

### Modifying Public API
1. Edit `workspace.py` or `auth_types.py`
2. Update `__init__.py` exports if needed
3. Never expose `_internal` types in signatures

## DO NOT

- Expose `_internal` types in public signatures
- Use `except Exception:` (use `MixpanelHeadlessError`)
- Use mutable defaults (`list` → `field(default_factory=list)`)
- Skip type annotations
- Skip docstrings
- Commit without running all checks
