# Feature Specification: Report Links

**Feature Branch**: `045-report-links`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "@context/report-links-plan.md" (Linear issues AIE-561 and AIE-562)

## Overview

A **report link** is a Mixpanel web URL that opens a report in the browser. This feature adds two capabilities to mixpanel-headless.

1. **Create a link.** A user turns a headless query into a shareable link to an unsaved Insights report. The link opens the same query in the Mixpanel report editor.
2. **Resolve a link.** A user turns a report link back into the query behind it. The user can then run that query through headless.

Both capabilities are available in the Python library and in the CLI. This follows the Library-First principle of the project constitution.

### Terms

- **Unsaved report**: a report that Mixpanel stores under a short server-issued identifier, but that does not appear in the saved-report list.
- **Slug**: the 12-character identifier of an unsaved report. It is the part after `#` in a link such as `https://mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw`. The slug is a lookup key on the Mixpanel server. It is not an encoded query, so no tool can decode it offline.
- **Saved report**: a report that a user saved in Mixpanel. It has a numeric report ID. Headless already exposes saved reports as bookmarks.
- **Shortlink**: a Mixpanel URL of the form `https://mixpanel.com/s/{code}`. The Mixpanel server redirects it to a full report link.
- **Query parameters**: the raw parameter document that describes a report. Headless already produces this document for Insights, Funnels, Retention, and Flows queries.
- **Legacy hash link**: an older link format where the part after `#` starts with `~(`. Mixpanel still opens these links in the browser.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Share a headless query as a report link (Priority: P1)

An internal agent, or an analyst who uses headless, builds a query in headless. The user wants a URL that a colleague can open in the Mixpanel web app. The colleague must see the same query in the report editor, with no manual rebuild.

**Why this priority**: This is the direct customer request in AIE-561. Without it, a headless result is a dead end for anyone who works in the web app.

**Independent Test**: Build query parameters for one event over the last 7 days. Create a link. Open the link in a browser. The Insights editor shows that event and that date range.

**Acceptance Scenarios**:

1. **Given** valid Insights query parameters, **When** the user creates a link, **Then** the result contains a URL, the slug, the report type, and the project ID.
2. **Given** a typed query result from a headless Insights, Funnels, Retention, or Flows query, **When** the user creates a link from that result, **Then** the system infers the report type from the result. The user does not pass the type.
3. **Given** the user passes a report type that contradicts the result type, **When** the user creates a link, **Then** the system rejects the call with a clear error before any network call.
4. **Given** the active session has a known workspace, **When** the user creates a link, **Then** the URL includes the workspace segment.
5. **Given** the session cannot resolve a workspace, **When** the user creates a link, **Then** the system emits a project-only URL. Link creation does not fail.
6. **Given** query parameters that fail schema validation, **When** the user creates a link, **Then** the system reports a validation error and makes no network call.
7. **Given** the user disables validation, **When** the user creates a link with unusual parameters, **Then** the system skips the local check and sends the parameters as given.
8. **Given** the CLI, **When** the user runs the link command with parameters from a flag, a file, or standard input, **Then** the command prints the link. A plain output format prints only the URL, so a shell can capture it.
9. **Given** the user opens the created URL in a browser, **When** the report editor loads, **Then** the editor shows the same report type and the same query.

---

### User Story 2 - Resolve a report link to its query and run it (Priority: P1)

A user receives a Mixpanel report link. The link points to an unsaved report or to a saved report. The user wants the query parameters behind the link, and the user wants to run that query through headless.

**Why this priority**: This is the direct customer request in AIE-562. Today the part after `#` is opaque to the customer.

**Independent Test**: Create a link with User Story 1. Resolve that link. The resolved parameters equal the parameters used at creation. Run the resolved query. The result is a normal headless query result.

**Acceptance Scenarios**:

