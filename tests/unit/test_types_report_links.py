"""Unit tests for the report-link public types (045-report-links).

Covers ``BookmarkUrl`` (server record), ``ReportLink`` (create result),
``ResolvedReport`` (resolve result), and the two type aliases.
"""

from __future__ import annotations

import dataclasses
import json
from typing import get_args

import pytest

from mixpanel_headless.exceptions import ParamValidationError
from mixpanel_headless.types import (
    Bookmark,
    BookmarkUrl,
    FlowQueryResult,
    FunnelQueryResult,
    QueryResult,
    ReportLink,
    ReportLinkQueryResult,
    ReportLinkType,
    ResolvedReport,
    RetentionQueryResult,
)

_SLUG = "EBrV5bW2u9Mw"
_PARAMS = {"sections": {"show": []}, "displayOptions": {"chartType": "line"}}


class TestReportLinkType:
    """``ReportLinkType`` lists the four slug-record types."""

    def test_members(self) -> None:
        """Exactly insights, funnels, retention, flows."""
        assert set(get_args(ReportLinkType)) == {
            "insights",
            "funnels",
            "retention",
            "flows",
        }

    def test_query_result_alias_members(self) -> None:
        """``ReportLinkQueryResult`` unions the four typed results."""
        assert set(get_args(ReportLinkQueryResult)) == {
            QueryResult,
            FunnelQueryResult,
            RetentionQueryResult,
            FlowQueryResult,
        }


class TestBookmarkUrl:
    """The server record for an unsaved report."""

    def test_parses_server_record_with_type_alias(self) -> None:
        """``type`` populates ``bookmark_type``; defaults are None or empty."""
        record = BookmarkUrl.model_validate(
            {
                "slug": _SLUG,
                "type": "funnels",
                "params": _PARAMS,
                "project_id": 3,
                "user_id": 42,
                "created_at": "2026-09-02T10:00:00",
            }
        )
        assert record.slug == _SLUG
        assert record.bookmark_type == "funnels"
        assert record.params == _PARAMS
        assert record.project_id == 3
        assert record.user_id == 42
        assert record.created_at == "2026-09-02T10:00:00"
        assert record.name is None
        assert record.description is None
        assert record.overrides is None
        assert record.bookmark_id is None
        assert record.bookmark is None

    def test_params_default_empty_dict(self) -> None:
        """A record without ``params`` yields an empty dict."""
        record = BookmarkUrl.model_validate({"slug": _SLUG, "type": "insights"})
        assert record.params == {}

    def test_populate_by_name(self) -> None:
        """``bookmark_type=`` works as a constructor keyword."""
        record = BookmarkUrl(slug=_SLUG, bookmark_type="retention")
        assert record.bookmark_type == "retention"

    def test_embedded_bookmark(self) -> None:
        """An embedded ``bookmark`` object becomes a ``Bookmark`` model."""
        record = BookmarkUrl.model_validate(
            {
                "slug": _SLUG,
                "type": "insights",
                "params": {},
                "overrides": {"originDashboard": 555},
                "bookmark": {
                    "id": 123,
                    "name": "Weekly actives",
                    "type": "insights",
                    "params": {"sections": {}},
                },
            }
        )
        assert isinstance(record.bookmark, Bookmark)
        assert record.bookmark.id == 123
        assert record.bookmark.bookmark_type == "insights"
        assert record.overrides == {"originDashboard": 555}

    def test_extra_keys_kept(self) -> None:
        """Unknown server keys survive under ``extra``."""
        record = BookmarkUrl.model_validate(
            {"slug": _SLUG, "type": "insights", "future_key": 1}
        )
        assert record.model_extra == {"future_key": 1}

    def test_frozen(self) -> None:
        """The model rejects attribute assignment."""
        record = BookmarkUrl(slug=_SLUG, bookmark_type="insights")
        with pytest.raises(Exception, match="frozen"):
            record.slug = "x"  # type: ignore[misc]

    def test_dump_by_alias(self) -> None:
        """``model_dump(by_alias=True)`` emits ``type``."""
        record = BookmarkUrl(slug=_SLUG, bookmark_type="flows")
        assert record.model_dump(by_alias=True)["type"] == "flows"


