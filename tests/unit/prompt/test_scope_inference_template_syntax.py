"""Regression: scope_inference catches TemplateSyntaxError explicitly.

After extract_action_names_from_template was changed to raise TemplateSyntaxError
on bad templates (instead of returning an empty set), the broad `except Exception`
in scope_inference would mis-categorize the syntax error as "Prompt retrieval
failed." The fix narrows the handler: prompt retrieval and template parsing get
distinct except blocks with distinct log messages.
"""

import logging

import pytest

from agent_actions.prompt.context.scope_inference import infer_dependencies


@pytest.fixture(autouse=True)
def _enable_propagate():
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = original


_SCOPE_INFERENCE_LOGGER = "agent_actions.prompt.context.scope_inference"


class TestScopeInferenceTemplateSyntaxError:
    """Template syntax errors during scope inference log a specific warning."""

    def test_template_syntax_error_logs_scope_warning_not_prompt_warning(self, caplog):
        """Bad template surfaces a 'Template syntax error during scope inference' warning."""
        action_config = {
            "name": "downstream",
            "prompt": "{% if broken %} {{ upstream.field }}",
            "context_scope": {},
        }
        workflow_actions = ["upstream", "downstream"]

        with caplog.at_level(logging.WARNING, logger=_SCOPE_INFERENCE_LOGGER):
            input_sources, context_sources = infer_dependencies(
                action_config, workflow_actions, action_name="downstream", validate=False
            )
            result = set(input_sources) | set(context_sources)

        assert isinstance(result, set)
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        scope_warnings = [r for r in warning_records if "scope inference" in r.message.lower()]
        assert len(scope_warnings) >= 1, (
            "expected a scope-inference warning for the bad template; "
            f"got messages: {[r.message for r in warning_records]}"
        )
        assert "downstream" in scope_warnings[0].message
        prompt_warnings = [r for r in warning_records if "prompt retrieval" in r.message.lower()]
        assert not prompt_warnings, (
            "syntax error must not be mis-categorized as a prompt retrieval failure"
        )

    def test_valid_template_no_warning(self, caplog):
        """Well-formed templates produce no syntax warning."""
        action_config = {
            "name": "downstream",
            "prompt": "Summary: {{ upstream.summary }}",
            "context_scope": {},
        }
        workflow_actions = ["upstream", "downstream"]

        with caplog.at_level(logging.WARNING, logger=_SCOPE_INFERENCE_LOGGER):
            input_sources, context_sources = infer_dependencies(
                action_config, workflow_actions, action_name="downstream", validate=False
            )
            result = set(input_sources) | set(context_sources)

        assert "upstream" in result
        syntax_warnings = [r for r in caplog.records if "syntax error" in r.message.lower()]
        assert syntax_warnings == []
