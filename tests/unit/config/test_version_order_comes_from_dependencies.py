"""`versions.mode` and `version_mode` are not settings — version order is the graph's.

Asserted at the render step because that is the only place the `versions:` block
is read: it is stripped from the action before `WorkflowConfig` validates, so a
check on the model alone never fires on a real workflow.
"""

import pytest
import yaml
from pydantic import ValidationError

from agent_actions.config import schema as schema_module
from agent_actions.config.schema import WorkflowConfig
from agent_actions.errors import ConfigurationError
from agent_actions.output.response.expander import ActionExpander
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}

# What the refusal has to say. A bare unknown-key error reads as a typo and sends
# the author to spell it differently rather than to the mechanism that works.
GUIDANCE = ("is no longer read", "configures nothing", "always parallel", "${i-1}")


def _action(**extra):
    return {
        "name": "a1",
        "kind": "llm",
        "intent": "i",
        "prompt": "p",
        "schema": {"verdict": "string"},
        **extra,
    }


def _workflow(defaults=None, actions=None):
    return {
        "name": "wf",
        "description": "d",
        "defaults": {**BASE_DEFAULTS, **(defaults or {})},
        "actions": actions or [_action()],
    }


def _render(tmp_path, workflow):
    """Load *workflow* the way every real config load does."""
    path = tmp_path / "wf.yml"
    path.write_text(yaml.safe_dump(workflow))
    templates = tmp_path / "templates"
    templates.mkdir(exist_ok=True)
    return yaml.safe_load(render_pipeline_with_templates(path, templates, compile_schemas=False))


def _agents(rendered):
    expanded = ActionExpander.expand_actions_to_agents(rendered)
    return [agent for agents in expanded.values() for agent in agents]


def _says_why(message):
    for phrase in GUIDANCE:
        assert phrase in message, f"the refusal does not say why or what to do instead: {message!r}"


class TestTheVersionsBlockIsRefusedWhereItIsRead:
    @pytest.mark.parametrize("mode", ["sequential", "parallel"])
    def test_a_mode_is_refused_with_the_mechanism_that_works(self, tmp_path, mode):
        """Both spellings: `parallel` configured nothing either, it only agreed."""
        workflow = _workflow(actions=[_action(versions={"range": [1, 3], "mode": mode})])

        with pytest.raises(ConfigurationError) as caught:
            _render(tmp_path, workflow)

        message = str(caught.value)
        assert "mode" in message
        assert "a1" in message, "a workflow of thirty actions needs to say which one"
        _says_why(message)

    def test_a_typo_in_the_block_is_refused_too(self, tmp_path):
        """The block reaches production unvalidated, so `param` could be misspelt
        and silently replaced by the default."""
        workflow = _workflow(actions=[_action(versions={"parem": "round", "range": [1, 2]})])

        with pytest.raises(ConfigurationError) as caught:
            _render(tmp_path, workflow)

        assert "parem" in str(caught.value)

    def test_a_range_that_is_not_a_range_is_refused(self, tmp_path):
        workflow = _workflow(actions=[_action(versions={"range": "one to three"})])

        with pytest.raises(ConfigurationError):
            _render(tmp_path, workflow)


class TestVersionModeOnAnActionIsRefused:
    def test_the_action_surface_refuses_it(self):
        with pytest.raises(ValidationError) as caught:
            WorkflowConfig.model_validate(_workflow(actions=[_action(version_mode="sequential")]))

        message = str(caught.value)
        assert "version_mode" in message
        _says_why(message)

    def test_the_defaults_surface_refuses_it(self):
        """Never declared there, but a refusal that only lists valid keys sends the
        author to try the block one level up — which is how a dead key spreads."""
        with pytest.raises(ValidationError) as caught:
            WorkflowConfig.model_validate(_workflow(defaults={"version_mode": "sequential"}))

        message = str(caught.value)
        assert "version_mode" in message
        _says_why(message)


