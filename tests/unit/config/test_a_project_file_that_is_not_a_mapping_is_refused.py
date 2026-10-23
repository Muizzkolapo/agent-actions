"""``load_project_config`` refuses a document that is not a mapping, like it refuses bad YAML.

A scalar or list document used to come back as-is, and every reader then failed on
``.get`` with an AttributeError that named nothing.
"""

import pytest

from agent_actions.config.path_config import load_project_config
from agent_actions.errors import ConfigValidationError


@pytest.mark.parametrize(("text", "kind"), [("hello\n", "str"), ("- a\n- b\n", "list")])
def test_a_non_mapping_document_is_refused_with_its_type_named(tmp_path, text, kind):
    (tmp_path / "agent_actions.yml").write_text(text)

    with pytest.raises(ConfigValidationError) as info:
        load_project_config(tmp_path)

    assert f"must be a mapping at the top level, got {kind}" in info.value.context["reason"]
    assert info.value.context["config_path"] == str(tmp_path / "agent_actions.yml")


def test_an_empty_document_is_the_empty_mapping(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("")

    assert load_project_config(tmp_path) == {}
