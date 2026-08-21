"""Round-trip unit tests for the full ``$type`` codec table (design D4.4).

One test per codec: encode the rich value into vector JSON (must be
``json.dumps``-safe), decode it back through the D7 replay path, and assert
equality with the original. The tagged encodings themselves are asserted
for the scalar codecs (``datetime``/``SecretStr``/``bytes``/``callback``)
because the TS mirror table (``conformance-runner/src/codecs.ts``) is built
against exactly these shapes.
"""

from __future__ import annotations

import datetime
import json
import math
from typing import Any

import pytest
from pydantic import SecretStr

from conformance.record.codecs import (
    RecordingCallback,
    UndecodableValueError,
    UnencodableValueError,
    decode_input_kwargs,
    decode_value,
    encode_input_kwargs,
    encode_input_value,
)
from mixpanel_headless.types import (
    CohortBreakdown,
    CohortCriteria,
    CohortDefinition,
    CohortMetric,
    Filter,
    FlowStep,
    Formula,
    FrequencyBreakdown,
    FrequencyFilter,
    FunnelStep,
    GroupBy,
    InlineCustomProperty,
    Metric,
    PropertyInput,
    RetentionEvent,
    TimeComparison,
    UserAction,
)


def _round_trip(value: object) -> Any:
    """Encode a value to vector JSON and decode it back (design D4.4/D7).

    Also proves the encoding is JSON-serializable — the property the
    corpus depends on.

    Args:
        value: The rich input value.

    Returns:
        The decoded reconstruction.
    """
    encoded = encode_input_value(value)
    json.dumps(encoded)
    return decode_value(encoded)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(Filter.equals("country", "US"), id="Filter-equals"),
        pytest.param(Filter.between("amount", 10, 100), id="Filter-between"),
        pytest.param(Filter.is_set("email"), id="Filter-is-set"),
        pytest.param(Metric(event="Login", math="total"), id="Metric"),
        pytest.param(
            Metric(
                event="Purchase",
                math="average",
                property="amount",
                filters=[Filter.equals("plan", "pro")],
            ),
            id="Metric-nested-filters",
        ),
        pytest.param(Formula(expression="A/B", label="ratio"), id="Formula"),
        pytest.param(GroupBy(property="plan"), id="GroupBy"),
        pytest.param(TimeComparison(type="relative", unit="day"), id="TimeComparison"),
        pytest.param(
            FunnelStep(event="Signup", filters=[Filter.equals("plan", "pro")]),
            id="FunnelStep",
        ),
        pytest.param(RetentionEvent(event="Login"), id="RetentionEvent"),
        pytest.param(FlowStep(event="Login", forward=2), id="FlowStep"),
        pytest.param(CohortMetric(cohort=456, name="savers"), id="CohortMetric"),
        pytest.param(
            FrequencyBreakdown(
                event="Login", bucket_size=1, bucket_min=0, bucket_max=10
            ),
            id="FrequencyBreakdown",
        ),
        pytest.param(
            FrequencyFilter(event="Login", value=3, operator="is at least"),
            id="FrequencyFilter",
        ),
        pytest.param(
            UserAction(
                timestamp=1,
                action="click",
                target_node_id=5,
                target_desc="button",
                url="https://x.test",
                metadata={"a": 1},
                description="Clicked button",
            ),
            id="UserAction",
        ),
        pytest.param(
            InlineCustomProperty(
                formula="a + b",
                inputs={
                    "a": PropertyInput(
                        name="amount", type="number", resource_type="event"
                    )
                },
            ),
            id="InlineCustomProperty",
        ),
    ],
)
def test_dataclass_codecs_round_trip(value: object) -> None:
    """Each D4.4 dataclass codec reconstructs an equal instance.

    Args:
        value: The parametrized rich value.

    Raises:
        AssertionError: If decode(encode(value)) != value.
    """
    assert _round_trip(value) == value


def test_filter_list_contains_restores_tuple_fields() -> None:
    """Tuple-typed dataclass fields survive the JSON list round trip.

    ``Filter._list_item_filters`` is ``tuple[Filter, ...]`` — decode must
    coerce the JSON array back to a tuple or reconstruction and equality
    both break (``__post_init__`` re-validates list_contains mode).

    Raises:
        AssertionError: If the tuple field comes back as a list or unequal.
    """
    original = Filter.list_contains(
        "items", Filter.equals("sku", "A"), quantifier="any"
    )
    decoded = _round_trip(original)
    assert decoded == original
    assert isinstance(decoded._list_item_filters, tuple)


