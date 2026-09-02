"""A named `suite:` must resolve when the action actually runs, not just in preflight.

`expect: {suite: <name>}` is documented, and preflight validates the reference —
it is handed the project root. No runtime caller was, so every run of such an
action raised instead: online surfaced it as a failed action, and batch logged
it per file and finished reporting success with each of them missing from the
output.

The action config already carries the project root, so the resolution reads what
is on the config rather than threading another argument through four call sites.
"""

from pathlib import Path

import pytest
import yaml

from agent_actions.expectations.service import (
    ExpectationConfigurationError,
    create_expectation_service_from_config,
)

SUITE = "grounded_summary"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "agent_actions.yml").write_text("name: test\nschema_path: schema\n")
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / f"{SUITE}.yml").write_text(
        yaml.safe_dump(
            {
                "expectations": [
                    {"id": "enough_options", "type": "item_count", "field": "options", "min": 2}
                ],
            }
        )
    )
    return tmp_path


def _expect() -> dict:
    return {"suite": SUITE, "repair": "none"}


class TestTheSuiteResolvesFromTheActionConfig:
    def test_a_named_suite_builds_a_service(self, project: Path):
        service = create_expectation_service_from_config(
            _expect(),
            action_name="summarize",
            agent_config={"_project_root": str(project)},
        )
        assert service is not None, (
            "the action config carried everything needed and the suite still would not resolve"
        )

    def test_it_is_the_suite_from_disk(self, project: Path):
        service = create_expectation_service_from_config(
            _expect(),
            action_name="summarize",
            agent_config={"_project_root": str(project)},
        )
        assert service.suite.name == SUITE
        assert [e.id for e in service.suite.expectations] == ["enough_options"]

    def test_the_resolved_suite_actually_judges(self, project: Path):
        service = create_expectation_service_from_config(
            _expect(),
            action_name="summarize",
            agent_config={"_project_root": str(project)},
        )
        verdict, _per_record = service.verdict_for_response(
            {"options": ["only-one"]}, check_schema=False
        )
        assert verdict.overall_pass is False
        assert [o.id for o in verdict.failed] == ["enough_options"]

    def test_a_bare_expect_resolves_the_actions_own_schema(self, project: Path):
        service = create_expectation_service_from_config(
            {"repair": "none"},
            action_name="summarize",
            agent_config={"_project_root": str(project), "schema_name": SUITE},
        )
        assert service.suite.name == SUITE
        assert [e.id for e in service.suite.expectations] == ["enough_options"]

    def test_a_bare_expect_reads_the_inlined_schema_dict(self):
        service = create_expectation_service_from_config(
            {"repair": "none"},
            action_name="summarize",
            agent_config={
                "schema": {
                    "fields": [{"id": "options", "type": "array"}],
                    "expectations": [
                        {"id": "enough_options", "type": "item_count", "field": "options", "min": 2}
                    ],
                }
            },
        )
        assert [e.id for e in service.suite.expectations] == ["enough_options"]

    def test_an_inlined_schema_dict_without_rules_is_an_error(self):
        with pytest.raises(ExpectationConfigurationError, match="no expectations"):
            create_expectation_service_from_config(
                {"repair": "none"},
                action_name="summarize",
                agent_config={"schema": {"fields": [{"id": "options", "type": "array"}]}},
            )


class TestExplicitArgumentsStillWin:
    def test_they_override_the_config(self, project: Path):
        service = create_expectation_service_from_config(
            _expect(),
            action_name="summarize",
            agent_config={"_project_root": "/nonexistent"},
            project_root=project,
        )
        assert service.suite.name == SUITE


class TestWhatCannotBeResolvedStillSaysSo:
    def test_no_root_anywhere_is_an_error(self):
        with pytest.raises(ExpectationConfigurationError, match="no project root"):
            create_expectation_service_from_config(
                _expect(), action_name="summarize", agent_config={}
            )

    def test_a_bare_expect_without_a_named_schema_is_an_error(self, project: Path):
        with pytest.raises(ExpectationConfigurationError, match="bare expect"):
            create_expectation_service_from_config(
                {"repair": "none"},
                action_name="summarize",
                agent_config={"_project_root": str(project)},
            )

    def test_a_suite_that_is_not_on_disk_is_an_error(self, project: Path):
        with pytest.raises(Exception, match="missing_suite|not found|No such file"):
            create_expectation_service_from_config(
                {"suite": "missing_suite", "repair": "none"},
                action_name="summarize",
                agent_config={"_project_root": str(project)},
            )

    def test_an_inline_block_never_needed_either(self):
        service = create_expectation_service_from_config(
            {"repair": "none", "expectations": [{"id": "x", "type": "item_count", "field": "o"}]},
            action_name="summarize",
            agent_config={},
        )
        assert service is not None


