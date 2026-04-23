"""Tests for guard completions and diagnostics — dotted namespace paths only."""

from pathlib import Path

from lsprotocol import types as lsp

from agent_actions.tooling.lsp.completions import build_guard_completions
from agent_actions.tooling.lsp.diagnostics import (
    collect_available_guard_variables,
    collect_diagnostics,
)
from agent_actions.tooling.lsp.models import (
    ActionMetadata,
    Location,
    ProjectIndex,
    SchemaDefinition,
)


def _make_index(
    tmp_path: Path,
    actions: dict[str, ActionMetadata],
    schemas: dict[str, SchemaDefinition] | None = None,
) -> tuple[ProjectIndex, Path]:
    """Build a ProjectIndex with the given actions and schemas, return (index, file_path)."""
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    wf_file = root / "agent_config" / "workflow.yml"
    wf_file.parent.mkdir(parents=True, exist_ok=True)
    wf_file.touch()

    idx = ProjectIndex(root=root)
    idx.file_actions[wf_file] = actions
    if schemas:
        idx.schemas.update(schemas)
    return idx, wf_file


# ---------------------------------------------------------------------------
# collect_available_guard_variables
# ---------------------------------------------------------------------------


class TestCollectAvailableGuardVariables:
    """Only dotted namespace paths should appear — never bare field names."""

    def test_observe_dotted_path_included(self, tmp_path: Path):
        """Dotted observe refs like 'validate.pass' are in the result."""
        action = ActionMetadata(
            name="score",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["validate.pass", "validate.score"],
        )
        idx, wf = _make_index(tmp_path, {"score": action})
        result = collect_available_guard_variables(wf, idx)

        assert "validate.pass" in result
        assert "validate.score" in result

    def test_observe_bare_field_excluded(self, tmp_path: Path):
        """Bare field names extracted from dotted observe refs must NOT appear."""
        action = ActionMetadata(
            name="score",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["validate.pass", "validate.score"],
        )
        idx, wf = _make_index(tmp_path, {"score": action})
        result = collect_available_guard_variables(wf, idx)

        assert "pass" not in result
        assert "score" not in result

    def test_passthrough_dotted_path_included(self, tmp_path: Path):
        """Dotted passthrough refs are in the result."""
        action = ActionMetadata(
            name="finalize",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_passthrough=["extract.name", "extract.email"],
        )
        idx, wf = _make_index(tmp_path, {"finalize": action})
        result = collect_available_guard_variables(wf, idx)

        assert "extract.name" in result
        assert "extract.email" in result

    def test_passthrough_bare_field_excluded(self, tmp_path: Path):
        """Bare field names extracted from dotted passthrough refs must NOT appear."""
        action = ActionMetadata(
            name="finalize",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_passthrough=["extract.name", "extract.email"],
        )
        idx, wf = _make_index(tmp_path, {"finalize": action})
        result = collect_available_guard_variables(wf, idx)

        assert "name" not in result
        assert "email" not in result

    def test_schema_fields_use_dotted_path(self, tmp_path: Path):
        """Schema fields are added as action_name.field, not bare field."""
        schema = SchemaDefinition(
            name="validate_schema",
            location=Location(file_path=tmp_path / "s.yml", line=0),
            fields=["pass", "reason"],
        )
        action = ActionMetadata(
            name="validate",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            schema_ref="validate_schema",
        )
        idx, wf = _make_index(tmp_path, {"validate": action}, {"validate_schema": schema})
        result = collect_available_guard_variables(wf, idx)

        assert "validate.pass" in result
        assert "validate.reason" in result
        assert "pass" not in result
        assert "reason" not in result

    def test_multiple_actions_all_dotted(self, tmp_path: Path):
        """Variables from multiple actions are all dotted, none bare."""
        action_a = ActionMetadata(
            name="a",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["x.field1"],
            context_passthrough=["y.field2"],
        )
        action_b = ActionMetadata(
            name="b",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            context_observe=["z.field3"],
        )
        idx, wf = _make_index(tmp_path, {"a": action_a, "b": action_b})
        result = collect_available_guard_variables(wf, idx)

        assert result == {"x.field1", "y.field2", "z.field3"}

    def test_empty_actions_returns_empty_set(self, tmp_path: Path):
        """No actions means no guard variables."""
        idx, wf = _make_index(tmp_path, {})
        result = collect_available_guard_variables(wf, idx)

        assert result == set()


# ---------------------------------------------------------------------------
# build_guard_completions
# ---------------------------------------------------------------------------


