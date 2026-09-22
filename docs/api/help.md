# Built-in Help

`mixpanel_headless.help()` prints reference text for any public name. `mixpanel_headless.reference` returns the same information as structured, frozen dataclasses. Both work offline: no network call, no config file, no `Workspace`. See the [Built-in Help guide](../guide/built-in-help.md) for the query grammar, the three output formats, and the `mp help` CLI command.

```python
import mixpanel_headless as mp
from mixpanel_headless import reference as ref

mp.help("Workspace.query")                       # prints text, returns None
entry = ref.describe("Workspace.query_funnel")   # HelpEntry
hits = ref.search("retention")                   # SearchResult
print(ref.render(entry, "markdown"))
```

!!! warning "Import with an alias"
    `from mixpanel_headless import help` shadows the Python builtin in that namespace. Prefer `import mixpanel_headless as mp` and `mp.help(...)`.

## `mixpanel_headless.reference`

::: mixpanel_headless.reference
    options:
      show_root_heading: true
      show_root_toc_entry: true

## `HelpLookupError`

Raised by `describe()` on a miss and by `search()` for an empty term. Carries `query`, `suggestions`, and `hits`. The CLI maps it to exit code 4. Listed with the rest of the hierarchy under [Exceptions](exceptions.md#help-lookup-exceptions).

::: mixpanel_headless.HelpLookupError
    options:
      show_root_heading: true
      show_root_toc_entry: true
