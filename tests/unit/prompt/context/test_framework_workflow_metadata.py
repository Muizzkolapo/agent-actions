"""Regression: the runtime `workflow.*` namespace matches what inspect and
the static analyzer promise.

Before VIOL-0008 the inspect view showed `workflow: name, run_id` but no
runtime path populated `workflow_metadata` with those keys, so
`{{ workflow.name }}` raised at render time. This test locks in the
end-to-end contract:

1. `FRAMEWORK_FIELDS["workflow"]` is the source of truth.
2. `build_workflow_metadata(...)` emits exactly those keys.
3. Passing the resulting dict through `build_field_context_with_history` →
   `apply_context_scope` → Jinja renders `{{ workflow.name }}` and
   `{{ workflow.run_id }}` cleanly.
"""

import pytest

from agent_actions.errors import TemplateVariableError
from agent_actions.prompt.context.scope_application import (
    FRAMEWORK_FIELDS,
    apply_context_scope,
    build_workflow_metadata,
)
from agent_actions.prompt.context.scope_builder import build_field_context_with_history
from agent_actions.prompt.service import PromptPreparationService


def _render(template: str, prompt_context: dict) -> str:
    return PromptPreparationService._render_prompt_template(
        template, prompt_context, agent_name="test"
    )


class TestWorkflowMetadataSchema:
    def test_framework_fields_declares_workflow_schema(self):
        assert FRAMEWORK_FIELDS["workflow"] == ("name", "run_id")

    def test_build_workflow_metadata_matches_schema(self):
        meta = build_workflow_metadata(name="wf_A", run_id="run_123")
        assert set(meta.keys()) == set(FRAMEWORK_FIELDS["workflow"])
        assert meta["name"] == "wf_A"
        assert meta["run_id"] == "run_123"

    def test_build_workflow_metadata_run_id_none_emits_empty_string(self):
        # `run_id=None` at service-init time (before cli/run.py sets it).
        # Emitting the key with "" keeps `{{ workflow.run_id }}` valid rather
        # than raising TemplateVariableError.
        meta = build_workflow_metadata(name="wf_A")
        assert meta == {"name": "wf_A", "run_id": ""}


class TestWorkflowNamespaceRuntimeResolution:
    """`{{ workflow.name }}` / `{{ workflow.run_id }}` resolve when the
    runtime injects a workflow_metadata dict — the end-to-end contract."""

    def _context_for(self, workflow_metadata: dict) -> dict:
        return build_field_context_with_history(
            agent_name="my_action",
            agent_config={},
            workflow_metadata=workflow_metadata,
        )

    def _scope_and_render(self, template: str, field_context: dict) -> str:
        prompt_context, _, _ = apply_context_scope(field_context, {}, action_name="my_action")
        return _render(template, prompt_context)

    def test_workflow_name_resolves(self):
        field_context = self._context_for(
            build_workflow_metadata(name="my_workflow", run_id="run_42")
        )
        assert (
            self._scope_and_render("Name: {{ workflow.name }}", field_context)
            == "Name: my_workflow"
        )

    def test_workflow_run_id_resolves(self):
        field_context = self._context_for(
            build_workflow_metadata(name="my_workflow", run_id="run_42")
        )
        assert self._scope_and_render("Run: {{ workflow.run_id }}", field_context) == "Run: run_42"

    def test_workflow_both_fields_resolve_in_one_template(self):
        field_context = self._context_for(
            build_workflow_metadata(name="my_workflow", run_id="run_42")
        )
        assert (
            self._scope_and_render("{{ workflow.name }} / {{ workflow.run_id }}", field_context)
            == "my_workflow / run_42"
        )

    def test_workflow_run_id_pre_run_renders_empty(self):
        # Service init populates name-only; cli/run.py fills in run_id later.
        # Between those two events (rare, but preview/batch-prep paths), the
        # template should render "" rather than crash.
        field_context = self._context_for(build_workflow_metadata(name="my_workflow"))
        assert self._scope_and_render("Run: {{ workflow.run_id }}", field_context) == "Run: "

    def test_workflow_unknown_field_still_raises(self):
        # Fields NOT in FRAMEWORK_FIELDS["workflow"] must still fail loudly —
        # otherwise typos like `{{ workflow.session_id }}` become silent Nones.
        field_context = self._context_for(
            build_workflow_metadata(name="my_workflow", run_id="run_42")
        )
        with pytest.raises(TemplateVariableError):
            self._scope_and_render("Session: {{ workflow.session_id }}", field_context)
