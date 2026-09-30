"""Tests for guard completions and diagnostics — dotted namespace paths only."""

from pathlib import Path

from lsprotocol import types as lsp

from agent_actions.tooling.lsp.completions import build_guard_completions
from agent_actions.tooling.lsp.diagnostics import (
    _get_action_schema_fields,
    collect_available_guard_variables,
    collect_diagnostics,
)
from agent_actions.tooling.lsp.models import (
    ActionMetadata,
    Location,
    ProjectIndex,
    SchemaDefinition,
)
from agent_actions.utils.constants import RUNTIME_BUS_NAMESPACES


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
    """A guard clause is reported only where the file can prove it resolves nowhere.

    A dotted reference is never reported: the record carries every namespace the run
    accumulated, and the framework attaches keys a schema may not declare (`expect`).
    Reporting them produced 19 warnings on the sample project, all on clauses the runtime
    answers.
    """

    def test_a_bare_name_no_upstream_produces_is_flagged(self, tmp_path: Path):
        checker = ActionMetadata(
            name="checker",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            output_field="verdict",
        )
        judge = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["checker"],
            guard_condition="passed == true",
            guard_line=7,
            guard_variables=["passed"],
        )
        idx, wf = _make_index(tmp_path, {"checker": checker, "judge": judge})
        diagnostics = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert len(diagnostics) == 1
        assert "`passed`" in diagnostics[0].message
        assert diagnostics[0].severity == lsp.DiagnosticSeverity.Warning

    def test_a_flagged_bare_name_is_offered_its_dotted_spelling(self, tmp_path: Path):
        """The warning is only actionable if it names the spelling that would resolve."""
        schema = SchemaDefinition(
            name="validate_schema",
            location=Location(file_path=tmp_path / "s.yml", line=0),
            fields=["score"],
        )
        validate = ActionMetadata(
            name="validate",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            schema_ref="validate_schema",
        )
        judge = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["validate"],
            guard_condition="score > 1",
            guard_line=7,
            guard_variables=["score"],
        )
        idx, wf = _make_index(
            tmp_path, {"validate": validate, "judge": judge}, {"validate_schema": schema}
        )
        diagnostics = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert len(diagnostics) == 1
        assert "Did you mean `validate.score`?" in diagnostics[0].message

    def test_two_upstreams_declaring_the_field_are_both_offered(self, tmp_path: Path):
        """Which one was meant is not decidable here, so the warning names both."""
        schemas = {
            f"{n}_schema": SchemaDefinition(
                name=f"{n}_schema",
                location=Location(file_path=tmp_path / "s.yml", line=0),
                fields=["score"],
            )
            for n in ("validate", "quality")
        }
        actions = {
            n: ActionMetadata(
                name=n,
                location=Location(file_path=tmp_path / "w.yml", line=0),
                schema_ref=f"{n}_schema",
            )
            for n in ("validate", "quality")
        }
        actions["judge"] = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["validate", "quality"],
            guard_condition="score > 1",
            guard_line=7,
            guard_variables=["score"],
        )
        idx, wf = _make_index(tmp_path, actions, schemas)
        diagnostics = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert len(diagnostics) == 1
        assert "`quality.score`" in diagnostics[0].message
        assert "`validate.score`" in diagnostics[0].message

    def test_a_bare_name_no_upstream_schema_declares_gets_no_suggestion(self, tmp_path: Path):
        """A suggestion is only offered where one would actually resolve."""
        schema = SchemaDefinition(
            name="validate_schema",
            location=Location(file_path=tmp_path / "s.yml", line=0),
            fields=["score"],
        )
        validate = ActionMetadata(
            name="validate",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            schema_ref="validate_schema",
        )
        judge = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["validate"],
            guard_condition="nonexistent > 1",
            guard_line=7,
            guard_variables=["nonexistent"],
        )
        idx, wf = _make_index(
            tmp_path, {"validate": validate, "judge": judge}, {"validate_schema": schema}
        )
        diagnostics = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert len(diagnostics) == 1
        assert "Did you mean" not in diagnostics[0].message

    def test_a_bare_name_matching_an_output_field_is_not_flagged(self, tmp_path: Path):
        """guard_context.py promotes `output_field` to the top level for exactly this."""
        checker = ActionMetadata(
            name="checker",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            output_field="passed",
        )
        judge = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["checker"],
            guard_condition="passed == true",
            guard_line=7,
            guard_variables=["passed"],
        )
        idx, wf = _make_index(tmp_path, {"checker": checker, "judge": judge})

        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_version_param_is_not_flagged(self, tmp_path: Path):
        """The declared loop param is promoted, so a bare reference to it resolves.

        `dependencies` is set deliberately: with none, the first-stage short-circuit returns
        before `versions_params` is consulted and the test passes for the wrong reason.
        """
        seed = ActionMetadata(name="seed", location=Location(file_path=tmp_path / "w.yml", line=0))
        action = ActionMetadata(
            name="voter",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["seed"],
            versions_params=["voter_id"],
            guard_condition="voter_id == 1",
            guard_line=7,
            guard_variables=["voter_id"],
        )
        idx, wf = _make_index(tmp_path, {"seed": seed, "voter": action})

        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_promoted_version_keys_are_not_flagged(self, tmp_path: Path):
        """Measured: build_guard_context promotes i, idx, base_name and param_name."""
        for name in ("i", "idx", "base_name", "param_name"):
            action = ActionMetadata(
                name="voter_1",
                location=Location(file_path=tmp_path / "w.yml", line=0),
                dependencies=["seed"],
                guard_condition=f"{name} == 1",
                guard_line=3,
                guard_variables=[name],
            )
            seed = ActionMetadata(
                name="seed", location=Location(file_path=tmp_path / "w.yml", line=0)
            )
            idx, wf = _make_index(tmp_path, {"seed": seed, "voter_1": action})

            found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
            assert found == [], (
                f"{name} is promoted to the top level; flagging it is a false positive"
            )

    def test_a_reserved_version_key_is_still_flagged(self, tmp_path: Path):
        """`first` and `last` stay under `version`, so a bare one resolves nowhere.

        `length` is deliberately absent: it is also a guard function, so the extractor never
        yields it as a variable and asserting it here would pin an unreachable path.
        """
        for name in ("first", "last"):
            action = ActionMetadata(
                name="voter_1",
                location=Location(file_path=tmp_path / "w.yml", line=0),
                dependencies=["seed"],
                guard_condition=f"{name} == 1",
                guard_line=3,
                guard_variables=[name],
            )
            seed = ActionMetadata(
                name="seed", location=Location(file_path=tmp_path / "w.yml", line=0)
            )
            idx, wf = _make_index(tmp_path, {"seed": seed, "voter_1": action})

            found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
            assert len(found) == 1, f"bare {name} resolves nowhere and should be reported"

    def test_a_runtime_bus_namespace_is_never_flagged(self, tmp_path: Path):
        """source/version/workflow/seed are supplied by the runtime, not by an action."""
        for namespace in sorted(RUNTIME_BUS_NAMESPACES):
            seed = ActionMetadata(
                name="seed", location=Location(file_path=tmp_path / "w.yml", line=0)
            )
            action = ActionMetadata(
                name="act",
                location=Location(file_path=tmp_path / "w.yml", line=5),
                dependencies=["seed"],
                guard_condition=f"{namespace}.anything == 1",
                guard_line=7,
                guard_variables=[f"{namespace}.anything"],
            )
            idx, wf = _make_index(tmp_path, {"seed": seed, "act": action})

            found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
            assert found == [], f"`{namespace}` is a runtime namespace, not a missing action"

    def test_a_bare_runtime_namespace_is_not_flagged(self, tmp_path: Path):
        """`source IS NOT NULL` names the namespace itself, which is promoted to top level."""
        for namespace in sorted(RUNTIME_BUS_NAMESPACES):
            seed = ActionMetadata(
                name="seed", location=Location(file_path=tmp_path / "w.yml", line=0)
            )
            action = ActionMetadata(
                name="act",
                location=Location(file_path=tmp_path / "w.yml", line=5),
                dependencies=["seed"],
                guard_condition=f"{namespace} IS NOT NULL",
                guard_line=7,
                guard_variables=[namespace],
            )
            idx, wf = _make_index(tmp_path, {"seed": seed, "act": action})

            found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
            assert found == [], f"bare `{namespace}` resolves at runtime"

    def test_a_bare_upstream_namespace_is_not_flagged(self, tmp_path: Path):
        """Every dependency namespace is promoted to top level, so `assess` resolves bare."""
        assess = ActionMetadata(
            name="assess", location=Location(file_path=tmp_path / "w.yml", line=0)
        )
        act = ActionMetadata(
            name="act",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["assess"],
            guard_condition="assess IS NOT NULL",
            guard_line=7,
            guard_variables=["assess"],
        )
        idx, wf = _make_index(tmp_path, {"assess": assess, "act": act})

        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_dotted_record_field_is_not_flagged(self, tmp_path: Path):
        """guards.md documents `metadata.reason`; batch-recovery documents `_recovery.*`."""
        for variable in ("metadata.reason", "lineage.root_target_id", "_recovery.retry.ok"):
            up = ActionMetadata(name="up", location=Location(file_path=tmp_path / "w.yml", line=0))
            act = ActionMetadata(
                name="act",
                location=Location(file_path=tmp_path / "w.yml", line=5),
                dependencies=["up"],
                guard_condition=f"{variable} IS NOT NULL",
                guard_line=7,
                guard_variables=[variable],
            )
            idx, wf = _make_index(tmp_path, {"up": up, "act": act})

            found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
            assert found == [], f"`{variable}` is a record key the evaluator promotes"

    def test_bare_content_is_still_flagged(self, tmp_path: Path):
        """`content` is the one record key the evaluator strips -- it spreads its namespaces.

        Measured: `content == 'x'` gives matched=False, so exempting it would hide exactly
        the silent filter this check exists for.
        """
        up = ActionMetadata(name="up", location=Location(file_path=tmp_path / "w.yml", line=0))
        act = ActionMetadata(
            name="act",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["up"],
            guard_condition="content == 'x'",
            guard_line=7,
            guard_variables=["content"],
        )
        idx, wf = _make_index(tmp_path, {"up": up, "act": act})

        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
        assert len(found) == 1, "a clause on `content` resolves against nothing"

    def test_a_dotted_output_field_is_not_flagged(self, tmp_path: Path):
        """The promoted value may be an object, so `payload.score` resolves as bare does."""
        dep = ActionMetadata(
            name="assess",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            output_field="payload",
        )
        act = ActionMetadata(
            name="act",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["assess"],
            guard_condition="payload.score > 1",
            guard_line=7,
            guard_variables=["payload.score"],
        )
        idx, wf = _make_index(tmp_path, {"assess": dep, "act": act})

        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_fan_in_on_version_variants_keeps_the_bare_check_on(self, tmp_path: Path):
        """A variant is never a key in file_actions; treating that miss as unknown upstream
        switched the whole bare-name check off for every fan-in action."""
        base = ActionMetadata(
            name="score",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            version_variants=["score_1", "score_2"],
            output_field="verdict",
        )
        tally = ActionMetadata(
            name="tally",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["score_1", "score_2"],
            guard_condition="nonexistent == true",
            guard_line=7,
            guard_variables=["nonexistent"],
        )
        idx, wf = _make_index(tmp_path, {"score": base, "tally": tally})

        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
        assert len(found) == 1, "the check must still run for an action fanning in on variants"

    def test_a_record_envelope_field_is_not_flagged(self, tmp_path: Path):
        """_prepare_eval_context keeps every record key but `content`, so these resolve."""
        for name in ("source_guid", "node_id", "target_id", "lineage"):
            up = ActionMetadata(name="up", location=Location(file_path=tmp_path / "w.yml", line=0))
            act = ActionMetadata(
                name="act",
                location=Location(file_path=tmp_path / "w.yml", line=5),
                dependencies=["up"],
                guard_condition=f"{name} IS NOT NULL",
                guard_line=7,
                guard_variables=[name],
            )
            idx, wf = _make_index(tmp_path, {"up": up, "act": act})

            found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
            assert found == [], f"`{name}` is a record field the runtime promotes"

    def test_an_unknown_upstream_leaves_the_bare_name_alone(self, tmp_path: Path):
        """A dependency this file cannot see makes the reference unprovable, not wrong."""
        act = ActionMetadata(
            name="act",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["defined_elsewhere"],
            guard_condition="whatever == true",
            guard_line=7,
            guard_variables=["whatever"],
        )
        idx, wf = _make_index(tmp_path, {"act": act})

        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_suggestion_can_come_from_an_observed_reference(self, tmp_path: Path):
        """The upstream declares no schema, so context_scope is the only source of a spelling."""
        upstream = ActionMetadata(
            name="upstream", location=Location(file_path=tmp_path / "w.yml", line=0)
        )
        judge = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["upstream"],
            context_observe=["upstream.score"],
            guard_condition="score > 1",
            guard_line=7,
            guard_variables=["score"],
        )
        idx, wf = _make_index(tmp_path, {"upstream": upstream, "judge": judge})
        diagnostics = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert len(diagnostics) == 1
        assert "Did you mean `upstream.score`?" in diagnostics[0].message

    def test_the_dotted_messages_name_the_real_remedy(self, tmp_path: Path):
        """The test is workflow-wide, so "add it as an upstream" is not the fix."""
        known = ActionMetadata(
            name="known", location=Location(file_path=tmp_path / "w.yml", line=0)
        )
        act = ActionMetadata(
            name="act",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["known", "absent"],
            guard_condition="absent.field == 1",
            guard_line=7,
            guard_variables=["absent.field"],
        )
        idx, wf = _make_index(tmp_path, {"known": known, "act": act})
        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert len(found) == 1
        assert "no action in this workflow produces `absent`" in found[0].message
        assert "does not produce" not in found[0].message, (
            "that wording implies the action exists and merely lacks the field"
        )

    def test_a_first_stage_action_is_not_flagged(self, tmp_path: Path):
        """Its content is the staging row, whose columns this file does not know."""
        action = ActionMetadata(
            name="triage",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            guard_condition="priority == 'high'",
            guard_line=2,
            guard_variables=["priority"],
        )
        idx, wf = _make_index(tmp_path, {"triage": action})

        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_dotted_field_is_never_judged_against_a_schema(self, tmp_path: Path):
        """`a.expect.overall_pass` resolves at runtime and no schema may declare `expect`.

        Which fields a namespace holds is not decidable here; whether the namespace exists is.
        """
        schema = SchemaDefinition(
            name="validate_schema",
            location=Location(file_path=tmp_path / "s.yml", line=0),
            fields=["score", "reason"],
        )
        validate = ActionMetadata(
            name="validate",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            schema_ref="validate_schema",
        )
        judge = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["validate"],
            guard_condition="validate.expect.overall_pass == true",
            guard_line=7,
            guard_variables=["validate.expect.overall_pass"],
        )
        idx, wf = _make_index(
            tmp_path, {"validate": validate, "judge": judge}, {"validate_schema": schema}
        )

        assert _get_action_schema_fields(idx, wf, "validate") == ["score", "reason"], (
            "without a populated schema this test passes whether or not the field check exists"
        )
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_namespace_no_action_in_the_workflow_writes_is_flagged(self, tmp_path: Path):
        """A misspelled action name. The runtime turns it into "condition not matched",
        which is a silent filter, so the editor is the only place it surfaces."""
        judge = ActionMetadata(
            name="judge",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            dependencies=["validate"],
            guard_condition="absent_action.field == true",
            guard_line=3,
            guard_variables=["absent_action.field"],
        )
        idx, wf = _make_index(tmp_path, {"judge": judge})
        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert len(found) == 1, found
        assert "`absent_action.field`" in found[0].message

    def test_a_prefix_of_an_action_name_is_still_flagged(self, tmp_path: Path):
        """`extract_raw` is not produced just because `extract_raw_qa_1` is -- that is a typo."""
        produced = ActionMetadata(
            name="extract_raw_qa",
            location=Location(file_path=tmp_path / "w.yml", line=0),
            version_variants=["extract_raw_qa_1", "extract_raw_qa_2"],
        )
        consumer = ActionMetadata(
            name="canonicalize",
            location=Location(file_path=tmp_path / "w.yml", line=5),
            dependencies=["extract_raw_qa"],
            guard_condition="extract_raw.ready == true",
            guard_line=7,
            guard_variables=["extract_raw.ready"],
        )
        idx, wf = _make_index(tmp_path, {"extract_raw_qa": produced, "canonicalize": consumer})

        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
        assert len(found) == 1, "a namespace no action writes must be reported"


