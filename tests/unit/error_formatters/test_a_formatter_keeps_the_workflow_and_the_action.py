"""A formatter that builds its own context keeps the workflow as the agent and the action as the
action."""

from pathlib import Path

import pytest

from agent_actions.config.manager import ConfigManager
from agent_actions.errors import UDFLoadError
from agent_actions.input.loaders.udf import discover_udfs
from agent_actions.logging.errors import format_user_error
from agent_actions.output.response.config_schema import AgentConfig
from agent_actions.output.response.expander_validation import validate_required_fields
from agent_actions.prompt.renderer import ConfigRenderingService
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.services.preflight_service import PreflightService
from agent_actions.utils.udf_management.registry import clear_registry, get_udf_metadata
from agent_actions.workflow.config_pipeline import _run_config_stage

WORKFLOW = "my_workflow"
CLI_CONTEXT = {"command": "run", "agent": WORKFLOW}


def _raised(fn) -> Exception:
    with pytest.raises(Exception) as exc_info:
        fn()
    return exc_info.value


def _template_error(prompt: str) -> Exception:
    return _raised(
        lambda: PromptPreparationService.prepare_prompt_with_field_context(
            {"prompt": prompt, "context_scope": {"observe": ["source.*"]}},
            "write_question",
            {},
            field_context={"source": {"text": "hi"}},
        )
    )


def _preflight_function_error() -> Exception:
    clear_registry()
    configs = {"fetch_rows": {"kind": "tool", "model_name": "no_such_probe_fn"}}
    return _raised(lambda: PreflightService(WORKFLOW, configs, None, "w.yml").validate())


def _manager_vendor_error() -> Exception:
    manager = ConfigManager(constructor_path="unused.yml", default_path="")
    manager.agent_configs = {
        "classify": AgentConfig.model_validate(
            {"agent_type": "classify", "name": "classify", "kind": "llm"}
        )
    }
    return _raised(manager.get_all_agent_configs_as_dicts)


ACTION_ERRORS = {
    "template_missing_variable": ("write_question", lambda: _template_error("{{ source.nope }}")),
    "template_syntax": ("write_question", lambda: _template_error("{{ source.text ")),
    "function_not_found": ("fetch_rows", _preflight_function_error),
    "required_fields": (
        "summarize_doc",
        lambda: _raised(lambda: validate_required_fields({}, "summarize_doc")),
    ),
    "manager_model_vendor": ("classify", _manager_vendor_error),
}


def _lines(error: Exception, context: dict | None = None) -> list[str]:
    return format_user_error(error, context).splitlines()


def _problem(lines: list[str]) -> str:
    return next(line for line in lines if line.startswith("  Problem:"))


@pytest.mark.parametrize("case", ACTION_ERRORS)
def test_the_action_prints_as_the_action_and_never_as_the_agent(case):
    action, raise_it = ACTION_ERRORS[case]
    lines = _lines(raise_it())

    assert f"  Action: {action}" in lines
    assert f"  Agent: {action}" not in lines
    assert not any(f"agent '{action}'" in line for line in lines)
    assert action not in lines[0]
    assert action not in _problem(lines)


@pytest.mark.parametrize("case", ACTION_ERRORS)
def test_the_cli_workflow_prints_as_the_agent_and_the_action_stays(case):
    action, raise_it = ACTION_ERRORS[case]
    lines = _lines(raise_it(), CLI_CONTEXT)

    assert f"  Agent: {WORKFLOW}" in lines
    assert f"  Action: {action}" in lines
    assert action not in lines[0]


def test_the_template_title_names_the_workflow_only_when_one_is_known():
    error = _template_error("{{ source.nope }}")

    assert _lines(error)[0] == "Template Error: Template rendering failed"
    assert (
        _lines(error, CLI_CONTEXT)[0]
        == f"Template Error: Template rendering failed in agent '{WORKFLOW}'"
    )


def test_a_preflight_refusal_names_its_own_workflow_without_cli_context():
    lines = _lines(_preflight_function_error())

    assert f"  Agent: {WORKFLOW}" in lines


def test_a_lookup_outside_any_action_prints_no_action_line():
    clear_registry()
    error = _raised(lambda: get_udf_metadata("no_such_probe_fn"))
    lines = _lines(error, CLI_CONTEXT)

    assert lines[0] == "Configuration Error: Function 'no_such_probe_fn' not found"
    assert f"  Agent: {WORKFLOW}" in lines
    assert not any(line.startswith("  Action:") for line in lines)


def _yaml_error(tmp_path: Path) -> Exception:
    config = tmp_path / "w.yml"
    config.write_text("name: w\nactions:\n  - name: a\n    prompt: [unclosed\n")
    return _raised(
        lambda: ConfigRenderingService().render_and_load_config(
            "w", config, tmp_path, tmp_path / "out", project_root=tmp_path
        )
    )


def _udf_discovery_error(tmp_path: Path) -> Exception:
    error = _raised(lambda: discover_udfs(tmp_path / "no_tools_here"))
    assert isinstance(error, UDFLoadError)
    return error


def _udf_import_error(tmp_path: Path) -> Exception:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "broken_probe.py").write_text(
        "from agent_actions import udf_tool\nimport no_such_module_probe\n\n"
        "@udf_tool\ndef probe(data):\n    return data\n"
    )
    clear_registry()
    error = _raised(lambda: discover_udfs(tools))
    assert isinstance(error, UDFLoadError)
    return error


SIBLINGS = {
    "yaml_syntax": _yaml_error,
    "udf_discovery": _udf_discovery_error,
    "udf_import": _udf_import_error,
}


@pytest.mark.parametrize("case", SIBLINGS)
def test_a_formatter_that_builds_its_context_keeps_the_cli_workflow(tmp_path, case):
    error = SIBLINGS[case](tmp_path)

    assert not any(line.startswith("  Agent:") for line in _lines(error))
    assert f"  Agent: {WORKFLOW}" in _lines(error, CLI_CONTEXT)


def test_an_error_that_names_its_own_workflow_keeps_it_over_the_cli(tmp_path):
    missing = tmp_path / "no_tools_here"
    error = _raised(lambda: _run_config_stage(discover_udfs, "discover", "own_workflow", missing))
    lines = _lines(error, CLI_CONTEXT)

    assert "  Agent: own_workflow" in lines
    assert f"  Agent: {WORKFLOW}" not in lines
