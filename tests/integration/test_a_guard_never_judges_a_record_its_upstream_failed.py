"""A record an action above failed is quarantined, never put to a guard (1347).

Online, an action's guard judged each record before the cascade filter quarantined the
ones an action above had failed. A guard reading that action's fields is false for such
a record, since they are null. Under `on_false: skip` the record was written as a
`guard_skipped` tombstone with a `passthrough` disposition, a state that blocks nothing:
every action below sent it to the model and stored the answer as a success, built on an
upstream answer that does not exist, and read `completed`. Under `on_false: filter` it
was `filtered` and gone from everything below. Batch preparation checks the record's
state before its guard, and stores it `cascade_skipped` and `unprocessed` at every action
below the failure; its cases pin that the two modes agree.

Three actions: `summarize` fails page alpha, `publish` has a guard false wherever
`summarize` answered nothing, and `archive` reads `publish`. Every command is a real
`agac run` or `agac retry` in its own process. Only the fault is stood in for: while a
flag file exists, the model fails `summarize`'s request for page alpha, online by
raising and in a batch with an error row. The same stand-in logs every request.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "upstream_failed"
ALPHA = "Page alpha."
PAGES = {
    "pages1.json": [ALPHA, "Page beta."],
    "pages2.json": ["Page gamma.", "Page delta."],
}
FLAG = "alpha_fails"
REQUESTS = "requests.jsonl"
BELOW = ("publish", "archive")
# Each action's prompt says which action a request is for, online and in a batch alike.
SUMMARIZE_PROMPT = "Summarise the page"
PROMPT_OF = {
    "summarize": SUMMARIZE_PROMPT,
    "publish": "Restate this summary verbatim",
    "archive": "Archive this page",
}

_STAND_IN = f"""
import json
from pathlib import Path

from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.llm.providers.agac.client import AgacClient


def _failing(prompt):
    return Path({FLAG!r}).exists() and {SUMMARIZE_PROMPT!r} in prompt and {ALPHA!r} in prompt


def _log(prompt, content):
    with Path({REQUESTS!r}).open("a") as log:
        log.write(json.dumps({{"prompt": prompt, "content": content}}) + "\\n")


call_json = AgacClient.call_json


def answering(api_key, agent_config, prompt_config, context_data, schema):
    _log(str(prompt_config), json.dumps(context_data, default=str))
    if _failing(str(prompt_config)):
        raise RuntimeError("the model failed page alpha")
    return call_json(api_key, agent_config, prompt_config, context_data, schema)


AgacClient.call_json = staticmethod(answering)

submit = AgacBatchClient._submit_to_provider_api


def submitting(self, input_file, batch_name):
    for line in Path(input_file).read_text().splitlines():
        if line.strip():
            task = json.loads(line)
            _log(str(task.get("prompt")), json.dumps(task.get("user_content"), default=str))
    return submit(self, input_file, batch_name)


AgacBatchClient._submit_to_provider_api = submitting

fetch = AgacBatchClient._fetch_raw_results


def fetching(self, batch_id):
    prompts = {{
        task["custom_id"]: str(task.get("prompt"))
        for task in self._tasks_by_batch.get(batch_id, [])
    }}
    results = [json.loads(line) for line in fetch(self, batch_id).decode().splitlines()]
    for result in results:
        if _failing(prompts.get(result["custom_id"], "")):
            result["response"] = {{"status_code": 500, "body": {{}}}}
            result["error"] = {{"message": "the model failed page alpha"}}
    return "\\n".join(json.dumps(result) for result in results).encode()


AgacBatchClient._fetch_raw_results = fetching
"""

_SCHEMA = """\
name: upstream_failed_page
fields:
  - id: summary
    type: string
  - id: exam_density
    type: string