1. **Given** a full link to an unsaved report in the active project and region, **When** the user resolves it, **Then** the result contains the report type, the query parameters, the project ID, the workspace ID when present, the slug, and a canonical URL.
2. **Given** only the bare 12-character slug, **When** the user resolves it, **Then** the system looks it up in the active project and region.
3. **Given** a link to a saved report, **When** the user resolves it, **Then** the result contains the saved report, its parameters, and its report type. The report type comes from the saved report, not from the URL.
4. **Given** an unsaved report that Mixpanel stored with a reference to a saved report, **When** the user resolves it, **Then** the result includes that saved report.
5. **Given** a resolved report, **When** the user runs it, **Then** the system runs the correct engine for the report type and returns the matching typed result.
6. **Given** a resolved Flows report, **When** the user runs it with no explicit mode, **Then** the system derives the mode from the parameters. When the parameters give no valid mode, the system uses the default Sankey mode.
7. **Given** a link string, **When** the user runs it in one call, **Then** the system resolves the link and then runs it. **Given** an already resolved report as input, the system does not fetch it a second time.
8. **Given** the CLI, **When** the user runs the resolve command with a link, **Then** the command prints the resolved report as structured output. With a run flag, the command prints the query result instead.
9. **Given** a link to a saved report that carries a trailing override segment, **When** the user resolves it, **Then** the system returns the base parameters and warns that the override segment is ignored.

---

### User Story 3 - Resolve a shortlink (Priority: P2)

A user receives a shortlink of the form `https://mixpanel.com/s/{code}`. The user wants the same resolution as in User Story 2.

**Why this priority**: Shortlinks are common in chat and email. They add one redirect step on top of User Story 2, so they depend on it.

**Independent Test**: Resolve a known shortlink with headless credentials. The result equals the result of a direct resolve of the target link.

**Acceptance Scenarios**:

1. **Given** a valid shortlink, **When** the user resolves it, **Then** the system follows one redirect to the full link and resolves that link. The result records both the input and the expanded URL.
2. **Given** a shortlink whose target is very long, **When** the Mixpanel server returns a page instead of a redirect, **Then** the system still extracts the target URL from that page.
3. **Given** a shortlink whose target is another shortlink, **When** the user resolves it, **Then** the system stops with a clear error. It does not loop.
4. **Given** a shortlink code that does not exist, **When** the user resolves it, **Then** the system reports a not-found error.
5. **Given** the credentials cannot see the shortlink, **When** the server redirects to a login page, **Then** the system reports an authentication error. It does not treat the login page as the target.

---

### User Story 4 - Add a link to existing CLI query output (Priority: P3)

A user already runs headless CLI query commands. The user wants those commands to include a web link in their output, on request.

**Why this priority**: This is a convenience on top of User Stories 1 and 2. It does not add a new capability, but it removes a second step for CLI users.

**Independent Test**: Run a saved-report query command with the link flag. The output contains a URL that opens that saved report in the browser.

**Acceptance Scenarios**:

1. **Given** the segmentation command with a single event, dates, a unit, and an optional bare breakdown property, **When** the user adds the link flag, **Then** the output includes a URL to an unsaved Insights report with the same event, dates, unit, and breakdown.
2. **Given** the segmentation command with a filter expression or a complex breakdown, **When** the user adds the link flag, **Then** the command prints a warning on the error stream and omits the link. The query itself still succeeds.
3. **Given** link creation fails for any reason, **When** the segmentation command runs with the link flag, **Then** the command prints a warning on the error stream. The query result still prints and the exit code is success.
4. **Given** the saved-report, funnel, or flows query commands, **When** the user adds the link flag, **Then** the output includes a URL to that saved report. This link needs no network call.
5. **Given** the link flag is absent, **When** any of these commands runs, **Then** the output is unchanged from today.

---

### User Story 5 - Build a link to a saved report without a network call (Priority: P3)

A user knows a saved report ID and its type. The user wants the web URL for it.

**Why this priority**: This is a small, pure helper. User Story 4 depends on it.

**Independent Test**: Ask for the link to saved report 123 of type Insights. The URL has the correct host for the session region, the project ID, and the saved-report hash form.

