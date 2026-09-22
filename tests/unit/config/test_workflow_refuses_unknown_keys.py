"""What a workflow file does with a top-level key the schema does not declare.

The block's *contents* are already guarded; this is the surface holding it. A
transposed letter in `defaults:` costs the whole section rather than one setting,
and the run that follows looks healthy.
"""

import pytest
import yaml
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import WorkflowConfig

VALID = {
    "name": "w",
    "description": "d",
    "actions": [{"name": "a", "intent": "i"}],
}


def refusal(**top_level) -> str:
    """Only what validation said, without pydantic's echo of the input.

    `str(ValidationError)` repeats the whole input dict under `input_value=`, so
    asserting a bare key name against it matches the echo rather than the message
    the refusal built.
    """
    with pytest.raises(ValidationError) as excinfo:
        WorkflowConfig.model_validate({**VALID, **top_level})
    return "; ".join(error["msg"] for error in excinfo.value.errors())


class TestAKeyTheWorkflowDoesNotDeclare:
    def test_a_misspelled_defaults_block_is_refused_with_the_near_match(self):
        """One transposed letter silently discarded every default in the file."""
        assert "unknown workflow key 'defaluts' — did you mean 'defaults'?" in refusal(
            defaluts={"model_vendor": "openai", "temperature": 0.2}
        )

    def test_a_capitalised_defaults_block_is_refused_too(self):
        """YAML keys are case-sensitive; `Defaults:` reads as a different key."""
        assert "unknown workflow key 'Defaults' — did you mean 'defaults'?" in refusal(
            Defaults={"model_vendor": "openai"}
        )

    def test_a_key_resembling_nothing_is_refused_and_the_valid_keys_named(self):
        """A guess is a string-distance match. When it lands on nothing, a reader
        given only the guess is left with nothing, so the accepted set is listed."""
        message = refusal(pipeline=["a", "b"])

        assert "unknown workflow key 'pipeline'" in message
        assert "did you mean" not in message
        assert (
            "valid workflow keys are actions, defaults, description, name, storage, tool_path, version"
            in message
        )

    def test_the_retired_plan_key_is_refused(self):
        """Carried by four fixtures and read by nothing. Removing them is part of
        this change, so a file that still writes it must not load quietly."""
        assert "unknown workflow key 'plan'" in refusal(plan=[{"step": 1}])

    def test_every_stray_key_is_named_not_just_the_first(self):
        """Fixing one key at a time, a file at a time, is the cost of naming one."""
        message = refusal(defaluts={}, pipeline=[])

        assert "unknown workflow key 'defaluts'" in message
        assert "unknown workflow key 'pipeline'" in message

    def test_a_workflow_of_only_declared_keys_still_loads(self):
        """The guard against over-refusal: every key the schema declares, at once."""
        workflow = WorkflowConfig.model_validate(
            {
                **VALID,
                "version": "0.1.0",
                "defaults": {"model_vendor": "openai"},
                "tool_path": "tools",
            }
        )

        assert workflow.defaults is not None
        assert workflow.defaults.model_vendor == "openai"
        assert [a.name for a in workflow.actions] == ["a"]


class TestToolPathAtTheWorkflowTopLevel:
    """`manager.py` reads this key off the workflow dict, so the model has to
    declare it — a surface that forbids extras cannot refuse a key the framework
    itself goes looking for."""

    def test_it_is_a_declared_field(self):
        assert WorkflowConfig.model_validate({**VALID, "tool_path": "my_tools"}).tool_path == (
            "my_tools"
        )

    def test_it_accepts_the_list_form_the_resolver_normalises(self):
        assert WorkflowConfig.model_validate(
            {**VALID, "tool_path": ["tools", "extra"]}
        ).tool_path == ["tools", "extra"]

    def test_it_defaults_to_none_when_the_workflow_does_not_set_it(self):
        assert WorkflowConfig.model_validate(VALID).tool_path is None

    @pytest.mark.parametrize(
        ("workflow_value", "default_value", "expected"),
        [
            ("wf_tools", "def_tools", ["wf_tools"]),
            (None, "def_tools", ["def_tools"]),
            (None, None, ["proj_tools"]),
        ],
        ids=["workflow wins", "default wins", "project config is the fallback"],
    )
    def test_the_resolution_order_survives(self, tmp_path, workflow_value, default_value, expected):
        """workflow > default > project config. Asserted here because declaring the
        key on the model must not change where the value is read from."""
        (tmp_path / "agent_actions.yml").write_text("tool_path: proj_tools\n")
        workflow = {**VALID}
        if workflow_value:
            workflow["tool_path"] = workflow_value
        wf_file = tmp_path / "wf.yml"
        wf_file.write_text(yaml.safe_dump(workflow))
        default_file = tmp_path / "default.yml"
        default_file.write_text(
            yaml.safe_dump({"tool_path": default_value} if default_value else {})
        )

        manager = ConfigManager(str(wf_file), str(default_file), project_root=tmp_path)
        manager.load_configs()

        assert manager.tool_path == expected
