"""What a `defaults:` block does with a key the schema does not declare."""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import DefaultsConfig
from agent_actions.llm.providers.generation_params import extract_generation_params


def refusal(**defaults) -> str:
    with pytest.raises(ValidationError) as excinfo:
        DefaultsConfig.model_validate({"model_vendor": "openai", **defaults})
    return str(excinfo.value)


class TestAKeyTheSchemaDoesNotDeclare:
    def test_a_mistyped_known_key_is_refused_with_the_near_match(self):
        """The whole point of refusing: a typo does nothing today and says nothing."""
        message = refusal(temperture=0.7)

        assert "temperture" in message
        assert "temperature" in message

    def test_a_key_with_no_near_match_is_refused_naming_the_valid_ones(self):
        message = refusal(few_shot=0)

        assert "few_shot" in message
        assert "model_vendor" in message and "record_limit" in message

    def test_a_key_far_from_every_field_is_not_given_a_suggestion(self):
        """A retired spelling is not a typo, and guessing at one misdirects."""
        message = refusal(reprompt={"max_iterations": 2})

        assert "did you mean" not in message

    def test_every_unknown_key_is_named_not_only_the_first(self):
        message = refusal(few_shot=0, totally_bogus=True)

        assert "few_shot" in message
        assert "totally_bogus" in message


class TestASupersededSpellingKeepsBeingRefused:
    """Refused by the rule that covers every undeclared key, not by a table of
    the ones someone remembered to list."""

    @pytest.mark.parametrize("key", ["reprompt", "on_schema_mismatch"])
    def test_it_is_refused(self, key):
        assert key in refusal(**{key: {"max_iterations": 2}})

    @pytest.mark.parametrize("key", ["reprompt", "on_schema_mismatch"])
    def test_the_refusal_does_not_narrate_the_replacement(self, key):
        message = refusal(**{key: {"max_iterations": 2}})

        assert "has been replaced" not in message
        assert "expect:" not in message


class TestTheParamsTheProvidersActuallySend:
    """`frequency_penalty` and `presence_penalty` are the only params any client
    asks for beyond the core four, and a default is where they are written."""

    def test_they_survive_validation(self):
        config = DefaultsConfig.model_validate(
            {"model_vendor": "openai", "frequency_penalty": 0.2, "presence_penalty": 0.1}
        )

        assert (config.frequency_penalty, config.presence_penalty) == (0.2, 0.1)

    def test_they_reach_a_client_through_the_merged_defaults(self):
        config = DefaultsConfig.model_validate(
            {"model_vendor": "openai", "temperature": 0.7, "frequency_penalty": 0.2}
        )
        agent_config = config.model_dump(mode="python", exclude_unset=True, by_alias=True)

        params = extract_generation_params(
            agent_config, extra_params=("frequency_penalty", "presence_penalty")
        )

        assert params == {"temperature": 0.7, "frequency_penalty": 0.2}

    @pytest.mark.parametrize("value", [-2.5, 2.5])
    def test_a_value_the_api_rejects_is_refused_here(self, value):
        assert "frequency_penalty" in refusal(frequency_penalty=value)


class TestADeclaredKeyIsUntouched:
    def test_it_is_accepted(self):
        config = DefaultsConfig.model_validate({"model_vendor": "openai", "temperature": 0.7})

        assert (config.model_vendor, config.temperature) == ("openai", 0.7)

    def test_an_empty_block_is_accepted(self):
        assert DefaultsConfig.model_validate({}).model_vendor is None
