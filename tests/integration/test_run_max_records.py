"""`--max-records` caps every action from the command line.

Exercised through the loader the run command uses, so what is asserted is the
config the workflow engine actually receives.
"""

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.utils.limits import MAX_RECORDS_KEY, effective_record_limit

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "inline_rules"


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    monkeypatch.chdir(root)
    return root


def _configs(project, **kwargs):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=True, project_root=project
    )
    workflow = load_workflow(WORKFLOW, paths, project, read_only=True, **kwargs)
    return workflow.action_configs


def test_the_cap_reaches_every_action(project):
    configs = _configs(project, max_records=2)

    assert configs, "no actions loaded; the fixture changed"
    for name, config in configs.items():
        assert config[MAX_RECORDS_KEY] == 2, f"{name} did not carry the cap"


def test_the_cap_is_what_the_resolver_then_applies(project):
    """The stamped value has to be the one effective_record_limit reads."""
    configs = _configs(project, max_records=2)

    for config in configs.values():
        assert effective_record_limit(config) == 2


def test_no_cap_leaves_the_config_untouched(project):
    configs = _configs(project)

    for name, config in configs.items():
        assert MAX_RECORDS_KEY not in config, f"{name} carries a cap nobody asked for"


def test_a_cap_does_not_raise_a_smaller_configured_limit(project):
    configs = _configs(project, max_records=50)

    for config in configs.values():
        config["record_limit"] = 3
        assert effective_record_limit(config) == 3


class TestTheFlag:
    def test_it_is_offered_on_run(self):
        result = CliRunner().invoke(cli, ["run", "--help"])
        assert "--max-records" in result.output

    @pytest.mark.parametrize("value", ["0", "-1", "nonsense", "2.5"])
    def test_a_value_that_cannot_cap_anything_is_refused(self, project, value):
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--max-records", value])
        assert result.exit_code == 2, result.output

    def test_it_is_not_required(self):
        result = CliRunner().invoke(cli, ["run", "--help"])
        assert "--max-records" in result.output
        assert "[required]" not in result.output.split("--max-records")[1][:120]
