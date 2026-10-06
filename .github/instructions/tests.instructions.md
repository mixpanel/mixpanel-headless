---
applyTo: "tests/**"
---
# Tests

- Follow the conventions of the file you edit. A one-line summary docstring
  is enough when the neighboring tests use one. Every new test, fixture, or
  helper needs at least that one line. The interrogate gate for `tests/` is
  an aggregate (95%), so it does not catch one undocumented definition.
- A test must fail when the behavior it covers breaks. An assertion that
  stays true when the code is wrong is a defect.
- Isolation: tests not marked live never read or write the real `~/.mp`
  folder, the real auth bridge file, or real `MP_*` variables. The autouse
  fixture `_clean_mp_env` in `tests/conftest.py` scrubs every variable in
  `_MP_ENV_VARS`. A new `MP_*` variable that production code reads must go
  into that list.
- Tests not marked live make no real HTTP requests. Use
  `httpx.MockTransport`, for example through the `mock_client_factory`
  fixture.
- Tests marked `@pytest.mark.live` (in `tests/live/` and a few files in
  `tests/integration/`) call the real Mixpanel API on purpose. The default
  pytest options deselect them. Never run them in a review session.
- Property-based tests use Hypothesis, in files with a `_pbt` suffix.

Greptile rules for this area: `test-isolation`, `no-live-network`,
`test-docstring-presence`.
