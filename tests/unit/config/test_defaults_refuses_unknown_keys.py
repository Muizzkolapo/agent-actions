"""What a `defaults:` block does with a key the schema does not declare."""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, DefaultsConfig, WorkflowConfig
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.output.response.config_fields import SIMPLE_CONFIG_FIELDS
from agent_actions.output.response.expander import ActionExpander

BASE = {"model_vendor": "openai", "model_name": "gpt-4o-mini", "api_key": "KEY"}


def refusal(**defaults) -> str:
    with pytest.raises(ValidationError) as excinfo:
        DefaultsConfig.model_validate({**BASE, **defaults})
    return str(excinfo.value)


def agent_for(**defaults) -> dict:
    """The agent dict a provider is handed, built the way a run builds it."""
    workflow = WorkflowConfig.model_validate(
        {
            "name": "w",
            "description": "d",
            "defaults": {**BASE, **defaults},
            "actions": [{"name": "act", "intent": "i", "kind": "llm"}],
        }
    )
    expanded = {
        "name": "w",
        "actions": [
            a.model_dump(mode="python", exclude_unset=True, by_alias=True) for a in workflow.actions
        ],
        "defaults": workflow.defaults.model_dump(mode="python", exclude_unset=True, by_alias=True),
    }
    return ActionExpander.expand_actions_to_agents(expanded)["w"][0]


class TestAKeyTheSchemaDoesNotDeclare:
    def test_a_mistyped_known_key_is_refused_with_the_near_match(self):
        """The whole point of refusing: a typo does nothing today and says nothing."""
        assert "unknown defaults key 'temperture' — did you mean 'temperature'?" in refusal(
            temperture=0.7
        )

    def test_a_named_near_match_replaces_the_list_rather_than_joining_it(self):
        """Asserted by the list's absence, because the list holds every declared
        key — so a refusal that only ever lists them satisfies any test looking
        for the resembled key by name."""
        message = refusal(temperture=0.7)

        assert "valid defaults keys are" not in message
        assert "record_limit" not in message

    def test_a_key_with_no_near_match_is_refused_naming_the_valid_ones(self):
        message = refusal(few_shot=0)

        assert "unknown defaults key 'few_shot'" in message
        assert "model_vendor" in message and "record_limit" in message

    def test_a_key_far_from_every_field_is_not_given_a_suggestion(self):
        """A superseded spelling is not a typo, and guessing at one misdirects.

        `reprompt` sits at 0.600 against `prompt_debug`, under the cutoff by
        0.05 — so declaring a field spelled near it would flip this.
        """
        assert "did you mean" not in refusal(reprompt={"max_iterations": 2})

    def test_every_unknown_key_is_named_not_only_the_first(self):
        message = refusal(few_shot=0, totally_bogus=True)

        assert "few_shot" in message
        assert "totally_bogus" in message


class TestASupersededSpellingKeepsBeingRefused:
    """Refused by the rule covering every undeclared key, not by a table of the
    ones someone remembered to list."""

    @pytest.mark.parametrize("key", ["reprompt", "on_schema_mismatch"])
    def test_it_is_refused_by_that_rule(self, key):
        message = refusal(**{key: {"max_iterations": 2}})

        assert f"unknown defaults key '{key}'" in message
        assert "valid defaults keys are" in message

    @pytest.mark.parametrize("key", ["reprompt", "on_schema_mismatch"])
    def test_the_refusal_does_not_narrate_the_replacement(self, key):
        message = refusal(**{key: {"max_iterations": 2}})

        assert "has been replaced" not in message
        assert "expect:" not in message


class TestAnActionIsRefusedTheSameWay:
    def test_a_mistyped_action_key_names_the_key_it_resembles(self):
        with pytest.raises(ValidationError) as excinfo:
            ActionConfig.model_validate({"name": "a", "intent": "i", "temperture": 0.7})

        assert "unknown action key 'temperture' — did you mean 'temperature'?" in str(excinfo.value)

    def test_a_key_spelled_as_its_alias_is_accepted(self):
        """`schema:` is the spelling the field validates from; the field's own
        name is not, so accepted keys have to be read off the aliases."""
        assert (
            ActionConfig.model_validate({"name": "a", "intent": "i", "schema": "s"}).output_schema
            == "s"
        )


class TestWhatTheFrameworkReadsFromADefaultsBlock:
    def test_every_inherited_field_can_be_written_there(self):
        """Field inheritance reads each of these out of `defaults:`, so refusing
        one would refuse a key the framework itself goes looking for."""
        assert set(SIMPLE_CONFIG_FIELDS) <= set(DefaultsConfig.model_fields)

    @pytest.mark.parametrize(
        "key,value",
        [
            ("enable_prompt_caching", True),
            ("anthropic_version", "2023-06-01"),
            ("max_execution_time", 30),
            ("enable_caching", False),
            ("tokenizer_model", "cl100k_base"),
            ("split_method", "tiktoken"),
            ("where_clause", {"field": "x"}),
        ],
    )
    def test_it_reaches_the_agent(self, key, value):
        assert agent_for(**{key: value})[key] == value


class TestTheParamsTheProvidersActuallySend:
    """`frequency_penalty` and `presence_penalty` are the only params any client
    asks for beyond the core four, and a default is where they are written."""

    def test_they_reach_a_client_through_the_real_expansion(self):
        agent = agent_for(temperature=0.7, frequency_penalty=0.2, presence_penalty=0.1)

        params = extract_generation_params(
            agent, extra_params=("frequency_penalty", "presence_penalty")
        )

        assert params == {"temperature": 0.7, "frequency_penalty": 0.2, "presence_penalty": 0.1}

    def test_an_action_can_override_the_default(self):
        workflow = WorkflowConfig.model_validate(
            {
                "name": "w",
                "description": "d",
                "defaults": {**BASE, "frequency_penalty": 0.2},
                "actions": [
                    {"name": "act", "intent": "i", "kind": "llm", "frequency_penalty": 1.5}
                ],
            }
        )
        expanded = {
            "name": "w",
            "actions": [
                a.model_dump(mode="python", exclude_unset=True, by_alias=True)
                for a in workflow.actions
            ],
            "defaults": workflow.defaults.model_dump(
                mode="python", exclude_unset=True, by_alias=True
            ),
        }
        agent = ActionExpander.expand_actions_to_agents(expanded)["w"][0]

        assert agent["frequency_penalty"] == 1.5

    @pytest.mark.parametrize("value", [-2.5, 2.5])
    def test_a_value_the_api_rejects_is_refused_here(self, value):
        assert "frequency_penalty" in refusal(frequency_penalty=value)

    @pytest.mark.parametrize("value", [-0.1, 1.1])
    def test_a_top_p_outside_its_range_is_refused(self, value):
        """A near match points here from `top_k`, and an unbounded value would
        travel to the provider verbatim."""
        assert "top_p" in refusal(top_p=value)


class TestADeclaredKeyIsUntouched:
    def test_it_is_accepted(self):
        config = DefaultsConfig.model_validate({**BASE, "temperature": 0.7})

        assert (config.model_vendor, config.temperature) == ("openai", 0.7)

    def test_an_empty_block_is_accepted(self):
        assert DefaultsConfig.model_validate({}).model_vendor is None
