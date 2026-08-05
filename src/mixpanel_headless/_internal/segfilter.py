"""Filter-to-segfilter conversion for flows step filters.

The conversion itself lives on the filter models — see
``AbstractFilter._dump_segfilter`` and the ``_segfilter_operand`` overrides
in ``mixpanel_headless.types``. A filter knows its own operand shape, so
rendering it there removes the operator frozensets this module used to keep
in parallel with the model split.

Example:
    ```python
    from mixpanel_headless import FilterFactory
    from mixpanel_headless._internal.segfilter import build_segfilter_entry

    f = FilterFactory.equals("country", "US")
    entry = build_segfilter_entry(f)
    # {
    #     "property": {"name": "country", "source": "properties", "type": "string"},
    #     "type": "string",
    #     "selected_property_type": "string",
    #     "filter": {"operator": "==", "operand": ["US"]},
    # }
    ```
"""

from __future__ import annotations

from typing import Any

from mixpanel_headless.types import (
    DATETIME_OPERATOR_MAP as DATETIME_OPERATOR_MAP,
)
from mixpanel_headless.types import (
    NUMBER_OPERATOR_MAP as NUMBER_OPERATOR_MAP,
)
from mixpanel_headless.types import (
    RESOURCE_TYPE_MAP as RESOURCE_TYPE_MAP,
)
from mixpanel_headless.types import (
    STRING_OPERATOR_MAP as STRING_OPERATOR_MAP,
)
from mixpanel_headless.types import (
    AbstractFilter,
)
from mixpanel_headless.types import (
    _convert_date_format as _convert_date_format,
)


def build_segfilter_entry(f: AbstractFilter) -> dict[str, Any]:
    """Convert a Filter to segfilter format for flows step filters.

    Args:
        f: A ``Filter`` instance created via one of the
            :class:`~mixpanel_headless.types.FilterFactory` constructors
            (e.g. ``FilterFactory.equals()``).

    Returns:
        A dict with the segfilter structure:

        - ``property``: dict with ``name``, ``source``, ``type``
        - ``type``: property type string
        - ``selected_property_type``: property type string (same as ``type``)
        - ``filter``: dict with ``operator``/``operand`` (and optionally ``unit``)

    Raises:
        ValueError: If the filter's property type or operator has no
            segfilter form.

    Example:
        ```python
        f = FilterFactory.equals("country", "US")
        entry = build_segfilter_entry(f)
        assert entry["filter"]["operator"] == "=="
        assert entry["filter"]["operand"] == ["US"]
        ```
    """
    return f.mixpanel_model_dump("segfilter")
