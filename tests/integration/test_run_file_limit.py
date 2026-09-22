"""`agac run --file-limit` and `AGAC_FILE_LIMIT` bound a run by files.

The record axis has a flag and a variable; the file axis had neither, so the only
way to bound a run by files was to stage fewer of them — editing the project,
which is what a run-level limit exists to avoid.

Driven through the command on a workflow whose action is a local tool, so what is
asserted is what the run actually walked rather than a key that was set.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"
ACTION = "flatten"
FILES = 2
PER_FILE = 3


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Two staged files of three records each — one file cannot tell the axes apart."""
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    for index in range(FILES):
        staging.joinpath(f"pages{index}.json").write_text(
            json.dumps([{"page_content": f"file {index} page {i}"} for i in range(PER_FILE)])
        )
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv("AGAC_FILE_LIMIT", raising=False)
    return root


def _backend(project):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _files_walked(project):
    """How many input files the action produced output for."""
    backend = _backend(project)
    try:
        return len(backend.list_target_files(ACTION))
    finally:
        backend.close()


def _processed(project):
    backend = _backend(project)
    try:
        return sum(
            len(backend.read_target(ACTION, path)) for path in backend.list_target_files(ACTION)
        )
    finally:
        backend.close()


def _stamp(project, action):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    return json.loads((paths.io_dir / ".agent_status.json").read_text())[action]


def _guids_by_file(project):
    backend = _backend(project)
    try:
        return {
            path: [r["source_guid"] for r in backend.read_target(ACTION, path)]
            for path in backend.list_target_files(ACTION)
        }
    finally:
        backend.close()


def _fail(project, record_id):
    backend = _backend(project)
    try:
        backend.set_disposition(ACTION, record_id, "failed", reason="constructed for this test")
    finally:
        backend.close()


def _disposition(project, record_id):
    backend = _backend(project)
    try:
        rows = [r for r in backend.get_disposition(ACTION) if r.get("record_id") == record_id]
        return rows[0]["disposition"] if rows else None
    finally:
        backend.close()


def _options_section(help_text):
    """Help below the Options heading — the examples above it also name the flag."""
    return help_text.split("Options:", 1)[1]


class TestTheFlag:
    def test_it_is_offered_on_run(self):
        result = CliRunner().invoke(cli, ["run", "--help"])

        assert "--file-limit" in _options_section(result.output), result.output

    @pytest.mark.parametrize("value", ["0", "-1", "nonsense", "2.5"])
    def test_a_value_that_cannot_cap_anything_is_refused(self, project, value):
        """Refused for being out of range, not for the option being unknown —
        click answers both with exit 2 and a message naming the flag."""
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--file-limit", value])

        assert result.exit_code == 2, result.output
        assert "No such option" not in result.output, result.output

    def test_it_is_not_required(self):
        result = CliRunner().invoke(cli, ["run", "--help"])
        after = _options_section(result.output).split("--file-limit")[1][:160]

        assert "[required]" not in after


class TestItActuallyBoundsARun:
    def test_the_cap_reduces_the_files_walked(self, project):
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--file-limit", "1", "--fresh"])

        assert result.exit_code == 0, result.output
        assert _files_walked(project) == 1
        assert _processed(project) == PER_FILE

    def test_without_the_cap_every_file_is_walked(self, project):
        """The control: otherwise a cap that did nothing would look the same."""
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert _files_walked(project) == FILES
        assert _processed(project) == FILES * PER_FILE

    def test_the_record_cap_alone_still_walks_every_file(self, project):
        """The gap this closes: capping records shrinks each file, not the walk,
        so a run stays proportional to the file count however small the cap."""
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--record-limit", "1", "--fresh"])

        assert result.exit_code == 0, result.output
        assert _files_walked(project) == FILES

    def test_the_bounded_walk_says_what_stopped_it(self, project):
        """The source and the limit, not just that a walk ended — a shortened run
        otherwise looks like a complete one."""
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--file-limit", "1", "--fresh"])

        assert result.exit_code == 0, result.output
        assert f"--file-limit=1: {ACTION} stopped after 1 file(s)" in result.output, result.output

    def test_an_unbounded_run_says_nothing_about_a_file_limit(self, project):
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert "file-limit" not in result.output, result.output


