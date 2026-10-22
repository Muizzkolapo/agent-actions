"""A guard reads the seed data its action declares, as the action's prompt does (1525).

`build_guard_context` never added `seed`, so `seed.conf.mode == 'on'` named a field no
guard context held. The guard filtered every record and the run exited 0 in either run
mode. The guard context now carries the declared seed. A guard reading a seed key its
action does not declare is refused before the run, as a prompt reading one is, including
when no action declares any seed and the workflow has no seed directory.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.trace_store import trace_rows

WORKFLOW = "w"
PAGES = [
    {"page_id": "p1", "page_content": "two"},
    {"page_id": "p2", "page_content": "one"},
]

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
tool_path: ["tools"]
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "A guard on the action's seed data"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {mode}
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: produce
    kind: tool
    intent: "Produce"
    schema: fix1525_produce_out
    impl: fix1525_produce
    context_scope: {{ observe: [source.page_content] }}
  - name: consumer
    intent: "Consume"
    dependencies: [produce]
    schema: fix1525_consumer_out
    prompt: $w.consumer
    context_scope:
      observe: [produce.*]
{seed}    guard: {{ condition: "{condition}", on_false: filter }}
"""

_PROMPT = """\
{{prompt consumer}}
Say {{{{ produce.severity }}}}{prompt_extra}
{{end_prompt}}
"""

_TOOL = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def fix1525_produce(data: Any, *args) -> list[dict]:
    return [{"severity": "high"}]
"""

_PRODUCE_SCHEMA = """\
name: fix1525_produce_out
fields:
  - id: severity
    type: string
"""

_CONSUMER_SCHEMA = """\
name: fix1525_consumer_out
fields:
  - id: summary
    type: string
"""


_FILE_CONSUMER = """\
  - name: consumer
    kind: tool
    granularity: File
    intent: "Keep"
    dependencies: [produce]
    schema: fix1525_produce_out
    impl: fix1525_keep
    context_scope:
      observe: [produce.severity]
{seed}    guard: {{ condition: "{condition}", on_false: filter }}
"""

_FILE_TOOL = """\
from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import FileUDFResult, Granularity


@udf_tool(granularity=Granularity.FILE)
def fix1525_keep(data: Any, *args) -> Any:
    return FileUDFResult(
        [{"source_index": i, "data": {"severity": "kept"}} for i in range(len(data))]
    )
