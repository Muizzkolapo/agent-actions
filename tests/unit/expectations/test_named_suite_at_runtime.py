"""A named `suite:` must resolve when the action actually runs, not just in preflight.

`expect: {suite: <name>}` is documented, and preflight validates the reference —
it is handed the project root and the workflow. No runtime caller was, so every
run of such an action raised instead: online surfaced it as a failed action, and
batch logged it per file and finished reporting success with each of them
missing from the output.

The action config already carries the project root, so the resolution reads what
is on the config rather than threading two more arguments through four call
sites.
"""

from pathlib import Path

import pytest
import yaml

from agent_actions.expectations.service import (
    ExpectationConfigurationError,
    create_expectation_service_from_config,
)

WORKFLOW = "my_workflow"
SUITE = "grounded_summary"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "agent_actions.yml").write_text("name: test\n")
    suite_dir = tmp_path / "expectations" / WORKFLOW
    suite_dir.mkdir(parents=True)
    (suite_dir / f"{SUITE}.yml").write_text(
        yaml.safe_dump(
            {
                "name": SUITE,
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
            agent_config={"_project_root": str(project), "_workflow": WORKFLOW},
        )
        assert service is not None, (
            "the action config carried everything needed and the suite still would not resolve"
        )

    def test_it_is_the_suite_from_disk(self, project: Path):
        service = create_expectation_service_from_config(
            _expect(),
            action_name="summarize",
            agent_config={"_project_root": str(project), "_workflow": WORKFLOW},
        )
        assert service.suite.name == SUITE
        assert [e.id for e in service.suite.expectations] == ["enough_options"]

    def test_the_resolved_suite_actually_judges(self, project: Path):
        service = create_expectation_service_from_config(
            _expect(),
            action_name="summarize",
            agent_config={"_project_root": str(project), "_workflow": WORKFLOW},
        )
        verdict, _per_record = service.verdict_for_response(
            {"options": ["only-one"]}, check_schema=False
        )
        assert verdict.overall_pass is False
        assert [o.id for o in verdict.failed] == ["enough_options"]


class TestExplicitArgumentsStillWin:
    def test_they_override_the_config(self, project: Path):
        service = create_expectation_service_from_config(
            _expect(),
            action_name="summarize",
            agent_config={"_project_root": "/nonexistent", "_workflow": "wrong"},
            project_root=project,
            workflow=WORKFLOW,
        )
        assert service.suite.name == SUITE


class TestWhatCannotBeResolvedStillSaysSo:
    def test_no_root_anywhere_is_an_error(self):
        with pytest.raises(ExpectationConfigurationError, match="no project root or workflow"):
            create_expectation_service_from_config(
                _expect(), action_name="summarize", agent_config={"_workflow": WORKFLOW}
            )

    def test_no_workflow_anywhere_is_an_error(self, project: Path):
        with pytest.raises(ExpectationConfigurationError, match="no project root or workflow"):
            create_expectation_service_from_config(
                _expect(),
                action_name="summarize",
                agent_config={"_project_root": str(project)},
            )

    def test_a_suite_that_is_not_on_disk_is_an_error(self, project: Path):
        with pytest.raises(Exception, match="missing_suite|not found|No such file"):
            create_expectation_service_from_config(
                {"suite": "missing_suite", "repair": "none"},
                action_name="summarize",
                agent_config={"_project_root": str(project), "_workflow": WORKFLOW},
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
                "_workflow": WORKFLOW,
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
                    "_workflow": WORKFLOW,
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
                "_workflow": WORKFLOW,
                "expect": {"suite": SUITE, "repair": "none"},
            }
        )
        assert strategy._expectation_service is not None
        assert strategy._expectation_service.suite.name == SUITE


class TestTheWorkflowNameIsStampedOnEveryAction:
    def test_the_loader_stamps_it_next_to_the_project_root(self):
        """Without this the config carries a root but no workflow, and the
        resolution still cannot find the file."""
        import inspect

        from agent_actions.workflow import config_pipeline

        source = inspect.getsource(config_pipeline.load_workflow_configs)
        assert '"_workflow"' in source
        assert '"_project_root"' in source