class TestBuildGuardCompletions:
    """Completions must only suggest dotted namespace paths."""

    def test_completions_only_dotted_paths(self, tmp_path: Path):
        """Completion labels contain only dotted paths, not bare fields."""
        action = ActionMetadata(
            name="validate",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["score_quality.score", "score_quality.reason"],
        )
        idx, wf = _make_index(tmp_path, {"validate": action})
        items = build_guard_completions(wf, idx)
        labels = {item.label for item in items}

        assert "score_quality.score" in labels
        assert "score_quality.reason" in labels
        assert "score" not in labels
        assert "reason" not in labels

    def test_completion_item_kind_is_variable(self, tmp_path: Path):
        """Guard completions have Variable kind."""
        action = ActionMetadata(
            name="a",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["x.field"],
        )
        idx, wf = _make_index(tmp_path, {"a": action})
        items = build_guard_completions(wf, idx)

        assert all(item.kind == lsp.CompletionItemKind.Variable for item in items)

    def test_completions_sorted(self, tmp_path: Path):
        """Completion items are sorted alphabetically."""
        action = ActionMetadata(
            name="a",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["z.field", "a.field", "m.field"],
        )
        idx, wf = _make_index(tmp_path, {"a": action})
        items = build_guard_completions(wf, idx)
        labels = [item.label for item in items]

        assert labels == sorted(labels)


# ---------------------------------------------------------------------------
# Diagnostics — bare field suggestion
# ---------------------------------------------------------------------------


class TestGuardDiagnostics:
    """Guard diagnostics should flag bare fields and suggest dotted paths."""

    def test_bare_field_flagged_with_suggestion(self, tmp_path: Path):
        """Using a bare field triggers a diagnostic that suggests the dotted path."""
        action = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["validate.pass"],
            guard_condition="pass == true",
            guard_line=5,
            guard_variables=["pass"],
        )
        idx, wf = _make_index(tmp_path, {"judge": action})
        diagnostics = collect_diagnostics(wf, idx)

        assert len(diagnostics) == 1
        diag = diagnostics[0]
        assert diag.severity == lsp.DiagnosticSeverity.Warning
        assert "`pass`" in diag.message
        assert "Did you mean `validate.pass`?" in diag.message

    def test_dotted_field_no_diagnostic(self, tmp_path: Path):
        """Using a correct dotted path triggers no diagnostic."""
        action = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["validate.pass"],
            guard_condition="validate.pass == true",
            guard_line=5,
            guard_variables=["validate.pass"],
        )
        idx, wf = _make_index(tmp_path, {"judge": action})
        diagnostics = collect_diagnostics(wf, idx)

        assert len(diagnostics) == 0

    def test_bare_field_multiple_matches(self, tmp_path: Path):
        """When a bare field matches multiple namespaces, all are suggested."""
        action = ActionMetadata(
            name="final",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["validate.score", "quality.score"],
            guard_condition="score > 0.5",
            guard_line=5,
            guard_variables=["score"],
        )
        idx, wf = _make_index(tmp_path, {"final": action})
        diagnostics = collect_diagnostics(wf, idx)

        assert len(diagnostics) == 1
        diag = diagnostics[0]
        assert "`quality.score`" in diag.message
        assert "`validate.score`" in diag.message

    def test_unknown_field_no_suggestion(self, tmp_path: Path):
        """A completely unknown field gets the standard message without suggestion."""
        action = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["validate.pass"],
            guard_condition="nonexistent == true",
            guard_line=5,
            guard_variables=["nonexistent"],
        )
        idx, wf = _make_index(tmp_path, {"judge": action})
        diagnostics = collect_diagnostics(wf, idx)

        assert len(diagnostics) == 1
        diag = diagnostics[0]
        assert "`nonexistent`" in diag.message
        assert "Did you mean" not in diag.message

    def test_dotted_unknown_no_suggestion(self, tmp_path: Path):
        """A dotted variable not in available gets a plain warning, no suggestion."""
        action = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["validate.pass"],
            guard_condition="wrong_action.field == true",
            guard_line=5,
            guard_variables=["wrong_action.field"],
        )
        idx, wf = _make_index(tmp_path, {"judge": action})
        diagnostics = collect_diagnostics(wf, idx)

        assert len(diagnostics) == 1
        diag = diagnostics[0]
        assert "`wrong_action.field`" in diag.message
        assert "Did you mean" not in diag.message

    def test_guard_scoped_to_own_action(self, tmp_path: Path):
        """Action A's guard cannot reference action B's observe entries."""
        action_a = ActionMetadata(
            name="action_a",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            context_observe=["upstream.field_a"],
            guard_condition="upstream.field_b == true",
            guard_line=3,
            guard_variables=["upstream.field_b"],
        )
        action_b = ActionMetadata(
            name="action_b",
            location=Location(file_path=tmp_path / "w.yml", line=10),
            context_observe=["upstream.field_b"],
        )
        idx, wf = _make_index(tmp_path, {"action_a": action_a, "action_b": action_b})
        diagnostics = collect_diagnostics(wf, idx)

        # action_a's guard references upstream.field_b, but only action_b observes it
        assert len(diagnostics) == 1
        diag = diagnostics[0]
        assert "`upstream.field_b`" in diag.message
