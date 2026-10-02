"""`expect:` in `default_agent_config:` goes through ExpectConfig like anywhere else.

`DefaultAgentConfig` is extra="allow", so the block reached ExpectationService unchecked
while the identical block is refused on an action. That matters more since #1066, whose
refusal message sends a migrating author to this very block — landing them back in the
silence the refusal exists to end.
"""

import pytest

from agent_actions.errors import ConfigurationError


def _validate(defaults: dict):
    """Imported per call so this file still collects before the helper exists."""
    from agent_actions.config.manager import _validate_project_expect_block

    return _validate_project_expect_block(defaults)


class TestTheBlockIsRefusedWhereItWouldRunWrong:
    def test_an_out_of_range_iteration_count_is_refused(self):
        """Declared 1-10; measured, 99 ran 99 generations per record."""
        with pytest.raises(ConfigurationError) as excinfo:
            _validate({"expect": {"max_iterations": 99}})

        assert "default_agent_config.expect" in str(excinfo.value)
        assert "less than or equal to 10" in str(excinfo.value)

    def test_iteration_keys_under_repair_none_are_refused(self):
        """They were silently dropped — `repair: none` never loops."""
        with pytest.raises(ConfigurationError) as excinfo:
            _validate({"expect": {"repair": "none", "max_iterations": 2}})

        assert "max_iterations" in str(excinfo.value)

    def test_a_scalar_block_is_refused_rather_than_coerced_to_none(self):
        with pytest.raises(ConfigurationError):
            _validate({"expect": "auto"})

    def test_the_message_names_the_surface(self):
        """An author reading it has to know which of the four blocks to fix."""
        with pytest.raises(ConfigurationError, match=r"default_agent_config\.expect"):
            _validate({"expect": {"max_iterations": 0}})


class TestValidConfigurationIsUnaffected:
    def test_a_valid_block_passes_through(self):
        result = _validate({"expect": {"max_iterations": 5}})

        assert result["expect"] == {"max_iterations": 5}

    def test_only_what_the_author_wrote_survives(self):
        """exclude_unset, or the merge below would see defaults as explicit settings
        and outrank a workflow that set them deliberately."""
        result = _validate({"expect": {"repair": "auto"}})

        assert result["expect"] == {"repair": "auto"}, result["expect"]

    def test_no_expect_block_is_left_alone(self):
        defaults = {"model_vendor": "openai", "chunk_config": {"size": 1}}

        assert _validate(defaults) == defaults

    def test_other_keys_are_preserved_beside_a_validated_block(self):
        result = _validate({"model_vendor": "openai", "expect": {"max_iterations": 2}})

        assert result["model_vendor"] == "openai"
        assert result["expect"] == {"max_iterations": 2}


class TestTheShippedProjectsStillLoad:
    """A load-time refusal must not reject a project that runs today."""

    def test_no_shipped_project_declares_a_block_this_would_refuse(self):
        from pathlib import Path

        import yaml

        root = Path(__file__).resolve().parents[3]
        files = sorted(root.glob("examples/*/agent_actions.yml"))
        files += sorted(root.glob("tests/integration/fixtures/*/agent_actions.yml"))
        assert files, "no project files found"

        for path in files:
            data = yaml.safe_load(path.read_text()) or {}
            defaults = data.get("default_agent_config") or {}
            _validate(defaults)
