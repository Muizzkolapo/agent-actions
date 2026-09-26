"""`versions.mode` and `version_mode` are not settings — version order is the graph's.

Asserted at the render step because that is the only place the `versions:` block
is read: it is stripped from the action before `WorkflowConfig` validates, so a
check on the model alone never fires on a real workflow.
"""

import pytest
import yaml
from pydantic import ValidationError

from agent_actions.config import schema as schema_module
from agent_actions.config.schema import ActionConfig, VersionConfig, WorkflowConfig
from agent_actions.errors import ConfigurationError
from agent_actions.output.response.expander import ActionExpander
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.workflow.parallel.action_executor import ActionLevelOrchestrator

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}

# What the refusal has to say. A bare unknown-key error reads as a typo and sends
# the author to spell it differently rather than to the mechanism that works.
GUIDANCE = (
    "is no longer read",
    "configures nothing",
    "always parallel",
    "--execution-mode sequential",
)


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


def _render(tmp_path, workflow, validate=True):
    """Load *workflow* the way every real config load does.

    Validation is part of the path, not an extra: the loader renders and then
    validates the rendered config, and a versioned workflow that expands cleanly
    can still be refused by the dependency check the second step runs.
    """
    path = tmp_path / "wf.yml"
    path.write_text(yaml.safe_dump(workflow))
    templates = tmp_path / "templates"
    templates.mkdir(exist_ok=True)
    rendered = yaml.safe_load(
        render_pipeline_with_templates(path, templates, compile_schemas=False)
    )
    if validate:
        WorkflowConfig.model_validate(rendered)
    return rendered


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
        # Quoted: the hint ends in `--execution-mode sequential`, so a bare "mode"
        # is satisfied by the advice and says nothing about naming the key.
        assert "'mode'" in message
        assert "a1" in message, "a workflow of thirty actions needs to say which one"
        _says_why(message)

    def test_a_typo_in_the_block_is_refused_too(self, tmp_path):
        """The block reaches production unvalidated, so `param` could be misspelt
        and silently replaced by the default."""
        workflow = _workflow(actions=[_action(versions={"parem": "round", "range": [1, 2]})])

        with pytest.raises(ConfigurationError) as caught:
            _render(tmp_path, workflow)

        message = str(caught.value)
        assert "did you mean 'param'?" in message, (
            f"a bare unknown-key error sends the author to guess again: {message!r}"
        )
        assert "valid versions keys are param, range" in message

    @pytest.mark.parametrize("bad", ["one to three", {"from": 1}], ids=["string", "mapping"])
    def test_a_range_that_is_not_a_list_is_refused(self, tmp_path, bad):
        workflow = _workflow(actions=[_action(versions={"range": bad})])

        with pytest.raises(ConfigurationError) as caught:
            _render(tmp_path, workflow)

        assert "versions.range" in str(caught.value), "the refusal has to name the key"

    def test_a_range_written_as_floats_still_counts(self, tmp_path):
        """Pydantic coerces these, and the expansion reads what was validated —
        reading the raw block instead turned a valid config into a bare TypeError."""
        rendered = _render(tmp_path, _workflow(actions=[_action(versions={"range": [1.0, 3.0]})]))

        assert [a["name"] for a in rendered["actions"]] == ["a1_1", "a1_2", "a1_3"]

    def test_a_range_of_names_still_expands_over_them(self, tmp_path):
        """The documented non-numeric form: the values become the version suffixes."""
        workflow = _workflow(
            actions=[
                _action(
                    name="translate",
                    versions={"param": "strategy", "range": ["literal", "idiomatic", "domain"]},
                )
            ]
        )

        rendered = _render(tmp_path, workflow)

        assert [a["name"] for a in rendered["actions"]] == [
            "translate_literal",
            "translate_idiomatic",
            "translate_domain",
        ]

    def test_a_pair_of_names_cannot_be_counted_between(self, tmp_path):
        """Two elements are a start and an end, which names cannot be."""
        workflow = _workflow(actions=[_action(versions={"range": ["literal", "idiomatic"]})])

        with pytest.raises(ConfigurationError) as caught:
            _render(tmp_path, workflow)

        assert "no spelling here" in str(caught.value)

    @pytest.mark.parametrize("bad", [[], [3, 1]], ids=["empty", "descending"])
    def test_a_range_that_expands_to_nothing_is_refused(self, tmp_path, bad):
        """Expanding to zero versions deletes the action, reported only as a
        dangling dependency against whatever needed it."""
        workflow = _workflow(actions=[_action(versions={"range": bad})])

        with pytest.raises(ConfigurationError) as caught:
            _render(tmp_path, workflow)

        assert "removes the action" in str(caught.value)

    @pytest.mark.parametrize("block", [{}, None], ids=["braces", "bare"])
    def test_an_empty_block_declares_nothing_and_is_refused(self, tmp_path, block):
        """It fans out nothing, which is the shape this whole change refuses.

        `range` carrying a default means a missing field no longer refuses it, so
        the block has to be refused for being empty rather than for being short.
        """
        workflow = _workflow(actions=[_action(versions=block)])

        with pytest.raises(ConfigurationError) as caught:
            _render(tmp_path, workflow)

        message = str(caught.value)
        assert "a1" in message
        assert "fans out nothing" in message

    def test_a_block_that_only_names_the_param_still_expands(self, tmp_path):
        """The contrast: naming the param configures something, so it is not empty."""
        rendered = _render(tmp_path, _workflow(actions=[_action(versions={"param": "round"})]))

        assert [a["name"] for a in rendered["actions"]] == ["a1_1"]

    def test_a_key_only_the_static_analyser_looked_for_is_refused(self, tmp_path):
        """`items_from` was read out of this block and written by no workflow."""
        workflow = _workflow(
            actions=[_action(versions={"range": [1, 2], "items_from": "src.items"})]
        )

        with pytest.raises(ConfigurationError) as caught:
            _render(tmp_path, workflow)

        message = str(caught.value)
        assert "items_from" in message
        assert "valid versions keys are param, range" in message

    def test_a_block_with_no_range_expands_to_one_version(self, tmp_path):
        """`range` carries the default the expansion already applied."""
        rendered = _render(tmp_path, _workflow(actions=[_action(versions={"param": "round"})]))

        assert [a["name"] for a in rendered["actions"]] == ["a1_1"]


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


