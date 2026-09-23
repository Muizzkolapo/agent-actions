"""What a `defaults:` block does with a key the schema does not declare."""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import (
    ActionConfig,
    DefaultsConfig,
    StorageConfig,
    WorkflowConfig,
)
from agent_actions.llm.providers.generation_params import extract_generation_params
from agent_actions.output.response.config_fields import SIMPLE_CONFIG_FIELDS
from agent_actions.output.response.expander import ActionExpander

BASE = {"model_vendor": "openai", "model_name": "gpt-4o-mini", "api_key": "KEY"}


def refusal(**defaults) -> str:
    """Only what validation said, without pydantic's echo of the input.

    `str(ValidationError)` repeats the whole input dict under `input_value=`,
    so asserting a bare key name against it matches the echo rather than the
    message the refusal built.
    """
    with pytest.raises(ValidationError) as excinfo:
        DefaultsConfig.model_validate({**BASE, **defaults})
    return "; ".join(error["msg"] for error in excinfo.value.errors())


def bounds_refusal(model, **fields) -> str:
    """What either config surface says about a value outside a field's range."""
    payload = (
        {"name": "a", "intent": "i", **fields} if model is ActionConfig else {**BASE, **fields}
    )
    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(payload)
    return "; ".join(error["msg"] for error in excinfo.value.errors())


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

    def test_the_keys_it_takes_are_listed_even_when_one_is_guessed(self):
        """A guess is a string-distance match and lands on a real field often
        enough to be wrong; the list is what the reader falls back to."""
        message = refusal(temperture=0.7)

        assert "valid defaults keys are" in message
        assert "record_limit" in message

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

        assert "unknown defaults key 'few_shot'" in message
        assert "unknown defaults key 'totally_bogus'" in message

    def test_a_typo_the_cutoff_barely_admits_is_still_named(self):
        """`top_k` scores 0.800 against `top_p`, the lowest-scoring near miss
        the framework should still name. Pins the cutoff from above; the
        superseded spellings pin it from below."""
        assert "did you mean 'top_p'?" in refusal(top_k=40)


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


class TestWhatTheFrameworkReadsFromADefaultsBlock:
    def test_no_field_is_aliased(self):
        """The refusal reads accepted keys off field names. An aliased field
        validates from its alias instead, so one added here would be listed
        under a spelling the block rejects, and its real spelling refused."""
        aliased = [
            name
            for name, field in DefaultsConfig.model_fields.items()
            if field.alias or field.validation_alias
        ]

        assert aliased == []

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
            ("tokenizer_model", "gpt2"),
            ("split_method", "sentence"),
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

    @pytest.mark.parametrize("model", [ActionConfig, DefaultsConfig])
    @pytest.mark.parametrize(
        "field,value,bound",
        [
            ("temperature", -0.1, "greater than"),
            ("temperature", 2.1, "less than"),
            ("top_p", -0.1, "greater than"),
            ("top_p", 1.1, "less than"),
            ("frequency_penalty", -2.5, "greater than"),
            ("frequency_penalty", 2.5, "less than"),
            ("presence_penalty", -2.5, "greater than"),
            ("presence_penalty", 2.5, "less than"),
        ],
    )
    def test_a_value_outside_its_range_is_refused_on_both_surfaces(
        self, model, field, value, bound
    ):
        """By the range, not by the field name: an undeclared field is refused
        with its name in the message too. `top_p` matters most — a near match
        points there from `top_k` — but a range is only a guard where something
        checks it, so each surface is asserted."""
        assert bound in bounds_refusal(model, **{field: value})


class TestADeclaredKeyIsUntouched:
    def test_it_is_accepted(self):
        config = DefaultsConfig.model_validate({**BASE, "temperature": 0.7})

        assert (config.model_vendor, config.temperature) == ("openai", 0.7)

    def test_an_empty_block_is_accepted(self):
        assert DefaultsConfig.model_validate({}).model_vendor is None


class TestTheBackstopBehindTheRefusal:
    """Both surfaces carry `extra="forbid"` as well as the before-validator.

    The validator raises first, so pydantic's own refusal never fires and no
    behavioural test can reach it — a mutation probe flipping `forbid` to
    `ignore` survives the whole suite. Pinned here so the line is not read as
    dead and deleted, which would leave the refusal resting on one mechanism:
    `_refuse_undeclared_keys` returns its input untouched for anything that is
    not a dict, and `forbid` is what covers that.
    """

    @pytest.mark.parametrize("model", [DefaultsConfig, WorkflowConfig, StorageConfig])
    def test_extras_are_forbidden_not_merely_refused_by_the_validator(self, model):
        assert model.model_config.get("extra") == "forbid"
