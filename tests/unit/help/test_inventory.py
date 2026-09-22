"""Unit tests for ``mixpanel_headless._internal.help.inventory``.

These tests lock the public-surface inventory that every other help module
builds on:

- the inventory is the deduplicated, sorted ``mixpanel_headless.__all__``
  and never comes from ``dir()``;
- every export classifies to exactly one ``HelpKind``, with the
  exported ``Literal`` aliases classified as ``literal`` and cross-checked
  against ``LITERAL_ALIAS_DOCS``;
- ``workspace_members()`` lists the public ``Workspace`` properties and
  methods;
- ``module_members()`` follows a namespace module's ``__all__``;
- the inventory is cached per process and ``clear_cache()`` resets it.
"""

from __future__ import annotations

import dataclasses
import enum
import types
import typing
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

import pytest
from pydantic import BaseModel

import mixpanel_headless as mp
from mixpanel_headless._internal.help.inventory import (
    Export,
    classify,
    clear_cache,
    export,
    exports_of_kind,
    inventory,
    inventory_names,
    module_members,
    workspace_members,
)
from mixpanel_headless._internal.help.models import HELP_KINDS, HelpKind
from mixpanel_headless._literal_types import LITERAL_ALIAS_DOCS
from mixpanel_headless.workspace import Workspace

# =============================================================================
# Fixtures and local classification samples
# =============================================================================


@pytest.fixture(autouse=True)
def _fresh_cache() -> typing.Iterator[None]:
    """Clear the inventory cache before and after every test.

    Yields:
        Nothing; the fixture only brackets the test with ``clear_cache()``.
    """
    clear_cache()
    yield
    clear_cache()


class _Color(enum.Enum):
    """Sample enum for classification tests."""

    RED = "red"


class _Model(BaseModel):
    """Sample Pydantic model for classification tests."""

    name: str


@dataclass
class _Point:
    """Sample dataclass for classification tests."""

    x: int


class _Plain:
    """Sample plain class for classification tests."""


class _Proto(Protocol):
    """Sample protocol for classification tests."""

    def run(self) -> None:
        """Protocol method."""


class _Boom(Exception):
    """Sample exception for classification tests."""


def _sample_function() -> None:
    """Sample function for classification tests."""


def _exported_literal_aliases() -> list[str]:
    """Return every ``__all__`` name whose runtime value is a ``typing.Literal``.

    Returns:
        Sorted list of export names.
    """
    return sorted(
        name
        for name in set(mp.__all__)
        if typing.get_origin(getattr(mp, name)) is typing.Literal
    )


def _public_workspace_properties() -> list[str]:
    """Return the public ``property`` names defined on ``Workspace``.

    Returns:
        Sorted property names.
    """
    return sorted(
        name
        for name, value in vars(Workspace).items()
        if not name.startswith("_") and isinstance(value, property)
    )


def _public_workspace_methods() -> list[str]:
    """Return the public callable names on ``Workspace`` that are not properties.

    Returns:
        Sorted method names.
    """
    properties = set(_public_workspace_properties())
    return sorted(
        name
        for name in dir(Workspace)
        if not name.startswith("_")
        and name not in properties
        and callable(getattr(Workspace, name))
    )


# =============================================================================
# Export record
# =============================================================================


class TestExport:
    """``Export`` is a frozen record whose identity ignores ``obj``."""

    def test_is_frozen(self) -> None:
        """Assigning a field raises ``FrozenInstanceError``."""
        row = Export(name="Filter", kind="dataclass", obj=mp.Filter)
        with pytest.raises(dataclasses.FrozenInstanceError):
            row.name = "Other"  # type: ignore[misc]

    def test_equality_ignores_obj(self) -> None:
        """Two rows with the same name and kind compare equal whatever ``obj`` is."""
        first = Export(name="Filter", kind="dataclass", obj=mp.Filter)
        second = Export(name="Filter", kind="dataclass", obj=object())
        assert first == second
        assert hash(first) == hash(second)

    def test_differs_on_name(self) -> None:
        """Rows with different names are not equal."""
        first = Export(name="Filter", kind="dataclass", obj=mp.Filter)
        second = Export(name="Cohort", kind="dataclass", obj=mp.Filter)
        assert first != second


# =============================================================================
# classify
# =============================================================================