class TestTheIndexerReadsRealWorkflowText:
    """Parse actual YAML, not a hand-built ActionMetadata.

    Every other test here constructs the metadata directly, so both halves of the indexer fix
    could be reverted with the whole suite still green and the sample project back from 91
    guards seen to 3. These go through `_index_workflow_file`, which is the only way that
    regression is visible.
    """

    @staticmethod
    def _index(tmp_path: Path, text: str):
        from ruamel.yaml import YAML

        from agent_actions.tooling.lsp.indexer import _index_workflow_file

        wf = tmp_path / "w.yml"
        wf.write_text(text)
        idx = ProjectIndex(root=tmp_path)
        idx.file_actions[wf] = {}
        idx.references_by_file[wf] = []
        idx.duplicate_actions_by_file[wf] = set()
        _index_workflow_file(idx, wf, YAML(typ="safe"))
        return idx, wf

    def test_an_inline_guard_yields_variables(self, tmp_path: Path):
        """87 of the sample project's 90 guards are written this way."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: act\n"
            "    guard: { condition: 'checker.passed == true', on_false: filter }\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.guard_condition, "the inline form was not recognised at all"
        assert action.guard_variables == ["checker.passed"], action.guard_variables

    def test_a_block_guard_still_yields_variables(self, tmp_path: Path):
        idx, wf = self._index(
            tmp_path,
            "actions:\n  - name: act\n    guard:\n      condition: 'checker.passed == true'\n",
        )

        assert idx.file_actions[wf]["act"].guard_variables == ["checker.passed"]

    def test_inline_context_scope_is_captured(self, tmp_path: Path):
        """The sample project writes 287 inline directive lists against 162 block ones."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: act\n"
            "    context_scope: { observe: [up.id, up.score], drop: [up.secret] }\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.context_observe == ["up.id", "up.score"], action.context_observe
        assert action.context_drop == ["up.secret"], action.context_drop

    def test_a_condition_holding_a_double_quoted_literal_is_read(self, tmp_path: Path):
        """`condition: 'a.b == "x"'` is the idiomatic spelling; naive quote-stripping breaks it.

        Stripping both quote characters off the outside leaves the inner literal unterminated,
        so the literal-blanking step stops matching and the literal's own words are extracted
        as variables -- a warning on a clause that resolves.
        """
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: extract\n"
            "  - name: act\n"
            "    dependencies: [extract]\n"
            "    guard: { condition: 'extract.status == \"approved\"', on_false: filter }\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.guard_variables == ["extract.status"], action.guard_variables
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_an_action_level_output_field_reaches_its_own_action(self, tmp_path: Path):
        """The per-action spelling, which is the mechanism the bare-name rule rests on."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: checker\n"
            "    output_field: verdict\n"
            "  - name: act\n"
            "    dependencies: [checker]\n"
            "    guard: { condition: 'verdict == true', on_false: filter }\n",
        )

        assert idx.file_actions[wf]["checker"].output_field == "verdict"
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_defaults_block_written_after_actions_still_reaches_them(self, tmp_path: Path):
        """Legal YAML; read from the parsed document so line order cannot decide it."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: checker\n"
            "  - name: act\n"
            "    dependencies: [checker]\n"
            "    guard: { condition: 'verdict == true', on_false: filter }\n"
            "defaults:\n"
            "  output_field: verdict\n",
        )

        assert idx.file_actions[wf]["checker"].output_field == "verdict"
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_guard_naming_a_versioned_base_is_flagged(self, tmp_path: Path):
        """A versions block expands before the run: the base namespace is never written.

        The runtime turns the unresolved clause into "condition not matched" and filters
        every record, which is precisely the silent loss this check exists to surface.
        """
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: voter\n"
            "    versions: { param: voter_id, range: [1, 3] }\n"
            "  - name: tally\n"
            "    dependencies: [voter]\n"
            "    guard: { condition: 'voter.score > 1', on_false: filter }\n",
        )
        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert len(found) == 1, "the base namespace resolves against nothing at runtime"

    def test_the_versioned_message_names_the_real_variants(self, tmp_path: Path):
        """A named range is stored as `base_fast`; advising `base_1` swaps one silent
        filter for another, plus an unresolved-reference Error."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: ask\n"
            "    versions: { param: model, range: [fast, slow, best] }\n"
            "  - name: pick\n"
            "    dependencies: [ask]\n"
            "    guard: { condition: 'ask.value > 1', on_false: filter }\n",
        )
        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert len(found) == 1
        assert "`ask_fast`" in found[0].message, found[0].message
        assert "`ask_1`" not in found[0].message

    def test_a_guard_naming_a_versioned_variant_is_not_flagged(self, tmp_path: Path):
        """`voter_1` is what the expander actually writes, so it resolves."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: voter\n"
            "    versions: { param: voter_id, range: [1, 3] }\n"
            "  - name: tally\n"
            "    dependencies: [voter]\n"
            "    guard: { condition: 'voter_1.score > 1', on_false: filter }\n",
        )
        action = idx.file_actions[wf]["voter"]

        assert action.version_variants == ["voter_1", "voter_2", "voter_3"], action.version_variants
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_documented_operator_is_not_read_as_a_field(self, tmp_path: Path):
        """CONTAINS/LIKE/BETWEEN/LENGTH are guard syntax, and the docs teach all four."""
        for clause, expected in (
            ('extract.tags CONTAINS "urgent"', ["extract.tags"]),
            ('extract.name LIKE "prod_%"', ["extract.name"]),
            ("extract.score BETWEEN 1 AND 5", ["extract.score"]),
            ("LENGTH(extract.items) > 2", ["extract.items"]),
        ):
            case_dir = tmp_path / clause[:12].replace(" ", "_").replace('"', "").replace("(", "")
            case_dir.mkdir(parents=True, exist_ok=True)
            idx, wf = self._index(
                case_dir,
                "actions:\n"
                "  - name: extract\n"
                "  - name: act\n"
                "    dependencies: [extract]\n"
                f"    guard: {{ condition: '{clause}', on_false: filter }}\n",
            )
            action = idx.file_actions[wf]["act"]

            assert action.guard_variables == expected, (clause, action.guard_variables)
            found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
            assert found == [], (clause, [d.message for d in found])

    def test_a_trailing_comment_is_not_read_as_fields(self, tmp_path: Path):
        """A shipped example writes exactly this; the comment's words were becoming variables."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: extract\n"
            "  - name: act\n"
            "    dependencies: [extract]\n"
            "    guard:\n"
            "      condition: 'extract.score >= 6'   # pre-check gate: skip low quality\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.guard_variables == ["extract.score"], action.guard_variables
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_an_inline_guard_with_a_trailing_comment_is_still_indexed(self, tmp_path: Path):
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: extract\n"
            "  - name: act\n"
            "    dependencies: [extract]\n"
            "    guard: { condition: 'extract.ok == true' }  # deliberate comment\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.guard_condition, "a comment after the closing brace hid the whole guard"
        assert action.guard_variables == ["extract.ok"], action.guard_variables

    def test_a_block_scalar_condition_is_read(self, tmp_path: Path):
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: extract\n"
            "  - name: act\n"
            "    dependencies: [extract]\n"
            "    guard:\n"
            "      condition: >-\n"
            "        extract.score > 1\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.guard_variables == ["extract.score"], action.guard_variables

    def test_a_quoted_output_field_is_captured(self, tmp_path: Path):
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: checker\n"
            '    output_field: "verdict"\n'
            "  - name: act\n"
            "    dependencies: [checker]\n"
            "    guard: { condition: 'verdict == true', on_false: filter }\n",
        )

        assert idx.file_actions[wf]["checker"].output_field == "verdict"
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_quoted_block_form_scope_item_keeps_the_check_on(self, tmp_path: Path):
        """Quotes left on a list item made the namespace `'up`, which switched the check off."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: up\n"
            "  - name: act\n"
            "    dependencies: [up]\n"
            "    context_scope:\n"
            "      observe:\n"
            "        - 'up.title'\n"
            "    guard: { condition: 'nonexistent == true', on_false: filter }\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.context_observe == ["up.title"], action.context_observe
        everything = collect_diagnostics(wf, idx)
        assert not [d for d in everything if "Cannot resolve" in d.message], (
            "quotes left on the reference make the namespace `'up` and raise an Error"
        )
        found = [d for d in everything if "Guard condition" in d.message]
        assert len(found) == 1, "the bare-name check must still run for this action"

    def test_a_udf_guard_reports_nothing(self, tmp_path: Path):
        """`udf:` names a python callable, not fields; the framework's checker skips it too."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: up\n"
            "  - name: act\n"
            "    dependencies: [up]\n"
            "    guard: { condition: 'udf:validators.should_extract', on_false: filter }\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.guard_variables == [], action.guard_variables
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_guard_string_shorthand_is_indexed(self, tmp_path: Path):
        """`guard:` is `str | dict`; six framework sites branch on the string form."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: up\n"
            "  - name: act\n"
            "    dependencies: [up]\n"
            "    guard: 'up.ok == true'\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.guard_condition == "up.ok == true"
        assert action.guard_line is not None, "the shorthand must still anchor the CodeLens"

    def test_the_guard_anchor_is_the_guard_line(self, tmp_path: Path):
        """guard_line gates the CodeLens and places the squiggle, exactly as versions_line."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: up\n"
            "  - name: act\n"
            "    dependencies: [up]\n"
            "    guard: { condition: 'nonexistent == true', on_false: filter }\n",
        )
        action = idx.file_actions[wf]["act"]
        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert action.guard_line == 4, action.guard_line
        assert len(found) == 1
        assert found[0].range.start.line == 4, "the warning must sit on the guard's own line"

    def test_a_block_guard_with_a_trailing_comment_still_anchors(self, tmp_path: Path):
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: up\n"
            "  - name: act\n"
            "    dependencies: [up]\n"
            "    guard:   # gate\n"
            "      condition: 'up.ok == true'\n",
        )

        assert idx.file_actions[wf]["act"].guard_line is not None

    def test_a_commented_name_line_still_names_the_action(self, tmp_path: Path):
        """The parsed lookup is keyed by name, so a comment swallowed into it loses everything."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: up\n"
            "  - name: act   # the one under test\n"
            "    dependencies: [up]\n"
            "    guard: { condition: 'up.ok == true', on_false: filter }\n",
        )

        assert "act" in idx.file_actions[wf], sorted(idx.file_actions[wf])
        assert idx.file_actions[wf]["act"].guard_condition == "up.ok == true"

    def test_a_quoted_block_form_dependency_keeps_the_check_on(self, tmp_path: Path):
        """Quotes left on `- 'up'` made the dependency `'up`, which no lookup finds --
        and an unknown upstream switches the whole bare-name check off."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: up\n"
            "  - name: act\n"
            "    dependencies:\n"
            "      - 'up'\n"
            "    guard: { condition: 'nonexistent == true', on_false: filter }\n",
        )
        action = idx.file_actions[wf]["act"]
        everything = collect_diagnostics(wf, idx)
        errors = [d for d in everything if d.severity == lsp.DiagnosticSeverity.Error]

        assert action.dependencies == ["up"], action.dependencies
        # By severity, not by message text: quotes left on emit `Unresolved action
        # reference`, and filtering for any one wording makes this assertion vacuous.
        assert errors == [], [d.message for d in errors]
        assert len([d for d in everything if "Guard condition" in d.message]) == 1

    def test_a_project_level_output_field_reaches_every_action(self, tmp_path: Path):
        """agent_actions.yml's default_agent_config is merged beneath the workflow's own."""
        from agent_actions.tooling.lsp.indexer import build_index

        root = tmp_path / "proj"
        (root / "agent_workflow" / "wf" / "agent_config").mkdir(parents=True)
        (root / "agent_actions.yml").write_text(
            "project_name: p\ndefault_agent_config:\n  output_field: verdict\n"
        )
        (root / "agent_workflow" / "wf" / "agent_config" / "wf.yml").write_text(
            "actions:\n"
            "  - name: checker\n"
            "  - name: act\n"
            "    dependencies: [checker]\n"
            "    guard: { condition: 'verdict == true', on_false: filter }\n"
        )
        index = build_index(root)
        wf = root / "agent_workflow" / "wf" / "agent_config" / "wf.yml"

        assert index.file_actions[wf]["checker"].output_field == "verdict"
        assert [d for d in collect_diagnostics(wf, index) if "Guard condition" in d.message] == []

    def test_a_variant_from_another_workflow_does_not_count(self, tmp_path: Path):
        """The sweep is workflow-wide, not project-wide: another workflow's variant is not
        a namespace this record carries, so naming it is still a silent filter."""
        from agent_actions.tooling.lsp.indexer import build_index

        root = tmp_path / "proj"
        root.mkdir(parents=True)
        (root / "agent_actions.yml").write_text("project_name: p\n")
        for wf_name, body in (
            ("alpha", "actions:\n  - name: score\n    versions: { param: i, range: [1, 2] }\n"),
            (
                "beta",
                "actions:\n"
                "  - name: seed\n"
                "  - name: tally\n"
                "    dependencies: [seed]\n"
                "    guard: { condition: 'score_1.value > 1', on_false: filter }\n",
            ),
        ):
            d = root / "agent_workflow" / wf_name / "agent_config"
            d.mkdir(parents=True)
            (d / f"{wf_name}.yml").write_text(body)

        index = build_index(root)
        beta = root / "agent_workflow" / "beta" / "agent_config" / "beta.yml"
        found = [d for d in collect_diagnostics(beta, index) if "Guard condition" in d.message]

        assert len(found) == 1, "another workflow's variant is not produced here"

    def test_a_variant_declared_in_a_sibling_file_is_not_flagged(self, tmp_path: Path):
        """get_action_metadata searches the whole workflow, so the variant sweep must too."""
        from agent_actions.tooling.lsp.indexer import build_index

        root = tmp_path / "proj"
        config = root / "agent_workflow" / "wf" / "agent_config"
        config.mkdir(parents=True)
        (root / "agent_actions.yml").write_text("project_name: p\n")
        (config / "a_stage.yml").write_text(
            "actions:\n  - name: score\n    versions: { param: i, range: [1, 2] }\n"
        )
        (config / "b_stage.yml").write_text(
            "actions:\n"
            "  - name: tally\n"
            "    dependencies: [score_1]\n"
            "    guard: { condition: 'score_1.value > 1', on_false: filter }\n"
        )
        index = build_index(root)

        offenders = [
            d.message
            for f in index.file_actions
            for d in collect_diagnostics(f, index)
            if "Guard condition" in d.message
        ]
        assert offenders == [], offenders

    def test_a_declared_version_param_is_exempt_through_the_indexer(self, tmp_path: Path):
        """M65: dropping `versions_params` turns on a warning for every versioned action
        guarding on its own loop param -- the exact false positive this check removes."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: seed\n"
            "  - name: voter\n"
            "    dependencies: [seed]\n"
            "    versions: { param: voter_id, range: [1, 2] }\n"
            "    guard: { condition: 'voter_id == 1', on_false: filter }\n",
        )
        action = idx.file_actions[wf]["voter"]

        assert action.versions_params == ["voter_id"], action.versions_params
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_duplicate_version_param_is_reported(self, tmp_path: Path):
        """The other consumer of versions_params, which had no coverage at all."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: voter\n"
            "    versions:\n"
            "      - { param: i, range: [1, 2] }\n"
            "      - { param: i, range: [3, 4] }\n",
        )
        found = [d for d in collect_diagnostics(wf, idx) if "param" in d.message.lower()]

        assert len(found) == 1, [d.message for d in found]

    def test_a_scope_naming_only_the_runtime_bus_adds_no_upstream(self, tmp_path: Path):
        """M24: counting `source` as an upstream makes the lookup miss, and a missing
        upstream switches the whole bare-name check off."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: up\n"
            "  - name: act\n"
            "    dependencies: [up]\n"
            "    context_scope: { observe: [source.text, version.i] }\n"
            "    guard: { condition: 'nonexistent == true', on_false: filter }\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.context_observe == ["source.text", "version.i"]
        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
        assert len(found) == 1, "a runtime-bus ref is not an upstream; the check must still run"

    def test_a_double_quoted_condition_literal_does_not_leak(self, tmp_path: Path):
        """M64: `condition: "a.b == 'x'"` -- the inner single-quoted literal must blank too."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: extract\n"
            "  - name: act\n"
            "    dependencies: [extract]\n"
            "    guard: { condition: \"extract.status == 'approved'\", on_false: filter }\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.guard_variables == ["extract.status"], action.guard_variables
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_double_quoted_scope_item_is_unquoted(self, tmp_path: Path):
        """M55/M54: both quote characters, and the reference range must skip the quote."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: up\n"
            "  - name: act\n"
            "    dependencies: [up]\n"
            "    context_scope:\n"
            "      observe:\n"
            '        - "up.title"\n',
        )
        action = idx.file_actions[wf]["act"]
        refs = [r for r in idx.references_by_file[wf] if r.value == "up.title"]

        assert action.context_observe == ["up.title"], action.context_observe
        assert refs, "the reference must be recorded under the unquoted name"
        line = wf.read_text().splitlines()[refs[0].location.line]
        assert line[refs[0].location.column] == "u", (
            f"range starts on the quote, not the name: {line[refs[0].location.column :]!r}"
        )

    def test_a_quoted_action_name_is_indexed(self, tmp_path: Path):
        """M52: a quoted name must still reach the index, or the action vanishes silently."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: 'up'\n"
            '  - name: "act"\n'
            "    dependencies: [up]\n"
            "    guard: { condition: 'up.ok == true', on_false: filter }\n",
        )

        assert sorted(idx.file_actions[wf]) == ["act", "up"], sorted(idx.file_actions[wf])
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_scalar_dependency_and_scope_are_read_as_one_item(self, tmp_path: Path):
        """M37/M41: YAML allows a bare scalar where a list is expected."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: up\n"
            "  - name: act\n"
            "    dependencies: up\n"
            "    context_scope: { observe: up.title }\n"
            "    guard: { condition: 'nonexistent == true', on_false: filter }\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.dependencies == ["up"], action.dependencies
        assert action.context_observe == ["up.title"], action.context_observe
        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
        assert len(found) == 1, "the upstream is known, so the bare name is provably wrong"

    def test_a_file_granularity_version_merge_inverts_namespacing(self, tmp_path: Path):
        """Measured with a real run: the BARE clause works and the dotted one filters all.

        merge_version_content spreads such a tool's output flat over record content, so its
        fields are content's own top-level keys. Reporting the bare spelling would warn on
        the only clause that works, and name the edit that destroys the data as the fix.
        """
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: voter\n"
            "    versions: { param: i, range: [1, 2] }\n"
            "  - name: fmerge\n"
            "    kind: tool\n"
            "    impl: merge_it\n"
            "    granularity: file\n"
            "    version_consumption: { pattern: merge }\n"
            "    dependencies: [voter]\n"
            "  - name: act\n"
            "    dependencies: [fmerge]\n"
            "    guard: { condition: 'fdecision == \"keep\"', on_false: filter }\n",
        )

        assert idx.file_actions[wf]["fmerge"].spreads_output_flat
        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_a_record_granularity_merge_still_namespaces(self, tmp_path: Path):
        """The inversion is specific to FILE granularity; record granularity nests."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: voter\n"
            "    versions: { param: i, range: [1, 2] }\n"
            "  - name: rmerge\n"
            "    kind: tool\n"
            "    impl: merge_it\n"
            "    granularity: record\n"
            "    version_consumption: { pattern: merge }\n"
            "    dependencies: [voter]\n"
            "  - name: act\n"
            "    dependencies: [rmerge]\n"
            "    guard: { condition: 'nonexistent == true', on_false: filter }\n",
        )

        assert not idx.file_actions[wf]["rmerge"].spreads_output_flat
        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
        assert len(found) == 1, "a record-granularity merge namespaces, so the check applies"

    def test_a_documented_function_call_is_not_read_as_a_field(self, tmp_path: Path):
        """guards.md teaches `len(...)`/`max(...)`; measured, no call syntax parses at all.

        So the clause is broken, but "without an action prefix" names a mistake that is not
        the mistake and a fix that does not exist. The loader reports it; this stays quiet.
        """
        for clause in ("len(up.items) > 0", "max(up.scores) >= 85", "LENGTH(up.items) > 2"):
            case = tmp_path / clause[:3]
            case.mkdir(parents=True, exist_ok=True)
            idx, wf = self._index(
                case,
                "actions:\n"
                "  - name: up\n"
                "  - name: act\n"
                "    dependencies: [up]\n"
                f"    guard: {{ condition: '{clause}', on_false: filter }}\n",
            )
            found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]
            assert found == [], (clause, [d.message for d in found])

    def test_an_action_whose_name_is_not_the_first_key_is_indexed(self, tmp_path: Path):
        """YAML does not care about key order and neither does the loader.

        Unindexed, every reference to it became an Unresolved error -- and because one
        unresolvable upstream short-circuits the bare-name rule, it also switched the check
        off for everything downstream.
        """
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - kind: tool\n"
            "    impl: stage\n"
            "    name: stage_items\n"
            "  - name: act\n"
            "    dependencies: [stage_items]\n"
            "    guard: { condition: 'stage_items.ok == true', on_false: filter }\n",
        )

        assert sorted(idx.file_actions[wf]) == ["act", "stage_items"]
        assert collect_diagnostics(wf, idx) == []

    def test_a_flow_style_action_entry_is_indexed(self, tmp_path: Path):
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - { name: stage_items, kind: tool, impl: stage }\n"
            "  - name: act\n"
            "    dependencies: [stage_items]\n"
            "    guard: { condition: 'stage_items.ok == true', on_false: filter }\n",
        )

        assert sorted(idx.file_actions[wf]) == ["act", "stage_items"]
        assert collect_diagnostics(wf, idx) == []

    def test_the_project_config_is_found_under_every_accepted_spelling(self, tmp_path: Path):
        """Four spellings are accepted; reading one means every bare name warns in the rest."""
        from agent_actions.tooling.lsp.indexer import build_index

        for n, spelling in enumerate(
            ("agent_actions.yml", "agent_actions.yaml", ".agent_actions.yml")
        ):
            root = tmp_path / f"p{n}"
            (root / "agent_workflow" / "wf" / "agent_config").mkdir(parents=True)
            (root / spelling).write_text(
                "project_name: p\ndefault_agent_config:\n  output_field: verdict\n"
            )
            (root / "agent_workflow" / "wf" / "agent_config" / "wf.yml").write_text(
                "actions:\n"
                "  - name: checker\n"
                "  - name: act\n"
                "    dependencies: [checker]\n"
                "    guard: { condition: 'verdict == true', on_false: filter }\n"
            )
            index = build_index(root)
            wf = root / "agent_workflow" / "wf" / "agent_config" / "wf.yml"
            found = [d for d in collect_diagnostics(wf, index) if "Guard condition" in d.message]
            assert found == [], (spelling, [d.message for d in found])

    def test_an_inline_versions_block_sets_the_lens_anchor(self, tmp_path: Path):
        """versions_line gates the CodeLens; the inline form is what real configs write."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n  - name: voter\n    versions: { param: voter_id, range: [1, 3] }\n",
        )

        assert idx.file_actions[wf]["voter"].versions_line is not None

    def test_inline_context_scope_captures_passthrough(self, tmp_path: Path):
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: act\n"
            "    context_scope: { passthrough: [up.id], observe: [up.score] }\n",
        )
        action = idx.file_actions[wf]["act"]

        assert action.context_passthrough == ["up.id"], action.context_passthrough
        assert action.context_observe == ["up.score"], action.context_observe

    def test_a_defaults_level_output_field_reaches_every_action(self, tmp_path: Path):
        """`output_field` is a SIMPLE_CONFIG_FIELDS entry, so defaults inherit into actions."""
        idx, wf = self._index(
            tmp_path,
            "defaults:\n  output_field: verdict\nactions:\n  - name: act\n    intent: x\n",
        )

        assert idx.file_actions[wf]["act"].output_field == "verdict"

    def test_a_bare_name_inherited_from_defaults_is_not_flagged(self, tmp_path: Path):
        """The runtime promotes it, so warning here is the false positive this check forbids."""
        idx, wf = self._index(
            tmp_path,
            "defaults:\n"
            "  output_field: verdict\n"
            "actions:\n"
            "  - name: checker\n"
            "    intent: x\n"
            "  - name: act\n"
            "    dependencies: [checker]\n"
            "    guard: { condition: 'verdict == true', on_false: filter }\n",
        )

        assert [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message] == []

    def test_an_upstream_reached_only_by_inline_scope_is_not_first_stage(self, tmp_path: Path):
        """Without inline scope parsed, this action names no upstream, is read as first-stage,
        and a bare name that resolves nowhere is passed in silence."""
        idx, wf = self._index(
            tmp_path,
            "actions:\n"
            "  - name: checker\n"
            "    intent: x\n"
            "  - name: act\n"
            "    context_scope: { observe: [checker.id] }\n"
            "    guard: { condition: 'totally_bogus == true', on_false: filter }\n",
        )
        found = [d for d in collect_diagnostics(wf, idx) if "Guard condition" in d.message]

        assert len(found) == 1, found
        assert "`totally_bogus`" in found[0].message


