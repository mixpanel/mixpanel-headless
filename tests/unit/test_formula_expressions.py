"""Unit tests for the formula expression rules in ``_internal/query/formula.py``.

Covers the syntax check against the server formula grammar (``FM4_SYNTAX``),
the uppercase ``E`` literal rule (``FM5_UPPER_E``), the letter-to-index
mapping (A to Z, then BA), and the operand letter check
(``FM2_UNKNOWN_LETTER``).
"""

from __future__ import annotations

import pytest

from mixpanel_headless._internal.query.formula import (
    ParsedFormula,
    check_letters,
    check_upper_e,
    index_for_letters,
    letters_for_index,
    parse_formula,
    validate_operand_formula,
)
from mixpanel_headless.exceptions import (
    CODED_GUARD_REGISTRY,
    MixpanelHeadlessError,
    ParamValidationError,
)

# =============================================================================
# parse_formula: accepted expressions
# =============================================================================


class TestParseFormulaAccepts:
    """Expressions in the server grammar parse without error."""

    @pytest.mark.parametrize(
        "expression",
        [
            "A",
            "(B / A) * 100",
            "A + B - C",
            "A * B / C",
            "A ^ 2",
            "A ^ B ^ C",
            "-A",
            "--A",
            "-A ^ 2",
            "A * -B",
            "A / -B",
            "A + -B",
            "A - -B",
            "(-A) ^ 2",
            "A ^ (-B)",
            "((A))",
            "(A + B) ^ (C - D)",
            "BA + BB",
            "1",
            "1.5",
            ".5",
            "1_000",
            "1_000.000_1",
            "1e5",
            "1e+5",
            "1e-5",
            "2.5e1_0",
            "1E5",
            "\tA\t+ B ",
            "A+B",
            "lowercase_name",
            "_x1",
        ],
    )
    def test_valid_expression_parses(self, expression: str) -> None:
        """Each expression in the grammar parses and keeps its source text."""
        parsed = parse_formula(expression)
        assert isinstance(parsed, ParsedFormula)
        assert parsed.expression == expression

    def test_variables_in_first_use_order_without_repeats(self) -> None:
        """``variables`` lists each variable once, in order of first use."""
        parsed = parse_formula("(C + A) / C - BA * A")
        assert parsed.variables == ("C", "A", "BA")

    def test_numbers_in_source_order_as_written(self) -> None:
        """``numbers`` lists each numeric literal as written, in source order."""
        parsed = parse_formula("A * 1_000 + 1E5 - .5 + 1_000")
        assert parsed.numbers == ("1_000", "1E5", ".5", "1_000")

    def test_constant_expression_has_no_variables(self) -> None:
        """An expression without letters parses with no variables."""
        parsed = parse_formula("1 + 2")
        assert parsed.variables == ()
        assert parsed.numbers == ("1", "2")

    def test_number_exponent_letter_is_not_a_variable(self) -> None:
        """The ``e`` or ``E`` of a scientific literal is part of the number."""
        parsed = parse_formula("A * 1e5 + 2E3")
        assert parsed.variables == ("A",)
        assert parsed.numbers == ("1e5", "2E3")

    def test_parsed_formula_is_frozen(self) -> None:
        """A ``ParsedFormula`` cannot be changed after construction."""
        parsed = parse_formula("A")
        with pytest.raises(AttributeError):
            parsed.expression = "B"  # type: ignore[misc]


# =============================================================================
# parse_formula: refused expressions (FM4_SYNTAX)
# =============================================================================


