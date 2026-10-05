"""Property-based tests for the formula expression rules.

Covers the letter mapping (index to letters to index, A to Z then BA), the
server grammar (generated valid expressions parse, generated invalid ones
raise ``FM4_SYNTAX``), the uppercase ``E`` rule (``FM5_UPPER_E``), and the
operand letter check (``FM2_UNKNOWN_LETTER``). Hypothesis profiles come from
``tests/conftest.py`` (``default``, ``dev``, ``ci``).

Usage:
    # Run with default profile (100 examples)
    pytest tests/unit/test_formula_expressions_pbt.py

    # Run with dev profile (10 examples, verbose)
    HYPOTHESIS_PROFILE=dev pytest tests/unit/test_formula_expressions_pbt.py
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.query.formula import (
    ParsedFormula,
    check_letters,
    check_upper_e,
    index_for_letters,
    letters_for_index,
    parse_formula,
)
from mixpanel_headless.exceptions import ParamValidationError

# =============================================================================
# Strategies
# =============================================================================

indexes = st.integers(min_value=0, max_value=10**7)
"""Operand indexes, including values with four or more letters."""

letter_strings = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", max_size=5)
"""Any run of uppercase letters, canonical or not."""

variables = st.integers(min_value=0, max_value=60).map(letters_for_index)
"""Canonical operand letters from A to CI."""

numbers = st.from_regex(
    r"(?:[0-9](?:_?[0-9]){0,3}(?:\.[0-9](?:_?[0-9]){0,2})?|\.[0-9](?:_?[0-9]){0,2})"
    r"(?:e[+-]?[0-9](?:_?[0-9]){0,2})?",
    fullmatch=True,
)
"""Numeric literals in the server grammar, with a lowercase exponent only."""

upper_e_numbers = st.from_regex(
    r"[0-9](?:_?[0-9]){0,3}(?:\.[0-9]{1,2})?E[+-]?[0-9]{1,2}", fullmatch=True
)
"""Numeric literals with an uppercase exponent."""

gaps = st.sampled_from(["", " ", "\t", "  "])
"""Ignored whitespace between tokens (the grammar ignores spaces and tabs)."""

atoms = st.one_of(variables, numbers)
"""A letter variable or a numeric literal."""


def _extend(children: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
    """Build one grammar level on top of smaller valid expressions.

    Args:
        children: Strategy for smaller valid expressions.

    Returns:
        Strategy for expressions one operator deeper. The right side of
        ``^`` is always parenthesized, because only an atom can follow it.
    """
    binary = st.tuples(children, gaps, st.sampled_from("+-*/"), gaps, children).map(
        "".join
    )
    power = st.tuples(children, gaps, children).map(
        lambda parts: f"{parts[0]}{parts[1]}^({parts[2]})"
    )
    return st.one_of(
        binary,
        power,
        children.map(lambda e: f"({e})"),
        children.map(lambda e: f"-{e}"),
    )


expressions = st.recursive(atoms, _extend, max_leaves=12)
"""Valid expressions generated from the server grammar."""

bad_characters = st.sampled_from(["$", "%", "\n", "\r", ",", "!", "#", "=", "\u00e9"])
"""Characters that are in no token and are not ignored, wherever they appear."""


def _starts_with_minus(expression: str) -> bool:
    """Return whether the expression starts with a unary minus.

    Args:
        expression: A generated expression.

    Returns:
        ``True`` when the first character is ``-``.
    """
    return expression.startswith("-")


# =============================================================================
# Letter mapping
# =============================================================================


class TestLetterMappingProperties:
    """Operand letters are base-26 numerals with A as zero, as on the server."""

    @given(indexes)
    def test_index_to_letters_to_index_round_trip(self, index: int) -> None:
        """Every index survives the trip to letters and back."""
        assert index_for_letters(letters_for_index(index)) == index

    @given(letter_strings)
    def test_letters_to_index_to_letters_round_trip(self, letters: str) -> None:
        """A canonical letter string survives the trip to an index and back."""
        index = index_for_letters(letters)
        canonical = bool(letters) and (len(letters) == 1 or letters[0] != "A")
        assert (index is not None) == canonical
        if index is not None:
            assert letters_for_index(index) == letters

    @given(indexes, indexes)
    def test_letter_order_follows_index_order(self, first: int, second: int) -> None:
        """Shorter letters come first, then alphabetical order, as indexes grow."""
        a, b = letters_for_index(first), letters_for_index(second)
        assert (first < second) == ((len(a), a) < (len(b), b))

    @given(indexes)
    def test_letters_are_uppercase_ascii(self, index: int) -> None:
        """Letters use A to Z only, and only index 0 starts with A."""
        letters = letters_for_index(index)
        assert letters.isascii()
        assert letters.isalpha()
        assert letters.isupper()
        assert letters.startswith("A") == (index == 0)


# =============================================================================
# Grammar
# =============================================================================


class TestGrammarProperties:
    """The checker accepts the grammar and refuses what is outside it."""

    @given(expressions)
    def test_generated_valid_expression_parses(self, expression: str) -> None:
        """Each expression built from the grammar parses."""
        parsed = parse_formula(expression)
        assert parsed.expression == expression

    @given(expressions)
    def test_variables_are_the_distinct_letters_in_order(self, expression: str) -> None:
        """``variables`` holds distinct names, and each occurs in the source."""
        parsed = parse_formula(expression)
        assert len(set(parsed.variables)) == len(parsed.variables)
        assert all(name in expression for name in parsed.variables)
        assert all(index_for_letters(name) is not None for name in parsed.variables)

    @given(expressions, gaps, st.sampled_from("+-*/^"))
    def test_trailing_operator_raises_fm4(
        self, expression: str, gap: str, operator: str
    ) -> None:
        """An expression that ends with an operator is incomplete."""
        text = f"{expression}{gap}{operator}"
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula(text)
        assert excinfo.value.code == "FM4_SYNTAX"
        assert excinfo.value.details["position"] == len(text)

    @given(st.sampled_from("+*/^)"), gaps, expressions)
    def test_leading_binary_operator_raises_fm4(
        self, operator: str, gap: str, expression: str
    ) -> None:
        """An expression cannot start with a binary operator or ``)``."""
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula(f"{operator}{gap}{expression}")
        assert excinfo.value.code == "FM4_SYNTAX"
        assert excinfo.value.details["position"] == 0

    @given(expressions, expressions.filter(lambda e: not _starts_with_minus(e)))
    def test_two_expressions_side_by_side_raise_fm4(
        self, first: str, second: str
    ) -> None:
        """Two operands with no operator between them are refused."""
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula(f"{first} {second}")
        assert excinfo.value.code == "FM4_SYNTAX"

    @given(expressions)
    def test_unbalanced_parentheses_raise_fm4(self, expression: str) -> None:
        """A missing ``)`` or an extra ``)`` is refused."""
        for text in (f"({expression}", f"{expression})"):
            with pytest.raises(ParamValidationError) as excinfo:
                parse_formula(text)
            assert excinfo.value.code == "FM4_SYNTAX"

    @given(expressions, atoms)
    def test_unary_minus_after_power_raises_fm4(
        self, expression: str, atom: str
    ) -> None:
        """Only an atom can follow ``^``; a unary minus there is refused."""
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula(f"{expression} ^ -{atom}")
        assert excinfo.value.code == "FM4_SYNTAX"

    @given(expressions, bad_characters, st.data())
    def test_inserted_bad_character_raises_fm4(
        self, expression: str, character: str, data: st.DataObject
    ) -> None:
        """A character outside the grammar fails wherever it appears."""
        position = data.draw(st.integers(min_value=0, max_value=len(expression)))
        text = expression[:position] + character + expression[position:]
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula(text)
        assert excinfo.value.code == "FM4_SYNTAX"

    @given(st.text(max_size=30))
    def test_any_text_parses_or_raises_fm4(self, text: str) -> None:
        """The checker is total: any string parses or raises FM4_SYNTAX."""
        try:
            parsed = parse_formula(text)
        except ParamValidationError as exc:
            assert exc.code == "FM4_SYNTAX"
            assert 0 <= exc.details["position"] <= len(text)
        else:
            assert isinstance(parsed, ParsedFormula)


# =============================================================================
# Uppercase E and operand letters
# =============================================================================


class TestUpperEProperties:
    """``FM5_UPPER_E`` fires exactly for literals with an uppercase ``E``."""

    @given(expressions)
    def test_lowercase_literals_pass(self, expression: str) -> None:
        """Generated expressions use a lowercase exponent and pass the rule."""
        check_upper_e(parse_formula(expression))

    @given(expressions, upper_e_numbers, st.sampled_from("+-*/"))
    def test_uppercase_literal_raises_fm5(
        self, expression: str, literal: str, operator: str
    ) -> None:
        """Adding a literal with an uppercase exponent raises FM5_UPPER_E."""
        text = f"{expression} {operator} {literal}"
        with pytest.raises(ParamValidationError) as excinfo:
            check_upper_e(parse_formula(text))
        assert excinfo.value.code == "FM5_UPPER_E"
        assert excinfo.value.details["literal"] == literal


class TestOperandLetterProperties:
    """``FM2_UNKNOWN_LETTER`` fires exactly for letters past the operand count."""

    @given(expressions, st.integers(min_value=0, max_value=70))
    def test_known_letters_pass_and_unknown_letters_raise(
        self, expression: str, operand_count: int
    ) -> None:
        """The check passes iff every variable indexes below the operand count."""
        parsed = parse_formula(expression)
        expected = [index_for_letters(name) for name in parsed.variables]
        if all(i is not None and i < operand_count for i in expected):
            assert list(check_letters(parsed, operand_count)) == expected
        else:
            with pytest.raises(ParamValidationError) as excinfo:
                check_letters(parsed, operand_count)
            assert excinfo.value.code == "FM2_UNKNOWN_LETTER"
            assert excinfo.value.details["unknown"] == [
                name
                for name, i in zip(parsed.variables, expected, strict=True)
                if i is None or i >= operand_count
            ]
