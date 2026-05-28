"""Unit tests for SignedReplay (044-session-replay, data-model §2.2).

Critical: query_string is a bearer credential. These tests lock the masking
behaviour in __repr__/__str__ so a future refactor cannot accidentally leak
credentials into log lines or default-format output.
"""

from __future__ import annotations

import json
import time

import pytest

from mixpanel_headless.types import SignedReplay

QS = "URLPrefix=ABCDEF&Expires=1716810300&KeyName=K&Signature=zzzzzzzzzz"
URL = "https://cdn.mxpnl.com/srr-us/abc123-3713224/"


def _build(**overrides: object) -> SignedReplay:
    """Construct a SignedReplay with sensible defaults; tests override per-case."""
    defaults: dict[str, object] = {
        "replay_id": "r-19221",
        "url": URL,
        "query_string": QS,
        "env": "prod",
        "signed_at": 1716810000.0,
    }
    defaults.update(overrides)
    return SignedReplay(**defaults)  # type: ignore[arg-type]


class TestSignedReplayMasking:
    """Bearer credential never leaks into __repr__/__str__/default logging."""

    def test_repr_masks_query_string(self) -> None:
        """__repr__ replaces query_string with '<redacted N chars>'."""
        s = _build()
        r = repr(s)
        assert f"<redacted {len(QS)} chars>" in r
        assert "Signature=" not in r
        assert "URLPrefix=" not in r
        assert "Expires=" not in r

    def test_str_equals_repr(self) -> None:
        """__str__ delegates to __repr__ to keep f-string and print() safe."""
        s = _build()
        assert str(s) == repr(s)

    def test_unique_signature_chunk_does_not_leak(self) -> None:
        """The unique signature portion of the credential MUST NOT appear in repr/str.

        Uses a credential with a deliberately distinctive 16-char signature so the
        check is strong without picking up coincidental short substrings (e.g.
        ``=171`` overlapping with ``signed_at=1716810000.0``).
        """
        distinctive = (
            "URLPrefix=ABCDEFGHIJKL&Expires=NOPQRSTUVW&"
            "KeyName=KEYY&Signature=ZYXWVUTSRQPONMLK"
        )
        s = _build(query_string=distinctive)
        body = repr(s) + str(s)
        # Slide a 12-char window across the credential — none of these chunks
        # have any business showing up in repr/str.
        for start in range(0, len(distinctive) - 12):
            chunk = distinctive[start : start + 12]
            assert chunk not in body, (
                f"Query-string chunk {chunk!r} leaked into repr/str: {body!r}"
            )
        # Belt-and-braces: the distinctive Signature value MUST NOT appear.
        assert "ZYXWVUTSRQPONMLK" not in body

    def test_repr_includes_other_fields(self) -> None:
        """Non-credential fields stay visible in repr for debugging."""
        s = _build()
        r = repr(s)
        assert "r-19221" in r
        assert URL in r
        assert "'prod'" in r


class TestSignedReplayExpiration:
    """5-minute TTL — expires_at and is_expired arithmetic."""

    def test_expires_at_is_signed_at_plus_300(self) -> None:
        """SignedReplay.expires_at == signed_at + 300."""
        s = _build(signed_at=1716810000.0)
        assert s.expires_at == 1716810300.0

    def test_is_expired_false_just_before_boundary(self) -> None:
        """A URL signed 299 seconds ago is not yet expired."""
        s = _build(signed_at=time.time() - 299)
        assert not s.is_expired

    def test_is_expired_true_at_boundary(self) -> None:
        """At exactly +300s the URL is considered expired."""
        s = _build(signed_at=time.time() - 300)
        assert s.is_expired

    def test_is_expired_true_well_after(self) -> None:
        """Long-stale URLs are obviously expired."""
        s = _build(signed_at=time.time() - 10_000)
        assert s.is_expired


class TestSignedReplayToDict:
    """to_dict() is the documented escape hatch — it includes the credential."""

    def test_includes_full_credential(self) -> None:
        """to_dict preserves query_string verbatim (the documented escape hatch)."""
        d = _build().to_dict()
        assert d["query_string"] == QS

    def test_includes_warning_key(self) -> None:
        """to_dict carries the _warning key flagging the bearer-credential nature."""
        d = _build().to_dict()
        assert "_warning" in d
        assert "bearer credential" in d["_warning"]
        assert "5 minutes" in d["_warning"]

    def test_includes_every_field(self) -> None:
        """All five visible fields make it through to_dict."""
        d = _build().to_dict()
        for key in ("replay_id", "url", "query_string", "env", "signed_at"):
            assert key in d

    def test_to_dict_json_serializable(self) -> None:
        """to_dict output round-trips through json.dumps."""
        json.dumps(_build().to_dict())


class TestSignedReplayValidation:
    """Construction validation per data-model §2.2."""

    def test_url_must_end_with_slash(self) -> None:
        """url without a trailing slash is rejected."""
        with pytest.raises(ValueError, match="url"):
            _build(url="https://cdn.mxpnl.com/srr-us/abc123-3713224")

    def test_empty_query_string_rejected(self) -> None:
        """query_string must be non-empty (server contract)."""
        with pytest.raises(ValueError, match="query_string"):
            _build(query_string="")

    @pytest.mark.parametrize("bad_env", ["staging", "PROD", "test", ""])
    def test_invalid_env_rejected(self, bad_env: str) -> None:
        """env must be exactly 'prod' or 'dev'."""
        with pytest.raises(ValueError, match="env"):
            _build(env=bad_env)

    @pytest.mark.parametrize("good_env", ["prod", "dev"])
    def test_valid_env_accepted(self, good_env: str) -> None:
        """Both documented env values construct cleanly."""
        assert _build(env=good_env).env == good_env

    def test_negative_signed_at_rejected(self) -> None:
        """signed_at must be non-negative."""
        with pytest.raises(ValueError, match="signed_at"):
            _build(signed_at=-1.0)
