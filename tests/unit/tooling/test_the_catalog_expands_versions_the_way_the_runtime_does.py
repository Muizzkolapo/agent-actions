"""The catalog's version expansion must name the same agents the runtime does.

Three sites derive `{name}_{value}`: the runtime expander, the docs parser's own expansion,
and the map the parser normalises `context_scope` against. Determinism at each is not enough
-- they have to agree, and for a two-element range they did not: the expander reads it as an
inclusive start and end, the parser read it literally, so `range: [2, 5]` ran four actions and
documented two.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from agent_actions.config.schema import version_variant_names
from agent_actions.output.response.expander import ActionExpander
from agent_actions.tooling.docs.parser import WorkflowParser

# The expander resolves the model hierarchy before naming, so defaults must carry it.
_DEFAULTS = {"model_vendor": "anthropic", "model_name": "claude-3", "api_key": "ANTHROPIC_API_KEY"}
_RANGES = [
    {"param": "voter_id", "range": [1, 2, 3]},
    {"param": "voter_id", "range": [1, 2]},
    {"param": "iteration", "range": [2, 5]},
]


def _catalog_actions(version_config: dict) -> list[str]:
    workflow = {
        "name": "versioned",
        "description": "one versioned action",
        "defaults": dict(_DEFAULTS),
        "actions": [{"name": "voter", "intent": "v", "prompt": "p", "versions": version_config}],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "w.yml"
        path.write_text(yaml.dump(workflow), encoding="utf-8")
        parsed = WorkflowParser.parse_workflow(str(path))
    assert parsed is not None
    return sorted(parsed["actions"])


@pytest.mark.parametrize("version_config", _RANGES, ids=lambda c: str(c["range"]))
class TestAllThreeSitesAgree:
    def test_the_helper_matches_the_runtime_expander(self, version_config):
        expanded = ActionExpander._expand_versioned_action(
            {"name": "voter", "intent": "x", "prompt": "p"}, version_config, dict(_DEFAULTS)
        )
        expected = version_variant_names("voter", version_config)
        assert [a["name"] for a in expanded] == expected
        assert [a["agent_type"] for a in expanded] == expected

    def test_the_catalog_lists_exactly_those_agents(self, version_config):
        assert _catalog_actions(version_config) == sorted(
            version_variant_names("voter", version_config)
        )


def test_a_bounded_range_is_a_start_and_an_end():
    """The divergence this file exists for: [2, 5] is four agents, not two."""
    assert version_variant_names("voter", {"param": "i", "range": [2, 5]}) == [
        "voter_2",
        "voter_3",
        "voter_4",
        "voter_5",
    ]
    assert _catalog_actions({"param": "i", "range": [2, 5]}) == [
        "voter_2",
        "voter_3",
        "voter_4",
        "voter_5",
    ]


def test_an_explicit_list_is_taken_literally():
    """Three or more values are the values themselves, not bounds."""
    assert version_variant_names("voter", {"param": "i", "range": [1, 3, 7]}) == [
        "voter_1",
        "voter_3",
        "voter_7",
    ]


@pytest.mark.parametrize("version_config", _RANGES, ids=lambda c: str(c["range"]))
def test_the_renderer_names_variants_the_same_way(version_config):
    """The fourth site, and the one that matters most to the catalog.

    `render_workflow._expand_versioned_action` writes `artefact/rendered_workflows/`, which is
    what the docs scanner reads once a project has run. It keeps its own copy of the rule, so
    the map the catalog builds from `_version_context.base_name` only lines up with the action
    names in the same file while the two agree. Nothing else pins that.
    """
    from agent_actions.prompt.render_workflow import _expand_versioned_action

    action = {"name": "voter", "intent": "x", "prompt": "p", "versions": version_config}
    rendered = _expand_versioned_action(action)

    assert [a["name"] for a in rendered] == version_variant_names("voter", version_config)


def test_the_renderer_records_the_base_name_the_catalog_reads():
    """`_version_context.base_name` is the datum the catalog's version map is built from."""
    from agent_actions.prompt.render_workflow import _expand_versioned_action

    rendered = _expand_versioned_action(
        {
            "name": "voter",
            "intent": "x",
            "prompt": "p",
            "versions": {"param": "vid", "range": [1, 3]},
        }
    )

    assert [a["_version_context"]["base_name"] for a in rendered] == ["voter"] * 3
    assert all("versions" not in a for a in rendered), "the renderer strips the key"
