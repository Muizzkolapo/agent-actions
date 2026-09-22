"""`--record-limit` caps every action from the command line.

Exercised through the loader the run command uses, so what is asserted is the
config the workflow engine actually receives.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.cli.workflow_loader import load_workflow
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from agent_actions.utils.limits import RECORD_LIMIT_KEY, resolve_record_limit

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
    configs = _configs(project, record_limit=2)

    assert configs, "no actions loaded; the fixture changed"
    for name, config in configs.items():
        assert config[RECORD_LIMIT_KEY] == 2, f"{name} did not carry the cap"


def test_the_cap_is_what_the_resolver_then_applies(project):
    """The stamped value has to be the one the resolver reads."""
    configs = _configs(project, record_limit=2)

    for config in configs.values():
        assert resolve_record_limit(config)[0] == 2


def test_no_cap_leaves_the_config_untouched(project):
    configs = _configs(project)

    for name, config in configs.items():
        assert RECORD_LIMIT_KEY not in config, f"{name} carries a cap nobody asked for"


MULTI = "shared_suite"


def _multi_action_project(tmp_path, monkeypatch):
    """Two actions, one configuring a limit below the cap and one above it.

    A single-action fixture with no configured limit cannot tell a cap that
    reaches every action from one that reaches the first, nor one that respects
    a configured limit from one that overwrites it.
    """
    root = tmp_path / "multi"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    config = root / "agent_workflow" / MULTI / "agent_config" / f"{MULTI}.yml"
    config.write_text(
        config.read_text()
        .replace("  - name: summarize\n", "  - name: summarize\n    record_limit: 1\n")
        .replace("  - name: resummarize\n", "  - name: resummarize\n    record_limit: 100\n")
    )
    monkeypatch.chdir(root)
    paths = ProjectPathsFactory.create_project_paths(
        MULTI, MULTI, auto_create=True, project_root=root
    )
    return load_workflow(MULTI, paths, root, read_only=True, record_limit=5).action_configs


def test_a_cap_does_not_raise_an_action_configured_lower(tmp_path, monkeypatch):
    configs = _multi_action_project(tmp_path, monkeypatch)

    assert resolve_record_limit(configs["summarize"])[0] == 1, "the cap raised a smaller limit"


def test_a_cap_lowers_an_action_configured_higher(tmp_path, monkeypatch):
    configs = _multi_action_project(tmp_path, monkeypatch)

    assert resolve_record_limit(configs["resummarize"])[0] == 5


def test_an_action_that_configures_a_limit_still_carries_the_cap(tmp_path, monkeypatch):
    """Otherwise an action could escape the cap by configuring anything at all."""
    configs = _multi_action_project(tmp_path, monkeypatch)

    for name, config in configs.items():
        assert config[RECORD_LIMIT_KEY] == 5, f"{name} escaped the cap"


def test_the_cap_does_not_overwrite_a_configured_limit(tmp_path, monkeypatch):
    configs = _multi_action_project(tmp_path, monkeypatch)

    assert configs["summarize"]["record_limit"] == 1
    assert configs["resummarize"]["record_limit"] == 100


def _options_section(help_text):
    """Help below the Options heading — the examples above it also name the flag."""
    return help_text.split("Options:", 1)[1]


class TestTheFlag:
    def test_it_is_offered_on_run(self):
        result = CliRunner().invoke(cli, ["run", "--help"])

        assert "--record-limit" in _options_section(result.output), result.output

    @pytest.mark.parametrize("value", ["0", "-1", "nonsense", "2.5"])
    def test_a_value_that_cannot_cap_anything_is_refused(self, project, value):
        """Refused for being out of range, not for the option being unknown —
        click answers both with exit 2 and a message naming the flag."""
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--record-limit", value])

        assert result.exit_code == 2, result.output
        assert "No such option" not in result.output, result.output

    def test_it_is_not_required(self):
        result = CliRunner().invoke(cli, ["run", "--help"])
        after = _options_section(result.output).split("--record-limit")[1][:160]

        assert "[required]" not in after


TOOL_WORKFLOW = "tool_action"


def _stage(project, count):
    """Put *count* records where the tool workflow will read them."""
    staging = project / "agent_workflow" / TOOL_WORKFLOW / "agent_io" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "pages.json").write_text(
        json.dumps([{"page_content": f"page number {i}"} for i in range(count)])
    )


def _stamp(project, action):
    """The completion metadata stored for *action*."""
    paths = ProjectPathsFactory.create_project_paths(
        TOOL_WORKFLOW, TOOL_WORKFLOW, auto_create=False, project_root=project
    )
    return json.loads((paths.io_dir / ".agent_status.json").read_text())[action]


def _processed(project):
    """How many records the action actually produced, read from the store."""
    paths = ProjectPathsFactory.create_project_paths(
        TOOL_WORKFLOW, TOOL_WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(
        workflow_path=str(paths.io_dir.parent), workflow_name=TOOL_WORKFLOW
    )
    backend.initialize()
    try:
        return sum(
            len(backend.read_target("flatten", path))
            for path in backend.list_target_files("flatten")
        )
    finally:
        backend.close()


class TestItActuallyCapsARun:
    """Driven through the command, on a workflow whose action is a local tool —
    a config key that is set but never reaches the run would pass everything else.
    """

    def test_the_cap_reduces_the_records_processed(self, project):
        _stage(project, 6)

        result = CliRunner().invoke(
            cli, ["run", "-a", TOOL_WORKFLOW, "--record-limit", "2", "--fresh"]
        )

        assert result.exit_code == 0, result.output
        assert _processed(project) == 2

    def test_without_the_cap_every_record_is_processed(self, project):
        """The control: otherwise a cap that did nothing would look the same."""
        _stage(project, 6)

        result = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert _processed(project) == 6

    def test_the_capped_run_says_what_it_dropped(self, project):
        """The counts, not just the flag name — an error message mentioning the
        flag would otherwise satisfy this."""
        _stage(project, 6)

        result = CliRunner().invoke(
            cli, ["run", "-a", TOOL_WORKFLOW, "--record-limit", "2", "--fresh"]
        )

        assert result.exit_code == 0, result.output
        assert "--record-limit=2: processing 2 of 6 records" in result.output, result.output

    def test_a_limit_larger_than_the_input_says_nothing(self, project):
        """The limit resolves and the slice runs; nothing is dropped, so there is
        nothing to announce. This is the noisy case — a limit that never bites
        still fires once per action per input file."""
        _stage(project, 6)

        result = CliRunner().invoke(
            cli, ["run", "-a", TOOL_WORKFLOW, "--record-limit", "10", "--fresh"]
        )

        assert result.exit_code == 0, result.output
        assert _processed(project) == 6
        assert "processing" not in result.output, result.output

    def test_an_uncapped_run_says_nothing_about_a_limit(self, project):
        """The announcement exists because a truncated run looks complete. One
        that fires when nothing was dropped spends that signal."""
        _stage(project, 6)

        result = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert "record-limit" not in result.output, result.output

    def test_the_cap_counts_per_input_file(self, project):
        """The same unit record_limit uses. Two files of six under a cap of two
        is four records, not two — and a single-file fixture cannot tell those apart."""
        staging = project / "agent_workflow" / TOOL_WORKFLOW / "agent_io" / "staging"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for index in range(2):
            (staging / f"pages{index}.json").write_text(
                json.dumps([{"page_content": f"file {index} page {i}"} for i in range(6)])
            )

        result = CliRunner().invoke(
            cli, ["run", "-a", TOOL_WORKFLOW, "--record-limit", "2", "--fresh"]
        )

        assert result.exit_code == 0, result.output
        assert _processed(project) == 4


class TestARunThatAlreadyCompleted:
    """A completed action is skipped unless something it depends on changed.

    The codebase already treats a changed limit as such a change; a cap is a
    changed limit, and the project this feature exists for is one you have
    already run at least once.
    """

    def test_capping_a_completed_run_reprocesses_it(self, project):
        _stage(project, 6)
        first = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])
        assert first.exit_code == 0, first.output
        assert _processed(project) == 6

        second = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--record-limit", "2"])

        assert second.exit_code == 0, second.output
        assert _processed(project) == 2, "the cap was ignored on an already-completed action"

    def test_lifting_a_cap_reprocesses_what_it_truncated(self, project):
        """Otherwise a truncated run is served as a complete one indefinitely."""
        _stage(project, 6)
        first = CliRunner().invoke(
            cli, ["run", "-a", TOOL_WORKFLOW, "--record-limit", "2", "--fresh"]
        )
        assert first.exit_code == 0, first.output
        assert _processed(project) == 2

        second = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW])

        assert second.exit_code == 0, second.output
        assert _processed(project) == 6, "a truncated run was served as a complete one"


class TestARunCappedByTheEnvironment:
    """The variable and the flag are one knob, so a completed run must treat
    them the same. Only what reaches the completion stamp gets that treatment.
    """

    def test_lifting_the_variable_reprocesses_what_it_truncated(self, project, monkeypatch):
        _stage(project, 6)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")
        first = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])
        assert first.exit_code == 0, first.output
        assert _processed(project) == 2

        monkeypatch.delenv("AGAC_RECORD_LIMIT")
        second = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW])

        assert second.exit_code == 0, second.output
        assert _processed(project) == 6, "a truncated run was served as a complete one"

    def test_the_variable_still_set_does_not_reprocess(self, project, monkeypatch):
        """The control: invalidating on every run would satisfy the test above."""
        _stage(project, 6)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")
        first = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])
        assert first.exit_code == 0, first.output

        second = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW])

        assert second.exit_code == 0, second.output
        assert "already complete" in second.output, second.output

    def test_the_stamp_records_the_limit_that_applied(self, project, monkeypatch):
        """Whichever door set it. A stamp of what was configured describes a run
        that did not happen."""
        _stage(project, 6)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "2")

        result = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert _stamp(project, "flatten")["record_limit"] == 2

    def test_an_uncapped_run_stamps_no_limit(self, project, monkeypatch):
        """The other half: a resolved stamp must not invent a limit, or every
        completed action re-runs once on upgrade."""
        _stage(project, 6)
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)

        result = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert _stamp(project, "flatten")["record_limit"] is None


class TestTheRetiredEnvironmentName:
    """Rejected end to end, before any action runs — not only in the resolver."""

    def test_the_run_fails_and_names_the_replacement(self, project, monkeypatch):
        """Asserted on the exception, not the console: the runner invokes the
        command group directly, below the entrypoint that renders errors."""
        _stage(project, 6)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "2")

        result = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])

        assert result.exit_code != 0
        assert "AGAC_RECORD_LIMIT" in str(result.exception), result.exception

    def test_nothing_is_processed(self, project, monkeypatch):
        """Refused while the run is assembled, so no action gets as far as
        completing and then failing to record that it did."""
        _stage(project, 6)
        monkeypatch.setenv("AGAC_MAX_RECORDS", "2")

        CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])

        assert _processed(project) == 0


TAG_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def tag_density(data: Any, *args) -> list[dict]:
    return [{"summary": str((data or {}).get("summary", "")), "exam_density": "high"}]
"""

