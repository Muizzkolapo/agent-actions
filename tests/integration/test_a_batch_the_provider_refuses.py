"""A batch the provider refuses leaves the action as if the file had not been sent.

Nothing will come back for a refused file. What the store records as sent must still
describe the batch the registry names, since collecting that batch reads it. And the
action must not complete on the batches of its other files as if this one were among
them: completed, it is not run again, and the file's records are never answered.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from tests.integration.test_a_collect_pass_leaves_collected_files_alone import (
    _Action,
    _Provider,
)
from tests.integration.test_batch_rerun_matches_online import ACTION, rec

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "batch_field_rules"
CLI_ACTION = "summarize"


class _RefusingProvider(_Provider):
    """Takes every batch until told to refuse, as a provider over its quota does."""

    def __init__(self) -> None:
        super().__init__()
        self.refusing = False

    def submit_batch(self, tasks, batch_name, output_directory):
        if self.refusing:
            raise ConnectionError("the provider refused the batch")
        return super().submit_batch(tasks, batch_name, output_directory)


def _recorded_as_sent(action: _Action, name: str) -> tuple[Any, Any]:
    return (
        BatchContextManager.load_batch_context_map(action.backend, ACTION, name),
        BatchContextManager.load_batch_inputs(action.backend, ACTION, name),
    )


def test_a_refused_batch_leaves_the_record_of_the_batch_the_registry_names(tmp_path):
    action = _Action(tmp_path)
    action.provider = _RefusingProvider()
    action.run({"page1.json": [rec("a1", keep=True)]})
    before = _recorded_as_sent(action, "page1.json")

    # a2 arrives and is sent; the provider will not take it.
    files = {"page1.json": [rec("a1", keep=True), rec("a2", keep=True)]}
    action.upstream_holds(files)
    action.provider.refusing = True
    with pytest.raises(AgentActionsError, match="Failed to submit batch job"):
        action.process("page1.json", files["page1.json"])

    entry = BatchRegistryManager(action.backend, ACTION).get_batch_job("page1.json")
    assert entry is not None and entry.batch_id == "batch-1"
    assert _recorded_as_sent(action, "page1.json") == before, (
        "the store describes a batch the provider never took, beside a registry naming "
        "the one before it"
    )


# `agac`, with three faults a provider can have, each switched on per run. The agac
# provider has none of its own; these stand in for them in the process that meets them.
_AGAC_WITH_FAULTS = """
import json, os, sys
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

refuse = os.environ.get("REFUSE")
if refuse:
    submit = AgacBatchClient._submit_to_provider_api
    def refusing(self, input_file, batch_name):
        if batch_name == refuse:
            raise ConnectionError(f"the provider refused {batch_name}")
        return submit(self, input_file, batch_name)
    AgacBatchClient._submit_to_provider_api = refusing

fail = os.environ.get("FAIL")
if fail:
    fetch = AgacBatchClient._fetch_raw_results
    def failing(self, batch_id):
        lines = fetch(self, batch_id).decode().splitlines()
        tasks = {t["custom_id"]: t for t in self._tasks_by_batch.get(batch_id, [])}
        results = [json.loads(line) for line in lines]
        for result in results:
            if fail in json.dumps(tasks.get(result["custom_id"])):
                result["response"] = {"status_code": 500, "body": {}}
                result["error"] = {"message": "the provider failed it"}
        return "\\n".join(json.dumps(result) for result in results).encode()
    AgacBatchClient._fetch_raw_results = failing

stop_at = os.environ.get("STOP_AT")
if stop_at:
    collect = BatchProcessingService._process_single_batch_file
    def stopping(self, *args, **kwargs):
        if kwargs.get("file_name") == stop_at:
            raise RuntimeError(f"the collect pass was stopped at {stop_at}")
        return collect(self, *args, **kwargs)
    BatchProcessingService._process_single_batch_file = stopping

