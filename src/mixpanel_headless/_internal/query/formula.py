"""Formula expression rules: syntax, uppercase ``E`` literals, and operand letters.

A formula expression is arithmetic over letter variables, for example
``"(B / A) * 100"``. Each letter names an operand by position: ``A`` is the
first operand, ``B`` the second, ``Z`` the 26th, then ``BA``, ``BB``, and so
on. This module checks an expression against the grammar of the Mixpanel
query server, lists the letters it uses, and maps an operand index to its
letters and back. It is stdlib-only and makes no network calls.

The server grammar (``formulas/grammar.lark`` in the Mixpanel query server)::

    expr   : term | expr "+" term | expr "-" term
    term   : factor | term "*" factor | term "/" factor
    factor : atom | "-" factor | factor "^" atom
    atom   : NUMBER | VAR | "(" expr ")"

``NUMBER`` allows ``_`` between digits and scientific notation (``1e5``).
``VAR`` is a C-style name. Spaces and tabs are ignored; any other character,
including a newline, is an error. Only an atom can follow ``^``, so
``A ^ -B`` is an error on the server; ``A ^ (-B)`` is correct.

The checker is a small state machine over tokens, not a recursive parser, so
deep parentheses cannot exhaust the Python stack. It accepts exactly the
strings the grammar accepts.

This is a private implementation detail. Use
:class:`~mixpanel_headless.Formula` instead of importing this module directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

from mixpanel_headless.exceptions import ParamValidationError

_NUMBER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:[0-9](?:_?[0-9])*(?:\.[0-9](?:_?[0-9])*)?|\.[0-9](?:_?[0-9])*)"
    r"(?:[eE][+-]?[0-9](?:_?[0-9])*)?"
)
"""The server ``NUMBER`` terminal, copied from the grammar without change."""

_VAR_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
"""The server ``VAR`` terminal (Lark ``common.CNAME``: ASCII only)."""

_OPERATORS: Final[frozenset[str]] = frozenset("+-*/^()")
"""Single-character tokens of the grammar."""

_IGNORED: Final[frozenset[str]] = frozenset(" \t")
"""Characters the grammar ignores (Lark ``common.WS_INLINE``)."""

_SYNTAX_HINT: Final[str] = (
    "A formula uses letters (A, B, ...), numbers, + - * / ^, and parentheses."
)
"""Sentence appended to every ``FM4_SYNTAX`` message."""

_LETTER_COUNT: Final[int] = 26
"""Number of letters from ``A`` to ``Z``: the base of the operand letters."""

_TokenKind = Literal["number", "var", "op"]
"""What a token is: a numeric literal, a variable name, or an operator."""


@dataclass(frozen=True)
class _Token:
    """One token of a formula expression.

    Attributes:
        kind: ``"number"``, ``"var"``, or ``"op"``.
        text: The token text as written.
        position: Zero-based index of the first character in the expression.
    """

    kind: _TokenKind
    text: str
    position: int


@dataclass(frozen=True)
class ParsedFormula:
    """The facts that the formula rules need from one valid expression.

    Attributes:
        expression: The source text, unchanged.
        variables: Each variable name once, in order of first use.
        numbers: Each numeric literal as written, in source order.

    Example:
        ```python
        parsed = parse_formula("(B / A) * 1e2")
        parsed.variables  # ("B", "A")
        parsed.numbers    # ("1e2",)
        ```
    """

    expression: str
    variables: tuple[str, ...]
    numbers: tuple[str, ...]


def _syntax_error(expression: str, position: int, problem: str) -> ParamValidationError:
    """Build the ``FM4_SYNTAX`` error for one expression.

    Args:
        expression: The expression that failed.
        position: Zero-based index of the problem in the expression.
        problem: A clause that states the problem, for example
            ``"has an unexpected token 'B' at position 2"``.

    Returns:
        The coded error, ready to raise.
    """
    return ParamValidationError(
        f"Formula expression {expression!r} {problem}. {_SYNTAX_HINT}",
        code="FM4_SYNTAX",
        details={"expression": expression, "position": position},
    )


def _tokenize(expression: str) -> list[_Token]:
    """Split an expression into tokens the same way as the server lexer.

    Args:
        expression: The formula expression.

    Returns:
        The tokens in source order. Ignored characters produce no token.

    Raises:
        ParamValidationError: ``FM4_SYNTAX`` for a character that starts no
            token.
    """
    tokens: list[_Token] = []
    position = 0
    while position < len(expression):
        char = expression[position]
        if char in _IGNORED:
            position += 1
            continue
        if char in _OPERATORS:
            tokens.append(_Token("op", char, position))
            position += 1
            continue
        number = _NUMBER_RE.match(expression, position)
        if number is not None:
            tokens.append(_Token("number", number.group(), position))
            position = number.end()
            continue
        var = _VAR_RE.match(expression, position)
        if var is not None:
            tokens.append(_Token("var", var.group(), position))
            position = var.end()
            continue
        raise _syntax_error(
            expression,
            position,
            f"has an unexpected character {char!r} at position {position}",
        )
    return tokens


def _check_grammar(expression: str, tokens: list[_Token]) -> None:
    """Check a token list against the server grammar.

    Three states track what the grammar accepts next:

    - ``operand``: the start of a factor. A unary ``-``, an atom, or ``(``.
    - ``atom``: after ``^``. An atom or ``(`` only; no unary ``-``.
    - ``after``: after an atom. A binary operator, ``^``, ``)``, or the end.

    A counter tracks the open parentheses.

    Args:
        expression: The formula expression (for error messages).
        tokens: The tokens of ``expression``.

    Raises:
        ParamValidationError: ``FM4_SYNTAX`` for a token in the wrong place
            or an expression that ends too early.
    """
    state: Literal["operand", "atom", "after"] = "operand"
    depth = 0
    for token in tokens:
        text = token.text
        if state == "after":
            if text in ("+", "-", "*", "/"):
                state = "operand"
                continue
            if text == "^":
                state = "atom"
                continue
            if text == ")" and depth > 0:
                depth -= 1
                continue
        else:
            if token.kind != "op":
                state = "after"
                continue
            if text == "(":
                depth += 1
                state = "operand"
                continue
            if text == "-" and state == "operand":
                continue
        raise _syntax_error(
            expression,
            token.position,
            f"has an unexpected token {text!r} at position {token.position}",
        )
    if state != "after" or depth > 0:
        raise _syntax_error(expression, len(expression), "is incomplete")


def parse_formula(expression: str) -> ParsedFormula:
    """Check an expression against the server formula grammar.

    Args:
        expression: The formula expression, for example ``"(B / A) * 100"``.

    Returns:
        The parsed facts: the variables in first-use order and the numeric
        literals as written.

    Raises:
        ParamValidationError: ``FM4_SYNTAX`` when the expression is not in the
            grammar. ``details`` holds ``expression`` and ``position`` (the
            zero-based index of the problem; the length of the expression when
            it ends too early).

    Example:
        ```python
        parse_formula("(B / A) * 100").variables  # ("B", "A")
        parse_formula("A ^ -B")  # raises FM4_SYNTAX: only an atom follows ^
        ```
    """
    tokens = _tokenize(expression)
    _check_grammar(expression, tokens)
    variables = tuple(dict.fromkeys(t.text for t in tokens if t.kind == "var"))
    numbers = tuple(t.text for t in tokens if t.kind == "number")
    return ParsedFormula(expression=expression, variables=variables, numbers=numbers)


def check_upper_e(parsed: ParsedFormula) -> None:
    """Refuse a numeric literal with an uppercase ``E``.

    When a formula holds its own operands, the server renames each letter
    variable by a text search for uppercase letters. That search also changes
    the ``E`` of a literal such as ``1E5``, and the formula then fails. A
    lowercase ``e`` is safe.

    Args:
        parsed: The parsed expression.

    Raises:
        ParamValidationError: ``FM5_UPPER_E`` for the first literal with an
            uppercase ``E``. ``details`` holds ``expression`` and ``literal``.

    Example:
        ```python
        check_upper_e(parse_formula("A * 1e5"))  # passes
        check_upper_e(parse_formula("A * 1E5"))  # raises FM5_UPPER_E
        ```
    """
    for literal in parsed.numbers:
        if "E" in literal:
            raise ParamValidationError(
                f"Formula expression {parsed.expression!r} has the literal "
                f"{literal!r} with an uppercase E. Write {literal.lower()!r}: "
                "the server renames uppercase letters in a formula with its "
                "own operands, and that breaks the literal.",
                code="FM5_UPPER_E",
                details={"expression": parsed.expression, "literal": literal},
            )


def letters_for_index(index: int) -> str:
    """Return the formula letters for an operand index.

    The letters are base-26 numerals with ``A`` as zero, the same as the
    server and the web app: 0 is ``A``, 25 is ``Z``, 26 is ``BA`` (not
    ``AA``), and 26**4 is ``BAAAA``.

    Args:
        index: Zero-based operand position.

    Returns:
        The letters that name the operand in an expression.

    Raises:
        ValueError: If ``index`` is negative.

    Example:
        ```python
        letters_for_index(0)   # "A"
        letters_for_index(26)  # "BA"
        ```
    """
    if index < 0:
        raise ValueError(f"operand index must be non-negative, got {index}")
    letters = ""
    while True:
        index, digit = divmod(index, _LETTER_COUNT)
        letters = chr(ord("A") + digit) + letters
        if index == 0:
            return letters


def index_for_letters(letters: str) -> int | None:
    """Return the operand index that formula letters name.

    Args:
        letters: A variable name from an expression.

    Returns:
        The zero-based operand index, or ``None`` when the server never
        generates ``letters`` for any index: an empty string, a character
        outside ``A`` to ``Z``, or a leading ``A`` on more than one letter
        (``AA`` and ``AB`` name no operand).

    Example:
        ```python
        index_for_letters("BA")  # 26
        index_for_letters("AA")  # None
        ```
    """
    if not letters or any(not "A" <= char <= "Z" for char in letters):
        return None
    if len(letters) > 1 and letters[0] == "A":
        return None
    index = 0
    for char in letters:
        index = index * _LETTER_COUNT + (ord(char) - ord("A"))
    return index


def _letter_range(operand_count: int) -> str:
    """Describe the letters that name ``operand_count`` operands.

    Args:
        operand_count: Number of operands.

    Returns:
        ``"no operands"``, ``"1 operand (A)"``, or for example
        ``"3 operands (A to C)"``.
    """
    if operand_count <= 0:
        return "no operands"
    if operand_count == 1:
        return "1 operand (A)"
    return f"{operand_count} operands (A to {letters_for_index(operand_count - 1)})"


def check_letters(parsed: ParsedFormula, operand_count: int) -> tuple[int, ...]:
    """Check that each variable names one of the operands.

    Args:
        parsed: The parsed expression.
        operand_count: Number of operands the formula holds.

    Returns:
        The operand index of each variable, in first-use order.

    Raises:
        ParamValidationError: ``FM2_UNKNOWN_LETTER`` when a variable names no
            operand. ``details`` holds ``expression``, ``unknown`` (every
            unknown variable, in first-use order), and ``operand_count``.

    Example:
        ```python
        check_letters(parse_formula("B / A"), 2)  # (1, 0)
        check_letters(parse_formula("A + C"), 2)  # raises FM2_UNKNOWN_LETTER
        ```
    """
    indexes: list[int] = []
    unknown: list[str] = []
    for name in parsed.variables:
        index = index_for_letters(name)
        if index is None or index >= operand_count:
            unknown.append(name)
        else:
            indexes.append(index)
    if unknown:
        names = ", ".join(repr(name) for name in unknown)
        raise ParamValidationError(
            f"Formula expression {parsed.expression!r} uses {names}, but the "
            f"formula has {_letter_range(operand_count)}. Each letter names an "
            "operand by position: A is the first, Z the 26th, then BA, BB.",
            code="FM2_UNKNOWN_LETTER",
            details={
                "expression": parsed.expression,
                "unknown": unknown,
                "operand_count": operand_count,
            },
        )
    return tuple(indexes)


def validate_operand_formula(expression: str, operand_count: int) -> ParsedFormula:
    """Run every expression rule for a formula that holds its own operands.

    The rules run in this order: syntax (``FM4_SYNTAX``), uppercase ``E``
    literals (``FM5_UPPER_E``), then operand letters (``FM2_UNKNOWN_LETTER``).

    Args:
        expression: The formula expression.
        operand_count: Number of operands the formula holds.

    Returns:
        The parsed expression.

    Raises:
        ParamValidationError: ``FM4_SYNTAX``, ``FM5_UPPER_E``, or
            ``FM2_UNKNOWN_LETTER``, for the first rule that fails.

    Example:
        ```python
        validate_operand_formula("(B / A) * 100", 2).variables  # ("B", "A")
        ```
    """
    parsed = parse_formula(expression)
    check_upper_e(parsed)
    check_letters(parsed, operand_count)
    return parsed
