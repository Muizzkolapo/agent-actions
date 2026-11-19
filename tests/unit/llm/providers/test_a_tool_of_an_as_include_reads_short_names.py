"""A tool of an `as:` include gets its record's namespaces under the short names of its instance."""

from __future__ import annotations

import json

from agent_actions.llm.providers.tools.client import ToolClient

CONFIG = {
    "_include": {"instance": "c2", "names": {"write": "c2__write", "spec": "a", "prior": "a"}}
}


def test_a_namespace_of_the_instance_is_given_under_its_short_name_only():
    data = {"c2__write": {"text": "two"}, "a": {"text": "s"}, "source": {"text": "r"}}

    assert ToolClient._with_short_names(data, CONFIG) == {
        "write": {"text": "two"},
        "spec": {"text": "s"},
        "prior": {"text": "s"},
        "source": {"text": "r"},
    }


def test_a_record_given_as_json_text_is_renamed_too():
    renamed = ToolClient._with_short_names(json.dumps({"c2__write": {"text": "two"}}), CONFIG)

    assert json.loads(renamed) == {"write": {"text": "two"}}


def test_a_tool_outside_an_as_include_and_a_file_of_records_are_left_as_given():
    data = {"c2__write": {"text": "two"}}
    records = [{"c2__write": {"text": "two"}}]

    assert ToolClient._with_short_names(data, {"_include": {"instance": "pair"}}) is data
    assert ToolClient._with_short_names(data, {}) is data
    assert ToolClient._with_short_names(records, CONFIG) is records
