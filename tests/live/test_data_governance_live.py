# ruff: noqa: S101, S603, S607
"""Live QA tests for Data Governance CRUD — Phase 027.

Exercises the full stack against the real Mixpanel API. All created
objects are prefixed ``QA-027-`` and cleaned up after tests.

Usage (set ``MP_LIVE_ACCOUNT=<account> MP_LIVE_WRITE_PROJECT=<project id>``):
    uv run pytest tests/live/test_data_governance_live.py -v -m live
    uv run pytest tests/live/test_data_governance_live.py -v -m live -k Tags
    uv run pytest tests/live/test_data_governance_live.py -v -m live -k DropFilters
    uv run pytest tests/live/test_data_governance_live.py -v -m live -k CustomProperties
    uv run pytest tests/live/test_data_governance_live.py -v -m live -k LookupTables
    uv run pytest tests/live/test_data_governance_live.py -v -m live -k CustomEvents
    uv run pytest tests/live/test_data_governance_live.py -v -m live -k EdgeCases

Environment:
    - ``MP_LIVE_ACCOUNT`` — the configured account to run as. Every test
      skips when it is unset; the suite never uses the default session.
    - ``MP_LIVE_WRITE_PROJECT`` — the project id this suite may write to.
      Every test skips unless it is set and the account resolves to that
      project. The ``mp`` CLI calls pass both as global flags.

Constraints:
    - Never modifies pre-existing non-QA objects permanently. The Lexicon
      update tests change one existing event and one existing event
      property, and put back the values they read. They use definitions
      that are not Mixpanel built-ins: for a built-in (for example
      ``$session_start``) the read API returns the built-in text, not the
      stored custom text, so writing back what was read would replace the
      stored text. They read back the exact row (name and resource type),
      because a name lookup can return several rows.
    - All QA objects named ``QA-027-*``
    - Cleanup guaranteed via fixtures with finalizers
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from mixpanel_headless import Workspace
from mixpanel_headless.exceptions import QueryError
from mixpanel_headless.types import (
    BulkEventUpdate,
    BulkPropertyUpdate,
    BulkUpdateEventsParams,
    BulkUpdatePropertiesParams,
    ComposedPropertyValue,
    CreateCustomPropertyParams,
    CreateDropFilterParams,
    CreateTagParams,
    CustomProperty,
    DropFilter,
    DropFilterLimitsResponse,
    EventDefinition,
    LexiconTag,
    LookupTable,
    LookupTableUploadUrl,
    PropertyDefinition,
    UpdateCustomPropertyParams,
    UpdateDropFilterParams,
    UpdateEventDefinitionParams,
    UpdatePropertyDefinitionParams,
    UpdateTagParams,
    UploadLookupTableParams,
)
from tests.live._live_settings import (
    live_cli_command,
    live_cli_env,
    live_workspace,
    requires_live_account,
    requires_write_project,
)

# All tests require the `live` marker, MP_LIVE_ACCOUNT, and
# MP_LIVE_WRITE_PROJECT — skipped by default
pytestmark = [pytest.mark.live, requires_live_account, requires_write_project]

QA_PREFIX = "QA-027-"


def _unique_name(label: str) -> str:
    """Generate a unique QA object name.

    Args:
        label: Human-readable label for the test.

    Returns:
        Unique name with QA prefix and short UUID suffix.
    """
    short = uuid.uuid4().hex[:8]
    return f"{QA_PREFIX}{label}-{short}"


def _mp(*args: str) -> subprocess.CompletedProcess[str]:
    """Run an ``mp`` CLI command on the live account and write project.

    Args:
        *args: CLI arguments after the global ``--account`` and
            ``--project`` flags.

    Returns:
        Completed process with captured stdout and stderr.
    """
    return subprocess.run(
        live_cli_command(*args),
        capture_output=True,
        text=True,
        timeout=60,
        env=live_cli_env(),
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def ws() -> Workspace:
    """Create the Workspace on the ``MP_LIVE_ACCOUNT`` account.

    Returns:
        Workspace on ``MP_LIVE_WRITE_PROJECT``; the test skips when a
        setting is missing or the account resolves to another project.
    """
    return live_workspace(write=True)


def _is_builtin(definition: EventDefinition | PropertyDefinition) -> bool:
    """Return whether a Lexicon definition is a Mixpanel built-in.

    For a built-in, the read API returns the built-in text instead of the
    stored custom text, so its read values cannot be written back.

    Args:
        definition: An event or property definition as the API returned it.

    Returns:
        ``True`` when the response marks it ``isMixpanelDefinition``.
    """
    return bool((definition.model_extra or {}).get("isMixpanelDefinition"))


def _event_row(ws: Workspace, name: str) -> EventDefinition:
    """Read the definition row of exactly one event.

    Args:
        ws: Workspace fixture.
        name: The event name.

    Returns:
        The row whose name equals ``name``.
    """
    rows = [d for d in ws.get_event_definitions(names=[name]) if d.name == name]
    assert len(rows) == 1, f"expected one definition row for {name!r}, got {rows}"
    return rows[0]


def _event_property_row(ws: Workspace, name: str) -> PropertyDefinition:
    """Read the definition row of exactly one event property.

    A name lookup can return several rows (other resource types and names),
    so the row must match the name and the ``event`` resource type.

    Args:
        ws: Workspace fixture.
        name: The event property name.

    Returns:
        The row whose name equals ``name`` and whose resource type is event.
    """
    rows = [
        d
        for d in ws.get_property_definitions(names=[name], resource_type="event")
        if d.name == name and (d.resource_type or "").lower() == "event"
    ]
    assert len(rows) == 1, f"expected one event property row for {name!r}, got {rows}"
    return rows[0]


_LOOKUP_BATCH = 50
"""Names per Lexicon definition lookup while searching for a candidate."""


def _batches(names: list[str]) -> Iterator[list[str]]:
    """Split names into lookup batches of at most :data:`_LOOKUP_BATCH`.

    Args:
        names: The names to look up.

    Yields:
        Consecutive slices of ``names``.
    """
    for start in range(0, len(names), _LOOKUP_BATCH):
        yield names[start : start + _LOOKUP_BATCH]


def _restore(step: str, restore: Callable[[], object]) -> None:
    """Run one restore step; any failure fails the test with its error text.

    A restore puts back a value that the test changed on an existing
    definition, so a silent failure would leave the project changed.

    Args:
        step: What the step restores, for the failure message.
        restore: The call that writes the old value back.
    """
    try:
        restore()
    except Exception as exc:  # noqa: BLE001 - every failure must fail the test
        pytest.fail(f"restore failed ({step}): {type(exc).__name__}: {exc}")


@pytest.fixture(scope="module")
def custom_event(ws: Workspace) -> str:
    """Name an event of the project whose definition is not a Mixpanel built-in.

    The Lexicon update tests change this event and put its values back.

    Args:
        ws: Workspace fixture.

    Returns:
        The event name. The test skips when the project has none.
    """
    names = [e for e in ws.events() if not e.startswith("$")]
    for batch in _batches(names):
        for definition in ws.get_event_definitions(names=batch):
            if definition.name in batch and not _is_builtin(definition):
                return definition.name
    pytest.skip("no event definition that is not a Mixpanel built-in")


@pytest.fixture(scope="module")
def custom_event_property(ws: Workspace, custom_event: str) -> str:
    """Name an event property whose definition is not a Mixpanel built-in.

    The Lexicon update test changes this property and puts its values back.

    Args:
        ws: Workspace fixture.
        custom_event: An event whose properties are searched.

    Returns:
        The property name. The test skips when none qualifies.
    """
    names = [p for p in ws.properties(custom_event) if not p.startswith("$")]
    for batch in _batches(names):
        for definition in ws.get_property_definitions(
            names=batch, resource_type="event"
        ):
            if (
                definition.name in batch
                and (definition.resource_type or "").lower() == "event"
                and not _is_builtin(definition)
            ):
                return definition.name
    pytest.skip("no event property definition that is not a Mixpanel built-in")


@pytest.fixture(scope="module", autouse=True)
def cleanup_stale_qa_objects(ws: Workspace) -> None:
    """Remove leftover QA-027-* objects from prior runs.

    Scans tags, drop filters, custom properties, and lookup tables
    for objects with the QA-027- prefix and deletes them silently.

    Args:
        ws: Workspace fixture.
    """
    # Tags (list_lexicon_tags returns LexiconTag objects)
    with contextlib.suppress(Exception):
        tags = ws.list_lexicon_tags()
        for tag in tags:
            if tag.name.startswith(QA_PREFIX):
                with contextlib.suppress(Exception):
                    ws.delete_lexicon_tag(tag.name)

    # Drop filters (may fail if account lacks event_deletion permission)
    with contextlib.suppress(Exception):
        filters = ws.list_drop_filters()
        for f in filters:
            if f.event_name.startswith(QA_PREFIX):
                with contextlib.suppress(Exception):
                    ws.delete_drop_filter(f.id)

    # Custom properties
    with contextlib.suppress(Exception):
        props = ws.list_custom_properties()
        for p in props:
            if p.name.startswith(QA_PREFIX):
                with contextlib.suppress(Exception):
                    ws.delete_custom_property(str(p.custom_property_id))

    # Lookup tables
    with contextlib.suppress(Exception):
        tables = ws.list_lookup_tables()
        for t in tables:
            if t.name.startswith(QA_PREFIX):
                with contextlib.suppress(Exception):
                    ws.delete_lookup_tables([t.id])


# =============================================================================
# Domain 1: Lexicon Tags + Event/Property Definitions + Export
# =============================================================================


class TestTagsCRUD:
    """Tag create / list / update / delete — happy path."""

    def test_list_tags(self, ws: Workspace) -> None:
        """Listing tags returns a list of LexiconTag objects.

        Args:
            ws: Workspace fixture.
        """
        tags = ws.list_lexicon_tags()
        assert isinstance(tags, list)
        for t in tags:
            assert isinstance(t, LexiconTag)
            assert isinstance(t.name, str)

    def test_create_update_delete_tag(self, ws: Workspace) -> None:
        """Full lifecycle: create -> update -> delete a tag.

        Args:
            ws: Workspace fixture.
        """
        name = _unique_name("tag")
        created: LexiconTag | None = None
        try:
            # Create
            created = ws.create_lexicon_tag(CreateTagParams(name=name))
            assert isinstance(created, LexiconTag)
            assert created.name == name
            assert isinstance(created.id, int)

            # Verify in list
            tags = ws.list_lexicon_tags()
            tag_names = [t.name for t in tags]
            assert name in tag_names

            # Update
            new_name = _unique_name("tag-renamed")
            updated = ws.update_lexicon_tag(created.id, UpdateTagParams(name=new_name))
            assert updated.name == new_name

            # Delete by new name
            ws.delete_lexicon_tag(new_name)

            # Verify absent
            tags_after = ws.list_lexicon_tags()
            tag_names_after = [t.name for t in tags_after]
            assert new_name not in tag_names_after
            created = None  # already deleted

        finally:
            if created is not None:
                with contextlib.suppress(Exception):
                    ws.delete_lexicon_tag(created.name)

    def test_delete_nonexistent_tag(self, ws: Workspace) -> None:
        """Deleting a non-existent tag raises QueryError or is a no-op.

        Args:
            ws: Workspace fixture.
        """
        with pytest.raises((QueryError, Exception)):  # noqa: B017
            ws.delete_lexicon_tag("QA-027-does-not-exist-ever")

    def test_create_duplicate_tag_name(self, ws: Workspace) -> None:
        """Creating a tag with a duplicate name raises or returns existing.

        Args:
            ws: Workspace fixture.
        """
        name = _unique_name("dup-tag")
        tag1: LexiconTag | None = None
        try:
            tag1 = ws.create_lexicon_tag(CreateTagParams(name=name))
            # Second create with same name — discover behavior
            try:
                tag2 = ws.create_lexicon_tag(CreateTagParams(name=name))
                # If no error, the API accepted it (idempotent or duplicate)
                assert tag2.name == name
            except (QueryError, Exception):
                pass  # Expected: duplicate rejected
        finally:
            if tag1 is not None:
                with contextlib.suppress(Exception):
                    ws.delete_lexicon_tag(name)


class TestEventDefinitions:
    """Event definition get / update / bulk-update / history."""

    def test_get_event_definitions(self, ws: Workspace) -> None:
        """Getting event definitions by name returns matching results.

        Args:
            ws: Workspace fixture.
        """
        result = ws.get_event_definitions(names=["$session_start"])
        assert isinstance(result, list)
        assert len(result) >= 1
        ev = result[0]
        assert isinstance(ev, EventDefinition)
        assert ev.name == "$session_start"

    def test_get_nonexistent(self, ws: Workspace) -> None:
        """Getting a non-existent event returns empty or raises.

        Args:
            ws: Workspace fixture.
        """
        result = ws.get_event_definitions(names=["QA-027-nonexistent-event-xyz"])
        # API may return empty list or raise
        assert isinstance(result, list)
        assert len(result) == 0

    def test_get_empty_list(self, ws: Workspace) -> None:
        """Getting event definitions with empty names list is an edge case.

        Args:
            ws: Workspace fixture.
        """
        result = ws.get_event_definitions(names=[])
        assert isinstance(result, list)

    def test_update_description(self, ws: Workspace, custom_event: str) -> None:
        """Updating an event description takes effect and can be reverted.

        Args:
            ws: Workspace fixture.
            custom_event: An event that is not a Mixpanel built-in.
        """
        old_desc = _event_row(ws, custom_event).description or ""
        new_desc = f"QA-027 test description {uuid.uuid4().hex[:8]}"
        try:
            updated = ws.update_event_definition(
                custom_event,
                UpdateEventDefinitionParams(description=new_desc),
            )
            assert updated.description == new_desc
        finally:
            _restore(
                "event description",
                lambda: ws.update_event_definition(
                    custom_event,
                    UpdateEventDefinitionParams(description=old_desc),
                ),
            )
            restored = _event_row(ws, custom_event).description or ""
            assert restored == old_desc, (
                f"restore left description {restored!r}, expected {old_desc!r}"
            )

    def test_update_hidden_flag(self, ws: Workspace, custom_event: str) -> None:
        """Setting hidden=True then hidden=False both take effect.

        Args:
            ws: Workspace fixture.
            custom_event: An event that is not a Mixpanel built-in.
        """
        old_hidden = bool(_event_row(ws, custom_event).hidden)
        try:
            hidden = ws.update_event_definition(
                custom_event,
                UpdateEventDefinitionParams(hidden=True),
            )
            assert hidden.hidden is True

            visible = ws.update_event_definition(
                custom_event,
                UpdateEventDefinitionParams(hidden=False),
            )
            assert visible.hidden is False
        finally:
            _restore(
                "event hidden flag",
                lambda: ws.update_event_definition(
                    custom_event,
                    UpdateEventDefinitionParams(hidden=old_hidden),
                ),
            )
            restored = bool(_event_row(ws, custom_event).hidden)
            assert restored is old_hidden, (
                f"restore left hidden={restored}, expected {old_hidden}"
            )

    def test_bulk_update(self, ws: Workspace, custom_event: str) -> None:
        """Bulk-updating event definitions returns a list.

        The API may return 0 results if the event doesn't match or
        the response format differs from expectations. The verified flag
        that the update sets is put back afterwards.

        Args:
            ws: Workspace fixture.
            custom_event: An event that is not a Mixpanel built-in.
        """
        old_verified = bool(_event_row(ws, custom_event).verified)
        params = BulkUpdateEventsParams(
            events=[
                BulkEventUpdate(name=custom_event, verified=True),
            ]
        )
        try:
            result = ws.bulk_update_event_definitions(params)
            assert isinstance(result, list)
        finally:
            _restore(
                "event verified flag",
                lambda: ws.update_event_definition(
                    custom_event,
                    UpdateEventDefinitionParams(verified=old_verified),
                ),
            )
            restored = bool(_event_row(ws, custom_event).verified)
            assert restored is old_verified, (
                f"restore left verified={restored}, expected {old_verified}"
            )

    def test_tracking_metadata(self, ws: Workspace) -> None:
        """Getting tracking metadata for a known event returns a dict.

        Args:
            ws: Workspace fixture.
        """
        result = ws.get_tracking_metadata("$session_start")
        assert isinstance(result, dict)

    def test_event_history(self, ws: Workspace) -> None:
        """Getting event history returns a list of history entries.

        Args:
            ws: Workspace fixture.
        """
        result = ws.get_event_history("$session_start")
        assert isinstance(result, list)


class TestPropertyDefinitions:
    """Property definition get / update / bulk-update / history."""

    def test_get(self, ws: Workspace) -> None:
        """Getting property definitions by name returns matching results.

        The API may return multiple properties; we verify that at least
        one result is a PropertyDefinition. The Lexicon API may strip
        the ``$`` prefix (e.g. ``$browser`` -> ``browser``).

        Args:
            ws: Workspace fixture.
        """
        result = ws.get_property_definitions(names=["$browser"])
        assert isinstance(result, list)
        assert len(result) >= 1
        # Verify at least one is a PropertyDefinition
        assert isinstance(result[0], PropertyDefinition)
        # The returned name may or may not have the $ prefix
        prop_names = [p.name for p in result]
        assert "$browser" in prop_names or "browser" in prop_names

    def test_get_with_resource_type(self, ws: Workspace) -> None:
        """Filtering by resource_type narrows the results.

        Args:
            ws: Workspace fixture.
        """
        result = ws.get_property_definitions(names=["$browser"], resource_type="event")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_update(self, ws: Workspace, custom_event_property: str) -> None:
        """Updating a property description takes effect and can be reverted.

        The old description comes from the exact row (name and event
        resource type), and both writes name the event resource type.

        Args:
            ws: Workspace fixture.
            custom_event_property: An event property that is not a Mixpanel
                built-in.
        """
        old_desc = _event_property_row(ws, custom_event_property).description or ""
        new_desc = f"QA-027 test prop desc {uuid.uuid4().hex[:8]}"
        try:
            updated = ws.update_property_definition(
                custom_event_property,
                UpdatePropertyDefinitionParams(
                    description=new_desc, resource_type="Event"
                ),
            )
            assert updated.description == new_desc
        finally:
            _restore(
                "event property description",
                lambda: ws.update_property_definition(
                    custom_event_property,
                    UpdatePropertyDefinitionParams(
                        description=old_desc, resource_type="Event"
                    ),
                ),
            )
            restored = _event_property_row(ws, custom_event_property).description or ""
            assert restored == old_desc, (
                f"restore left description {restored!r}, expected {old_desc!r}"
            )

    def test_bulk_update(self, ws: Workspace) -> None:
        """Bulk-updating property definitions returns a list.

        The API expects capitalized resource_type values (e.g. ``"Event"``
        rather than ``"event"``).

        Args:
            ws: Workspace fixture.
        """
        params = BulkUpdatePropertiesParams(
            properties=[
                BulkPropertyUpdate(name="$browser", resource_type="Event"),
            ]
        )
        result = ws.bulk_update_property_definitions(params)
        assert isinstance(result, list)

    def test_property_history(self, ws: Workspace) -> None:
        """Getting property history returns a list of entries.

        Args:
            ws: Workspace fixture.
        """
        result = ws.get_property_history("$browser", "event")
        assert isinstance(result, list)


class TestLexiconExport:
    """Lexicon export — full and filtered."""

    def test_export_all(self, ws: Workspace) -> None:
        """Exporting all Lexicon data returns a dict.

        Args:
            ws: Workspace fixture.
        """
        result = ws.export_lexicon()
        assert isinstance(result, dict)

    def test_export_filtered(self, ws: Workspace) -> None:
        """Exporting with type filter returns a dict.

        Args:
            ws: Workspace fixture.
        """
        result = ws.export_lexicon(export_types=["events"])
        assert isinstance(result, dict)


class TestLexiconCLI:
    """Lexicon CLI commands end-to-end."""

    def test_tags_list_json(self) -> None:
        """``mp lexicon tags list --format json`` returns valid JSON list.

        Returns:
            None.
        """
        r = _mp("lexicon", "tags", "list", "--format", "json")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert isinstance(data, list)

    def test_tags_list_table(self) -> None:
        """``mp lexicon tags list --format table`` succeeds.

        Returns:
            None.
        """
        r = _mp("lexicon", "tags", "list", "--format", "table")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_tags_list_csv(self) -> None:
        """``mp lexicon tags list --format csv`` succeeds.

        Returns:
            None.
        """
        r = _mp("lexicon", "tags", "list", "--format", "csv")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_tags_list_jsonl(self) -> None:
        """``mp lexicon tags list --format jsonl`` produces valid JSONL.

        Returns:
            None.
        """
        r = _mp("lexicon", "tags", "list", "--format", "jsonl")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        lines = [line for line in r.stdout.strip().split("\n") if line]
        if lines:
            json.loads(lines[0])  # Each line is valid JSON

    def test_tags_crud_lifecycle(self) -> None:
        """Full CLI tag CRUD: create -> list -> update -> delete.

        Returns:
            None.
        """
        name = _unique_name("cli-tag")
        new_name = _unique_name("cli-tag-up")

        # Create
        r = _mp("lexicon", "tags", "create", "--name", name)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        tag = json.loads(r.stdout)
        tag_id = tag["id"]

        try:
            # List — verify present (tags list returns plain strings)
            r = _mp("lexicon", "tags", "list", "--format", "json")
            assert r.returncode == 0, f"stderr: {r.stderr}"
            tags = json.loads(r.stdout)
            assert name in tags

            # Update
            r = _mp(
                "lexicon", "tags", "update", "--id", str(tag_id), "--name", new_name
            )
            assert r.returncode == 0, f"stderr: {r.stderr}"

            # Delete
            r = _mp("lexicon", "tags", "delete", "--name", new_name)
            assert r.returncode == 0, f"stderr: {r.stderr}"
        except Exception:
            # Cleanup on failure
            with contextlib.suppress(Exception):
                _mp("lexicon", "tags", "delete", "--name", name)
            with contextlib.suppress(Exception):
                _mp("lexicon", "tags", "delete", "--name", new_name)
            raise

    def test_events_get(self) -> None:
        """``mp lexicon events get`` returns JSON for a known event.

        Returns:
            None.
        """
        r = _mp("lexicon", "events", "get", "--names", "$session_start")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_events_update_revert(self, custom_event: str) -> None:
        """CLI event update + revert succeeds.

        Args:
            custom_event: An event that is not a Mixpanel built-in.
        """
        # Get original from the exact row
        r = _mp("lexicon", "events", "get", "--names", custom_event)
        assert r.returncode == 0, f"stderr: {r.stderr}"
        rows = [e for e in json.loads(r.stdout) if e.get("name") == custom_event]
        assert len(rows) == 1, f"expected one row for {custom_event!r}, got {rows}"
        old_desc = rows[0].get("description") or ""

        new_desc = f"QA-027 CLI test {uuid.uuid4().hex[:8]}"
        try:
            r = _mp(
                "lexicon",
                "events",
                "update",
                "--name",
                custom_event,
                "--description",
                new_desc,
            )
            assert r.returncode == 0, f"stderr: {r.stderr}"
        finally:
            revert = _mp(
                "lexicon",
                "events",
                "update",
                "--name",
                custom_event,
                "--description",
                old_desc,
            )
            assert revert.returncode == 0, (
                f"CLI revert failed (exit {revert.returncode}): {revert.stderr}"
            )

    def test_events_bulk_update_invalid_json(self) -> None:
        """Bulk update with invalid JSON exits non-zero.

        Returns:
            None.
        """
        r = _mp("lexicon", "events", "bulk-update", "--data", "not-json")
        assert r.returncode != 0
        output = r.stdout + r.stderr
        assert "Invalid JSON" in output or "invalid" in output.lower()

    def test_properties_get(self) -> None:
        """``mp lexicon properties get`` returns JSON for a known property.

        Returns:
            None.
        """
        r = _mp("lexicon", "properties", "get", "--names", "$browser")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_properties_get_with_resource_type(self) -> None:
        """``mp lexicon properties get --resource-type event`` narrows results.

        Returns:
            None.
        """
        r = _mp(
            "lexicon",
            "properties",
            "get",
            "--names",
            "$browser",
            "--resource-type",
            "event",
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert isinstance(data, list)

    def test_tracking_metadata_cli(self) -> None:
        """``mp lexicon tracking-metadata`` succeeds for a known event.

        Returns:
            None.
        """
        r = _mp(
            "lexicon",
            "tracking-metadata",
            "--event-name",
            "$session_start",
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_event_history_cli(self) -> None:
        """``mp lexicon event-history`` succeeds for a known event.

        Returns:
            None.
        """
        r = _mp(
            "lexicon",
            "event-history",
            "--event-name",
            "$session_start",
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_property_history_cli(self) -> None:
        """``mp lexicon property-history`` succeeds for a known property.

        Returns:
            None.
        """
        r = _mp(
            "lexicon",
            "property-history",
            "--property-name",
            "$browser",
            "--entity-type",
            "event",
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_export_cli(self) -> None:
        """``mp lexicon export`` exits 0 and produces output.

        Returns:
            None.
        """
        r = _mp("lexicon", "export")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_export_filtered_cli(self) -> None:
        """``mp lexicon export --types events`` exits 0.

        Returns:
            None.
        """
        r = _mp("lexicon", "export", "--types", "events")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_jq_filter(self) -> None:
        """``mp lexicon tags list --jq '.[0]'`` extracts the first tag string.

        Returns:
            None.
        """
        r = _mp("lexicon", "tags", "list", "--jq", ".[0]")
        assert r.returncode == 0, f"stderr: {r.stderr}"


# =============================================================================
# Domain 2: Drop Filters
# =============================================================================


class TestDropFiltersCRUD:
    """Drop filter create / list / update / delete — happy path."""

    def test_list(self, ws: Workspace) -> None:
        """Listing drop filters returns a list of DropFilter objects.

        Args:
            ws: Workspace fixture.
        """
        filters = ws.list_drop_filters()
        assert isinstance(filters, list)
        for f in filters:
            assert isinstance(f, DropFilter)

    def test_create_returns_full_list(self, ws: Workspace) -> None:
        """Creating a drop filter returns the full list including the new one.

        Args:
            ws: Workspace fixture.
        """
        event_name = _unique_name("drop")
        created_id: int | None = None
        try:
            result = ws.create_drop_filter(
                CreateDropFilterParams(
                    event_name=event_name,
                    filters=[
                        {
                            "resourceType": "event",
                            "filterType": "string",
                            "filterOperator": "equals",
                            "filterValue": "test",
                            "value": "test",
                        }
                    ],
                )
            )
            assert isinstance(result, list)
            # Find our new filter
            our = [f for f in result if f.event_name == event_name]
            assert len(our) >= 1
            created_id = our[0].id
        finally:
            if created_id is not None:
                with contextlib.suppress(Exception):
                    ws.delete_drop_filter(created_id)

    def test_update_returns_full_list(self, ws: Workspace) -> None:
        """Updating a drop filter returns the full list with updates applied.

        Args:
            ws: Workspace fixture.
        """
        event_name = _unique_name("drop-upd")
        created_id: int | None = None
        try:
            result = ws.create_drop_filter(
                CreateDropFilterParams(
                    event_name=event_name,
                    filters=[
                        {
                            "resourceType": "event",
                            "filterType": "string",
                            "filterOperator": "equals",
                            "filterValue": "test",
                            "value": "test",
                        }
                    ],
                )
            )
            our = [f for f in result if f.event_name == event_name]
            assert len(our) >= 1
            created_id = our[0].id

            # Update — deactivate
            updated_list = ws.update_drop_filter(
                UpdateDropFilterParams(id=created_id, active=False)
            )
            assert isinstance(updated_list, list)
            updated_filter = [f for f in updated_list if f.id == created_id]
            assert len(updated_filter) == 1
            assert updated_filter[0].active is False
        finally:
            if created_id is not None:
                with contextlib.suppress(Exception):
                    ws.delete_drop_filter(created_id)

    def test_delete_returns_remaining_list(self, ws: Workspace) -> None:
        """Deleting a drop filter returns the remaining list without it.

        Args:
            ws: Workspace fixture.
        """
        event_name = _unique_name("drop-del")
        result = ws.create_drop_filter(
            CreateDropFilterParams(
                event_name=event_name,
                filters=[
                    {
                        "resourceType": "event",
                        "filterType": "string",
                        "filterOperator": "equals",
                        "filterValue": "staging",
                        "value": "staging",
                    }
                ],
            )
        )
        our = [f for f in result if f.event_name == event_name]
        assert len(our) >= 1
        created_id = our[0].id

        remaining = ws.delete_drop_filter(created_id)
        assert isinstance(remaining, list)
        remaining_ids = [f.id for f in remaining]
        assert created_id not in remaining_ids

    def test_deactivate_reactivate(self, ws: Workspace) -> None:
        """Create -> deactivate -> reactivate -> delete cycle.

        Args:
            ws: Workspace fixture.
        """
        event_name = _unique_name("drop-toggle")
        created_id: int | None = None
        try:
            result = ws.create_drop_filter(
                CreateDropFilterParams(
                    event_name=event_name,
                    filters=[
                        {
                            "resourceType": "event",
                            "filterType": "string",
                            "filterOperator": "equals",
                            "filterValue": "dev",
                            "value": "dev",
                        }
                    ],
                )
            )
            our = [f for f in result if f.event_name == event_name]
            assert len(our) >= 1
            created_id = our[0].id

            # Deactivate
            deactivated = ws.update_drop_filter(
                UpdateDropFilterParams(id=created_id, active=False)
            )
            inactive = [f for f in deactivated if f.id == created_id]
            assert len(inactive) == 1
            assert inactive[0].active is False

            # Reactivate
            reactivated = ws.update_drop_filter(
                UpdateDropFilterParams(id=created_id, active=True)
            )
            active = [f for f in reactivated if f.id == created_id]
            assert len(active) == 1
            assert active[0].active is True
        finally:
            if created_id is not None:
                with contextlib.suppress(Exception):
                    ws.delete_drop_filter(created_id)

    def test_limits(self, ws: Workspace) -> None:
        """Getting drop filter limits returns expected fields.

        Args:
            ws: Workspace fixture.
        """
        limits = ws.get_drop_filter_limits()
        assert isinstance(limits, DropFilterLimitsResponse)
        assert limits.filter_limit > 0

    def test_delete_nonexistent(self, ws: Workspace) -> None:
        """Deleting a non-existent drop filter raises an error.

        Args:
            ws: Workspace fixture.
        """
        with pytest.raises((QueryError, Exception)):  # noqa: B017
            ws.delete_drop_filter(999999999)


class TestDropFiltersCLI:
    """Drop filter CLI commands end-to-end."""

    def test_list_json(self) -> None:
        """``mp drop-filters list --format json`` returns valid JSON.

        Returns:
            None.
        """
        r = _mp("drop-filters", "list", "--format", "json")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert isinstance(data, list)

    def test_limits_cli(self) -> None:
        """``mp drop-filters limits`` succeeds with filter_limit in output.

        Returns:
            None.
        """
        r = _mp("drop-filters", "limits", "--format", "json")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert "filter_limit" in data

    def test_crud_lifecycle_cli(self) -> None:
        """Full CLI drop filter CRUD: create -> update -> delete.

        Returns:
            None.
        """
        event_name = _unique_name("cli-drop")
        filters_json = json.dumps(
            [
                {
                    "resourceType": "event",
                    "filterType": "string",
                    "filterOperator": "equals",
                    "filterValue": "test",
                    "value": "test",
                }
            ]
        )

        # Create
        r = _mp(
            "drop-filters",
            "create",
            "--event-name",
            event_name,
            "--filters",
            filters_json,
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        result = json.loads(r.stdout)
        assert isinstance(result, list)

        # Find our filter
        our = [f for f in result if f["event_name"] == event_name]
        assert len(our) >= 1
        filter_id = str(our[0]["id"])

        try:
            # Update — deactivate
            r = _mp(
                "drop-filters",
                "update",
                "--id",
                filter_id,
                "--no-active",
            )
            assert r.returncode == 0, f"stderr: {r.stderr}"

            # Delete
            r = _mp("drop-filters", "delete", "--id", filter_id)
            assert r.returncode == 0, f"stderr: {r.stderr}"
        except Exception:
            with contextlib.suppress(Exception):
                _mp("drop-filters", "delete", "--id", filter_id)
            raise

    def test_create_invalid_json(self) -> None:
        """Creating with invalid JSON filters exits non-zero.

        Returns:
            None.
        """
        r = _mp(
            "drop-filters",
            "create",
            "--event-name",
            "x",
            "--filters",
            "not-json",
        )
        assert r.returncode != 0
        output = r.stdout + r.stderr
        assert "Invalid JSON" in output or "invalid" in output.lower()

    def test_update_active_toggle(self) -> None:
        """CLI --active and --no-active toggles work correctly.

        Returns:
            None.
        """
        event_name = _unique_name("cli-drop-toggle")
        filters_json = json.dumps(
            [
                {
                    "resourceType": "event",
                    "filterType": "string",
                    "filterOperator": "equals",
                    "filterValue": "test",
                    "value": "test",
                }
            ]
        )

        # Create
        r = _mp(
            "drop-filters",
            "create",
            "--event-name",
            event_name,
            "--filters",
            filters_json,
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        result = json.loads(r.stdout)
        our = [f for f in result if f["event_name"] == event_name]
        assert len(our) >= 1
        filter_id = str(our[0]["id"])

        try:
            # Deactivate
            r = _mp("drop-filters", "update", "--id", filter_id, "--no-active")
            assert r.returncode == 0, f"stderr: {r.stderr}"
            updated = json.loads(r.stdout)
            ours = [f for f in updated if f["id"] == int(filter_id)]
            assert len(ours) == 1
            assert ours[0]["active"] is False

            # Reactivate
            r = _mp("drop-filters", "update", "--id", filter_id, "--active")
            assert r.returncode == 0, f"stderr: {r.stderr}"
            updated = json.loads(r.stdout)
            ours = [f for f in updated if f["id"] == int(filter_id)]
            assert len(ours) == 1
            assert ours[0]["active"] is True
        finally:
            with contextlib.suppress(Exception):
                _mp("drop-filters", "delete", filter_id)


# =============================================================================
# Domain 3: Custom Properties
# =============================================================================


class TestCustomPropertyValidation:
    """Client-side validation of CreateCustomPropertyParams (no API calls)."""

    def test_formula_and_behavior_exclusive(self) -> None:
        """Setting both display_formula and behavior raises ValidationError.

        Returns:
            None.
        """
        with pytest.raises(ValidationError):
            CreateCustomPropertyParams(
                name="bad",
                resource_type="events",
                display_formula='properties["x"]',
                composed_properties={
                    "x": ComposedPropertyValue(resource_type="event"),
                },
                behavior={"type": "count"},
            )

    def test_behavior_and_composed_exclusive(self) -> None:
        """Setting both behavior and composed_properties raises ValidationError.

        Returns:
            None.
        """
        with pytest.raises(ValidationError):
            CreateCustomPropertyParams(
                name="bad",
                resource_type="events",
                behavior={"type": "count"},
                composed_properties={
                    "x": ComposedPropertyValue(resource_type="event"),
                },
            )

    def test_formula_requires_composed(self) -> None:
        """Setting display_formula without composed_properties raises ValidationError.

        Returns:
            None.
        """
        with pytest.raises(ValidationError):
            CreateCustomPropertyParams(
                name="bad",
                resource_type="events",
                display_formula='properties["x"]',
            )

    def test_neither_set(self) -> None:
        """Setting neither display_formula nor behavior raises ValidationError.

        Returns:
            None.
        """
        with pytest.raises(ValidationError):
            CreateCustomPropertyParams(
                name="bad",
                resource_type="events",
            )

    def test_formula_with_composed_valid(self) -> None:
        """Valid formula + composed_properties combination passes validation.

        Returns:
            None.
        """
        params = CreateCustomPropertyParams(
            name="ok",
            resource_type="events",
            display_formula='if( _A , _A, "unknown")',
            composed_properties={
                "_A": ComposedPropertyValue(resource_type="event"),
            },
        )
        assert params.name == "ok"
        assert params.display_formula is not None

    def test_behavior_alone_valid(self) -> None:
        """Valid behavior-only combination passes validation.

        Returns:
            None.
        """
        params = CreateCustomPropertyParams(
            name="ok",
            resource_type="events",
            behavior={"type": "count"},
        )
        assert params.name == "ok"
        assert params.behavior is not None


class TestCustomPropertiesCRUD:
    """Custom property create / get / update / delete — happy path."""

    def test_list(self, ws: Workspace) -> None:
        """Listing custom properties returns a list of CustomProperty objects.

        Args:
            ws: Workspace fixture.
        """
        props = ws.list_custom_properties()
        assert isinstance(props, list)
        for p in props:
            assert isinstance(p, CustomProperty)

    @pytest.mark.skip(reason="Project plan does not allow saving custom properties")
    def test_create_get_update_delete(self, ws: Workspace) -> None:
        """Full CRUD cycle for a custom property with formula.

        Args:
            ws: Workspace fixture.
        """
        name = _unique_name("cprop")
        created: CustomProperty | None = None
        try:
            created = ws.create_custom_property(
                CreateCustomPropertyParams(
                    name=name,
                    resource_type="events",
                    display_formula='if( _A , _A, "unknown")',
                    composed_properties={
                        "_A": ComposedPropertyValue(resource_type="event"),
                    },
                )
            )
            assert isinstance(created, CustomProperty)
            assert created.name == name
            prop_id = str(created.custom_property_id)

            # Get
            fetched = ws.get_custom_property(prop_id)
            assert fetched.custom_property_id == created.custom_property_id
            assert fetched.name == name

            # Update — rename
            new_name = _unique_name("cprop-up")
            updated = ws.update_custom_property(
                prop_id,
                UpdateCustomPropertyParams(name=new_name),
            )
            assert updated.name == new_name

            # Delete
            ws.delete_custom_property(prop_id)
            created = None  # already deleted
        finally:
            if created is not None:
                with contextlib.suppress(Exception):
                    ws.delete_custom_property(str(created.custom_property_id))

    @pytest.mark.skip(reason="Project plan does not allow saving custom properties")
    def test_update_is_put(self, ws: Workspace) -> None:
        """Verify PUT semantics: updating only name preserves other fields.

        Args:
            ws: Workspace fixture.
        """
        name = _unique_name("cprop-put")
        created: CustomProperty | None = None
        try:
            created = ws.create_custom_property(
                CreateCustomPropertyParams(
                    name=name,
                    resource_type="events",
                    display_formula='if( _A , _A, "unknown")',
                    composed_properties={
                        "_A": ComposedPropertyValue(resource_type="event"),
                    },
                    description="QA PUT test",
                )
            )
            prop_id = str(created.custom_property_id)

            # Update only name
            new_name = _unique_name("cprop-put-up")
            updated = ws.update_custom_property(
                prop_id,
                UpdateCustomPropertyParams(name=new_name),
            )
            assert updated.name == new_name
            # Other fields should still be present
            assert updated.resource_type == "events"
        finally:
            if created is not None:
                with contextlib.suppress(Exception):
                    ws.delete_custom_property(str(created.custom_property_id))

    def test_validate_formula(self, ws: Workspace) -> None:
        """Validating a custom property formula returns a result dict.

        Args:
            ws: Workspace fixture.
        """
        result = ws.validate_custom_property(
            CreateCustomPropertyParams(
                name="QA-027-validate-test",
                resource_type="events",
                display_formula='if( _A , _A, "unknown")',
                composed_properties={
                    "_A": ComposedPropertyValue(resource_type="event"),
                },
            )
        )
        assert isinstance(result, dict)

    def test_get_nonexistent(self, ws: Workspace) -> None:
        """Getting a non-existent custom property raises QueryError.

        Args:
            ws: Workspace fixture.
        """
        with pytest.raises(QueryError):
            ws.get_custom_property("999999999")

    def test_delete_nonexistent(self, ws: Workspace) -> None:
        """Deleting a non-existent custom property raises QueryError.

        Args:
            ws: Workspace fixture.
        """
        with pytest.raises(QueryError):
            ws.delete_custom_property("999999999")


class TestCustomPropertiesCLI:
    """Custom property CLI commands end-to-end."""

    def test_list_json(self) -> None:
        """``mp custom-properties list --format json`` returns valid JSON.

        Returns:
            None.
        """
        r = _mp("custom-properties", "list", "--format", "json")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert isinstance(data, list)

    @pytest.mark.skip(reason="Project plan does not allow saving custom properties")
    def test_crud_lifecycle_cli(self) -> None:
        """Full CLI custom property CRUD: create -> get -> update -> delete.

        Returns:
            None.
        """
        name = _unique_name("cli-cprop")
        composed = json.dumps(
            {
                "_A": {"resource_type": "event"},
            }
        )

        # Create
        r = _mp(
            "custom-properties",
            "create",
            "--name",
            name,
            "--resource-type",
            "events",
            "--display-formula",
            'if( _A , _A, "unknown")',
            "--composed-properties",
            composed,
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        prop = json.loads(r.stdout)
        prop_id = str(prop["custom_property_id"])

        try:
            # Get
            r = _mp("custom-properties", "get", "--id", prop_id)
            assert r.returncode == 0, f"stderr: {r.stderr}"
            got = json.loads(r.stdout)
            assert got["name"] == name

            # Update
            new_name = _unique_name("cli-cprop-up")
            r = _mp(
                "custom-properties",
                "update",
                "--id",
                prop_id,
                "--name",
                new_name,
            )
            assert r.returncode == 0, f"stderr: {r.stderr}"

            # Delete
            r = _mp("custom-properties", "delete", "--id", prop_id)
            assert r.returncode == 0, f"stderr: {r.stderr}"
        except Exception:
            with contextlib.suppress(Exception):
                _mp("custom-properties", "delete", "--id", prop_id)
            raise

    def test_validate_cli(self) -> None:
        """``mp custom-properties validate`` exits 0 for a valid formula.

        Returns:
            None.
        """
        composed = json.dumps(
            {
                "_A": {"resource_type": "event"},
            }
        )
        r = _mp(
            "custom-properties",
            "validate",
            "--name",
            "QA-027-validate",
            "--resource-type",
            "events",
            "--display-formula",
            'if( _A , _A, "unknown")',
            "--composed-properties",
            composed,
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_create_invalid_composed_json(self) -> None:
        """Creating with invalid composed JSON exits non-zero.

        Returns:
            None.
        """
        r = _mp(
            "custom-properties",
            "create",
            "--name",
            "X",
            "--resource-type",
            "events",
            "--display-formula",
            'properties["x"]',
            "--composed-properties",
            "bad-json",
        )
        assert r.returncode != 0
        output = r.stdout + r.stderr
        assert "Invalid JSON" in output or "invalid" in output.lower()

    def test_get_nonexistent_cli(self) -> None:
        """Getting a non-existent custom property via CLI exits non-zero.

        Returns:
            None.
        """
        r = _mp("custom-properties", "get", "--id", "999999999")
        assert r.returncode != 0


# =============================================================================
# Domain 4: Lookup Tables
# =============================================================================


class TestLookupTableParamsValidation:
    """Client-side validation of UploadLookupTableParams (no API calls)."""

    def test_name_too_long(self) -> None:
        """Name exceeding 255 characters raises ValidationError.

        Returns:
            None.
        """
        with pytest.raises(ValidationError):
            UploadLookupTableParams(
                name="x" * 256,
                file_path="/tmp/test.csv",
            )

    def test_name_empty(self) -> None:
        """Empty name raises ValidationError.

        Returns:
            None.
        """
        with pytest.raises(ValidationError):
            UploadLookupTableParams(
                name="",
                file_path="/tmp/test.csv",
            )


class TestLookupTablesCRUD:
    """Lookup table list / upload / download / delete — happy path."""

    def test_list(self, ws: Workspace) -> None:
        """Listing lookup tables returns a list of LookupTable objects.

        Args:
            ws: Workspace fixture.
        """
        tables = ws.list_lookup_tables()
        assert isinstance(tables, list)
        for t in tables:
            assert isinstance(t, LookupTable)

    def test_upload_download_delete(self, ws: Workspace, tmp_path: Path) -> None:
        """Full cycle: upload CSV -> download -> verify -> delete.

        Args:
            ws: Workspace fixture.
            tmp_path: Pytest temporary directory.
        """
        csv_path = tmp_path / "qa_test.csv"
        csv_path.write_text("id,name\n1,foo\n2,bar\n")

        name = _unique_name("lut")
        table_id: int | None = None
        try:
            result = ws.upload_lookup_table(
                UploadLookupTableParams(
                    name=name,
                    file_path=str(csv_path),
                )
            )
            assert isinstance(result, LookupTable)
            table_id = result.id

            # Verify in list
            tables = ws.list_lookup_tables()
            table_names = [t.name for t in tables]
            assert name in table_names

            # Download (file_name is required by the API)
            data = ws.download_lookup_table(table_id, file_name="export.csv")
            assert isinstance(data, bytes)
            text = data.decode("utf-8", errors="replace")
            assert len(text) > 0

            # Delete
            ws.delete_lookup_tables([table_id])
            table_id = None  # already deleted

            # Verify absent
            tables_after = ws.list_lookup_tables()
            table_ids_after = [t.id for t in tables_after]
            assert table_id is None or table_id not in table_ids_after
        finally:
            if table_id is not None:
                with contextlib.suppress(Exception):
                    ws.delete_lookup_tables([table_id])

    def test_download_returns_bytes(self, ws: Workspace, tmp_path: Path) -> None:
        """Downloaded lookup table data is bytes containing CSV headers.

        Args:
            ws: Workspace fixture.
            tmp_path: Pytest temporary directory.
        """
        csv_path = tmp_path / "qa_bytes_test.csv"
        csv_path.write_text("code,country\nUS,United States\nGB,United Kingdom\n")

        name = _unique_name("lut-bytes")
        table_id: int | None = None
        try:
            result_dict = ws.upload_lookup_table(
                UploadLookupTableParams(
                    name=name,
                    file_path=str(csv_path),
                )
            )
            table_id = result_dict.id
            result = ws.download_lookup_table(table_id, file_name="export.csv")
            assert isinstance(result, bytes)
            decoded = result.decode("utf-8", errors="replace")
            assert len(decoded) > 0
        finally:
            if table_id is not None:
                with contextlib.suppress(Exception):
                    ws.delete_lookup_tables([table_id])

    def test_get_upload_url(self, ws: Workspace) -> None:
        """Getting upload URL returns LookupTableUploadUrl with required fields.

        Args:
            ws: Workspace fixture.
        """
        url_info = ws.get_lookup_upload_url()
        assert isinstance(url_info, LookupTableUploadUrl)
        assert url_info.url
        assert url_info.path
        assert url_info.key

    def test_upload_nonexistent_file(self, ws: Workspace) -> None:
        """Uploading a non-existent file raises FileNotFoundError.

        Args:
            ws: Workspace fixture.
        """
        with pytest.raises(FileNotFoundError):
            ws.upload_lookup_table(
                UploadLookupTableParams(
                    name="QA-027-nofile",
                    file_path="/nonexistent/path/qa_test.csv",
                )
            )


class TestLookupTablesCLI:
    """Lookup table CLI commands end-to-end."""

    def test_list_json(self) -> None:
        """``mp lookup-tables list --format json`` returns valid JSON.

        Returns:
            None.
        """
        r = _mp("lookup-tables", "list", "--format", "json")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert isinstance(data, list)

    def test_upload_lifecycle_cli(self, tmp_path: Path) -> None:
        """Full CLI lookup table lifecycle: upload -> download -> delete.

        Args:
            tmp_path: Pytest temporary directory.
        """
        csv_path = tmp_path / "cli_test.csv"
        csv_path.write_text("id,value\n1,alpha\n2,beta\n")

        name = _unique_name("cli-lut")

        # Upload
        r = _mp(
            "lookup-tables",
            "upload",
            "--name",
            name,
            "--file",
            str(csv_path),
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        table = json.loads(r.stdout)
        table_id = str(table["id"])

        try:
            # Verify in list
            r = _mp("lookup-tables", "list", "--format", "json")
            assert r.returncode == 0, f"stderr: {r.stderr}"

            # Delete
            r = _mp("lookup-tables", "delete", "--data-group-ids", table_id)
            assert r.returncode == 0, f"stderr: {r.stderr}"
        except Exception:
            with contextlib.suppress(Exception):
                _mp("lookup-tables", "delete", "--data-group-ids", table_id)
            raise

    def test_upload_nonexistent_file_cli(self) -> None:
        """Uploading a non-existent file via CLI exits non-zero.

        Returns:
            None.
        """
        r = _mp(
            "lookup-tables",
            "upload",
            "--name",
            "QA-027-nofile",
            "--file",
            "/nonexistent/path/qa_test.csv",
        )
        assert r.returncode != 0

    def test_download_to_stdout(self, ws: Workspace, tmp_path: Path) -> None:
        """Downloading a lookup table via CLI outputs CSV data to stdout.

        Args:
            ws: Workspace fixture.
            tmp_path: Pytest temporary directory.
        """
        csv_path = tmp_path / "dl_test.csv"
        csv_path.write_text("key,label\nA,first\nB,second\n")

        name = _unique_name("cli-dl")
        table_id: int | None = None
        try:
            result = ws.upload_lookup_table(
                UploadLookupTableParams(
                    name=name,
                    file_path=str(csv_path),
                )
            )
            table_id = result.id
            r = _mp(
                "lookup-tables",
                "download",
                "--data-group-id",
                str(table_id),
                "--file-name",
                "export.csv",
            )
            assert r.returncode == 0, f"stderr: {r.stderr}"
            assert "key" in r.stdout or "label" in r.stdout
        finally:
            if table_id is not None:
                with contextlib.suppress(Exception):
                    ws.delete_lookup_tables([table_id])

    def test_upload_url_cli(self) -> None:
        """``mp lookup-tables upload-url`` returns JSON with url field.

        Returns:
            None.
        """
        r = _mp("lookup-tables", "upload-url", "--format", "json")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert "url" in data

    def test_delete_invalid_ids(self) -> None:
        """Deleting with invalid data-group-ids exits non-zero.

        Returns:
            None.
        """
        r = _mp("lookup-tables", "delete", "--data-group-ids", "abc")
        assert r.returncode != 0

    def test_delete_empty_ids(self) -> None:
        """Deleting with empty data-group-ids exits non-zero.

        Returns:
            None.
        """
        r = _mp("lookup-tables", "delete", "--data-group-ids", "")
        assert r.returncode != 0


# =============================================================================
# Domain 5: Custom Events
# =============================================================================


class TestCustomEventsCRUD:
    """Custom event list / update / delete — happy path."""

    def test_list(self, ws: Workspace) -> None:
        """Listing custom events returns a list of EventDefinition objects.

        Args:
            ws: Workspace fixture.
        """
        events = ws.list_custom_events()
        assert isinstance(events, list)
        for e in events:
            assert isinstance(e, EventDefinition)

    def test_list_filters_custom_only(self, ws: Workspace) -> None:
        """Custom events list only returns events with custom_event_id set.

        Verifies that the ``custom_event=true`` filter is applied correctly
        by the API client.

        Args:
            ws: Workspace fixture.
        """
        events = ws.list_custom_events()
        if events:
            for e in events:
                assert e.custom_event_id is not None, (
                    f"Event {e.name} has no custom_event_id — "
                    f"custom_event=true filter may not be working"
                )

    def test_update_nonexistent(self, ws: Workspace) -> None:
        """Updating a non-existent custom event may raise or succeed silently.

        The API may not error on updates to nonexistent custom events,
        so we accept either a QueryError or a successful response.

        Args:
            ws: Workspace fixture.
        """
        try:
            result = ws.update_custom_event(
                999_999_999,  # ID that should not exist
                UpdateEventDefinitionParams(description="should fail"),
            )
            # API accepted the update silently — that's fine
            assert isinstance(result, EventDefinition)
        except QueryError:
            pass  # Expected: API rejects nonexistent event

    def test_delete_nonexistent(self, ws: Workspace) -> None:
        """Deleting a non-existent custom event raises QueryError.

        Args:
            ws: Workspace fixture.
        """
        with pytest.raises(QueryError):
            ws.delete_custom_event(999_999_999)


class TestCustomEventsCLI:
    """Custom event CLI commands end-to-end."""

    def test_list_json(self) -> None:
        """``mp custom-events list --format json`` returns valid JSON.

        Returns:
            None.
        """
        r = _mp("custom-events", "list", "--format", "json")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert isinstance(data, list)

    def test_list_table(self) -> None:
        """``mp custom-events list --format table`` succeeds.

        Returns:
            None.
        """
        r = _mp("custom-events", "list", "--format", "table")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_list_csv(self) -> None:
        """``mp custom-events list --format csv`` succeeds.

        Returns:
            None.
        """
        r = _mp("custom-events", "list", "--format", "csv")
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_list_jsonl(self) -> None:
        """``mp custom-events list --format jsonl`` produces valid JSONL.

        Returns:
            None.
        """
        r = _mp("custom-events", "list", "--format", "jsonl")
        assert r.returncode == 0, f"stderr: {r.stderr}"
        lines = [line for line in r.stdout.strip().split("\n") if line]
        if lines:
            json.loads(lines[0])

    def test_update_nonexistent_cli(self) -> None:
        """Updating a non-existent custom event via CLI exits non-zero.

        Returns:
            None.
        """
        r = _mp(
            "custom-events",
            "update",
            "--id",
            "999999999",
            "--description",
            "should fail",
        )
        assert r.returncode != 0

    def test_delete_nonexistent_cli(self) -> None:
        """Deleting a non-existent custom event via CLI exits non-zero.

        Returns:
            None.
        """
        r = _mp("custom-events", "delete", "--id", "999999999")
        assert r.returncode != 0

    def test_help_shows_commands(self) -> None:
        """``mp custom-events`` with no subcommand shows help.

        Returns:
            None.
        """
        r = _mp("custom-events")
        assert r.returncode == 2 or r.returncode == 0
        output = r.stdout + r.stderr
        assert "Commands" in output or "Usage" in output


# =============================================================================
# Cross-Cutting Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge cases across all data governance domains."""

    def test_comma_names_with_spaces(self) -> None:
        """Event names with leading/trailing spaces are handled.

        Returns:
            None.
        """
        r = _mp(
            "lexicon",
            "events",
            "get",
            "--names",
            " $session_start ",
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"

    def test_special_chars_in_tag_name(self, ws: Workspace) -> None:
        """Tag names with spaces are accepted by the API.

        Args:
            ws: Workspace fixture.
        """
        name = f"{QA_PREFIX}Test Tag {uuid.uuid4().hex[:6]}"
        created: LexiconTag | None = None
        try:
            created = ws.create_lexicon_tag(CreateTagParams(name=name))
            assert created.name == name
        finally:
            if created is not None:
                with contextlib.suppress(Exception):
                    ws.delete_lexicon_tag(created.name)

    def test_jq_invalid_expression(self) -> None:
        """Invalid jq expression exits non-zero.

        Returns:
            None.
        """
        r = _mp("lexicon", "tags", "list", "--jq", ".invalid[[")
        assert r.returncode != 0

    def test_second_delete_tag(self, ws: Workspace) -> None:
        """Deleting an already-deleted tag raises an error on second attempt.

        Args:
            ws: Workspace fixture.
        """
        name = _unique_name("double-del")
        ws.create_lexicon_tag(CreateTagParams(name=name))
        ws.delete_lexicon_tag(name)

        with pytest.raises((QueryError, Exception)):  # noqa: B017
            ws.delete_lexicon_tag(name)

    def test_output_format_plain(self) -> None:
        """``mp lexicon tags list --format plain`` exits 0.

        Returns:
            None.
        """
        r = _mp("lexicon", "tags", "list", "--format", "plain")
        assert r.returncode == 0, f"stderr: {r.stderr}"