class TestParseFormulaRefuses:
    """Expressions outside the server grammar raise ``FM4_SYNTAX``."""

    @pytest.mark.parametrize(
        "expression",
        [
            "",
            "   ",
            "A +",
            "A + + B",
            "A B",
            "2A",
            "A ^ -B",
            "A -^ B",
            "()",
            "(A",
            "A)",
            "(A))",
            ")A(",
            "*A",
            "A * * B",
            "A $ B",
            "A % B",
            "A\nB",
            "A +\n B",
            "1.",
            "1..5",
            "1.2.3",
            ".",
            "1__0",
            "1_",
            "1e",
            "1e+",
            "A\u00a0+ B",
            "\u00e9",
            "sqrt(A)",
            "A,B",
        ],
    )
    def test_invalid_expression_raises_fm4(self, expression: str) -> None:
        """Each expression outside the grammar raises FM4_SYNTAX."""
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula(expression)
        assert excinfo.value.code == "FM4_SYNTAX"
        assert excinfo.value.details["expression"] == expression

    def test_error_is_value_error_and_domain_error(self) -> None:
        """FM4_SYNTAX is catchable as ValueError and as MixpanelHeadlessError."""
        with pytest.raises(ValueError):
            parse_formula("A +")
        with pytest.raises(MixpanelHeadlessError):
            parse_formula("A +")

    def test_unexpected_character_names_character_and_position(self) -> None:
        """An unknown character is named with its position in the message."""
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula("A $ B")
        assert excinfo.value.details["position"] == 2
        assert "'$'" in excinfo.value.message
        assert "position 2" in excinfo.value.message

    def test_unexpected_token_names_token_and_position(self) -> None:
        """A token in the wrong place is named with its position."""
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula("A  B")
        assert excinfo.value.details["position"] == 3
        assert "'B'" in excinfo.value.message
        assert "position 3" in excinfo.value.message

    def test_unary_minus_after_power_is_unexpected(self) -> None:
        """The server grammar allows only an atom after ``^``, so ``-`` fails."""
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula("A ^ -B")
        assert excinfo.value.details["position"] == 4

    def test_closing_paren_without_opening_is_unexpected(self) -> None:
        """A ``)`` with no open ``(`` is an unexpected token."""
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula("A)")
        assert excinfo.value.details["position"] == 1

    @pytest.mark.parametrize("expression", ["", "A +", "(A", "((A + B)", "-"])
    def test_incomplete_expression_says_incomplete(self, expression: str) -> None:
        """An expression that ends too early is reported as incomplete."""
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula(expression)
        assert "incomplete" in excinfo.value.message
        assert excinfo.value.details["position"] == len(expression)

    def test_message_names_the_allowed_syntax(self) -> None:
        """The message tells the caller what an expression can contain."""
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula("A % B")
        assert "+ - * / ^" in excinfo.value.message

    def test_deep_nesting_does_not_exhaust_the_stack(self) -> None:
        """Very deep parentheses parse without recursion errors."""
        depth = 5000
        parse_formula("(" * depth + "A" + ")" * depth)
        with pytest.raises(ParamValidationError) as excinfo:
            parse_formula("(" * depth + "A" + ")" * (depth - 1))
        assert excinfo.value.code == "FM4_SYNTAX"


# =============================================================================
# check_upper_e (FM5_UPPER_E)
# =============================================================================


class TestCheckUpperE:
    """A numeric literal with an uppercase ``E`` raises ``FM5_UPPER_E``."""

    @pytest.mark.parametrize("expression", ["A * 1E5", "2E-3 + A", "A / 1.5E+2"])
    def test_uppercase_exponent_raises_fm5(self, expression: str) -> None:
        """Each literal with an uppercase exponent raises FM5_UPPER_E."""
        with pytest.raises(ParamValidationError) as excinfo:
            check_upper_e(parse_formula(expression))
        assert excinfo.value.code == "FM5_UPPER_E"
        assert excinfo.value.details["expression"] == expression

    def test_message_names_literal_and_fix(self) -> None:
        """The message names the literal and suggests the lowercase form."""
        with pytest.raises(ParamValidationError) as excinfo:
            check_upper_e(parse_formula("A * 1E5"))
        assert excinfo.value.details["literal"] == "1E5"
        assert "'1E5'" in excinfo.value.message
        assert "'1e5'" in excinfo.value.message

    @pytest.mark.parametrize("expression", ["A * 1e5", "E * 2", "A + E", "1_000"])
    def test_lowercase_exponent_and_letter_e_pass(self, expression: str) -> None:
        """A lowercase exponent and the letter variable ``E`` are accepted."""
        check_upper_e(parse_formula(expression))


# =============================================================================
# letters_for_index / index_for_letters
# =============================================================================


class TestLetterMapping:
    """Operand indexes map to letters A to Z, then BA (base 26, A is zero)."""

    @pytest.mark.parametrize(
        ("index", "letters"),
        [
            (0, "A"),
            (1, "B"),
            (25, "Z"),
            (26, "BA"),
            (27, "BB"),
            (51, "BZ"),
            (52, "CA"),
            (98, "DU"),
            (675, "ZZ"),
            (676, "BAA"),
            (26**2 * 3 + 26 * 5 + 1, "DFB"),
            (26**4, "BAAAA"),
        ],
    )
    def test_known_pairs(self, index: int, letters: str) -> None:
        """Each index maps to the server letters and back."""
        assert letters_for_index(index) == letters
        assert index_for_letters(letters) == index

    def test_negative_index_raises(self) -> None:
        """A negative operand index is a programming error."""
        with pytest.raises(ValueError, match="non-negative"):
            letters_for_index(-1)

    @pytest.mark.parametrize(
        "letters",
        ["", "AA", "AB", "AZ", "AAA", "a", "Ab", "bA", "A1", "_", "A_B", "\u00c9"],
    )
    def test_non_canonical_letters_have_no_index(self, letters: str) -> None:
        """Strings the server never generates map to ``None``."""
        assert index_for_letters(letters) is None


# =============================================================================
# check_letters (FM2_UNKNOWN_LETTER)
# =============================================================================


