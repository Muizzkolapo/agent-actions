"""A bare `?` inside `[ ]` or `{ }` is a YAML error, and the error says how to write it.

An optional observe entry ends in `?`. On a line of its own that is plain YAML; inside
an inline list or mapping the parser stops at it, and "check the YAML syntax" does not
say that quoting the entry is all it takes.
"""

from __future__ import annotations

import pytest
import yaml

from agent_actions.logging.errors.formatters.yaml import YAMLSyntaxErrorFormatter


@pytest.mark.parametrize(
    "document",
    [
        "context_scope: { observe: [source.text, review.rejected_text?] }",
        "observe:\n  - {field: review.rejected_text?, default: none}\n",
    ],
    ids=["inline-list", "inline-mapping"],
)
def test_the_fix_says_to_quote_the_entry(document):
    with pytest.raises(yaml.YAMLError) as raised:
        yaml.safe_load(document)

    fix = YAMLSyntaxErrorFormatter()._get_fix_suggestion(raised.value.problem)

    assert '"action.field?"' in fix
    assert "one entry per line" in fix


def test_the_quoted_entry_and_the_entry_on_its_own_line_both_load():
    quoted = yaml.safe_load('observe: [source.text, "review.rejected_text?"]')
    own_line = yaml.safe_load("observe:\n  - source.text\n  - review.rejected_text?\n")

    assert quoted == own_line == {"observe": ["source.text", "review.rejected_text?"]}
