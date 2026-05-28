"""Unit tests for the session-replay exception hierarchy (044-session-replay)."""

from __future__ import annotations

import json

import pytest

from mixpanel_headless.exceptions import (
    APIError,
    ReplayNotFoundError,
    SessionReplayAccessError,
    SessionReplayError,
    SignedURLExpiredError,
)


class TestSessionReplayHierarchy:
    """Every new replay exception subclasses APIError via SessionReplayError."""

    @pytest.mark.parametrize(
        "exc_cls",
        [SessionReplayAccessError, SignedURLExpiredError, ReplayNotFoundError],
    )
    def test_subclass_via_session_replay_error(
        self, exc_cls: type[SessionReplayError]
    ) -> None:
        """Each leaf class is a SessionReplayError and an APIError."""
        assert issubclass(exc_cls, SessionReplayError)
        assert issubclass(exc_cls, APIError)


class TestSessionReplayAccessError:
    """403 + SESSION_RECORDING_SENSITIVE_DATA mapping (error-messages.md §1)."""

    def _build(self) -> SessionReplayAccessError:
        """Construct an instance with the canonical message + details."""
        project_id = 3713224
        message = (
            f"Project {project_id} has SESSION_RECORDING_SENSITIVE_DATA enabled. "
            f"Your account lacks sensitive-data access. Contact the project owner "
            f"to grant the 'sensitive_data_replay' permission, or use a service "
            f"account that has it."
        )
        return SessionReplayAccessError(
            message,
            details={
                "project_id": project_id,
                "flag": "SESSION_RECORDING_SENSITIVE_DATA",
                "permission_required": "sensitive_data_replay",
            },
            status_code=403,
        )

    def test_canonical_message_verbatim(self) -> None:
        """Message matches the catalog in error-messages.md §1 verbatim."""
        exc = self._build()
        assert "has SESSION_RECORDING_SENSITIVE_DATA enabled" in str(exc)
        assert "lacks sensitive-data access" in str(exc)
        assert "'sensitive_data_replay'" in str(exc)
        assert "service account" in str(exc)

    def test_status_code(self) -> None:
        """status_code is exposed via the APIError property."""
        assert self._build().status_code == 403

    def test_details_preserved(self) -> None:
        """details keys survive `.details` access."""
        exc = self._build()
        assert exc.details["project_id"] == 3713224
        assert exc.details["flag"] == "SESSION_RECORDING_SENSITIVE_DATA"
        assert exc.details["permission_required"] == "sensitive_data_replay"

    def test_to_dict_round_trip(self) -> None:
        """details keys survive a to_dict() round-trip and are JSON-serializable."""
        exc = self._build()
        d = exc.to_dict()
        assert d["details"]["project_id"] == 3713224
        assert d["details"]["flag"] == "SESSION_RECORDING_SENSITIVE_DATA"
        assert d["details"]["permission_required"] == "sensitive_data_replay"
        # Ensure the whole dict is JSON-serializable.
        json.dumps(d)


class TestSignedURLExpiredError:
    """Signed-URL 5-min TTL expiry (error-messages.md §2)."""

    def _build(self) -> SignedURLExpiredError:
        """Construct an instance with the canonical message + details."""
        replay_id = "r-19221"
        message = (
            f"Signed URL for replay {replay_id} expired (5-minute TTL). "
            f"Re-sign with sign_replay({replay_id!r}) or use the default "
            f"re_sign_on_expiry=True on stream_replay."
        )
        return SignedURLExpiredError(
            message,
            details={
                "replay_id": replay_id,
                "signed_at": 1716810000.0,
                "expired_at": 1716810300.0,
            },
            status_code=403,
        )

    def test_canonical_message_verbatim(self) -> None:
        """Message matches the catalog in error-messages.md §2 verbatim."""
        exc = self._build()
        assert "Signed URL for replay r-19221 expired (5-minute TTL)" in str(exc)
        assert "Re-sign with sign_replay('r-19221')" in str(exc)
        assert "re_sign_on_expiry=True" in str(exc)

    def test_status_code(self) -> None:
        """status_code is exposed via the APIError property."""
        assert self._build().status_code == 403

    def test_details_round_trip(self) -> None:
        """details keys survive a to_dict() round-trip."""
        d = self._build().to_dict()
        assert d["details"]["replay_id"] == "r-19221"
        assert d["details"]["signed_at"] == 1716810000.0
        assert d["details"]["expired_at"] == 1716810300.0
        json.dumps(d)


class TestReplayNotFoundError:
    """404 on first CDN file (error-messages.md §3)."""

    def _build(self) -> ReplayNotFoundError:
        """Construct an instance with the canonical message + details."""
        replay_id = "r-19221"
        retention_days = 30
        url_prefix = "https://cdn.mxpnl.com/srr-us/abc123-3713224/"
        message = (
            f"Replay {replay_id} not found on CDN. The replay may have aged out "
            f"of its retention window ({retention_days} days), never been recorded, "
            f"or been deleted."
        )
        return ReplayNotFoundError(
            message,
            details={
                "replay_id": replay_id,
                "retention_days": retention_days,
                "cdn_url_prefix": url_prefix,
            },
            status_code=404,
        )

    def test_canonical_message_verbatim(self) -> None:
        """Message matches the catalog in error-messages.md §3 verbatim."""
        exc = self._build()
        assert "not found on CDN" in str(exc)
        assert "aged out of its retention window (30 days)" in str(exc)
        assert "never been recorded" in str(exc)

    def test_status_code(self) -> None:
        """status_code is exposed via the APIError property."""
        assert self._build().status_code == 404

    def test_details_round_trip(self) -> None:
        """details keys survive a to_dict() round-trip."""
        d = self._build().to_dict()
        assert d["details"]["replay_id"] == "r-19221"
        assert d["details"]["retention_days"] == 30
        assert (
            d["details"]["cdn_url_prefix"]
            == "https://cdn.mxpnl.com/srr-us/abc123-3713224/"
        )
        json.dumps(d)


class TestCatchByBaseClass:
    """Callers can catch any session-replay error with the base class."""

    def test_catch_access_error_as_session_replay_error(self) -> None:
        """SessionReplayAccessError raises as SessionReplayError."""
        with pytest.raises(SessionReplayError):
            raise SessionReplayAccessError(
                "msg",
                details={"project_id": 1},
                status_code=403,
            )

    def test_catch_expired_error_as_session_replay_error(self) -> None:
        """SignedURLExpiredError raises as SessionReplayError."""
        with pytest.raises(SessionReplayError):
            raise SignedURLExpiredError("msg", status_code=403)

    def test_catch_not_found_as_session_replay_error(self) -> None:
        """ReplayNotFoundError raises as SessionReplayError."""
        with pytest.raises(SessionReplayError):
            raise ReplayNotFoundError("msg", status_code=404)

    def test_catch_session_replay_error_as_api_error(self) -> None:
        """SessionReplayError raises as APIError (so existing handlers work)."""
        with pytest.raises(APIError):
            raise SessionReplayAccessError(
                "msg",
                details={"project_id": 1},
                status_code=403,
            )