class TestClassify:
    """``classify`` maps a runtime object to exactly one ``HelpKind``."""

    @pytest.mark.parametrize(
        ("obj", "expected"),
        [
            pytest.param(types, "module", id="module"),
            pytest.param(_Boom, "exception", id="exception"),
            pytest.param(KeyError, "exception", id="builtin-exception"),
            pytest.param(_Color, "enum", id="enum"),
            pytest.param(_Model, "model", id="model"),
            pytest.param(_Point, "dataclass", id="dataclass"),
            pytest.param(_Plain, "class", id="class"),
            pytest.param(_Proto, "class", id="protocol"),
            pytest.param(Literal["a", "b"], "literal", id="literal"),
            pytest.param(typing.Union[int, str], "alias", id="typing-union"),  # noqa: UP007
            pytest.param(int | str, "alias", id="pep604-union"),
            pytest.param(Annotated[int, "meta"], "alias", id="annotated"),
            pytest.param(_sample_function, "function", id="function"),
            pytest.param(len, "function", id="builtin"),
            pytest.param(_Plain.__init__, "function", id="wrapper-descriptor"),
            pytest.param(4096, "constant", id="int"),
            pytest.param("text", "constant", id="str"),
            pytest.param(1.5, "constant", id="float"),
            pytest.param(_Point(x=1), "constant", id="instance"),
        ],
    )
    def test_classifies(self, obj: object, expected: HelpKind) -> None:
        """Each sample object classifies to its expected kind.

        Args:
            obj: The object to classify.
            expected: The expected ``HelpKind``.
        """
        assert classify(obj) == expected

    def test_exception_wins_over_dataclass(self) -> None:
        """An exception that is also a dataclass classifies as ``exception``."""

        @dataclass
        class _DataError(Exception):
            """Exception with dataclass fields."""

            code: int = 0

        assert classify(_DataError) == "exception"


# =============================================================================
# inventory
# =============================================================================


class TestInventory:
    """``inventory()`` is the deduplicated, sorted ``__all__``."""

    def test_size_matches_unique_all(self) -> None:
        """One row per unique ``__all__`` name."""
        rows = inventory()
        assert len(rows) == len(set(mp.__all__))
        assert inventory_names() == tuple(sorted(set(mp.__all__)))

    def test_sorted_and_unique(self) -> None:
        """Rows are sorted by name and no name repeats."""
        names = [row.name for row in inventory()]
        assert names == sorted(names)
        assert len(names) == len(set(names))

    def test_objects_are_the_exports(self) -> None:
        """Every row holds the object bound to that name on the package."""
        for row in inventory():
            assert row.obj is getattr(mp, row.name)

    def test_every_kind_is_a_help_kind(self) -> None:
        """Every row carries a kind from ``HELP_KINDS``."""
        assert {row.kind for row in inventory()} <= set(HELP_KINDS)

    def test_no_private_names(self) -> None:
        """No row name starts with an underscore."""
        assert not [name for name in inventory_names() if name.startswith("_")]

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            pytest.param("Workspace", "class", id="Workspace"),
            pytest.param("Filter", "dataclass", id="Filter"),
            pytest.param("CreateCohortParams", "model", id="pydantic-model"),
            pytest.param("FeatureFlagStatus", "enum", id="enum"),
            pytest.param("HelpLookupError", "exception", id="exception"),
            pytest.param("MixpanelHeadlessError", "exception", id="base-exception"),
            pytest.param("Account", "alias", id="annotated-alias"),
            pytest.param("PropertySpec", "alias", id="union-alias"),
            pytest.param("BUSINESS_CONTEXT_MAX_CHARS", "constant", id="constant"),
            pytest.param("accounts", "module", id="module"),
            pytest.param("login_unified", "function", id="function"),
            pytest.param("MathType", "literal", id="literal"),
        ],
    )
    def test_known_exports(self, name: str, expected: HelpKind) -> None:
        """Named exports classify to their documented kinds.

        Args:
            name: Export name.
            expected: Expected ``HelpKind``.
        """
        row = export(name)
        assert row is not None
        assert row.kind == expected
        assert row.name == name

    def test_literal_aliases_match_literal_docs(self) -> None:
        """The ``literal`` rows are exactly the ``LITERAL_ALIAS_DOCS`` keys."""
        literals = [row.name for row in exports_of_kind("literal")]
        assert literals == _exported_literal_aliases()
        assert set(literals) == set(LITERAL_ALIAS_DOCS)
        assert len(literals) == 38

    def test_exports_of_kind_fixed_groups(self) -> None:
        """The small kind groups hold exactly the expected names."""
        assert [row.name for row in exports_of_kind("module")] == [
            "accounts",
            "reference",
            "session",
            "targets",
        ]
        assert [row.name for row in exports_of_kind("constant")] == [
            "BUSINESS_CONTEXT_MAX_CHARS"
        ]
        assert "Workspace" in [row.name for row in exports_of_kind("class")]

    def test_exports_of_kind_partitions_inventory(self) -> None:
        """Summing every kind group gives the whole inventory."""
        total = sum(len(exports_of_kind(kind)) for kind in HELP_KINDS)
        assert total == len(inventory())

    def test_exports_of_kind_unknown_kind_is_empty(self) -> None:
        """Kinds that never appear at the package root give an empty tuple."""
        assert exports_of_kind("overview") == ()
        assert exports_of_kind("parameter") == ()

    def test_export_miss_returns_none(self) -> None:
        """Unknown, private, and dotted names give ``None``."""
        assert export("NoSuchThing") is None
        assert export("_internal") is None
        assert export("Workspace.query") is None
        assert export("filter") is None


