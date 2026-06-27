"""The LSP variable extractor must ignore identifiers that appear inside
single- or double-quoted string literals — they are guard literals, not
variable references, and `agac validate-udfs` already treats them as
such. The LSP must agree.
"""

from __future__ import annotations

import pytest

from agent_actions.tooling.lsp.indexer import _extract_condition_variables


@pytest.mark.parametrize(
    "condition,expected_vars",
    [
        # `approved` is a string literal, not a variable.
        ('x.hitl_status == "approved"', {"x.hitl_status"}),
        # Single quotes — same rule.
        ("x.hitl_status == 'approved'", {"x.hitl_status"}),
        # Multi-comparison with a quoted literal mid-expression.
        (
            'source.status == "ready" and source.count > 0',
            {"source.status", "source.count"},
        ),
        # Two quoted literals — neither should appear.
        ('"foo" == source.label or source.label == "bar"', {"source.label"}),
        # No quotes — baseline that prior behavior holds.
        ("source.a > source.b", {"source.a", "source.b"}),
        # Escaped quotes inside a string must not break out of the literal.
        (r'source.label == "can\"t"', {"source.label"}),
    ],
)
def test_extract_ignores_quoted_string_literals(condition: str, expected_vars: set[str]) -> None:
    result = _extract_condition_variables(condition)
    dotted = {token for token in result if "." in token}
    assert dotted == expected_vars, (
        f"For condition {condition!r}, extractor returned {result!r}; "
        f"expected dotted variable set {expected_vars!r}."
    )


def test_extract_bare_identifier_outside_quotes_still_returned() -> None:
    """Bare identifiers (no dot) outside quotes remain extracted; only
    keywords are filtered. This guards the path that the strip pass
    doesn't accidentally swallow non-quoted tokens."""
    result = _extract_condition_variables("flag and source.x")
    assert "flag" in result
    assert "source.x" in result


def test_extract_bare_identifier_inside_quotes_is_ignored() -> None:
    """Quoted bare identifiers must not be extracted either."""
    result = _extract_condition_variables('source.x == "flag"')
    assert "flag" not in result
    assert "source.x" in result