def test_cohort_definition_round_trip_preserves_to_dict() -> None:
    """``CohortDefinition`` (init=False) reconstructs via all_of/any_of.

    Equality is asserted on ``to_dict()`` output — the class's public
    contract — because reconstruction goes through the classmethods, and
    on the operator/criteria fields directly.

    Raises:
        AssertionError: If the reconstructed definition serializes
            differently.
    """
    original = CohortDefinition.any_of(
        CohortCriteria.did_event("Purchase", at_least=3, within_days=30),
        CohortDefinition.all_of(CohortCriteria.has_property("plan", "premium")),
    )
    decoded = _round_trip(original)
    assert isinstance(decoded, CohortDefinition)
    assert decoded.to_dict() == original.to_dict()
    assert decoded._operator == "or"


def test_cohort_breakdown_with_inline_definition_round_trips() -> None:
    """Nested ``CohortDefinition`` inside ``CohortBreakdown`` decodes.

    Raises:
        AssertionError: If the nested definition serializes differently.
    """
    original = CohortBreakdown(
        cohort=CohortDefinition.all_of(CohortCriteria.has_property("plan", "premium")),
        name="premium",
    )
    decoded = _round_trip(original)
    assert isinstance(decoded, CohortBreakdown)
    assert isinstance(decoded.cohort, CohortDefinition)
    assert decoded.cohort.to_dict() == original.cohort.to_dict()  # type: ignore[union-attr]
    assert decoded.name == "premium"


def test_datetime_codec_round_trip() -> None:
    """``datetime`` values tag as ``{"$type": "datetime", "iso": ...}``.

    Raises:
        AssertionError: If the tagged shape or reconstruction is wrong.
    """
    original = datetime.datetime(2026, 1, 15, 12, 0, 0)
    encoded = encode_input_value(original)
    assert encoded == {"$type": "datetime", "iso": "2026-01-15T12:00:00"}
    assert decode_value(encoded) == original


def test_date_codec_round_trip() -> None:
    """``date`` values tag as ``{"$type": "date", "iso": ...}``.

    Raises:
        AssertionError: If the tagged shape or reconstruction is wrong.
    """
    original = datetime.date(2026, 1, 15)
    encoded = encode_input_value(original)
    assert encoded == {"$type": "date", "iso": "2026-01-15"}
    assert decode_value(encoded) == original


def test_secret_str_codec_round_trip() -> None:
    """``SecretStr`` serializes revealed (D5.5) and reconstructs.

    Raises:
        AssertionError: If the value is masked or lost.
    """
    encoded = encode_input_value(SecretStr("test_secret"))
    assert encoded == {"$type": "SecretStr", "value": "test_secret"}
    decoded = decode_value(encoded)
    assert isinstance(decoded, SecretStr)
    assert decoded.get_secret_value() == "test_secret"


def test_bytes_codec_round_trip() -> None:
    """``bytes`` values round-trip through base64 tagging (design D4.4).

    Raises:
        AssertionError: If the payload bytes change.
    """
    original = b"\x00\x01,csv,bytes\n"
    encoded = encode_input_value(original)
    assert encoded["$type"] == "bytes"
    assert encoded["encoding"] == "base64"
    assert decode_value(encoded) == original


def test_callback_codec_yields_recording_stub() -> None:
    """``callback`` kwargs decode to :class:`RecordingCallback` stubs (D4.4).

    The stub logs encoded positional args — the ``expect.callback_calls``
    diff surface for both runners.

    Raises:
        AssertionError: If the tag shape, stub type, or call log is wrong.
    """

    def on_batch(batch: list[dict[str, int]]) -> None:
        """Test callback placeholder.

        Args:
            batch: Unused.
        """
        del batch

    encoded = encode_input_kwargs({"on_batch": on_batch})
    assert encoded == {"on_batch": {"$type": "callback", "name": "on_batch"}}
    decoded = decode_input_kwargs(encoded)
    stub = decoded["on_batch"]
    assert isinstance(stub, RecordingCallback)
    stub([{"event": 1}], 7)
    stub([{"event": 2}])
    assert stub.calls == [[[{"event": 1}], 7], [[{"event": 2}]]]


def test_plain_json_passes_through_decode() -> None:
    """Untagged JSON structures decode to themselves, recursively.

    Raises:
        AssertionError: If plain values are altered.
    """
    value = {"a": [1, 2.5, "x", None, True], "b": {"nested": []}}
    assert decode_value(value) == value


def test_unknown_type_tag_raises() -> None:
    """An unknown ``$type`` fails decode loudly (design D4.4 table pact).

    Raises:
        AssertionError: If no :class:`UndecodableValueError` is raised.
    """
    with pytest.raises(UndecodableValueError, match="no codec for"):
        decode_value({"$type": "NotARealType", "x": 1})


