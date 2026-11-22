"""The action names a prompt references are read once per template and alias map."""

import logging

import pytest
from jinja2.exceptions import TemplateSyntaxError

from agent_actions.prompt.context.scope_parsing import extract_action_names_from_template

TEMPLATE = "{{ extract.claims }} {{ score.value }} {{ source.text }}"
ALIASED = "{% set e = extract %}{{ e.claims }} {{ score.value }}"


def test_every_call_gets_a_set_of_its_own():
    first = extract_action_names_from_template(TEMPLATE)
    first.add("intruder")

    assert extract_action_names_from_template(TEMPLATE) == {"extract", "score"}


def test_the_alias_map_is_part_of_what_is_read():
    assert extract_action_names_from_template(ALIASED) == {"score"}
    assert extract_action_names_from_template(ALIASED, {"e": "extract"}) == {"extract", "score"}
    assert extract_action_names_from_template(ALIASED) == {"score"}


def test_an_alias_map_with_unhashable_values_is_still_read():
    assert extract_action_names_from_template(ALIASED, {"e": ["extract"]}) == {"score"}  # type: ignore[dict-item]


def test_a_syntax_error_is_raised_and_reported_on_every_call(caplog):
    with caplog.at_level(logging.WARNING, logger="agent_actions.prompt.context.scope_parsing"):
        for _ in range(2):
            with pytest.raises(TemplateSyntaxError):
                extract_action_names_from_template("{% if broken %}")

    assert len(caplog.records) == 2