class TestTheIndexAgreesWithTheDocument:
    """Cross-check the index against a plain YAML read of the repo's own example projects.

    A corpus check, not an oracle. The expected side loads with the same parser, so it
    cannot catch a shared misreading, and measured against 87 mutants it killed none the
    hand-built tests did not. What it defends is the real spellings `examples/` happens to
    contain -- inline `guard: {`, inline `versions: {`, `condition: 'a == "b"'` -- against a
    return to line scanning.
    """

    @staticmethod
    def _examples() -> list[Path]:
        root = Path(__file__).resolve().parents[3] / "examples"
        return sorted(p for p in root.iterdir() if (p / "agent_workflow").is_dir())

    def test_every_example_action_matches_its_parsed_source(self):
        from ruamel.yaml import YAML

        from agent_actions.tooling.lsp.indexer import build_index

        projects = self._examples()
        assert projects, "no example projects found to cross-check"

        yaml = YAML(typ="safe")
        mismatches: list[str] = []
        checked = 0

        for project in projects:
            index = build_index(project)
            for file_path, actions in index.file_actions.items():
                data = yaml.load(file_path.read_text()) or {}
                defaults = data.get("defaults") or {}
                for entry in data.get("actions", []) or []:
                    if not isinstance(entry, dict) or not entry.get("name"):
                        continue
                    name = entry["name"]
                    checked += 1
                    if name not in actions:
                        mismatches.append(f"{file_path.name}::{name} missing from the index")
                        continue
                    meta = actions[name]

                    guard = entry.get("guard")
                    want = guard if isinstance(guard, str) else (guard or {}).get("condition")
                    if isinstance(want, str) and want.strip():
                        if meta.guard_condition != want:
                            mismatches.append(
                                f"{file_path.name}::{name} guard {meta.guard_condition!r} != {want!r}"
                            )
                        if meta.guard_line is None:
                            mismatches.append(f"{file_path.name}::{name} guard has no anchor line")

                    want_output = entry.get("output_field", defaults.get("output_field"))
                    if isinstance(want_output, str) and meta.output_field != want_output:
                        mismatches.append(
                            f"{file_path.name}::{name} output_field "
                            f"{meta.output_field!r} != {want_output!r}"
                        )

                    scope = entry.get("context_scope")
                    if isinstance(scope, dict):
                        for directive, got in (
                            ("observe", meta.context_observe),
                            ("passthrough", meta.context_passthrough),
                            ("drop", meta.context_drop),
                        ):
                            refs = scope.get(directive) or []
                            if isinstance(refs, str):
                                refs = [refs]
                            if [str(r) for r in refs] != list(got):
                                mismatches.append(
                                    f"{file_path.name}::{name}.{directive} {got} != {refs}"
                                )

        assert checked > 50, f"cross-check saw only {checked} actions; it is not exercising much"
        assert mismatches == [], "\n".join(mismatches)

    def test_no_example_project_produces_any_diagnostic(self):
        """These ship with the framework; anything here is something every reader sees.

        Deliberately unfiltered. Filtering on "Guard condition" hid six Error-severity
        false positives the same pass emitted on version variants.
        """
        from agent_actions.tooling.lsp.indexer import build_index

        projects = self._examples()
        assert projects, "no example projects found"

        offenders: list[str] = []
        guards = 0
        for project in projects:
            index = build_index(project)
            for file_path, actions in index.file_actions.items():
                guards += sum(
                    1
                    for a in actions.values()
                    if a.guard_condition and a.guard_variables and a.guard_line is not None
                )
                for diagnostic in collect_diagnostics(file_path, index):
                    offenders.append(
                        f"{project.name}/{file_path.name}:{diagnostic.range.start.line + 1} "
                        f"[{diagnostic.severity.name}] {diagnostic.message}"
                    )

        # Counted BEFORE the clean assertion: with guard indexing disabled this test was
        # green, because a check that never runs reports nothing. That is the original bug.
        assert guards >= 8, f"only {guards} guards indexed across {len(projects)} projects"
        assert offenders == [], "\n".join(offenders)