additionalProperties: true
"""

_PROMPTS = """\
{prompt Archive}
Archive this page.
## PAGE
{{ source.page_content }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""

ROLL_UP_TOOL = """from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import Granularity


@udf_tool(granularity=Granularity.FILE)
def roll_up_pages(data: Any, *args):
    for record in data:
        record["summary"] = "rolled " + str(record.get("summary"))
        record["exam_density"] = "low"
    return data
"""

LLM_PUBLISH = """\
    prompt: $p.Publish
    context_scope: { observe: [summarize.summary, source.page_content] }
"""
FILE_TOOL_PUBLISH = """\
    kind: tool
    granularity: File
    run_mode: online
    impl: roll_up_pages
    context_scope: { observe: [summarize.summary, source.page_content] }
"""


def _config(run_mode: str, publish: str, on_false: str) -> str:
    return f"""\
name: {WORKFLOW}
description: "A guard below an action that fails a record"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    intent: "Summarise"
    schema: upstream_failed_page
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
  - name: publish
    dependencies: [summarize]
    intent: "Publish"
    schema: upstream_failed_page
{publish}    guard: {{ condition: "summarize.summary != null", on_false: {on_false} }}
  - name: archive
    dependencies: [publish]
    intent: "Archive"
    schema: upstream_failed_page
    prompt: ${WORKFLOW}.Archive
    context_scope: {{ observe: [publish.summary, source.page_content] }}
"""


class Project:
    def __init__(self, base: Path, run_mode: str, publish: str, on_false: str) -> None:
        self.root = base / "project"
        shutil.copytree(FIXTURE, self.root, ignore=shutil.ignore_patterns("logs"))
        workflow = self.root / "agent_workflow" / WORKFLOW
        (workflow / "agent_config").mkdir(parents=True)
        (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
            _config(run_mode, publish, on_false)
        )
        staging = workflow / "agent_io" / "staging"
        staging.mkdir(parents=True)
        for name, pages in PAGES.items():
            (staging / name).write_text(
                json.dumps(
                    [{"page_id": f"p{n}", "page_content": page} for n, page in enumerate(pages)]
                )
            )
        (self.root / "schema" / WORKFLOW).mkdir()
        (self.root / "schema" / WORKFLOW / "upstream_failed_page.yml").write_text(_SCHEMA)
        (self.root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
        (self.root / "tools" / WORKFLOW).mkdir()
        (self.root / "tools" / WORKFLOW / "roll_up.py").write_text(ROLL_UP_TOOL)
        (self.root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
        self.stand_in = base / "stand_in"
        self.stand_in.mkdir()
        (self.stand_in / "sitecustomize.py").write_text(_STAND_IN)

    def agac(self, *args: str) -> str:
        result = run_agac(
            self.root,
            *args,
            env={
                "PYTHONPATH": str(self.stand_in),
                "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0",
                "COLUMNS": "240",
            },
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        return output

    def run_to_the_end(self, *args: str) -> None:
        """`agac run` until nothing is in flight: once online, a run per batch level."""
        output = self.agac("run", "-a", WORKFLOW, "-u", "tools", *args)
        for _ in range(6):
            if "run again" not in output:
                return
            output = self.agac("run", "-a", WORKFLOW, "-u", "tools")
        pytest.fail(f"the workflow never stopped asking to be run again:\n{output}")

    def retry_to_the_end(self) -> None:
        output = self.agac("retry", "-a", WORKFLOW)
        if "run again" in output:
            self.run_to_the_end()

    def alpha_fails(self, on: bool = True) -> None:
        flag = self.root / FLAG
        if on:
            flag.write_text("")
        else:
            flag.unlink()

    def _query(self, sql: str, *params: str) -> list[tuple]:
        (db,) = (self.root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()

    def dispositions(self, action: str) -> dict[str, tuple[str, str | None]]:
        return {
            record: (disposition, reason)
            for record, disposition, reason in self._query(
                "select record_id, disposition, reason from record_disposition "
                "where action_name = ? and record_id != '__node__'",
                action,
            )
        }

    def states(self, action: str) -> dict[str, str]:
        states: dict[str, str] = {}
        for (blob,) in self._query("select data from target_data where action_name = ?", action):
            loaded = json.loads(blob)
            for row in loaded if isinstance(loaded, list) else [loaded]:
                states[row["source_guid"]] = row.get("_state")
        return states

    def alpha(self) -> str:
        """Page alpha's source_guid: the one record `summarize` failed."""
        (guid,) = [
            record
            for record, (disposition, _reason) in self.dispositions("summarize").items()
            if disposition == "failed"
        ]
        return guid

    def statuses(self) -> dict[str, str]:
        path = self.root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
        return {action: entry["status"] for action, entry in json.loads(path.read_text()).items()}

    def sent_for_alpha(self) -> list[str]:
        """The action of each request that carried page alpha."""
        path = self.root / REQUESTS
        requests = (
            [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        )
        return [
            action
            for request in requests
            if ALPHA in request["prompt"] or ALPHA in request["content"]
            for action, marker in PROMPT_OF.items()
            if marker in request["prompt"]
        ]


def _after_alpha_failed(tmp_path: Path, run_mode: str, publish: str, on_false: str) -> Project:
    project = Project(tmp_path, run_mode, publish, on_false)
    project.alpha_fails()
    project.run_to_the_end("--fresh")
    return project


MODES = ["online", "batch"]


@pytest.mark.parametrize("run_mode", MODES)
def test_a_skip_guard_below_the_failure_leaves_it_to_the_quarantine(tmp_path, run_mode):
    project = _after_alpha_failed(tmp_path, run_mode, LLM_PUBLISH, "skip")
    alpha = project.alpha()

    for action in BELOW:
        assert project.states(action)[alpha] == "cascade_skipped", action
        assert project.dispositions(action)[alpha] == ("unprocessed", "upstream_unprocessed"), (
            action
        )
    assert project.statuses() == {
        "summarize": "completed_with_failures",
        "publish": "completed",
        "archive": "completed",
    }


@pytest.mark.parametrize("run_mode", MODES)
def test_nothing_is_sent_for_it_below_the_failure(tmp_path, run_mode):
    project = _after_alpha_failed(tmp_path, run_mode, LLM_PUBLISH, "skip")

    assert "summarize" in project.sent_for_alpha(), "the fault stand-in saw no request"
    assert [action for action in project.sent_for_alpha() if action in BELOW] == []


@pytest.mark.parametrize("run_mode", MODES)
def test_the_retry_answers_it_at_every_action(tmp_path, run_mode):
    project = _after_alpha_failed(tmp_path, run_mode, LLM_PUBLISH, "skip")
    alpha = project.alpha()
    project.alpha_fails(on=False)

    project.retry_to_the_end()

    for action in ("summarize", *BELOW):
        assert project.states(action)[alpha] == "processed", action
        assert project.dispositions(action)[alpha] == ("success", None), action
    assert set(project.statuses().values()) == {"completed"}


@pytest.mark.parametrize("run_mode", MODES)
def test_a_filter_guard_below_the_failure_does_not_remove_it(tmp_path, run_mode):
    """Filtered, the record left every action below with nothing saying it failed."""
    project = _after_alpha_failed(tmp_path, run_mode, LLM_PUBLISH, "filter")
    alpha = project.alpha()

    for action in BELOW:
        assert project.states(action).get(alpha) == "cascade_skipped", action
        assert project.dispositions(action)[alpha] == ("unprocessed", "upstream_unprocessed"), (
            action
        )


def test_a_file_tool_guard_below_the_failure_leaves_it_to_the_quarantine(tmp_path):
    """A FILE tool's guard reads the record as stored, paired by position with what the
    tool is handed; the record it does not judge leaves both lists in step."""
    project = _after_alpha_failed(tmp_path, "online", FILE_TOOL_PUBLISH, "skip")
    alpha = project.alpha()

    for action in BELOW:
        assert project.states(action)[alpha] == "cascade_skipped", action
        assert project.dispositions(action)[alpha] == ("unprocessed", "upstream_unprocessed"), (
            action
        )
    assert "archive" not in project.sent_for_alpha()
    others = set(project.states("publish")) - {alpha}
    assert {project.states("publish")[guid] for guid in others} == {"processed"}

    project.alpha_fails(on=False)
    project.retry_to_the_end()

    for action in ("summarize", *BELOW):
        assert project.dispositions(action)[alpha] == ("success", None), action