class TestTheExpanderHandsNeitherKeyToTheAgent:
    def test_the_pre_expanded_path_carries_neither(self, tmp_path):
        """The path every real load takes."""
        agents = _agents(
            _render(tmp_path, _workflow(actions=[_action(versions={"range": [1, 2]})]))
        )

        assert len(agents) == 2
        for agent in agents:
            assert "version_mode" not in agent
            assert "version_number" not in agent

    def test_the_directly_expanded_path_carries_neither(self):
        """Reached by calling the expander with an unstripped `versions:` block."""
        expanded = ActionExpander.expand_actions_to_agents(
            {
                "name": "wf",
                "defaults": dict(BASE_DEFAULTS),
                "actions": [_action(versions={"param": "round", "range": [1, 2]})],
            }
        )
        agents = expanded["wf"]

        assert len(agents) == 2
        for agent in agents:
            assert "version_mode" not in agent
            assert "version_number" not in agent

    def test_the_agent_is_still_marked_as_a_version(self, tmp_path):
        """Guard: the assertions above also pass if the expander stopped expanding."""
        agents = _agents(
            _render(tmp_path, _workflow(actions=[_action(versions={"range": [1, 2]})]))
        )

        assert [a["name"] for a in agents] == ["a1_1", "a1_2"]
        for agent in agents:
            assert agent["is_versioned_agent"] is True
            assert agent["version_base_name"] == "a1"

    def test_the_version_index_is_still_there_under_the_name_that_is_read(self, tmp_path):
        """`version_number` duplicated this and was read by nothing."""
        agents = _agents(
            _render(tmp_path, _workflow(actions=[_action(versions={"range": [1, 2]})]))
        )

        assert [a["_version_context"]["i"] for a in agents] == [1, 2]
        assert [a["_version_context"]["idx"] for a in agents] == [0, 1]


class TestTheOrderingThatDoesWork:
    def test_chained_versions_still_run_one_at_a_time(self, tmp_path):
        """What `mode: sequential` claimed, done by the dependency graph."""
        rendered = _render(
            tmp_path,
            _workflow(
                actions=[
                    _action(
                        name="refine",
                        versions={"range": [1, 3]},
                        dependencies=["refine_${i-1}"],
                    )
                ]
            ),
        )
        configs = {a["name"]: a for a in _agents(rendered)}
        orchestrator = ActionLevelOrchestrator(
            execution_order=list(configs), action_configs=configs
        )

        assert orchestrator.compute_execution_levels() == [["refine_1"], ["refine_2"], ["refine_3"]]

    def test_unchained_versions_stay_in_one_level(self, tmp_path):
        """The contrast the inert key could not express: same config minus the
        dependency chain, and all three run together."""
        rendered = _render(
            tmp_path, _workflow(actions=[_action(name="vote", versions={"range": [1, 3]})])
        )
        configs = {a["name"]: a for a in _agents(rendered)}
        orchestrator = ActionLevelOrchestrator(
            execution_order=list(configs), action_configs=configs
        )

        assert orchestrator.compute_execution_levels() == [["vote_1", "vote_2", "vote_3"]]


class TestTheEnumThatPromisedIt:
    def test_the_schema_no_longer_names_a_version_execution_mode(self):
        """`VersionMode.SEQUENTIAL` was the spelled promise behind the key."""
        assert not hasattr(schema_module, "VersionMode")
        assert "VersionMode" not in schema_module.__all__


class TestAWorkflowThatAsksForNothingRetiredStillLoads:
    def test_a_versioned_action_without_a_mode_expands(self, tmp_path):
        rendered = _render(
            tmp_path,
            _workflow(actions=[_action(versions={"param": "round", "range": [1, 3]})]),
        )

        assert [a["name"] for a in rendered["actions"]] == ["a1_1", "a1_2", "a1_3"]

    def test_an_unversioned_action_is_untouched(self, tmp_path):
        rendered = _render(tmp_path, _workflow())

        assert [a["name"] for a in rendered["actions"]] == ["a1"]
        assert "_version_context" not in rendered["actions"][0]