SECOND_ACTION = """  - name: enrich
    kind: tool
    dependencies: [flatten]
    intent: "Tag"
    schema: tool_action_output
    impl: tag_density
    record_limit: 2
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""


class TestALimitOnAnActionBelowTheFirst:
    """An action reading another action's output is sliced on a different path
    from one reading staging, and only a limit it alone carries reaches it."""

    @pytest.fixture
    def chained(self, project):
        _stage(project, 6)
        config = (
            project / "agent_workflow" / TOOL_WORKFLOW / "agent_config" / f"{TOOL_WORKFLOW}.yml"
        )
        config.write_text(config.read_text().rstrip("\n") + "\n" + SECOND_ACTION)
        (project / "tools" / TOOL_WORKFLOW / "tag.py").write_text(TAG_TOOL)
        return project

    def _rows(self, project, action):
        paths = ProjectPathsFactory.create_project_paths(
            TOOL_WORKFLOW, TOOL_WORKFLOW, auto_create=False, project_root=project
        )
        backend = get_storage_backend(
            workflow_path=str(paths.io_dir.parent), workflow_name=TOOL_WORKFLOW
        )
        backend.initialize()
        try:
            return sum(
                len(backend.read_target(action, path)) for path in backend.list_target_files(action)
            )
        finally:
            backend.close()

    def test_it_truncates_that_action_and_not_the_one_above(self, chained):
        result = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert self._rows(chained, "flatten") == 6, "the limit reached the wrong action"
        assert self._rows(chained, "enrich") == 2


class TestARunThatLostAFile:
    """A file the walk lost leaves records uncounted. The stamp must say so,
    or a later limit sitting above the short count — but below the true total —
    reads as one that could not have bitten, and the action is skipped with its
    short output vouched for."""

    @staticmethod
    def _stage_one_good_one_broken(project):
        staging = project / "agent_workflow" / TOOL_WORKFLOW / "agent_io" / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        for stale in staging.glob("*.json"):
            stale.unlink()
        (staging / "aaa_good.json").write_text(
            json.dumps([{"page_content": f"page {i}"} for i in range(4)])
        )
        (staging / "zzz_lost.json").write_text("{not json at all")
        return staging

    def test_the_stamp_cannot_say_what_it_processed(self, project, monkeypatch):
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
        self._stage_one_good_one_broken(project)

        result = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert _stamp(project, "flatten")["records_processed"] is None

    def test_a_limit_above_the_short_count_still_re_runs_it(self, project, monkeypatch):
        """The whole chain in one assertion: loss -> count unknown -> stamp ->
        re-run. 6 sits above the 4 records that survived and below the 13 the
        input really held, so a short count would have served as proof the
        limit was harmless."""
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
        staging = self._stage_one_good_one_broken(project)

        first = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--fresh"])
        assert first.exit_code == 0, first.output

        # The transient failure clears: the file reads now.
        (staging / "zzz_lost.json").write_text(
            json.dumps([{"page_content": f"recovered {i}"} for i in range(9)])
        )
        second = CliRunner().invoke(cli, ["run", "-a", TOOL_WORKFLOW, "--record-limit", "6"])

        assert second.exit_code == 0, second.output
        assert "already complete" not in second.output, (
            "the action was skipped on a limit that only looked harmless"
        )
        # Not just "it re-ran for some reason": 4 from the file that always
        # read, plus 6 of the recovered 9 — the limit applies per file.
        assert _processed(project) == 10