from agent_actions.cli.main import main
sys.argv[0] = "agac"
sys.exit(main())
"""


def _project(root: Path) -> Path:
    """The fixture project on the agac provider, staging a_pages.json and b_pages.json."""
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    for config in root.glob("agent_workflow/*/agent_config/*.yml"):
        config.write_text(
            config.read_text().replace("model_vendor: ollama_cloud", "model_vendor: agac-provider")
        )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\nOPENAI_API_KEY=sk-not-used\n")
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    for stale in staging.glob("*.json"):
        stale.unlink()
    for prefix in ("a", "b"):
        pages = [{"page_id": f"{prefix}{n}", "page_content": f"Page {prefix}{n}."} for n in (1, 2)]
        (staging / f"{prefix}_pages.json").write_text(json.dumps(pages))
    return root


def _agac(project: Path, *args: str, **faults: str) -> SimpleNamespace:
    """One `agac run`, in its own process, with *faults* switched on for it."""
    result = subprocess.run(
        [sys.executable, "-c", _AGAC_WITH_FAULTS, "run", "-a", WORKFLOW, "-u", "tools", *args],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
        env={
            **os.environ,
            "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0",
            # The checkout under test, not whichever one the interpreter has installed.
            "PYTHONPATH": str(REPO),
            **faults,
        },
    )
    io_dir = project / "agent_workflow" / WORKFLOW / "agent_io"
    status = json.loads((io_dir / ".agent_status.json").read_text())[CLI_ACTION]["status"]
    return SimpleNamespace(
        code=result.returncode, output=result.stdout + result.stderr, status=status
    )


def _store(project: Path) -> sqlite3.Connection:
    store = project / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    return sqlite3.connect(f"file:{sorted(store.glob('*.db'))[0]}?mode=ro", uri=True)


def _answered(project: Path) -> dict[str, list[str]]:
    """Each stored file, with the page of every row answered for one."""
    con = _store(project)
    try:
        stored = con.execute(
            "select relative_path, data from target_data where action_name = ?", (CLI_ACTION,)
        ).fetchall()
    finally:
        con.close()
    answered = {}
    for path, data in stored:
        rows = json.loads(data)
        answered[path] = sorted(
            str(((row.get("content") or {}).get("source") or {}).get("page_id"))
            for row in (rows if isinstance(rows, list) else [rows])
            if row.get("_state") == "processed"
        )
    return answered


EVERY_PAGE = {"a_pages.json": ["a1", "a2"], "b_pages.json": ["b1", "b2"]}


class TestAFileRefusedBesideOneThatIsSent:
    """A first run: the provider takes b_pages.json and refuses a_pages.json."""

    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _project(tmp_path_factory.mktemp("refused") / "project")
        refused = _agac(project, "--fresh", REFUSE="a_pages.json")
        then = [_agac(project), _agac(project)]
        return SimpleNamespace(project=project, refused=refused, then=then)

    def test_the_run_fails_rather_than_waiting_on_the_batch_beside_it(self, runs):
        assert runs.refused.code != 0, runs.refused.output
        assert runs.refused.status == "failed"

    def test_the_runs_after_it_answer_every_record_of_both_files(self, runs):
        assert [run.code for run in runs.then] == [0, 0], runs.then[-1].output
        assert runs.then[-1].status == "completed"
        assert _answered(runs.project) == EVERY_PAGE


class TestARefusedResendOverACollectedFile:
    """The sequence the issue was found with, one process per step.

    a_pages.json is collected with a1 failed; the collect pass stops before b_pages.json.
    The run after resends a1, and the provider refuses it while b_pages.json's batch is
    still owed.
    """

    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _project(tmp_path_factory.mktemp("resend") / "project")
        submitted = _agac(project, "--fresh")
        stopped = _agac(project, FAIL="Page a1.", STOP_AT="b_pages.json")
        assert (submitted.status, stopped.status) == ("batch_submitted", "failed"), stopped.output
        refused = _agac(project, REFUSE="a_pages.json")
        then = [_agac(project), _agac(project)]
        return SimpleNamespace(project=project, refused=refused, then=then)

    def test_the_run_the_provider_refused_fails(self, runs):
        assert runs.refused.code != 0, runs.refused.output
        assert runs.refused.status == "failed"

    def test_every_record_ends_answered_under_its_own_page(self, runs):
        assert runs.then[-1].status == "completed", runs.then[-1].output
        assert _answered(runs.project) == EVERY_PAGE