**Acceptance Scenarios**:

1. **Given** a saved report ID and a report type, **When** the user requests the link, **Then** the system returns a URL with the correct region host, the project ID, and the correct hash form for that type.
2. **Given** an explicit workspace ID, **When** the user requests the link, **Then** the URL includes that workspace. Otherwise the URL uses the session workspace when one is pinned, else a project-only path.

---

### Edge Cases

- **Legacy hash link.** The system recognizes the link but cannot decode it. Resolution fails with an error that tells the user to open the link in a browser and copy the new URL. The browser re-issues a slug on load.
- **Dashboard link.** The system recognizes it as a dashboard link. Resolution fails with a clear unsupported error. A dashboard link that also carries an edited-report slug resolves that slug.
- **Launch-analysis report link.** Resolution returns the saved report, but a run request fails with an unsupported-type error.
- **Project mismatch.** The link names a project other than the active one. The system fails before any network call. The error names both projects and states how to switch projects.
- **Region mismatch.** The link host belongs to a region other than the active session region. The system fails before any network call with a clear error.
- **Unknown slug.** The Mixpanel server returns not found. The error states that a slug is readable only in the project and region that created it.
- **Unknown saved report.** The error is a not-found error.
- **Empty hash.** A report URL with no part after `#` is a parse error.
- **Non-Mixpanel host.** A URL on another host, or on the Mixpanel API host, is a parse error.
- **Unrecognized path or hash.** A Mixpanel URL that is not a report link is a parse error. The error names which part was not recognized.
- **Decorated input.** Surrounding whitespace, a trailing slash before `#`, a query string, an upper-case host, a missing scheme, or a percent-encoded `#` do not change the parse result.
- **Legacy path form.** Older Mixpanel paths that start with `/report/{project}/` parse the same as the current paths.
- **Alternate domain.** A link on `mixpanel.org` parses as the US region. Created links always use the `mixpanel.com` hosts.
- **Overrides on an unsaved report.** The resolved result exposes the stored overrides as data. The system does not merge them into the parameters.
- **Credentials.** The credential header never appears in logs or error output.

## Requirements *(mandatory)*

### Functional Requirements

**Link creation**

- **FR-001**: The system MUST create a link to an unsaved report from query parameters for the Insights, Funnels, Retention, and Flows report types.
- **FR-002**: The system MUST accept a typed headless query result as input and MUST infer the report type from it.
- **FR-003**: The system MUST reject an explicit report type that contradicts the inferred type, before any network call.
- **FR-004**: The system MUST validate query parameters against the report-type schema before it stores the unsaved report. The user MUST be able to skip this validation.
- **FR-005**: The system MUST generate the slug locally, with 12 characters drawn from the Mixpanel slug alphabet.
- **FR-006**: The system MUST store the unsaved report in the active project, with the slug, the report type, the parameters, and the optional name, description, and saved-report reference.
- **FR-007**: The system MUST return the URL, the slug, the report type, the project ID, the workspace ID when known, and the name and description.
- **FR-008**: The system MUST choose the workspace for the URL in this order: an explicit workspace argument, then the pinned session workspace, then a resolved workspace. When no workspace can be resolved, the URL MUST omit the workspace segment.
- **FR-009**: The created URL MUST use the host for the session region and MUST point to an app path under which the Mixpanel report editor opens that report type. The app path per type MUST be held in one table so a change is one line.
- **FR-010**: The system MUST build the URL for a saved report from its ID and type, with no network call.

**Link parsing**

- **FR-011**: The system MUST parse every recognizable Mixpanel report link into its parts: kind, host, region, project ID, workspace ID, app, report type hint, slug, saved-report ID, dashboard ID, shortlink code, title segment, and override segment.
- **FR-012**: The parser MUST recognize these kinds: unsaved-report slug, saved report, shortlink, dashboard, and legacy hash. A bare 12-character slug MUST parse as a slug.
- **FR-013**: The parser MUST normalize decorated input, as listed in Edge Cases, before it parses.
- **FR-014**: The parser MUST reject input it cannot recognize with a parse error. The error MUST state whether the host, the path, or the hash was the problem, or whether the hash was empty.
- **FR-015**: The parser MUST never fail with any error other than a parse error, for any input string.