# =============================================================================
# workspace_members
# =============================================================================


class TestWorkspaceMembers:
    """``workspace_members()`` lists public ``Workspace`` properties and methods."""

    def test_composition(self) -> None:
        """Properties and methods match direct introspection of the class."""
        members = workspace_members()
        properties = [name for name, kind in members if kind == "property"]
        methods = [name for name, kind in members if kind == "method"]
        assert properties == _public_workspace_properties()
        assert methods == _public_workspace_methods()
        assert len(members) == len(properties) + len(methods)

    def test_counts(self) -> None:
        """``Workspace`` exposes 5 public properties and 209 public methods."""
        members = workspace_members()
        assert sum(1 for _, kind in members if kind == "property") == 5
        assert sum(1 for _, kind in members if kind == "method") == 209
        assert len(members) == 214

    def test_sorted_and_public(self) -> None:
        """Members are sorted by name and none is private."""
        names = [name for name, _ in workspace_members()]
        assert names == sorted(names)
        assert not [name for name in names if name.startswith("_")]

    def test_property_names(self) -> None:
        """The five properties are the session axes plus ``api``."""
        properties = {name for name, kind in workspace_members() if kind == "property"}
        assert properties == {"account", "api", "project", "session", "workspace"}

    def test_plain_data_attribute_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A public attribute that is neither callable nor a property is not a member.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
        """
        monkeypatch.setattr(Workspace, "HELP_TEST_CONSTANT", 1, raising=False)
        clear_cache()
        assert "HELP_TEST_CONSTANT" not in [name for name, _ in workspace_members()]


# =============================================================================
# module_members
# =============================================================================


class TestModuleMembers:
    """``module_members()`` follows ``__all__`` and falls back to public names."""

    @pytest.mark.parametrize("module_name", ["accounts", "session", "targets"])
    def test_namespace_modules_use_all(self, module_name: str) -> None:
        """Each namespace module lists exactly its sorted ``__all__``.

        Args:
            module_name: Export name of the namespace module.
        """
        module = getattr(mp, module_name)
        assert module_members(module) == tuple(sorted(set(module.__all__)))

    def test_fallback_to_public_dir(self) -> None:
        """A module without ``__all__`` lists its public attribute names."""
        module = types.ModuleType("fake_help_module")
        module.zeta = 1  # type: ignore[attr-defined]
        module.alpha = 2  # type: ignore[attr-defined]
        module._hidden = 3  # type: ignore[attr-defined]
        assert module_members(module) == ("alpha", "zeta")


# =============================================================================
# Cache
# =============================================================================


class TestCache:
    """The inventory is built once per process until ``clear_cache()``."""

    def test_same_object_until_cleared(self) -> None:
        """Repeated calls return the identical tuple; ``clear_cache`` rebuilds it."""
        first = inventory()
        assert inventory() is first
        assert workspace_members() is workspace_members()
        clear_cache()
        second = inventory()
        assert second is not first
        assert second == first

    def test_export_uses_cached_rows(self) -> None:
        """``export()`` returns the very row held in the cached tuple."""
        row = export("Filter")
        assert row is not None
        assert any(cached is row for cached in inventory())
