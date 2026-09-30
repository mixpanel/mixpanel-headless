"""Query builder and validator modules for the unified query system.

This subpackage contains translation and validation functions for the
query engines: show-clause builders for the bookmark JSON format, and
translators and validators for engines that don't use that format.

Modules:
    metric_builders: Typed metrics, formulas, funnel steps, and retention
        events → bookmark show clauses
    user_builders: Filter → engage selector string translation
    user_validators: Argument and parameter validation for query_user()
"""