def test_unknown_dataclass_field_raises() -> None:
    """Extra fields on a tagged dataclass payload fail decode loudly.

    Raises:
        AssertionError: If no :class:`UndecodableValueError` is raised.
    """
    encoded = encode_input_value(Formula(expression="A"))
    assert isinstance(encoded, dict)
    encoded["not_a_field"] = 1
    with pytest.raises(UndecodableValueError, match="unknown fields"):
        decode_value(encoded)


def test_malformed_bytes_encoding_raises() -> None:
    """A bytes tag with an unknown encoding fails decode loudly.

    Raises:
        AssertionError: If no :class:`UndecodableValueError` is raised.
    """
    with pytest.raises(UndecodableValueError):
        decode_value({"$type": "bytes", "encoding": "hex", "data": "00"})


def test_secretstr_inside_pydantic_model_is_revealed() -> None:
    """SecretStr model fields encode revealed, never masked (design D5.5).

    ``model_dump(mode="json")`` masks secrets to ``"**********"``; the
    field-level encoder must reveal the fake test literal so replay can
    reconstruct the value (PR-5 regression: ``OAuthTokens`` vectors).

    Raises:
        AssertionError: If the mask leaks into the encoding.
    """
    from mixpanel_headless._internal.auth.token import OAuthTokens

    tokens = OAuthTokens(
        access_token=SecretStr("access-tok-123"),
        refresh_token=SecretStr("refresh-tok-456"),
        expires_at=datetime.datetime(
            2026, 1, 15, 13, 0, 0, tzinfo=datetime.timezone.utc
        ),
        scope="projects",
        token_type="Bearer",
    )
    from conformance.record.codecs import encode_expect_value

    encoded = encode_input_value(tokens)
    assert encoded["$type"] == "OAuthTokens"
    assert encoded["access_token"] == {"$type": "SecretStr", "value": "access-tok-123"}
    assert encoded["refresh_token"] == {
        "$type": "SecretStr",
        "value": "refresh-tok-456",
    }
    assert encoded["expires_at"]["$type"] == "datetime"
    expect_side = encode_expect_value(tokens)
    assert expect_side["access_token"] == {
        "$type": "SecretStr",
        "value": "access-tok-123",
    }


def test_mock_arguments_are_unencodable() -> None:
    """unittest.mock arguments raise instead of encoding a false callback.

    PR-5 audit regression: ``MagicMock(spec=CohortDefinition)`` with a
    raising ``to_dict`` was encoded as ``$type: callback`` and replayed as
    a benign stub, silently flipping the U24 contract.

    Raises:
        AssertionError: If a mock encodes without error.
    """
    from unittest.mock import MagicMock, Mock

    from conformance.record.codecs import UnencodableValueError

    for double in (MagicMock(), Mock(), MagicMock(spec=CohortDefinition)):
        with pytest.raises(UnencodableValueError):
            encode_input_kwargs({"cohort": double})


def test_public_type_fallback_round_trips_params_models() -> None:
    """Wire Params models decode via the mechanical public-type fallback.

    The hand table covers builder dataclasses only; the PR-5 audit found
    61 wire-input tags (Params models, ``OAuthTokens``, ``HoldingConstant``)
    that must decode for the runner to replay entity CRUD vectors.

    Raises:
        AssertionError: If a round trip loses equality.
    """
    from mixpanel_headless._internal.auth.token import OAuthTokens
    from mixpanel_headless.types import CreateAnnotationParams, HoldingConstant

    params = CreateAnnotationParams(date="2026-03-31", description="note")
    encoded = encode_input_value(params)
    assert encoded["$type"] == "CreateAnnotationParams"
    assert decode_value(encoded) == params

    holding = HoldingConstant(property="platform")
    encoded_h = encode_input_value(holding)
    assert encoded_h["$type"] == "HoldingConstant"
    assert decode_value(encoded_h) == holding

    tokens = OAuthTokens(
        access_token=SecretStr("a-tok"),
        refresh_token=SecretStr("r-tok"),
        expires_at=datetime.datetime(2026, 1, 15, 13, tzinfo=datetime.timezone.utc),
        scope="projects",
        token_type="Bearer",
    )
    decoded = decode_value(encode_input_value(tokens))
    assert decoded.access_token.get_secret_value() == "a-tok"
    assert decoded.expires_at == tokens.expires_at


def test_nonfinite_float_tag_decodes_for_authored_vectors() -> None:
    """The decode-only ``$type: float`` tag yields non-finite floats (PR-7).

    Design D4.3's ``B20B_FILTER_VALUE_NOT_FINITE`` seed vector must pass a
    non-finite float into the validator while D6 rule 5 keeps bare
    ``Infinity`` tokens out of vector JSON.

    Raises:
        AssertionError: If a spelling decodes to the wrong value.
    """
    assert decode_value({"$type": "float", "value": "Infinity"}) == math.inf
    assert decode_value({"$type": "float", "value": "-Infinity"}) == -math.inf
    assert math.isnan(decode_value({"$type": "float", "value": "NaN"}))


