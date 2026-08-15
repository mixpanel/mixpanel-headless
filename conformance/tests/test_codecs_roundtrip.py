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
from typing import Any

import pytest
from pydantic import SecretStr

from conformance.record.codecs import (
    RecordingCallback,
    UndecodableValueError,
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