class TestTheEnvironmentDoor:
    def test_the_variable_bounds_the_walk(self, project, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert _files_walked(project) == 1

    def test_the_flag_outranks_the_variable_by_source_not_by_size(self, project, monkeypatch):
        """A larger number typed for this run beats a smaller ambient one, or
        configuration nobody typed quietly overrules what was asked for."""
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--file-limit", "2", "--fresh"])

        assert result.exit_code == 0, result.output
        assert _files_walked(project) == FILES

    @pytest.mark.parametrize("value", ["0", "-1", "nonsense"])
    def test_a_value_that_cannot_bound_anything_fails_the_run(self, project, monkeypatch, value):
        monkeypatch.setenv("AGAC_FILE_LIMIT", value)

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert result.exit_code != 0
        assert "AGAC_FILE_LIMIT" in str(result.exception), result.exception

    def test_an_unusable_value_stops_the_run_before_anything_is_processed(
        self, project, monkeypatch
    ):
        """Refused while the run is assembled. The walk does not consult a file
        limit until a file has been processed, so failing there would leave that
        action's work done and unrecorded."""
        monkeypatch.setenv("AGAC_FILE_LIMIT", "0")

        CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert _processed(project) == 0


class TestTheCompletionStamp:
    """A completed action is skipped unless something it depends on changed, and
    the codebase already treats a changed limit as such a change."""

    def test_it_records_the_file_limit_that_applied(self, project, monkeypatch):
        """Whichever door set it. A stamp of what was configured describes a run
        that did not happen."""
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert _stamp(project, ACTION)["file_limit"] == 1

    def test_an_unbounded_run_stamps_no_file_limit(self, project):
        """The other half: a resolved stamp must not invent a limit, or every
        completed action re-runs once on upgrade."""
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert _stamp(project, ACTION)["file_limit"] is None

    def test_lifting_the_cap_walks_the_files_it_skipped(self, project, monkeypatch):
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")
        first = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
        assert first.exit_code == 0, first.output
        assert _files_walked(project) == 1

        monkeypatch.delenv("AGAC_FILE_LIMIT")
        second = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

        assert second.exit_code == 0, second.output
        assert _files_walked(project) == FILES, "a shortened walk was served as a complete one"

    def test_the_cap_still_set_does_not_reprocess(self, project, monkeypatch):
        """The control: invalidating on every run would satisfy the test above."""
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")
        first = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
        assert first.exit_code == 0, first.output

        second = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

        assert second.exit_code == 0, second.output
        assert "already complete" in second.output, second.output


class TestARepairIsNotHeldBack:
    """A repair walks the files holding the records it named. Stopping short of
    one leaves that record's cleared disposition unwritten, which is the erasure
    a limit must never cause.
    """

    def _two_failures_in_two_files(self, project):
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
        assert result.exit_code == 0, result.output
        by_file = _guids_by_file(project)
        assert len(by_file) == FILES, "fixture no longer stages two files"
        named = [guids[0] for guids in by_file.values()]
        for guid in named:
            _fail(project, guid)
        return named

    def _configure_file_limit(self, project, limit):
        """Edit the fixture's YAML, and prove the edit landed.

        A string replacement that quietly stops matching would leave the tests
        using it asserting against a workflow with no limit configured at all —
        passing for the absence of the thing they exist to exercise.
        """
        config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
        edited = config.read_text().replace(
            f"  - name: {ACTION}\n", f"  - name: {ACTION}\n    file_limit: {limit}\n"
        )
        assert f"file_limit: {limit}" in edited, "the fixture no longer has the action to edit"
        config.write_text(edited)

    def test_a_configured_file_limit_does_not_strand_a_named_record(self, project):
        named = self._two_failures_in_two_files(project)
        self._configure_file_limit(project, 1)

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert [_disposition(project, guid) for guid in named] == ["success", "success"]

    def test_the_variable_does_not_strand_a_named_record(self, project, monkeypatch):
        """The door a shell profile can leave open, which is why it matters most."""
        named = self._two_failures_in_two_files(project)
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert [_disposition(project, guid) for guid in named] == ["success", "success"]

    def test_an_ordinary_run_is_still_held_back(self, project):
        """The control: exempting the repair must not exempt everything."""
        self._configure_file_limit(project, 1)

        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

        assert result.exit_code == 0, result.output
        assert _files_walked(project) == 1

    def test_a_repair_leaves_the_stored_file_limit_where_it_found_it(self, project, monkeypatch):
        """Recording the limit a repair ran under would make the next ordinary run
        read a change, clear the action's dispositions and re-run it."""
        self._two_failures_in_two_files(project)
        assert _stamp(project, ACTION)["file_limit"] is None
        monkeypatch.setenv("AGAC_FILE_LIMIT", "1")

        result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW])

        assert result.exit_code == 0, result.output
        assert _stamp(project, ACTION)["file_limit"] is None