class TestTheBatchRepairPathResolvesItToo:
    """The path that used to lose the whole output file for this config."""

    def test_build_repair_strategy_resolves_a_named_suite(self, project: Path):
        from agent_actions.llm.batch.services.repair_ops import build_repair_strategy

        strategy = build_repair_strategy(
            {
                "name": "summarize",
                "action_name": "summarize",
                "_project_root": str(project),
                "expect": {"suite": SUITE, "repair": "auto", "max_iterations": 2},
            }
        )
        assert strategy is not None, (
            "the repair check raised instead of building, so the batch loop logged it per file "
            "and the run finished with every affected file missing from the output"
        )

    def test_observe_mode_with_a_named_suite_does_not_raise(self, project: Path):
        from agent_actions.llm.batch.services.repair_ops import build_repair_strategy

        assert (
            build_repair_strategy(
                {
                    "name": "summarize",
                    "action_name": "summarize",
                    "_project_root": str(project),
                    "expect": {"suite": SUITE, "repair": "none"},
                }
            )
            is None
        )

    def test_the_online_factory_resolves_it(self, project: Path):
        from agent_actions.processing.invocation.factory import InvocationStrategyFactory

        strategy = InvocationStrategyFactory._create_online_strategy(
            {
                "name": "summarize",
                "action_name": "summarize",
                "_project_root": str(project),
                "expect": {"suite": SUITE, "repair": "none"},
            }
        )
        assert strategy._expectation_service is not None
        assert strategy._expectation_service.suite.name == SUITE


class TestTheBareBlockResolvesThroughTheRealPipeline:
    """The load pipeline inlines a named schema and drops its name, so the
    bare default must work from what the pipeline actually produces — not
    from a hand-assembled config."""

    def test_a_real_load_carries_the_schema_rules_to_the_factory(self, tmp_path, monkeypatch):
        from agent_actions.processing.invocation.factory import InvocationStrategyFactory
        from agent_actions.services.workflow_inspector import WorkflowInspector
        from agent_actions.utils.path_utils import reset_path_manager

        monkeypatch.setenv("OPENAI_API_KEY", "sk-not-used")
        root = tmp_path / "proj"
        (root / "wf" / "agent_config").mkdir(parents=True)
        (root / "wf" / "agent_io" / "staging").mkdir(parents=True)
        (root / "templates").mkdir()
        (root / "schema").mkdir()
        (root / "agent_actions.yml").write_text(
            "default_agent_config:\n"
            "  api_key: OPENAI_API_KEY\n"
            "  model_name: gpt-4o-mini\n"
            "  model_vendor: openai\n"
            "  ephemeral: false\n"
            "schema_path: schema\n"
        )
        (root / "schema" / "quality.yml").write_text(
            yaml.safe_dump(
                {
                    "fields": [{"id": "summary", "type": "string", "required": True}],
                    "expectations": [{"id": "has_summary", "type": "not_null", "field": "summary"}],
                }
            )
        )
        (root / "wf" / "agent_config" / "wf.yml").write_text(
            "name: wf\n"
            "description: bare expect end to end\n"
            "defaults:\n"
            "  json_mode: true\n"
            "  granularity: Record\n"
            "  run_mode: online\n"
            "  model_name: gpt-4o-mini\n"
            "  model_vendor: openai\n"
            "  api_key: OPENAI_API_KEY\n"
            "actions:\n"
            "  - name: summarize\n"
            "    intent: summarize the input\n"
            "    kind: llm\n"
            '    prompt: "Summarize."\n'
            "    schema: quality\n"
            "    expect:\n"
            "      repair: none\n"
        )
        reset_path_manager()
        try:
            configs = WorkflowInspector("wf", project_root=root).load()
            strategy = InvocationStrategyFactory._create_online_strategy(configs["summarize"])
        finally:
            reset_path_manager()
        service = strategy._expectation_service
        assert service is not None, (
            "the pipeline inlined the schema and the factory still refused the bare block"
        )
        assert [e.id for e in service.suite.expectations] == ["has_summary"]
