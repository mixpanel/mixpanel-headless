"""Tests for the Phase-2 contract-artifact generator (phase2-design C2/C3/C5/C8).

Covers the P2-1 done-criteria: artifact shapes match the measured
ground-truth inventory, the tag universe is built by a JSON-aware walk and
verified here against an INDEPENDENT JSON-aware scan (never grep — the
escaped ``\\"$type\\"`` pseudo-tag hazard is demonstrated explicitly), and
re-runs are byte-deterministic for a fixed ``--generated-from`` stamp.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from conformance.contract.generate_contract import (
    ARTIFACT_NAMES,
    BUILTIN_TAGS,
    DEFAULT_VECTORS_DIR,
    build_error_codes,
    build_literal_aliases,
    build_model_coverage,
    build_tag_universe,
    collect_tag_counts,
    load_coverage_overrides,
    main,
    write_artifacts,
)

_STAMP = "0000000000000000000000000000000000000000"
"""Fixed provenance stamp for deterministic test artifacts."""


@pytest.fixture(scope="module")
def error_codes() -> dict[str, Any]:
    """Build the error-codes artifact body once per module.

    Returns:
        The ``error-codes.json`` body.
    """
    return build_error_codes(_STAMP)


@pytest.fixture(scope="module")
def literal_aliases() -> dict[str, Any]:
    """Build the literal-aliases artifact body once per module.

    Returns:
        The ``literal-aliases.json`` body.
    """
    return build_literal_aliases(_STAMP)


@pytest.fixture(scope="module")
def tag_universe() -> dict[str, Any]:
    """Build the tag-universe artifact body once per module.

    Returns:
        The ``tag-universe.json`` body over the committed corpus.
    """
    return build_tag_universe(DEFAULT_VECTORS_DIR, _STAMP)


@pytest.fixture(scope="module")
def model_coverage() -> dict[str, Any]:
    """Build the model-coverage artifact body once per module.

    Returns:
        The ``model-coverage.json`` body over the committed corpus.
    """
    return build_model_coverage(DEFAULT_VECTORS_DIR, _STAMP)


class TestErrorCodesArtifact:
    """Shape and content locks for ``error-codes.json`` (design C3)."""

    def test_exception_class_census(self, error_codes: dict[str, Any]) -> None:
        """All 28 exported exception classes appear, with one root.

        Args:
            error_codes: The artifact body.

        Raises:
            AssertionError: If the census or parent edges are wrong.
        """
        classes = error_codes["exception_classes"]
        assert len(classes) == 28
        roots = [name for name, parent in classes.items() if parent is None]
        assert roots == ["MixpanelHeadlessError"]
        for name, parent in classes.items():
            assert parent is None or parent in classes, name

    def test_parent_edges_spot_checks(self, error_codes: dict[str, Any]) -> None:
        """Known hierarchy edges are recorded (C3 tree).

        Args:
            error_codes: The artifact body.

        Raises:
            AssertionError: If a known edge deviates.
        """
        classes = error_codes["exception_classes"]
        assert classes["APIError"] == "MixpanelHeadlessError"
        assert classes["ParamValidationError"] == "MixpanelHeadlessError"
        assert classes["SessionReplayError"] == "APIError"
        assert classes["SignedURLExpiredError"] == "SessionReplayError"
        assert classes["AccountNotFoundError"] == "ConfigError"
        assert classes["RegionProbeNetworkError"] == "RegionProbeError"

    def test_default_codes(self, error_codes: dict[str, Any]) -> None:
        """Every class carries its default code; spot-check known values.

        Args:
            error_codes: The artifact body.

        Raises:
            AssertionError: If a default code is missing or wrong.
        """
        codes = error_codes["default_codes"]
        assert set(codes) == set(error_codes["exception_classes"])
        assert codes["MixpanelHeadlessError"] == "UNKNOWN_ERROR"
        assert codes["ParamValidationError"] == "VALIDATION_ERROR"
        assert codes["ParamTypeError"] == "VALIDATION_ERROR"
        assert codes["ResponseValidationError"] == "RESPONSE_VALIDATION_ERROR"
        assert codes["APIError"] == "API_ERROR"
        # Instantiation-derived codes (no ``code=`` signature default).
        assert codes["AccountNotFoundError"] == "ACCOUNT_NOT_FOUND"
        assert codes["DateRangeTooLargeError"] == "DATE_RANGE_TOO_LARGE"
        assert codes["InvalidArgumentError"] == "INVALID_ARGUMENT"
        assert codes["WorkspaceScopeError"] == "NO_WORKSPACES"

    def test_registry_matches_runtime_sets(self, error_codes: dict[str, Any]) -> None:
        """Registry lists equal the live frozensets, sorted (no filtering).

        Args:
            error_codes: The artifact body.

        Raises:
            AssertionError: If either list drifts from the runtime set.
        """
        from mixpanel_headless import exceptions as exceptions_module

        registry = error_codes["coded_guard_registry"]
        twins = error_codes["coded_guard_twin_codes"]
        assert registry == sorted(exceptions_module.CODED_GUARD_REGISTRY)
        assert twins == sorted(exceptions_module.CODED_GUARD_TWIN_CODES)
        assert len(registry) == 120
        assert len(twins) == 9

    def test_registry_keeps_all_code_families(
        self, error_codes: dict[str, Any]
    ) -> None:
        """CF/CB/CA/UA constructor codes and BB builder codes are present.

        Design F6: the registry-equality gate compares FULL sets — the
        Phase-3 BB1-BB8 family and every Phase-2 constructor-guard family
        must survive into the artifact unfiltered.

        Args:
            error_codes: The artifact body.

        Raises:
            AssertionError: If any family member is missing.
        """
        registry = set(error_codes["coded_guard_registry"])
        for expected in (
            "CF1_COHORT_ID_NOT_POSITIVE",
            "CF2_COHORT_NAME_EMPTY",
            "CB1_COHORT_ID_NOT_POSITIVE",
            "CB2_COHORT_NAME_EMPTY",
            "CA1_AGGREGATION_PAIR",
            "CA2_EMPTY_AGGREGATION_PROPERTY",
            "UA1_TIMESTAMP_NOT_POSITIVE",
            "UA2_EMPTY_TARGET_DESC",
            "BB1_GROUP_BY_ELEMENT_TYPE",
            "BB8_COHORT_KEY_MISSING",
            "EV1_EMPTY_EVENT",
            "EV2_CONTROL_CHAR_EVENT",
            "CD7_EMPTY_PROPERTY",
        ):
            assert expected in registry, expected


class TestLiteralAliasesArtifact:
    """Shape and content locks for ``literal-aliases.json`` (design C2)."""

    def test_alias_and_enum_census(self, literal_aliases: dict[str, Any]) -> None:
        """37 distinct Literal aliases and 8 Enum classes are captured.

        Args:
            literal_aliases: The artifact body.

        Raises:
            AssertionError: If the census drifts.
        """
        assert len(literal_aliases["literal_aliases"]) == 37
        assert len(literal_aliases["enums"]) == 8

    def test_alias_members_spot_checks(self, literal_aliases: dict[str, Any]) -> None:
        """Known alias member tuples survive in declaration order.

        Args:
            literal_aliases: The artifact body.

        Raises:
            AssertionError: If a member tuple deviates.
        """
        aliases = literal_aliases["literal_aliases"]
        assert aliases["TimeUnit"] == ["day", "week", "month"]
        assert aliases["Region"] == ["us", "eu", "in"]
        assert aliases["AccountType"] == [
            "service_account",
            "oauth_browser",
            "oauth_token",
        ]
        # BookmarkType is a Literal alias in the Python source — the C2
        # source-kind-wins ruling — and BookmarkTypeLiteral is NOT public.
        assert "BookmarkType" in aliases
        assert "BookmarkTypeLiteral" not in aliases

    def test_enum_kinds_and_members(self, literal_aliases: dict[str, Any]) -> None:
        """The 7 str Enums and the one IntEnum carry kind + members.

        Args:
            literal_aliases: The artifact body.

        Raises:
            AssertionError: If a kind or member map deviates.
        """
        enums = literal_aliases["enums"]
        kinds = Counter(entry["kind"] for entry in enums.values())
        assert kinds == Counter({"str": 7, "int": 1})
        assert enums["AlertFrequencyPreset"]["kind"] == "int"
        assert enums["FeatureFlagStatus"]["kind"] == "str"
        assert all(entry["members"] for entry in enums.values())

    def test_newtypes(self, literal_aliases: dict[str, Any]) -> None:
        """The 4 auth NewType identifiers map to their supertypes.

        Args:
            literal_aliases: The artifact body.

        Raises:
            AssertionError: If the NewType map deviates.
        """
        assert literal_aliases["newtypes"] == {
            "AccountName": "str",
            "ProjectId": "str",
            "TargetName": "str",
            "WorkspaceId": "int",
        }


def _independent_tag_scan(vectors_dir: Path) -> dict[str, int]:
    """Independently tally ``$type`` tags with a parse-time hook.

    Deliberately a DIFFERENT mechanism from the generator's recursive
    post-parse walk: a ``json.JSONDecoder`` ``object_pairs_hook`` observes
    every object's key/value pairs during decoding, so string payloads
    containing escaped ``\\"$type\\"`` text can never register.

    Args:
        vectors_dir: The corpus root.

    Returns:
        Tag -> occurrence count over all corpus JSONL lines.
    """
    counts: Counter[str] = Counter()

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """Tally ``$type`` keys as objects decode.

        Args:
            pairs: The object's key/value pairs in document order.

        Returns:
            The materialized dict (decoding proceeds unchanged).
        """
        for key, value in pairs:
            if key == "$type" and isinstance(value, str):
                counts[value] += 1
        return dict(pairs)

    decoder = json.JSONDecoder(object_pairs_hook=hook)
    for path in sorted(vectors_dir.rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                decoder.decode(line)
    return dict(counts)


class TestTagUniverseArtifact:
    """JSON-aware tag census locks for ``tag-universe.json`` (design C8a)."""

    def test_matches_independent_json_aware_scan(
        self, tag_universe: dict[str, Any]
    ) -> None:
        """The generator's walk agrees with an independent JSON-aware scan.

        P2-1 done-criterion: the tag universe MUST be verified against an
        independently implemented JSON-aware scan, never grep.

        Args:
            tag_universe: The artifact body.

        Raises:
            AssertionError: If the two scans disagree on tags or counts.
        """
        independent = _independent_tag_scan(DEFAULT_VECTORS_DIR)
        artifact_observed = {
            tag: count for tag, count in tag_universe["tags"].items() if count > 0
        }
        assert artifact_observed == independent
        assert collect_tag_counts(DEFAULT_VECTORS_DIR) == independent

    def test_ground_truth_census(self, tag_universe: dict[str, Any]) -> None:
        """85 observed tags, 80 rich; ``date`` registered-but-unexercised.

        Args:
            tag_universe: The artifact body.

        Raises:
            AssertionError: If the census drifts from the measured
                inventory (re-measure before adjusting).
        """
        tags = tag_universe["tags"]
        observed = [tag for tag, count in tags.items() if count > 0]
        assert len(observed) == 85
        assert len(tag_universe["rich_tags"]) == 80
        assert sorted(tag_universe["built_in_tags"]) == sorted(BUILTIN_TAGS)
        assert tags["date"] == 0
        assert tags["datetime"] > 0
        assert tags["SecretStr"] > 0
        assert "OAuthTokens" in tag_universe["rich_tags"]

    def test_rich_tags_are_phase2_type_names(
        self, tag_universe: dict[str, Any]
    ) -> None:
        """Every rich tag is an exported type name (design inventory claim).

        Args:
            tag_universe: The artifact body.

        Raises:
            AssertionError: If a rich tag is not an exported name.
        """
        import mixpanel_headless as mp
        import mixpanel_headless.auth_types as auth_types

        exported = set(mp.__all__) | set(auth_types.__all__)
        stray = [tag for tag in tag_universe["rich_tags"] if tag not in exported]
        assert stray == []

    def test_builtin_tags_match_live_codec_module(self) -> None:
        """The built-in constant tracks the live codec table behaviorally.

        Encodes an exemplar of each built-in through the record codecs and
        asserts the emitted tag; ``callback``/``float`` are asserted via
        their decode arms (their encode sides are input-position rules).

        Raises:
            AssertionError: If a built-in stops round-tripping under its
                declared tag.
        """
        import datetime

        from pydantic import SecretStr

        from conformance.record.codecs import decode_value, encode_expect_value

        assert encode_expect_value(datetime.datetime(2026, 1, 1, 12, 0))["$type"] == (
            "datetime"
        )
        assert encode_expect_value(datetime.date(2026, 1, 1))["$type"] == "date"
        assert encode_expect_value(SecretStr("s3"))["$type"] == "SecretStr"
        assert encode_expect_value(b"\x00\x01")["$type"] == "bytes"
        callback = decode_value({"$type": "callback", "name": "on_batch"})
        assert callable(callback)
        assert decode_value({"$type": "float", "value": "NaN"}) != 0

    def test_grep_style_scan_is_unsafe(self) -> None:
        """A raw-text ``$type`` regex sees pseudo-tags a JSON walk must not.

        The canonical-selftest fixture (shipped inside the TS corpus
        snapshot alongside the vectors) embeds escaped ``\\"$type\\"``
        text INSIDE string payloads; a grep-style scanner counts them,
        the JSON-aware walk correctly does not.

        Raises:
            AssertionError: If the hazard fixture loses its embedded
                pseudo-tags (the guard would go vacuous).
        """
        selftest = DEFAULT_VECTORS_DIR.parent / "schema" / "canonical-selftest.json"
        text = selftest.read_text(encoding="utf-8")
        naive = re.findall(r'\\"\$type\\":\s*\\"([^"\\]+)', text)
        assert naive, "hazard fixture no longer embeds escaped $type text"
        counts: Counter[str] = Counter()
        parsed = json.loads(text)
        from conformance.contract.generate_contract import _walk_tags

        _walk_tags(parsed, counts)
        # The escaped occurrences live inside string VALUES: the JSON-aware
        # walk must see strictly fewer than raw-text matching would.
        raw_total = len(re.findall(r"\$type", text))
        assert sum(counts.values()) < raw_total


class TestModelCoverageArtifact:
    """Locks for ``model-coverage.json`` (design C5 item 5)."""

    def test_covers_all_exported_models(self, model_coverage: dict[str, Any]) -> None:
        """All 125 exported Pydantic models are accounted for.

        Args:
            model_coverage: The artifact body.

        Raises:
            AssertionError: If the census or row shape drifts.
        """
        assert model_coverage["model_count"] == 125
        assert len(model_coverage["models"]) == 125
        for name, row in model_coverage["models"].items():
            assert row["status"] in (
                "corpus_tag",
                "entity_golden",
                "authored_fixture",
                "deferred",
            ), name
            if row["status"] == "authored_fixture":
                assert isinstance(row["authored_fixture"], str), name
                assert row["authored_fixture"], name
            else:
                assert row["authored_fixture"] is None, name
            assert row["deferral"] is None, name

    def test_status_reflects_evidence(self, model_coverage: dict[str, Any]) -> None:
        """Statuses follow the corpus-tag > entity-golden > unresolved rule.

        Args:
            model_coverage: The artifact body.

        Raises:
            AssertionError: If a status contradicts its evidence fields.
        """
        for name, row in model_coverage["models"].items():
            if row["corpus_tag_occurrences"] > 0:
                assert row["status"] == "corpus_tag", name
            elif row["entity_golden_vector_ids"]:
                assert row["status"] == "entity_golden", name
            else:
                # P2-7: every mechanically-unresolved model is resolved by
                # the committed coverage_overrides.json table — NO model
                # may remain unresolved (design C5 item 5 done-criterion).
                assert row["status"] in ("authored_fixture", "deferred"), name

    def test_known_models_spot_checks(self, model_coverage: dict[str, Any]) -> None:
        """Known models land in their expected coverage buckets.

        ``CreateBookmarkParams`` rides ``call.input`` as a ``$type`` tag;
        ``Dashboard`` never appears as a tag but its CRUD wire vectors
        carry plain ``expect.result`` payloads (the V1 finding).

        Args:
            model_coverage: The artifact body.

        Raises:
            AssertionError: If a spot-checked bucket deviates.
        """
        models = model_coverage["models"]
        assert models["CreateBookmarkParams"]["status"] == "corpus_tag"
        # OAuthTokens is auth_types-only (not in the 125 top-level models);
        # its runtime lock is its corpus tag, asserted in the tag-universe
        # tests above.
        assert "OAuthTokens" not in models
        assert models["Dashboard"]["status"] == "entity_golden"
        assert models["Dashboard"]["entity_golden_vector_ids"]
        assert models["Cohort"]["status"] == "entity_golden"

    def test_hint_failures_are_named(self, model_coverage: dict[str, Any]) -> None:
        """Unresolvable return annotations are listed, never dropped.

        Args:
            model_coverage: The artifact body.

        Raises:
            AssertionError: If the known failure set changes silently.
        """
        assert model_coverage["hint_failures"] == ["pagination.paginate_all"]


class TestCoverageOverrides:
    """The P2-7 hand-maintained override table (design C5 item 5)."""

    def test_committed_table_resolves_every_model(
        self, model_coverage: dict[str, Any]
    ) -> None:
        """No model remains ``unresolved`` with the committed table.

        Args:
            model_coverage: The artifact body.

        Raises:
            AssertionError: If any model lacks all four evidence kinds.
        """
        unresolved = [
            name
            for name, row in model_coverage["models"].items()
            if row["status"] == "unresolved"
        ]
        assert unresolved == []

    def test_committed_table_shape(self) -> None:
        """The committed table parses and points at TS test paths.

        Raises:
            AssertionError: If a fixture value is not a TS test path.
        """
        overrides = load_coverage_overrides()
        assert overrides["deferrals"] == {}
        assert len(overrides["authored_fixtures"]) == 31
        for name, path in overrides["authored_fixtures"].items():
            assert path.endswith(".test.ts"), name

    def test_unknown_model_rejected(self) -> None:
        """An override naming a non-model is a hard error.

        Raises:
            AssertionError: If the generator accepts the bogus row.
        """
        overrides = {
            "authored_fixtures": {"NotAModel": "x.test.ts"},
            "deferrals": {},
        }
        with pytest.raises(ValueError, match="unknown models"):
            build_model_coverage(DEFAULT_VECTORS_DIR, _STAMP, overrides)

    def test_stale_override_rejected(self) -> None:
        """An override for a mechanically-resolved model is a hard error.

        Raises:
            AssertionError: If the generator accepts the stale row.
        """
        overrides = {
            "authored_fixtures": {"Dashboard": "x.test.ts"},
            "deferrals": {},
        }
        with pytest.raises(ValueError, match="stale coverage override"):
            build_model_coverage(DEFAULT_VECTORS_DIR, _STAMP, overrides)

    def test_double_booking_rejected(self) -> None:
        """A model in BOTH maps is a hard error.

        Raises:
            AssertionError: If the generator accepts the double row.
        """
        overrides = {
            "authored_fixtures": {"Target": "x.test.ts"},
            "deferrals": {"Target": {"reason": "r", "owner": "o"}},
        }
        with pytest.raises(ValueError, match="BOTH override maps"):
            build_model_coverage(DEFAULT_VECTORS_DIR, _STAMP, overrides)

    def test_deferral_rows_apply(self) -> None:
        """A deferral row lands as ``status: deferred`` with its payload.

        Raises:
            AssertionError: If the deferral row is not applied.
        """
        base = load_coverage_overrides()
        fixtures = dict(base["authored_fixtures"])
        deferral = {"reason": "phase-3 accounts batch", "owner": "B7"}
        fixtures.pop("Target")
        overrides = {"authored_fixtures": fixtures, "deferrals": {"Target": deferral}}
        body = build_model_coverage(DEFAULT_VECTORS_DIR, _STAMP, overrides)
        row = body["models"]["Target"]
        assert row["status"] == "deferred"
        assert row["deferral"] == deferral
        assert row["authored_fixture"] is None


class TestDeterminismAndCli:
    """Byte-determinism and CLI behavior (P2-1 done-criterion)."""

    def test_rerun_is_byte_identical(self, tmp_path: Path) -> None:
        """Two runs with the same stamp produce byte-identical artifacts.

        Args:
            tmp_path: pytest-provided scratch directory.

        Raises:
            AssertionError: If any artifact differs between runs.
        """
        first = write_artifacts(tmp_path / "a", DEFAULT_VECTORS_DIR, _STAMP)
        second = write_artifacts(tmp_path / "b", DEFAULT_VECTORS_DIR, _STAMP)
        assert set(first) == set(ARTIFACT_NAMES)
        for name in ARTIFACT_NAMES:
            assert first[name].read_bytes() == second[name].read_bytes(), name

    def test_stamp_is_injected_verbatim(self, tmp_path: Path) -> None:
        """The provenance stamp is written verbatim into every artifact.

        Args:
            tmp_path: pytest-provided scratch directory.

        Raises:
            AssertionError: If any artifact drops or rewrites the stamp.
        """
        written = write_artifacts(tmp_path, DEFAULT_VECTORS_DIR, "abc123")
        for name in ARTIFACT_NAMES:
            body = json.loads(written[name].read_text(encoding="utf-8"))
            assert body["generated_from"] == "abc123", name

    def test_main_writes_all_artifacts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The CLI writes all four artifacts and reports each path.

        Args:
            tmp_path: pytest-provided scratch directory.
            capsys: pytest stdout/stderr capture.

        Raises:
            AssertionError: If an artifact or report line is missing.
        """
        exit_code = main(
            [
                "--generated-from",
                _STAMP,
                "--out",
                str(tmp_path),
                "--vectors",
                str(DEFAULT_VECTORS_DIR),
            ]
        )
        assert exit_code == 0
        output = capsys.readouterr().out
        for name in ARTIFACT_NAMES:
            assert (tmp_path / name).is_file(), name
            assert name in output