def test_integral_float_tag_spelling_decodes() -> None:
    """Canonical integral spellings of the float tag decode to floats.

    P2-5a amendment to the D6 rule-3 posture (Risk #3 vector-flip fix):
    an integral-valued float INSIDE a rich ``$type`` payload cannot stay
    a raw number token, because the TS twin's double-only number model
    collapses ``1716810000.0`` to the integer ``1716810000`` on decode
    and the C8(a) round-trip sweep then diffs. Such floats are tagged
    ``{"$type": "float", "value": repr(value)}`` at record time and both
    decoders accept the canonical integral spellings.

    Raises:
        AssertionError: If a canonical integral spelling fails to decode.
    """
    assert decode_value({"$type": "float", "value": "18.0"}) == 18.0
    assert isinstance(decode_value({"$type": "float", "value": "18.0"}), float)
    assert decode_value({"$type": "float", "value": "-0.0"}) == 0.0
    assert (
        decode_value({"$type": "float", "value": "1000000000000000.0"})
        == 1000000000000000.0
    )
    assert decode_value({"$type": "float", "value": "1e+16"}) == 1e16


def test_noncanonical_float_tag_spelling_rejected() -> None:
    """Non-canonical / non-integral finite spellings are rejected (D6 rule 3).

    Non-integral floats round-trip fine as raw number tokens on both
    sides, so they must NEVER be tagged; a spelling that is not exactly
    ``repr(float(spelling))`` is not canonical and must fail loudly.

    Raises:
        AssertionError: If a non-canonical spelling decodes.
    """
    with pytest.raises(UndecodableValueError, match="non-canonical spelling"):
        decode_value({"$type": "float", "value": "1.5"})  # non-integral
    with pytest.raises(UndecodableValueError, match="non-canonical spelling"):
        decode_value({"$type": "float", "value": "18"})  # missing .0 marker
    with pytest.raises(UndecodableValueError, match="non-canonical spelling"):
        # repr(1e15) is "1000000000000000.0", so "1e15" is non-canonical.
        decode_value({"$type": "float", "value": "1e15"})
    with pytest.raises(UndecodableValueError, match="malformed"):
        decode_value({"$type": "float", "value": "bogus"})


def test_integral_float_tagged_inside_rich_payloads_only() -> None:
    """Integral floats are tagged inside rich payloads, raw elsewhere.

    The bare-kwarg encoding must stay a raw number (the ``compat.*``
    gate's ``rawInput`` float-vs-int branch depends on raw ``18.0``
    tokens), while dataclass/model field walks — including floats nested
    in lists/dicts UNDER a rich payload — emit the tagged form so the TS
    sweep can round-trip them.

    Raises:
        AssertionError: If either position encodes the wrong shape.
    """
    # Bare kwarg position: raw float, unchanged.
    assert encode_input_kwargs({"value": 18.0}) == {"value": 18.0}
    # Directly-held dataclass field (union-typed in Python source).
    tagged = encode_input_value(Filter.greater_than("age", 1e15))
    assert tagged["_value"] == {"$type": "float", "value": "1000000000000000.0"}
    # Nested inside a list under a dataclass field.
    nested = encode_input_value(Filter.between("age", 1.0, 2.5))
    assert nested["_value"] == [{"$type": "float", "value": "1.0"}, 2.5]
    # Round-trip: decode reconstructs the SAME dataclass.
    assert decode_value(tagged) == Filter.greater_than("age", 1e15)
    assert decode_value(nested) == Filter.between("age", 1.0, 2.5)


def test_integral_float_stays_raw_in_expect_position() -> None:
    """Expect-position encoding (plain to-dict shapes) never tags floats.

    ``expect.result`` payloads are diffed against live library output
    (D6 rule 3 keeps the ``18.0``-vs-``18`` distinction VISIBLE there);
    only replayable ``call.input`` rich payloads get the tagged form.

    Raises:
        AssertionError: If the expect encoder tags a float.
    """
    from conformance.record.codecs import encode_expect_value

    assert encode_expect_value({"signed_at": 1716810000.0}) == {
        "signed_at": 1716810000.0
    }


def test_nonfinite_floats_still_unencodable_at_record_time() -> None:
    """The ENCODE side keeps rejecting non-finite floats (D6 rule 5).

    The decode-only tag must not weaken record-time rejection.

    Raises:
        AssertionError: If a non-finite float encodes.
    """
    with pytest.raises(UnencodableValueError, match="non-finite float"):
        encode_input_value(math.inf)
