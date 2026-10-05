"""A guard UDF that writes to its input stops its action, through `agac run`.

The UDF is handed a read-only view of the record, and the view refuses the write by
raising. A guard whose UDF raises passes its record, so the refusal applied no guard: both
records went to the action, the one the guard rejects included, and the run exited 0 with
a warning per evaluation. Every run here goes through the CLI, executor and store, the
batch one through the provider mock.
"""

import json
import shutil

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from agent_actions.workflow.managers.state import ActionStatus
from tests.integration.test_retry_ignores_record_cap import SOURCE, TAG_TOOL, WORKFLOW
from tests.integration.test_retry_selection_under_batch import _agac, _cycle, _project, _unwrapped

GUARD = "keep_unless_rejected"
GUARDED = "enrich"
GUARDED_ACTION = f"""  - name: {GUARDED}
    kind: tool
    dependencies: [flatten]
    intent: "Tag"
    schema: tool_action_output
    impl: tag_density
    guard: "udf:{GUARD}"
    context_scope: {{ observe: [flatten.summary] }}
    expect: {{ repair: none }}
"""

_HEADER = "from typing import Any\n\nfrom agent_actions import udf_tool\n\n\n@udf_tool\n"
READS = (
    _HEADER
    + f"""def {GUARD}(data: Any) -> bool:
    page = data.get("source") or {{}}
    return str(page.get("page_content", "")).strip().lower() != "reject"
"""
)
TIDIES = (
    _HEADER
    + f"""def {GUARD}(data: Any) -> bool:
    page = data.get("source") or {{}}
    page["page_content"] = str(page.get("page_content", "")).strip().lower()
    return page["page_content"] != "reject"
"""
)
# Writes only where there is something to tidy, so only one record's file trips it.
TIDIES_WHEN_UNTIDY = (
    _HEADER
    + f"""def {GUARD}(data: Any) -> bool:
    page = data.get("source") or {{}}
    text = str(page.get("page_content", ""))
    if text != text.strip().lower():
        page["page_content"] = text.strip().lower()
    return text.strip().lower() != "reject"
"""
)

PAGES = [{"page_content": "keep"}, {"page_content": " Reject "}]


@pytest.fixture
def project(tmp_path):
    """Two records through two tool actions, the second guarded by a UDF.

    Each run is its own `agac` process: in one process the registry keeps the first
    function registered under a name, so a later test's guard would be an earlier one's.
    """
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging)
    staging.mkdir()
    (staging / "pages.json").write_text(json.dumps(PAGES))
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + GUARDED_ACTION)
    (root / "tools" / WORKFLOW / "tag.py").write_text(TAG_TOOL)
    return root


def _guard(project, source):
    (project / "tools" / WORKFLOW / "guard.py").write_text(source)


def _run(project):
    code, output = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    return code, _unwrapped(output)


def _status(project, action=GUARDED):
    status = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status.read_text())[action]["status"]


def _store(project, workflow=WORKFLOW):
    paths = ProjectPathsFactory.create_project_paths(
        workflow, workflow, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=workflow)
    backend.initialize()
    return backend


def _rows(backend, action):
    return [
        row
        for path in backend.list_target_files(action)
        for row in backend._read_target_raw(action, path)
    ]


def _answered(project):
    """The page of every record the guarded action ran on; a guard's skip stores it null."""
    backend = _store(project)
    try:
        pages = {
            row["source_guid"]: row["content"]["source"]["page_content"]
            for row in _rows(backend, "flatten")
        }
        return sorted(
            pages[row["source_guid"]] for row in _rows(backend, GUARDED) if row["content"][GUARDED]
        )
    finally:
        backend.close()


def test_a_guard_that_reads_skips_the_record_it_rejects(project):
    """The control: the same guard without the write decides through the same run."""
    _guard(project, READS)

    code, output = _run(project)

    assert code == 0, output
    assert _answered(project) == ["keep"], output


def test_a_guard_that_writes_to_its_input_fails_its_action_by_name(project):
    _guard(project, TIDIES)

    code, output = _run(project)

    assert code != 0, output
    assert _status(project) == ActionStatus.FAILED.value, output
    assert f"Guard UDF '{GUARD}' wrote to its input" in output
    assert "return a value instead of mutating the input" in output
    assert _answered(project) == [], "no record may reach an action whose guard gave no answer"
    assert _status(project, "flatten") == ActionStatus.COMPLETED.value


def test_a_write_for_one_record_fails_the_action_not_only_its_file(project):
    """A file's failure is otherwise taken alone: the run completes, exit 0, and every
    record of that file is missing, the ones the guard would admit included."""
    staging = project / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    (staging / "more.json").write_text(json.dumps([{"page_content": "keep too"}]))
    _guard(project, TIDIES_WHEN_UNTIDY)

    code, output = _run(project)

    assert code != 0, output
    assert _status(project) == ActionStatus.FAILED.value, output
    assert f"Guard UDF '{GUARD}' wrote to its input" in output
    assert " Reject " not in _answered(project)


BATCH_WORKFLOW = "batch_field_rules"


def _batch_project(tmp_path, guard):
    root = _project(tmp_path)
    staging = root / "agent_workflow" / BATCH_WORKFLOW / "agent_io" / "staging" / "pages.json"
    staging.write_text(json.dumps(PAGES))
    config = root / "agent_workflow" / BATCH_WORKFLOW / "agent_config" / f"{BATCH_WORKFLOW}.yml"
    anchor = "    prompt: $p.Summarize\n"
    assert anchor in config.read_text()
    config.write_text(config.read_text().replace(anchor, anchor + f'    guard: "udf:{GUARD}"\n'))
    tools = root / "tools" / BATCH_WORKFLOW
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "guard.py").write_text(guard)
    return root


def test_a_batch_action_whose_guard_writes_submits_nothing_and_fails(tmp_path):
    """Batch evaluates the guard while preparing what it submits, not in a pre-filter, and
    the first rows are prepared as a check before anything is submitted."""
    root = _batch_project(tmp_path, TIDIES)

    code, output = _agac(root, "run", "-a", BATCH_WORKFLOW, "--fresh")
    output = _unwrapped(output)

    assert code != 0, output
    assert "run again" not in output, "a batch went to the provider past a guard with no answer"
    assert f"Guard UDF '{GUARD}' wrote to its input" in output


def test_a_batch_row_past_that_check_whose_guard_writes_fails_alone(tmp_path):
    """Preparing the rows to submit fails a row on its own, whatever stops it, so this
    one record is failed, naming the guard, and the rest are submitted and answered."""
    root = _batch_project(tmp_path, TIDIES_WHEN_UNTIDY)

    _cycle(root, "run", "-a", BATCH_WORKFLOW, "--fresh")

    backend = _store(root, BATCH_WORKFLOW)
    try:
        dispositions = {row["record_id"]: row for row in backend.get_disposition("summarize")}
        rows = _rows(backend, "summarize")
    finally:
        backend.close()
    outcome = {
        row["content"]["source"]["page_content"]: dispositions[row["source_guid"]] for row in rows
    }
    assert outcome["keep"]["disposition"] == "success"
    assert outcome[" Reject "]["disposition"] == "failed"
    assert f"Guard UDF '{GUARD}' wrote to its input" in outcome[" Reject "]["reason"]
