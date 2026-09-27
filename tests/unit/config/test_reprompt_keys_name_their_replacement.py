"""`reprompt:` and `on_schema_mismatch:` are not config keys — `expect:` took over.

Four blocks can carry either. Two of them are validated by models that allow extra
keys, so leaving the field undeclared refuses nothing there: the value rode onto
every agent, where no stage read it, and anything dumping an agent config showed the
setting present and apparently applied.

Every refusal is asserted to name `expect:`, not merely to fail. Unlike a key whose
feature was deleted outright, the behaviour these two asked for is still available —
so "unknown key" is not just unhelpful here, it costs the reader the migration and
invites them to try the same block one level up, which is the surface that kept
accepting it.
"""

import pytest
import yaml
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import (
    _RETIRED_CONFIG_KEYS,
    DefaultsConfig,
    WorkflowConfig,
)
from agent_actions.errors import ConfigurationError

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}

# The shapes the deleted runtime took, so each key is refused for being the key it
# is rather than for carrying a malformed value.
WRITTEN = {
    "reprompt": {"on_schema_mismatch": "reprompt", "max_attempts": 3},
    "on_schema_mismatch": "reject",
}

# The `expect:` blocks each key's own refusal names. They are asserted to validate as
# well as to be quoted: guidance that does not load sends the reader in a circle.
PRESCRIBED = {
    "reprompt": [{"repair": "auto"}, {"expectations": [{"type": "no_null_fields"}]}],
    "on_schema_mismatch": [{"repair": "auto"}, {"max_iterations": 1, "on_exhausted": "raise"}],
}

KEYS = sorted(WRITTEN)


def _msgs(caught: pytest.ExceptionInfo[ValidationError]) -> str:
    """Only what validation said.

    `str(ValidationError)` repeats the whole input under `input_value=`, so a bare
    key name asserted against it matches the echo rather than the message.
    """
    return "; ".join(error["msg"] for error in caught.value.errors())


def _workflow(defaults=None, action=None):
    return {
        "name": "wf",
        "description": "d",
        "version": "1.0",
        "defaults": {**BASE_DEFAULTS, **(defaults or {})},
        "actions": [{"name": "a1", "intent": "i", "prompt": "p", **(action or {})}],
    }


def _bare_manager() -> ConfigManager:
    cm = ConfigManager.__new__(ConfigManager)
    cm.default_config = {}
    cm.tool_path = None
    cm.agent_configs = {}
    return cm


def _project(tmp_path, agent_defaults):
    """A project whose agent_actions.yml carries *agent_defaults*."""
    (tmp_path / "agent_actions.yml").write_text(
        yaml.safe_dump({"project_name": "p", "default_agent_config": agent_defaults})
    )
    config_dir = tmp_path / "agent_config"
    config_dir.mkdir()
    # Named for the workflow it holds: a mismatch is refused for its own reason,
    # which would fail these tests before they reached the refusal under test.
    (config_dir / "wf.yml").write_text(yaml.safe_dump(_workflow()))
    manager = ConfigManager(
        str(config_dir / "wf.yml"), str(tmp_path / "agent_actions.yml"), project_root=tmp_path
    )
    manager.load_configs()
    manager.validate_agent_name()
    return manager


def _assert_names_the_replacement(message, key, surface):
    assert key in message, f"the {surface} refusal does not name the key: {message!r}"
    assert "expect:" in message, (
        f"the {surface} refusal does not name `expect:`, so a reader who deletes the "
        f"block loses the behaviour it asked for: {message!r}"
    )
    assert surface in message, (
        f"the refusal does not say which block holds the key, so a project whose "
        f"{surface} is in another file sends the reader to the wrong one: {message!r}"
    )


class TestTheStrictSurfaces:
    """`defaults:` and an action. Both refuse an undeclared key already, but with a
    message that only says it is unknown — which is what sends the author to try the
    block somewhere it was still accepted."""

    @pytest.mark.parametrize("key", KEYS)
    @pytest.mark.parametrize("level", ["action", "defaults"])
    def test_a_workflow_carrying_the_key_is_refused_naming_expect(self, level, key):
        written = {key: WRITTEN[key]}
        config = _workflow(action=written) if level == "action" else _workflow(defaults=written)

        with pytest.raises(ValidationError) as caught:
            WorkflowConfig.model_validate(config)

        _assert_names_the_replacement(_msgs(caught), key, level)

    @pytest.mark.parametrize("key", KEYS)
    def test_the_refusal_names_the_action_it_came_from(self, key):
        """pydantic locates the error as `actions.0`; a workflow of thirty needs the name."""
        with pytest.raises(ValidationError) as caught:
            WorkflowConfig.model_validate(
                _workflow(action={"name": "review_extraction", key: WRITTEN[key]})
            )

        assert "review_extraction" in _msgs(caught)