class TestBothExpansionsRefuseTheSameBlock:
    """One block must not mean two things depending on which expander ran.

    The render step strips `versions:`, so the expander's own expansion is reached
    only by callers handing over an unstripped block — and it used to accept
    everything the render step refuses.
    """

    def _expand(self, versions):
        return ActionExpander.expand_actions_to_agents(
            {
                "name": "wf",
                "defaults": dict(BASE_DEFAULTS),
                "actions": [_action(versions=versions)],
            }
        )

    @pytest.mark.parametrize(
        "versions, expected",
        [
            ({"range": [1, 2], "mode": "sequential"}, "'mode'"),
            ({"parem": "round", "range": [1, 2]}, "did you mean 'param'?"),
            ({"range": []}, "removes the action"),
            ({"range": [3, 1]}, "removes the action"),
            ({"range": ["literal", "idiomatic"]}, "no spelling here"),
        ],
        ids=["mode", "typo", "empty", "descending", "name-pair"],
    )
    def test_the_expander_refuses_what_the_render_step_refuses(self, versions, expected):
        with pytest.raises(ConfigurationError) as caught:
            self._expand(versions)

        assert expected in str(caught.value)

    def test_a_sound_block_still_expands_there(self):
        """Guard: the refusals above also pass if the expander stopped expanding."""
        agents = self._expand({"param": "round", "range": [1, 2]})["wf"]

        assert [a["name"] for a in agents] == ["a1_1", "a1_2"]


class TestTheOrderingThatDoesWork:
    def test_a_predecessor_reference_on_the_first_version_is_still_refused(self, tmp_path):
        """`${i-1}` has no predecessor on the first version, so it names nothing.

        Dropping the dependency instead would re-root that version onto source data
        and schedule it first — a wrong graph in place of a refusal, and it took a
        real edge with it whenever the range did not start at the chain's first link.
        """
        workflow = _workflow(
            actions=[
                _action(name="refine", versions={"range": [1, 3]}, dependencies=["refine_${i-1}"])
            ]
        )

        with pytest.raises(ValidationError) as caught:
            _render(tmp_path, workflow)

        assert "refine_" in str(caught.value)

    def test_versions_stay_in_one_level(self, tmp_path):
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

    def test_the_action_surface_no_longer_declares_the_key(self):
        """Pinned on the field: re-adding it untyped would slip past the enum check."""
        assert "version_mode" not in ActionConfig.model_fields

    def test_the_block_declares_only_what_it_reads(self):
        """The authoring surfaces read this, so a stray field is offered to users."""
        assert set(VersionConfig.model_fields) == {"param", "range"}


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
