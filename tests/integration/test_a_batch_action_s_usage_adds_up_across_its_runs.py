"""A batch action's token usage is the sum over the runs that submit and collect it.

Against the mock provider, through the CLI: one run submits the main batch, the next reads
it and sends the judge batch, the last reads that and writes the file. Each run that read a
batch reports what the batch used in `artefact/runs.json`, and `agac usage` adds the runs up,
with the judge batch as `judge` calls at the batch price.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.cli.exit_codes import EXIT_PAUSED
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
        result = run_agac(project, "run", "-a", WORKFLOW, *args)
        output = result.stdout + result.stderr
        if result.returncode == EXIT_PAUSED:
            assert "run again" in output, output
            continue
        assert result.returncode == 0, output
        assert "run again" not in output, output
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


def _usage(project: Path, *args: str):
    return run_agac(project, "usage", "-w", WORKFLOW, *args, env={"COLUMNS": "200"})


def _report(project: Path, *args: str) -> dict:
    result = _usage(project, "--json", *args)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _with_prices(finished: Path, tmp_path: Path, prices: str) -> Path:
    """A copy of the finished project whose agent_actions.yml holds *prices*."""
    project = tmp_path / "project"
    shutil.copytree(finished, project)
    with open(project / "agent_actions.yml", "a") as config:
        config.write(prices)
    return project


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


def test_usage_adds_up_the_runs_that_collected_the_action_s_batches(finished):
    _submit, read_main, read_judge = _runs(finished)

    report = _report(finished)

    assert report["workflow"] == WORKFLOW
    assert report["runs"] == sorted([read_main["id"], read_judge["id"]])
    summarize = report["actions"]["summarize"]
    assert summarize["calls"] == RECORDS + RECORDS * VOTES
    for key in USAGE_KEYS:
        assert summarize[key] == read_main["usage"][key] + read_judge["usage"][key]
        assert report["total"][key] == summarize[key]
    assert [(row["kind"], row["batch"], row["calls"]) for row in summarize["by_kind"]] == [
        ("main", True, RECORDS),
        ("judge", True, RECORDS * VOTES),
    ]


def test_one_run_s_usage_is_shown_by_its_id(finished):
    _submit, _read_main, read_judge = _runs(finished)

    report = _report(finished, "--run", read_judge["id"])

    assert report["runs"] == [read_judge["id"]]
    assert [row["kind"] for row in report["actions"]["summarize"]["by_kind"]] == ["judge"]
    assert report["total"]["calls"] == RECORDS * VOTES


def test_a_run_that_used_nothing_is_refused_with_the_runs_that_did(finished):
    submit, read_main, read_judge = _runs(finished)

    result = _usage(finished, "--run", submit["id"])

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert f"No usage is recorded for run '{submit['id']}'" in output
    assert read_main["id"] in output and read_judge["id"] in output


def test_with_no_price_table_the_table_shows_tokens_and_says_how_to_add_prices(finished):
    result = _usage(finished)

    assert result.returncode == 0, result.stdout + result.stderr
    table = result.stdout
    assert "Usage: usage_in_batch (2 runs)" in table
    for heading in ("Action", "Kind", "Pricing", "Calls", "Input", "Cache read", "Output"):
        assert heading in table
    assert "Est. cost" not in table
    assert "summarize" in table and "judge" in table and "batch" in table and "Total" in table
    assert "agent_actions.yml has no prices: block" in table
    assert f"prices.{MODEL}" in table


def test_with_no_price_table_the_json_report_has_no_cost(finished):
    report = _report(finished)

    assert report["priced"] is False
    assert report["total"]["estimated_cost"] is None
    assert report["unpriced"] == [f"prices.{MODEL}"]


def test_a_price_table_adds_an_estimated_cost(finished, tmp_path):
    project = _with_prices(
        finished,
        tmp_path,
        f'prices:\n  "{MODEL}": {{input: 2.0, output: 10.0, batch_discount: 0.5}}\n',
    )

    report = _report(project)
    table = _usage(project).stdout

    total = report["total"]
    expected = (total["input_tokens"] * 2.0 + total["output_tokens"] * 10.0) / 1_000_000 * 0.5
    assert total["estimated_cost"] == pytest.approx(expected)
    assert report["actions"]["summarize"]["estimated_cost"] == pytest.approx(expected)
    assert all(
        row["estimated_cost"] is not None for row in report["actions"]["summarize"]["by_kind"]
    )
    assert (report["priced"], report["unpriced"]) == (True, [])
    assert "Est. cost" in table
    assert "is an estimate from the prices: block" in table
    assert f"{expected:,.4f}" in table


def test_a_model_the_price_table_lacks_shows_no_cost_and_is_named(finished, tmp_path):
    project = _with_prices(
        finished, tmp_path, "prices:\n  another-model: {input: 2.0, output: 10.0}\n"
    )

    report = _report(project)
    table = _usage(project).stdout

    assert report["priced"] is True
    assert report["total"]["estimated_cost"] is None
    assert report["unpriced"] == [f"prices.{MODEL}"]
    assert f"No cost for the calls that need: prices.{MODEL}" in table
    assert "0.0000" not in table, "an unknown cost was shown as zero"


def test_a_batch_call_of_a_model_with_no_batch_discount_shows_no_cost(finished, tmp_path):
    project = _with_prices(
        finished, tmp_path, f'prices:\n  "{MODEL}": {{input: 2.0, output: 10.0}}\n'
    )

    report = _report(project)

    assert report["total"]["estimated_cost"] is None
    assert report["unpriced"] == [f"prices.{MODEL}.batch_discount"]


def test_a_mistake_in_the_price_table_is_refused_by_its_key(finished, tmp_path):
    project = _with_prices(finished, tmp_path, f'prices:\n  "{MODEL}": {{input: cheap}}\n')

    result = _usage(project)

    assert result.returncode != 0
    shown = result.stdout + result.stderr
    assert f"prices.{MODEL}.input: must be a number, 0 or more" in shown
    assert "Invalid configuration in agent_actions.yml" in shown
    assert "Agent:" not in shown
