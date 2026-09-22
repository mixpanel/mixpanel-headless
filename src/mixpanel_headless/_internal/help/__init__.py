"""Built-in API reference help.

Private implementation behind :mod:`mixpanel_headless.reference` and
:func:`mixpanel_headless.help`. Modules in this package introspect the
installed library offline: they perform no network calls, read no config
file, and never construct a :class:`~mixpanel_headless.Workspace`.

Modules:
    models: Frozen result dataclasses (``HelpEntry``, ``SearchResult``, ...).
    docstrings: Google-style docstring parser.
    inventory: Public-surface inventory built from ``__all__``.
    registry: ``WORKSPACE_DOMAINS`` and ``REFERENCE_HINTS`` tables.
    resolve: Query-string and object resolution to inventory targets.
    introspect: Signature, field, and class-section extraction.
    relations: ``used_by``, ``referenced_types``, ``see_also``, exception tree.
    search: Case-insensitive substring search over the inventory.
    hints: Hosted-docs hint selection.
    render: Pure renderers (text, markdown, json).
"""