"""


def _project(
    tmp_path: Path,
    condition: str,
    mode: str = "online",
    declared: str | None = "conf",
    prompt_extra: str = "",
    file_tool: bool = False,
) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    seed = f"      seed: {{ {declared}: $file:conf.json }}\n" if declared else ""
    text = _WORKFLOW.format(mode=mode, condition=condition, seed=seed)
    if file_tool:
        text = text[: text.index("  - name: consumer")] + _FILE_CONSUMER.format(
            condition=condition, seed=seed
        )
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(text)
    if declared:
        (workflow / "seed_data").mkdir()
        (workflow / "seed_data" / "conf.json").write_text(json.dumps({"mode": "on"}))
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPT.format(prompt_extra=prompt_extra))
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "fix1525_produce_out.yml").write_text(_PRODUCE_SCHEMA)
    (root / "schema" / WORKFLOW / "fix1525_consumer_out.yml").write_text(_CONSUMER_SCHEMA)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW / "fix1525_produce.py").write_text(_TOOL)
    if file_tool:
        (root / "tools" / WORKFLOW / "fix1525_keep.py").write_text(_FILE_TOOL)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run_to_the_end(project: Path) -> str:
    outputs = []
    args = ["run", "-a", WORKFLOW, "--fresh"]
    for _ in range(4):
        result = run_agac(project, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"})
        output = result.stdout + result.stderr
        outputs.append(output)
        assert result.returncode == 0, "\n".join(outputs)
        if "run again" not in output:
            return "\n".join(outputs)
        args = ["run", "-a", WORKFLOW]
    pytest.fail("the workflow never stopped asking to be run again:\n" + "\n".join(outputs))


def _consumer_dispositions(project: Path) -> list[str]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select disposition from record_disposition where action_name = 'consumer'"
        )
        return sorted(disposition for (disposition,) in rows)
    finally:
        con.close()


def _refused(project: Path) -> str:
    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    store = project / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    if store.exists() and list(store.glob("*.db")):
        assert _consumer_dispositions(project) == [], output
    return output


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize(
    ("condition", "passed"),
    [
        ("seed.conf.mode == 'on'", ["success", "success"]),
        ("seed.conf.mode == 'off'", []),
        ("seed.conf.mode == 'on' and source.page_content == 'two'", ["success"]),
    ],
)
def test_a_guard_reads_the_seed_its_action_declares(tmp_path, mode, condition, passed):
    project = _project(tmp_path, condition, mode)

    _run_to_the_end(project)

    assert [d for d in _consumer_dispositions(project) if d == "success"] == passed


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize(
    ("condition", "passed"),
    [("seed.conf.mode == 'on'", ["success", "success"]), ("seed.conf.mode == 'off'", [])],
)
def test_a_file_tool_guard_reads_the_seed_its_action_declares(tmp_path, mode, condition, passed):
    project = _project(tmp_path, condition, mode, file_tool=True)

    _run_to_the_end(project)

    assert [d for d in _consumer_dispositions(project) if d == "success"] == passed


def test_the_prompt_still_reads_the_seed_beside_a_guard_reading_it(tmp_path):
    """The prompt and the guard read one load of the seed; the prompt still renders it."""
    project = _project(tmp_path, "seed.conf.mode == 'on'", prompt_extra=" in {{ seed.conf.mode }}")

    _run_to_the_end(project)

    prompts = [
        p for (p,) in trace_rows(project, "select compiled_prompt from prompt_trace") if "Say " in p
    ]
    assert prompts == ["Say high in on", "Say high in on"], prompts


def test_a_guard_reading_an_undeclared_seed_key_is_refused(tmp_path):
    project = _project(tmp_path, "seed.other.mode == 'on'")

    output = _refused(project)

    assert "references seed.other but 'other' is not declared in context_scope.seed" in output


def test_a_guard_reading_seed_with_none_declared_anywhere_is_refused(tmp_path):
    """No action declares a seed, and there is no seed directory to load one from."""
    project = _project(tmp_path, "seed.conf.mode == 'on'", declared=None)

    output = _refused(project)

    assert "references seed.conf but 'conf' is not declared in context_scope.seed" in output
    assert "Location: guard" in output, output


def test_a_prompt_reading_seed_with_none_declared_anywhere_is_refused(tmp_path):
    project = _project(
        tmp_path, "source.page_content != ''", declared=None, prompt_extra=" {{ seed.conf.mode }}"
    )

    output = _refused(project)

    assert "references seed.conf but 'conf' is not declared in context_scope.seed" in output
    assert "Location: prompt" in output, output


def _parses_in_process(project: Path, monkeypatch) -> int:
    """Run the workflow to the end in this process, counting each seed file parse."""
    from click.testing import CliRunner

    from agent_actions.cli.main import cli
    from agent_actions.prompt.context.static_loader import StaticDataLoader
    from agent_actions.utils.path_utils import reset_path_manager

    parses = []
    real = StaticDataLoader._load_file

    def counting(self, file_path, field_name):
        parses.append(field_name)
        return real(self, file_path, field_name)

    monkeypatch.setattr(StaticDataLoader, "_load_file", counting)
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    monkeypatch.chdir(project)
    reset_path_manager()
    args = ["run", "-a", WORKFLOW, "--fresh"]
    try:
        for _ in range(4):
            result = CliRunner().invoke(cli, args, catch_exceptions=False)
            assert result.exit_code == 0, result.output
            if "run again" not in result.output:
                break
            args = ["run", "-a", WORKFLOW]
    finally:
        reset_path_manager()
    return len(parses)


# What the prompt alone parses for two records, measured on the code before guards read
# seed: one per record online; batch also renders the first record to check it.
PROMPT_PARSES = {"online": 2, "batch": 3}


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize(
    ("condition", "guard_parses"),
    [
        # A guard that does not read seed parses nothing.
        ("source.page_content != ''", 0),
        # One that does parses each file once for the process, not once per record.
        ("seed.conf.mode == 'on'", 1),
    ],
)
def test_a_guard_adds_at_most_one_seed_parse(tmp_path, monkeypatch, mode, condition, guard_parses):
    project = _project(tmp_path, condition, mode, prompt_extra=" in {{ seed.conf.mode }}")

    assert _parses_in_process(project, monkeypatch) == PROMPT_PARSES[mode] + guard_parses


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize(
    ("condition", "parses"), [("source.page_content != ''", 0), ("seed.conf.mode == 'on'", 1)]
)
def test_a_file_tool_guard_parses_seed_once_at_most(tmp_path, monkeypatch, mode, condition, parses):
    project = _project(tmp_path, condition, mode, file_tool=True)

    assert _parses_in_process(project, monkeypatch) == parses