class TestTheSurfacesThatAllowExtras:
    """The bug. Neither model declares the key, and neither refuses it for that —
    so the value reached every agent and was read by none."""

    @pytest.mark.parametrize("key", KEYS)
    def test_the_legacy_agents_block_refuses_it(self, key):
        manager = _bare_manager()

        with pytest.raises(ConfigurationError) as caught:
            manager.merge_agent_configs(
                [{"agent_type": "a1", **BASE_DEFAULTS, "chunk_config": {}, key: WRITTEN[key]}]
            )

        message = str(caught.value)
        _assert_names_the_replacement(message, key, "agent")
        assert "a1" in message, "a list of agents needs to say which one carried it"

    @pytest.mark.parametrize("key", KEYS)
    def test_the_project_files_agent_defaults_refuse_it(self, key, tmp_path):
        """`default_agent_config:` is merged into every agent at once, so one block
        written here reached all of them."""
        manager = _project(tmp_path, {**BASE_DEFAULTS, key: WRITTEN[key]})

        with pytest.raises(ConfigurationError) as caught:
            manager.merge_agent_configs(manager.get_user_agents())

        _assert_names_the_replacement(str(caught.value), key, "default_agent_config")


class TestTheMigrationTheRefusalPrescribes:
    """A refusal that names a replacement is only as good as the replacement loading."""

    @pytest.mark.parametrize("key", KEYS)
    def test_every_expect_block_the_refusal_quotes_is_accepted(self, key):
        for block in PRESCRIBED[key]:
            WorkflowConfig.model_validate(_workflow(action={"expect": block}))
            DefaultsConfig.model_validate({**BASE_DEFAULTS, "expect": block})

    @pytest.mark.parametrize("key", KEYS)
    def test_the_refusal_quotes_the_block_that_replaces_this_key(self, key):
        """Pins guidance to key: `reject` halts and `reprompt` regenerates, and a
        refusal offering the other one silently changes what the action does."""
        with pytest.raises(ValidationError) as caught:
            WorkflowConfig.model_validate(_workflow(action={key: WRITTEN[key]}))

        message = _msgs(caught)
        assert "repair: auto" in message
        if key == "on_schema_mismatch":
            assert "on_exhausted: raise" in message, (
                "`reject` halted instead of regenerating; a refusal that only offers "
                f"repair: auto turns a halt into a retry loop: {message!r}"
            )
        else:
            assert "expectations:" in message, (
                "a block naming a validation: function becomes a rule list, and a "
                f"refusal that only offers repair: auto drops the checks: {message!r}"
            )


class TestTheSharedTableCoversEverySurface:
    """The guard the two keys needed: being in the table is what reaches all four
    blocks, so a key added to it without the surfaces behind it fails here."""

    @pytest.mark.parametrize("key", KEYS)
    def test_both_keys_are_in_the_table(self, key):
        assert key in _RETIRED_CONFIG_KEYS

    @pytest.mark.parametrize("key", sorted(_RETIRED_CONFIG_KEYS))
    def test_every_key_in_the_table_is_refused_on_all_four_surfaces(self, key, tmp_path):
        written = WRITTEN.get(key, {"any": "value"})

        for level in ("action", "defaults"):
            config = (
                _workflow(action={key: written})
                if level == "action"
                else _workflow(defaults={key: written})
            )
            with pytest.raises(ValidationError):
                WorkflowConfig.model_validate(config)

        with pytest.raises(ConfigurationError):
            _bare_manager().merge_agent_configs(
                [{"agent_type": "a1", **BASE_DEFAULTS, "chunk_config": {}, key: written}]
            )

        manager = _project(tmp_path, {**BASE_DEFAULTS, key: written})
        with pytest.raises(ConfigurationError):
            manager.merge_agent_configs(manager.get_user_agents())


class TestWhatTheRefusalMustNotSwallow:
    """Controls. Each asserts the check refuses only what it is for — a table that
    refuses a clean block, or one that replaces the general unknown-key rule, would
    pass every test above."""

    def test_a_key_that_is_merely_undeclared_still_gets_the_general_refusal(self):
        """The table is an extra message for keys that earned one, not the floor:
        anything undeclared is still refused by the rule that names what is valid."""
        with pytest.raises(ValidationError) as caught:
            DefaultsConfig.model_validate({**BASE_DEFAULTS, "few_shot": 0})

        message = _msgs(caught)
        assert "unknown defaults key 'few_shot'" in message
        assert "valid defaults keys are" in message

    def test_a_clean_project_still_reaches_every_agent(self, tmp_path):
        """The block really is merged into each agent, so the refusals above guard a
        value that arrived there — asserted on a setting the workflow does not carry,
        since one it does would be the action's own value arriving instead."""
        manager = _project(tmp_path, {**BASE_DEFAULTS, "temperature": 0.42})

        manager.merge_agent_configs(manager.get_user_agents())

        assert manager.agent_configs["a1"].model_dump()["temperature"] == 0.42

    def test_a_clean_legacy_agent_still_merges(self):
        manager = _bare_manager()

        manager.merge_agent_configs([{"agent_type": "a1", **BASE_DEFAULTS, "chunk_config": {}}])

        assert manager.agent_configs["a1"].model_dump()["model_name"] == "gpt-4"

    def test_an_expect_block_is_not_mistaken_for_the_keys_it_replaces(self):
        """`on_schema_mismatch` is refused as a key, not as a substring: `expect:`
        carries its own nested keys and a match on the wrong level would refuse the
        migration this change tells people to make."""
        config = _workflow(action={"expect": {"repair": "auto", "structural": "auto"}})

        assert WorkflowConfig.model_validate(config).actions[0].expect.structural == "auto"
