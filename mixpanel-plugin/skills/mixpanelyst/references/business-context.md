# Business context: read, write, audit, and seed

This file covers business context: the markdown documentation that grounds AI assistants in an organization's structure and goals. It gives the scopes, the size limit, the common workflows, and the permissions.

Look up the methods with `mp help Workspace --domain "business context"` and the result type with `mp help BusinessContext`.

## Scopes and limits

- There are two scopes. `level="organization"` is shared across the whole organization. `level="project"` (the default) is per project.
- The limit is 50,000 characters (`mp.BUSINESS_CONTEXT_MAX_CHARS`). The library checks it before the HTTP call and raises `BusinessContextValidationError`. Use this to detect oversize input without a wasted request.
- Organization-level calls resolve `organization_id` from the cached `/me` response. Pass `organization_id=N` to override. If the ID cannot be resolved, the call raises `WorkspaceScopeError`.
- A write replaces the whole content. Pass `""` to clear, or use `clear_business_context()` for clarity.

```python
import mixpanel_headless as mp

ws = mp.Workspace()

# Read one scope, or both in one request.
project_ctx = ws.get_business_context(level="project")
chain = ws.get_business_context_chain()
print(chain.organization.content)
print(chain.project.content)

print(f"{project_ctx.character_count}/{mp.BUSINESS_CONTEXT_MAX_CHARS} chars; "
      f"empty={project_ctx.is_empty}")

# Write (full replace) and clear.
ws.set_business_context("# About Acme\n...", level="project")
ws.clear_business_context(level="project")
```

Writes change what AI assistants see for every user of the project or organization. Confirm with the user before you write or clear.

## Workflows

- **"What is the business context for this project or organization?"** Call `ws.get_business_context_chain()`. One request returns both scopes.
- **Keep the project context in version control as a `.md` file.** In CI, run `ws.set_business_context(Path("ctx.md").read_text(), level="project")`.
- **"Which projects have AI context configured?"** Iterate over `ws.projects()`. For each project, call `ws.use(project=project.id)`, then `ws.get_business_context(level="project")`, and check `.is_empty`.
- **Seed a new project from the organization default.** Read the chain, then copy the organization content to the project:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
chain = ws.get_business_context_chain()
ws.set_business_context(chain.organization.content, level="project")
```

## Permissions

- A project-scope read needs any access to the project.
- A project-scope write needs `edit_project_info` on the project.
- An organization-scope write needs `edit_project_info` at the organization level. This usually means an OAuth login, not a service account.
- A missing permission returns HTTP 403, which the library raises as `QueryError`.