**Link resolution**

- **FR-016**: The system MUST resolve a full link, a bare slug, or a shortlink to its report type and query parameters.
- **FR-017**: The system MUST follow a shortlink exactly once. A shortlink that targets another shortlink MUST fail with a clear error.
- **FR-018**: The system MUST extract the shortlink target from a redirect response, or from the page the server returns for very long targets.
- **FR-019**: The system MUST treat a shortlink redirect to a login page as an authentication error.
- **FR-020**: The system MUST check the link region against the session region, and the link project against the active project, before any network call. A mismatch MUST fail with an error that names both values and states how to switch.
- **FR-021**: The system MUST NOT apply the project and region checks to a bare slug, because a bare slug carries neither.
- **FR-022**: The system MUST reject dashboard links and legacy hash links with an unsupported error. The legacy-hash error MUST tell the user to open the link in a browser and copy the re-issued URL.
- **FR-023**: For a saved-report link, the report type in the result MUST come from the saved report itself, not from the URL.
- **FR-024**: For an unsaved-report link, the report type MUST come from the stored record, not from the URL.
- **FR-025**: The resolved result MUST contain: the source kind, the report type, the parameters, the project ID, the workspace ID when known, the region, a canonical rebuilt URL, the original input, the expanded shortlink target when present, the slug or saved-report ID, the saved report when present, the name, the description, and any stored overrides.
- **FR-026**: When a saved-report link carries an override segment, the system MUST return the base parameters and MUST warn that the override segment is ignored.
- **FR-027**: A not-found response for a slug, a saved report, or a shortlink MUST surface as a not-found error with a message that names the missing item and its scope.

**Run**

- **FR-028**: The system MUST run a resolved report through the engine that matches its report type and MUST return the matching typed result.
- **FR-029**: The system MUST accept either a link string or an already resolved report as input to a run. An already resolved report MUST NOT trigger a second fetch.
- **FR-030**: For a Flows report with no explicit mode, the system MUST derive the mode from the parameters when they hold a valid mode, else use Sankey.
- **FR-031**: A run request for a launch-analysis report MUST fail with an unsupported-type error.

**CLI**

- **FR-032**: The CLI MUST provide a command that creates a link from parameters given by a flag, a file, or standard input. It MUST support type, name, description, workspace, saved-report reference, and a no-validate switch.
- **FR-033**: The CLI link command MUST print only the URL in plain output format.
- **FR-034**: The CLI MUST provide a command that resolves a link and prints the resolved report as structured output. A run flag MUST run the report and print the query result instead. A mode option MUST apply to Flows.
- **FR-035**: The CLI segmentation, funnel, saved-report, and flows query commands MUST accept an opt-in link flag that adds a URL to the output. The flag MUST default to off.
- **FR-036**: The segmentation link MUST reproduce the event, the dates, the unit, and a bare breakdown property. When a filter or a complex breakdown is present, the command MUST warn on the error stream and omit the link. A bare breakdown property is a value with no filter-expression token; the CLI contract lists the tokens.
- **FR-037**: A link failure inside a query command MUST never fail the query. The command MUST warn on the error stream and exit with success.
- **FR-038**: CLI exit codes MUST follow the project convention: not-found errors exit 4; parse, unsupported, scope-mismatch, and parameter-validation errors exit 3; authentication errors exit 2; shortlink extraction errors exit 1. Error output MUST include the hint when one exists.
- **FR-039**: Local CLI input errors, such as invalid JSON or two conflicting parameter sources, MUST exit 3.

**Errors and security**

- **FR-040**: The system MUST expose a dedicated error family for report links, with one machine-readable code per failure kind, and MUST carry the parsed link parts in the error details.
- **FR-041**: The system MUST never log or print the credential header or any credential value.

