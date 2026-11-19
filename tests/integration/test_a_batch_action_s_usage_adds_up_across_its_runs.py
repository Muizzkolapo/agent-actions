"""A batch action's token usage is the sum over the runs that submit and collect it.

Against the mock provider, through the CLI: one run submits the main batch, the next reads
it and sends the judge batch, the last reads that and writes the file. Each run that read a
batch reports what the batch used in `artefact/runs.json`, with the judge batch as `judge`
calls at the batch price.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "usage_in_batch"
MODEL = "gpt-oss:120b-cloud"
VOTES = 3
RECORDS = 2

_CONFIG = f"""\
name: {WORKFLOW}
description: "A judged rule on a batch action"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: batch
  model_vendor: agac-provider
  model_name: {MODEL}
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    intent: "Summarise"
    schema: usage_in_batch_summary
    prompt: $usage_in_batch.Summarize
    context_scope: {{ observe: [source.page_content] }}
    expect:
      repair: none
      expectations:
        - id: grounded
          type: llm_judge
          field: summary
          params: {{ rule: "The summary only states what the page says.", votes: {VOTES} }}
"""

_SUMMARY = """\
name: usage_in_batch_summary
fields:
  - id: summary
    type: string
additionalProperties: true
"""

_PROMPTS = """\
{prompt Summarize}
Summarise this.
## PAGE
{{ source.page_content }}
{end_prompt}
"""

USAGE_KEYS = [
    "calls",
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_CONFIG)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps(
            [{"page_id": f"p{i}", "page_content": f"page {i}"} for i in range(1, RECORDS + 1)]
        )
    )
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "usage_in_batch_summary.yml").write_text(_SUMMARY)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run_to_the_end(project: Path) -> int:
    for attempt in range(8):
        args = ("--fresh",) if attempt == 0 else ()
        result = run_agac(
            project, "run", "-a", WORKFLOW, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        if "run again" not in output:
            return attempt + 1
    pytest.fail(f"the workflow never stopped asking to be run again:\n{output}")


@pytest.fixture(scope="module")
def finished(tmp_path_factory) -> Path:
    project = _project(tmp_path_factory.mktemp("usage_in_batch"))
    assert _run_to_the_end(project) == 3, "a run to submit, one for the judge batch, one to finish"
    return project


def _runs(project: Path) -> list[dict]:
    history = json.loads((project / "artefact" / "runs.json").read_text())
    return list(reversed(history["executions"]))


def test_the_run_history_shows_the_tokens_of_the_batches_each_run_read(finished):
    submit, read_main, read_judge = _runs(finished)

    assert submit["total_tokens"] == 0, "the run that only submits reads no result"
    assert submit["usage"] == dict.fromkeys(USAGE_KEYS, 0)
    assert read_main["total_tokens"] > 0
    assert read_judge["total_tokens"] > 0
    for run in (read_main, read_judge):
        usage = run["actions"]["summarize"]["usage"]
        assert run["usage"] == {key: usage[key] for key in USAGE_KEYS}
        assert run["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
        assert run["actions"]["summarize"]["tokens"]["total_tokens"] == run["total_tokens"]


def test_each_run_s_entry_names_the_kind_of_call_and_that_it_was_a_batch(finished):
    _submit, read_main, read_judge = _runs(finished)

    (main,) = read_main["actions"]["summarize"]["usage"]["by_kind"]
    (judge,) = read_judge["actions"]["summarize"]["usage"]["by_kind"]
    assert (main["kind"], main["batch"], main["model"], main["calls"]) == (
        "main",
        True,
        MODEL,
        RECORDS,
    )
    assert (judge["kind"], judge["batch"], judge["model"], judge["calls"]) == (
        "judge",
        True,
        MODEL,
        RECORDS * VOTES,
    )