class TestCheckLetters:
    """Each variable must name an operand by position."""

    def test_returns_operand_indexes_in_first_use_order(self) -> None:
        """Known letters return their operand indexes in first-use order."""
        assert check_letters(parse_formula("(C + A) / C"), 3) == (2, 0)

    def test_letter_past_last_operand_raises_fm2(self) -> None:
        """A letter beyond the operand count raises FM2_UNKNOWN_LETTER."""
        with pytest.raises(ParamValidationError) as excinfo:
            check_letters(parse_formula("A + C"), 2)
        assert excinfo.value.code == "FM2_UNKNOWN_LETTER"
        assert excinfo.value.details == {
            "expression": "A + C",
            "unknown": ["C"],
            "operand_count": 2,
        }
        assert "'C'" in excinfo.value.message
        assert "A to B" in excinfo.value.message

    def test_all_unknown_letters_are_listed(self) -> None:
        """Every unknown variable is listed, in first-use order."""
        with pytest.raises(ParamValidationError) as excinfo:
            check_letters(parse_formula("Z + AA + a + B + Z"), 2)
        assert excinfo.value.details["unknown"] == ["Z", "AA", "a"]

    def test_letters_after_z_use_ba(self) -> None:
        """With 28 operands the letters run A to Z, then BA and BB."""
        assert check_letters(parse_formula("BB - BA + Z"), 28) == (27, 26, 25)
        with pytest.raises(ParamValidationError) as excinfo:
            check_letters(parse_formula("AA"), 28)
        assert excinfo.value.details["unknown"] == ["AA"]
        assert "A to BB" in excinfo.value.message

    def test_single_operand_range_reads_a(self) -> None:
        """With one operand the message names only the letter A."""
        with pytest.raises(ParamValidationError) as excinfo:
            check_letters(parse_formula("B"), 1)
        assert "(A)" in excinfo.value.message

    def test_zero_operands_refuses_every_letter(self) -> None:
        """With no operands every letter is unknown."""
        with pytest.raises(ParamValidationError) as excinfo:
            check_letters(parse_formula("A"), 0)
        assert excinfo.value.details["unknown"] == ["A"]
        assert "no operands" in excinfo.value.message

    def test_constant_expression_uses_no_operand(self) -> None:
        """An expression without letters uses no operand index."""
        assert check_letters(parse_formula("1 + 2"), 2) == ()


# =============================================================================
# validate_operand_formula
# =============================================================================


class TestValidateOperandFormula:
    """The operand-form check runs syntax, then uppercase E, then letters."""

    def test_valid_expression_returns_parsed_form(self) -> None:
        """A valid operand expression returns its parsed form."""
        parsed = validate_operand_formula("(B / A) * 1e2", 2)
        assert parsed.variables == ("B", "A")

    def test_syntax_error_wins_over_other_rules(self) -> None:
        """A syntax error is reported before the other rules."""
        with pytest.raises(ParamValidationError) as excinfo:
            validate_operand_formula("C * 1E5 +", 1)
        assert excinfo.value.code == "FM4_SYNTAX"

    def test_upper_e_wins_over_unknown_letter(self) -> None:
        """The uppercase E rule is reported before unknown letters."""
        with pytest.raises(ParamValidationError) as excinfo:
            validate_operand_formula("C * 1E5", 1)
        assert excinfo.value.code == "FM5_UPPER_E"

    def test_unknown_letter_is_reported_after_literals(self) -> None:
        """An unknown letter is reported when syntax and literals are valid."""
        with pytest.raises(ParamValidationError) as excinfo:
            validate_operand_formula("C * 1e5", 1)
        assert excinfo.value.code == "FM2_UNKNOWN_LETTER"

    @pytest.mark.parametrize("expression", ["1 + 2", "-(3)", "1e5"])
    def test_expression_without_letters_raises_v16(self, expression: str) -> None:
        """An expression that uses no operand raises V16_FORMULA_SYNTAX."""
        with pytest.raises(ParamValidationError) as excinfo:
            validate_operand_formula(expression, 2)
        assert excinfo.value.code == "V16_FORMULA_SYNTAX"
        assert excinfo.value.details == {"expression": expression}
        assert "at least one operand (A, B, C, ...)" in excinfo.value.message

    def test_uppercase_literal_without_letters_raises_fm5_first(self) -> None:
        """``1E5`` alone breaks the uppercase E rule before the letter rule."""
        with pytest.raises(ParamValidationError) as excinfo:
            validate_operand_formula("1E5", 1)
        assert excinfo.value.code == "FM5_UPPER_E"


# =============================================================================
# Registry
# =============================================================================


class TestFormulaGuardCodes:
    """The formula expression codes are registered coded-guard codes."""

    @pytest.mark.parametrize(
        "code", ["FM2_UNKNOWN_LETTER", "FM4_SYNTAX", "FM5_UPPER_E"]
    )
    def test_registered(self, code: str) -> None:
        """Each formula expression code is present in CODED_GUARD_REGISTRY."""
        assert code in CODED_GUARD_REGISTRY