class TestReportLink:
    """The create result."""

    def _build(self) -> ReportLink:
        """Construct a ReportLink with every field set."""
        return ReportLink(
            url=f"https://mixpanel.com/project/3/view/75/app/insights#{_SLUG}",
            slug=_SLUG,
            report_type="insights",
            project_id=3,
            workspace_id=75,
            name="Logins",
            description="last 7 days",
            bookmark_id=9,
            created_at="2026-09-02T10:00:00",
        )

    def test_to_dict_returns_every_field(self) -> None:
        """``to_dict`` has one key per field and is JSON-serializable."""
        link = self._build()
        d = link.to_dict()
        assert d == {
            "url": link.url,
            "slug": _SLUG,
            "report_type": "insights",
            "project_id": 3,
            "workspace_id": 75,
            "name": "Logins",
            "description": "last 7 days",
            "bookmark_id": 9,
            "created_at": "2026-09-02T10:00:00",
        }
        json.dumps(d)

    def test_defaults(self) -> None:
        """Optional fields default to empty strings and None."""
        link = ReportLink(
            url="https://mixpanel.com/project/3/app/flows#" + _SLUG,
            slug=_SLUG,
            report_type="flows",
            project_id=3,
            workspace_id=None,
        )
        assert link.name == ""
        assert link.description == ""
        assert link.bookmark_id is None
        assert link.created_at is None

    def test_str_is_url(self) -> None:
        """``str(link)`` is the URL so ``print(link)`` is shell-friendly."""
        link = self._build()
        assert str(link) == link.url

    def test_frozen(self) -> None:
        """The dataclass rejects attribute assignment."""
        link = self._build()
        with pytest.raises(dataclasses.FrozenInstanceError):
            link.slug = "x"  # type: ignore[misc]


class TestResolvedReport:
    """The resolve result."""

    def _build(self, bookmark: Bookmark | None) -> ResolvedReport:
        """Construct a ResolvedReport for a slug link.

        Args:
            bookmark: Optional embedded bookmark.
        """
        return ResolvedReport(
            source="slug",
            report_type="insights",
            params=_PARAMS,
            project_id=3,
            workspace_id=75,
            region="us",
            url=f"https://mixpanel.com/project/3/view/75/app/insights#{_SLUG}",
            input=_SLUG,
            expanded_url=None,
            slug=_SLUG,
            bookmark_id=None,
            bookmark=bookmark,
            name="Logins",
            description=None,
            overrides={"originDashboard": 555},
        )

    def test_to_dict_serializes_bookmark_by_alias(self) -> None:
        """An embedded bookmark dumps in JSON mode with the ``type`` alias."""
        bookmark = Bookmark(id=123, name="Weekly", bookmark_type="funnels", params={})
        d = self._build(bookmark).to_dict()
        assert d["bookmark"]["id"] == 123
        assert d["bookmark"]["type"] == "funnels"
        assert "bookmark_type" not in d["bookmark"]
        json.dumps(d)

    def test_to_dict_passes_none_bookmark_through(self) -> None:
        """A missing bookmark serializes as None."""
        d = self._build(None).to_dict()
        assert d["bookmark"] is None
        assert d["source"] == "slug"
        assert d["report_type"] == "insights"
        assert d["params"] == _PARAMS
        assert d["project_id"] == 3
        assert d["workspace_id"] == 75
        assert d["region"] == "us"
        assert d["input"] == _SLUG
        assert d["expanded_url"] is None
        assert d["slug"] == _SLUG
        assert d["bookmark_id"] is None
        assert d["name"] == "Logins"
        assert d["description"] is None
        assert d["overrides"] == {"originDashboard": 555}
        assert set(d) == {
            "source",
            "report_type",
            "params",
            "project_id",
            "workspace_id",
            "region",
            "url",
            "input",
            "expanded_url",
            "slug",
            "bookmark_id",
            "bookmark",
            "name",
            "description",
            "overrides",
        }

    def test_frozen(self) -> None:
        """The dataclass rejects attribute assignment."""
        resolved = self._build(None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            resolved.params = {}  # type: ignore[misc]

    def test_slug_source_requires_slug(self) -> None:
        """``source="slug"`` with no slug is rejected at construction."""
        with pytest.raises(ParamValidationError) as exc_info:
            dataclasses.replace(self._build(None), slug=None)
        assert exc_info.value.code == "RL5_RESOLVED_REPORT_INCONSISTENT"
        assert "source='slug'" in str(exc_info.value)
        assert exc_info.value.details == {"source": "slug", "missing": "slug"}

    def test_bookmark_source_requires_bookmark_id(self) -> None:
        """``source="bookmark"`` with no bookmark_id is rejected at construction."""
        with pytest.raises(ParamValidationError) as exc_info:
            dataclasses.replace(self._build(None), source="bookmark", slug=None)
        assert exc_info.value.code == "RL5_RESOLVED_REPORT_INCONSISTENT"
        assert exc_info.value.details == {
            "source": "bookmark",
            "missing": "bookmark_id",
        }

    def test_bookmark_source_with_id_is_fine(self) -> None:
        """A bookmark report needs ``bookmark_id`` only; ``bookmark`` may be None."""
        resolved = dataclasses.replace(
            self._build(None), source="bookmark", slug=None, bookmark_id=123
        )
        assert resolved.bookmark_id == 123
        assert resolved.bookmark is None
