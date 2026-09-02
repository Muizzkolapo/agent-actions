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


class TestTheProjectRootIsStampedOnEveryAction:
    def test_the_loader_stamps_the_root_and_nothing_stale(self):
        """Suite resolution needs only the project root; a workflow stamp would
        be dead weight the moment something started reading it again."""
        import inspect

        from agent_actions.workflow import config_pipeline

        source = inspect.getsource(config_pipeline.load_workflow_configs)
        assert '"_project_root"' in source
        assert '"_workflow"' not in source