### Key Entities

- **Report Link**: The result of link creation. It holds the URL, the slug, the report type, the project ID, the workspace ID when known, the name, the description, an optional saved-report reference, and a creation time.
- **Unsaved Report Record**: What Mixpanel stores under a slug. It holds the slug, the report type, the parameters, the name, the description, the stored overrides, the project ID, the creator, the creation time, and an optional embedded saved report.
- **Parsed Link**: The structured parts of a link string, as listed in FR-011. It is pure data with no network state.
- **Resolved Report**: The result of link resolution, as listed in FR-025. It is the input to a run.
- **Saved Report**: An existing headless entity. It has a numeric ID, a report type, and parameters.
- **Shortlink**: A short code that the Mixpanel server maps to a full link. Headless reads shortlinks. Headless does not create them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For each of the four report types, a user creates a link from headless query parameters, opens it in a browser, and sees the same report type and query. Success rate is 100 percent in the live test.
- **SC-002**: For every valid parameter document, a resolve of the created link returns parameters equal to the input and the same report type. The round trip holds for 100 percent of the live and unit test cases.
- **SC-003**: A user with a link and no other knowledge obtains the runnable query in one library call or one CLI command.
- **SC-004**: Every link in the URL grammar table parses to the documented kind and fields. Every decorated variant of the same link parses to the same result.
- **SC-005**: No input string causes the parser to fail with anything other than a parse error.
- **SC-006**: Every project mismatch, region mismatch, dashboard link, and legacy hash link fails with a specific, actionable message and makes zero network calls.
- **SC-007**: Every error case in Edge Cases maps to a documented exit code and machine-readable code.
- **SC-008**: Link creation adds no more than one network round trip to a query workflow. Saved-report links add zero.
- **SC-009**: The link flag on existing query commands never changes the exit code of a successful query, even when link creation fails.
- **SC-010**: The pure parse-and-build module reaches a mutation score of at least 80 percent, and total project coverage stays at or above 90 percent.
- **SC-011**: The credentials of the caller never appear in any log line, error message, or CLI output during the feature tests.

## Assumptions

- **Slug storage is server-side.** Mixpanel stores unsaved reports per project and per region under a slug. A slug is readable only in the project and region that created it. This was verified against the Mixpanel web app source on 2026-09-02.
- **Headless credentials can read and write unsaved reports and can read shortlinks.** Service-account and both OAuth account types are expected to work. The live test confirms this for each account type.
- **App segment per type.** The initial table follows the Mixpanel MCP server convention: Insights, Funnels, and Retention slugs open under the Insights app path, Flows under the Flows app path. Live QA (quickstart Part 3) confirms this. If the editor does not switch type, the table changes to one app per type. Either outcome satisfies FR-009.
- **Raw parameters are the resolve output.** A typed decompile of parameters into headless metric, filter, and breakdown objects is a separate follow-up feature. The reason is coverage risk, because the comparable SQL decompiler round-trips only about one third of real reports.
- **Overrides are data only.** Stored overrides on an unsaved report surface on the resolved result. The system does not merge them into the parameters in this version.
- **Segmentation link is an approximation.** The legacy segmentation engine and the Insights engine can differ at the edges. The link reproduces the same event, dates, unit, and breakdown. The user documentation states this.
- **Retention link flag is out of scope.** The legacy retention options do not map cleanly onto Insights retention buckets.
- **Existing components are reused.** Parameter builders, parameter schema validation, the saved-report reader, the live query engines, the session resolver, and the existing Mixpanel API access layer already exist and are the basis of this feature.

## Out of Scope

- Typed decompile of parameters into headless query objects.
- Decode of legacy hash links.
- Creation of shortlinks. The Mixpanel server allows this only from a browser session.
- The link flag on the retention command and on the other legacy query commands.
- Merge of stored overrides into parameters.
- Any change to how saved reports are created or edited.
