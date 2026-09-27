"""`reprompt:` and `on_schema_mismatch:` are not config keys — `expect:` took over.

Two of the four blocks that can carry either allow extra keys, so leaving the field
undeclared refuses nothing there and the value rode onto every agent unread. Each
refusal is asserted to name `expect:` rather than only to fail: the behaviour these
asked for is still available, so "unknown key" costs the reader the migration.
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
from agent_actions.expectations.loader import build_inline_suite
from agent_actions.output.response.expander import ActionExpander

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4", "api_key": "k"}

# The shapes the deleted runtime took, so each key is refused for being the key it
# is rather than for carrying a malformed value.
WRITTEN = {
    "reprompt": {"on_schema_mismatch": "reprompt", "max_attempts": 3},
    "on_schema_mismatch": "reject",
}

# What only the other key's migration says, so a single hint serving both is caught.
# They share `repair: auto`, and asserting on that alone would accept one sentence
# stitched from both — which tells a `reject` author to start a retry loop.
ONLY_THE_OTHERS = {
    "reprompt": "on_exhausted: raise",
    "on_schema_mismatch": "expectations:",
}

RETIRED_MARKER = "is no longer read"

KEYS = sorted(WRITTEN)


def _refusal_for(key: str, level: str = "action") -> str:
    written = {key: WRITTEN[key]}
    config = _workflow(action=written) if level == "action" else _workflow(defaults=written)
    with pytest.raises(ValidationError) as caught:
        WorkflowConfig.model_validate(config)
    return _msgs(caught)


def _quoted_expect_blocks(message: str) -> list[dict]:
    """Every `expect: {...}` the refusal quotes, parsed as the reader would paste it.

    Read out of the message rather than listed here on purpose: a list of blocks kept
    beside the test passes while the message drifts to prescribing something that does
    not load, which is the one failure a migration hint has.
    """
    marker = "expect: "
    blocks = []
    for start in (i for i in range(len(message)) if message.startswith(marker + "{", i)):
        depth, j = 0, start + len(marker)
        while j < len(message):
            if message[j] == "{":
                depth += 1
            elif message[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blocks.append(yaml.safe_load(message[start + len(marker) : j + 1]))
    return blocks


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


def _expand(action):
    """Expand a raw action dict, skipping validation.

    Deliberately not through `WorkflowConfig`, which now refuses this input: a test
    that could only reach the expander through the schema would stop exercising it at
    the point the expander's own half needs proving.
    """
    expanded = ActionExpander.expand_actions_to_agents(
        {
            "name": "wf",
            "actions": [{"name": "a1", "intent": "i", "prompt": "p", **action}],
            "defaults": dict(BASE_DEFAULTS),
        }
    )
    return expanded["wf"][0]


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
    def test_every_expect_block_the_refusal_quotes_actually_loads(self, key):
        """Parsed out of the message, not listed beside the test: the block a reader
        pastes is the one the message holds, so that is what has to validate.

        Config validation is not enough on its own. `ExpectConfig.expectations` keeps
        raw dicts, so a quoted rule reaches the run unchecked by the schema — a
        misspelt type, or a real one missing its required `field:`, loads here and dies
        where the suite is built. Both layers, or the rule half of the hint is unpinned.
        """
        message = _refusal_for(key)
        blocks = _quoted_expect_blocks(message)

        assert blocks, f"the refusal names no expect: block to migrate to: {message!r}"
        for block in blocks:
            WorkflowConfig.model_validate(_workflow(action={"expect": block}))
            DefaultsConfig.model_validate({**BASE_DEFAULTS, "expect": block})
            if block.get("expectations"):
                build_inline_suite(block["expectations"], "a1")

    @pytest.mark.parametrize("key", KEYS)
    def test_the_refusal_quotes_the_block_that_replaces_this_key(self, key):
        message = _refusal_for(key)

        assert "repair: auto" in message
        assert ONLY_THE_OTHERS[key] not in message, (
            f"the '{key}' refusal also offers the other key's migration, and the two "
            f"are not interchangeable — `reject` halts where `reprompt` regenerates, so "
            f"following the wrong one turns a deliberate halt into a retry loop, or "
            f"drops the rules a validation: function checked: {message!r}"
        )

    @pytest.mark.parametrize("key", KEYS)
    def test_the_block_it_quotes_does_what_the_key_did(self, key):
        """Loading is not enough: `reject` halted, so its replacement must halt too.

        Asserted on the validated model rather than the message, since the message is
        what is under test.
        """
        blocks = _quoted_expect_blocks(_refusal_for(key))
        validated = [DefaultsConfig.model_validate({**BASE_DEFAULTS, "expect": b}) for b in blocks]

        if key == "on_schema_mismatch":
            halting = [v.expect for v in validated if v.expect.on_exhausted == "raise"]
            assert halting, "no quoted block halts, so `reject` has no replacement offered"
            assert halting[0].max_iterations == 1, (
                "a halting block that still loops is not what `reject` did: "
                f"max_iterations={halting[0].max_iterations}"
            )
        else:
            assert any(v.expect.expectations for v in validated), (
                "no quoted block carries rules, so a block naming a validation: "
                "function has no replacement offered"
            )


class TestTheExpanderHandsNeitherKeyToTheAgent:
    """The two strict surfaces are refused, so nothing should reach expansion — but
    the expander copies action keys onto the agent and is the carrier that made the
    sibling retired key look applied. Asserted on the agent it actually builds."""

    @pytest.mark.parametrize("key", KEYS)
    def test_no_expanded_agent_carries_the_key(self, key):
        agent = _expand({key: WRITTEN[key]})

        assert key not in agent, (
            f"the expander copied '{key}' onto the agent, where no stage reads it: "
            f"{agent.get(key)!r}"
        )

    @pytest.mark.parametrize("key", KEYS)
    def test_the_expander_still_carries_what_it_processes_beside_the_key(self, key):
        """Guard on the guard: the assertion above also passes if the expander stopped
        building agents or ignored the action. `expect:` is the replacement and sits in
        the same step, so it must survive on an action carrying both."""
        agent = _expand({key: WRITTEN[key], "expect": {"repair": "auto"}})

        assert agent["expect"]["repair"] == "auto"
        assert key not in agent


class TestTheSharedTableCoversEverySurface:
    """The guard the two keys needed: being in the table is what reaches all four
    blocks, so a key added to it without the surfaces behind it fails here."""

    @pytest.mark.parametrize("key", KEYS)
    def test_both_keys_are_in_the_table(self, key):
        assert key in _RETIRED_CONFIG_KEYS

    @pytest.mark.parametrize("key", sorted(_RETIRED_CONFIG_KEYS))
    def test_every_key_in_the_table_is_refused_on_all_four_surfaces(self, key, tmp_path):
        written = WRITTEN.get(key, {"any": "value"})

        # The marker, not a bare raises: both strict surfaces already refuse any
        # undeclared key, so a key in the table that reached only the general rule
        # would satisfy `raises(ValidationError)` while saying nothing about itself.
        for level in ("action", "defaults"):
            config = (
                _workflow(action={key: written})
                if level == "action"
                else _workflow(defaults={key: written})
            )
            with pytest.raises(ValidationError) as caught:
                WorkflowConfig.model_validate(config)
            assert RETIRED_MARKER in _msgs(caught), (
                f"'{key}' is in the table but the {level} surface fell through to the "
                f"generic unknown-key refusal: {_msgs(caught)!r}"
            )

        with pytest.raises(ConfigurationError) as raised:
            _bare_manager().merge_agent_configs(
                [{"agent_type": "a1", **BASE_DEFAULTS, "chunk_config": {}, key: written}]
            )
        assert RETIRED_MARKER in str(raised.value)

        manager = _project(tmp_path, {**BASE_DEFAULTS, key: written})
        with pytest.raises(ConfigurationError) as raised:
            manager.merge_agent_configs(manager.get_user_agents())
        assert RETIRED_MARKER in str(raised.value)


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

    @pytest.mark.parametrize("key", KEYS)
    def test_a_retired_name_inside_a_rules_params_is_not_refused(self, key):
        """A rule's `params:` takes type-specific arguments under any name, so one may
        legitimately be spelled like a retired key — and matching recursively would
        refuse the migration this refusal prescribes.

        The fixture carries the name at depth and is a rule the run accepts: one level
        higher is refused by `Expectation`, so pinning that would assert the config
        layer taking something the run throws out.
        """
        rule = {"type": "no_null_fields", "params": {key: WRITTEN[key]}}
        config = _workflow(action={"expect": {"expectations": [rule]}})

        validated = WorkflowConfig.model_validate(config)
        build_inline_suite([rule], "a1")

        assert validated.actions[0].expect.expectations == [rule]
