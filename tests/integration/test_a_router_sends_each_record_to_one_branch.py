"""A `- route:` entry sends each record to the branch of its case; `- join:` gathers them.

`route_focus`, a tool, writes each record's format. The router `format_router` reads it:
`multi_choice` and `fill_blank` enter one LLM action each, `matching` enters an include
instance `m` of two actions, and any other value enters the default branch. `bank` joins
the last action of every branch. Each claim holds in both run modes: the LLM actions run
against the provider mock under `run_mode: online` and `run_mode: batch`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_actions.cli.exit_codes import EXIT_PAUSED
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

WORKFLOW = "router_flow"
RUN_MODES = pytest.mark.parametrize("run_mode", ["online", "batch"])
ENV = {"OPENAI_API_KEY": "sk-not-used"}
FORMATS = ["multi_choice", "matching", "fill_blank", "true_false"]

TOOLS = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def assign_format(data: Any, *args) -> dict:
    return {"format": data["source"]["format"]}


@udf_tool
def finalize_matching(data: Any, *args) -> dict:
    return {"pairs": "final " + str((data.get("write") or {}).get("draft"))}


@udf_tool
def publish_item(data: Any, *args) -> dict:
    return {"fields": ",".join(sorted((data.get("bank") or {}).keys()))}
"""


def _schema(name, field, enum=None):
    text = f"name: {name}\nfields:\n  - id: {field}\n    type: string\n"
    if enum:
        text += f"    enum: {json.dumps(enum)}\n"
    return text


PROMPTS = """\
{prompt Write}
Write one exam item about: {{ source.text }}
{end_prompt}
"""

BRANCH = """\
branch: format_branch
description: Draft one format, then finalize it
outputs: [finalize]
actions:
  - name: write
    intent: Draft
    prompt: $router_flow.Write
    schema: matching_draft
    context_scope: { observe: [source.text] }
  - name: finalize
    kind: tool
    impl: finalize_matching
    intent: Finalize
    schema: matching_item
    dependencies: [write]
    context_scope: { observe: [write.draft] }
"""

HEAD = """\
name: router_flow
description: "One router, four branches, one join"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: m
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: route_focus
    kind: tool
    impl: assign_format
    intent: Decide the format
    schema: route_focus_out
    context_scope: {{ observe: [source.format] }}
"""

ROUTER = """\
  - route: format_router
    on: route_focus.format
    cases:
      {first_case}: [mc_write]
      matching: m
      fill_blank: [fb_write]
    default: {default}
"""


def _llm(name, schema):
    return f"""\
  - name: {name}
    intent: Write
    prompt: $router_flow.Write
    schema: {schema}
    context_scope: {{ observe: [source.text] }}
"""


TAIL = """\
  - include: format_branch
    as: m
  - join: bank
    of: [{ends}]
  - name: publish
    kind: tool
    impl: publish_item
    intent: Publish
    schema: published
    dependencies: [bank]
    context_scope: {{ observe: [bank.*] }}
"""


def _config(run_mode, *, first_case="multi_choice", default="[other_write]", enum=FORMATS):
    ends = ["mc_write", "m", "fb_write"] + (["other_write"] if default != "filter" else [])
    return (
        HEAD.format(run_mode=run_mode)
        + ROUTER.format(first_case=first_case, default=default)
        + _llm("mc_write", "mc_item")
        + _llm("fb_write", "fb_item")
        + (_llm("other_write", "other_item") if default != "filter" else "")
        + TAIL.format(ends=", ".join(ends))
    )


def _project(base: Path, run_mode: str, formats: list[str], **config) -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    schemas = root / "schema" / WORKFLOW
    schemas.mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "branches").mkdir()
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\n"
        'tool_path: ["tools"]\n'
    )
    enum = config.pop("enum", FORMATS)
    for name, field in (
        ("mc_item", "question"),
        ("fb_item", "blank"),
        ("other_item", "statement"),
        ("matching_draft", "draft"),
        ("matching_item", "pairs"),
        ("published", "fields"),
    ):
        (schemas / f"{name}.yml").write_text(_schema(name, field))
    (schemas / "route_focus_out.yml").write_text(_schema("route_focus_out", "format", enum))
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    (root / "branches" / "format_branch.yml").write_text(BRANCH)
    (root / "tools" / WORKFLOW / "flow_tools.py").write_text(TOOLS)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _config(run_mode, enum=enum, **config)
    )
    (directory / "agent_io" / "staging" / "items.json").write_text(
        json.dumps([{"text": f"topic {i}", "format": f} for i, f in enumerate(formats)])
    )
    return root


def _agac(root: Path, *args: str) -> tuple[int, str]:
    result = run_agac(root, *args, "-a", WORKFLOW, env=ENV)
    return result.returncode, " ".join((result.stdout + result.stderr).split())


def _run_to_the_end(root: Path, *first: str) -> str:
    code, output = _agac(root, "run", *first)
    transcript = [output]
    while code == EXIT_PAUSED:
        assert "run again" in transcript[-1], transcript[-1]
        assert len(transcript) <= 8, "the workflow never stopped asking to be run again"
        code, output = _agac(root, "run")
        transcript.append(output)
    assert code == 0, transcript[-1]
    assert "run again" not in transcript[-1], transcript[-1]
    return "\n".join(transcript)


def _rows(root: Path, action: str) -> list[dict]:
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def _statuses(root: Path) -> dict[str, str]:
    status = root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return {name: entry["status"] for name, entry in json.loads(status.read_text()).items()}


def _dispositions(root: Path, action: str) -> list[tuple[str, str | None]]:
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return [
            (row["disposition"], row.get("reason"))
            for row in backend.get_disposition(action, snapshots=False)
        ]
    finally:
        backend.close()


def _texts(rows: list[dict]) -> list[str]:
    return sorted(row["content"]["source"]["text"] for row in rows)


THIRTY = ["multi_choice", "matching", "fill_blank"] * 10


@pytest.fixture(params=["online", "batch"])
def thirty(tmp_path, request):
    root = _project(tmp_path, request.param, THIRTY)
    return root, _run_to_the_end(root, "--fresh")


def test_7_1_a_router_with_three_cases_runs_each_branch_on_its_ten_records(thirty):
    root, transcript = thirty

    assert set(_statuses(root).values()) == {"completed"}, transcript
    counts = {a: len(_rows(root, a)) for a in ("mc_write", "m__write", "m__finalize", "fb_write")}
    assert counts == {"mc_write": 10, "m__write": 10, "m__finalize": 10, "fb_write": 10}
    assert len(_rows(root, "other_write")) == 0
    assert len(_rows(root, "bank")) == 30


def test_7_1_the_run_output_reports_none_of_the_other_twenty_as_filtered(thirty):
    _, transcript = thirty

    assert not re.search(r"\b[1-9]\d* filtered", transcript), transcript
    assert "records filtered by guard" not in transcript


def test_the_router_line_counts_each_case(thirty):
    _, transcript = thirty

    assert "format_router 30 records" in transcript, transcript
    assert "multi_choice 10, matching 10, fill_blank 10, default 0" in transcript, transcript


def test_the_join_holds_the_output_of_the_branch_each_record_went_through(thirty):
    root, _ = thirty

    by_text = {
        row["content"]["source"]["text"]: row["content"]["bank"] for row in _rows(root, "bank")
    }
    expected_field = {"multi_choice": "question", "matching": "pairs", "fill_blank": "blank"}
    for i, fmt in enumerate(THIRTY):
        assert list(by_text[f"topic {i}"]) == [expected_field[fmt]], (i, by_text[f"topic {i}"])
    published = {row["content"]["publish"]["fields"] for row in _rows(root, "publish")}
    assert published == {"question", "pairs", "blank"}


@RUN_MODES
def test_7_2_a_record_whose_value_has_no_case_goes_to_the_default_branch(tmp_path, run_mode):
    root = _project(tmp_path, run_mode, ["multi_choice", "true_false", "true_false", "matching"])

    transcript = _run_to_the_end(root, "--fresh")

    assert _texts(_rows(root, "other_write")) == ["topic 1", "topic 2"], transcript
    assert len(_rows(root, "bank")) == 4


@RUN_MODES
def test_a_join_after_a_branch_that_received_no_record_holds_every_other_record(tmp_path, run_mode):
    root = _project(tmp_path, run_mode, ["multi_choice", "matching"] * 3)

    transcript = _run_to_the_end(root, "--fresh")

    assert set(_statuses(root).values()) == {"completed"}, transcript
    assert len(_rows(root, "fb_write")) == 0
    assert len(_rows(root, "bank")) == 6


@RUN_MODES
def test_default_filter_filters_a_record_with_no_case_at_the_router(tmp_path, run_mode):
    """An ordinary filter, counted at the router: `agac dispositions` shows it as filtered."""
    root = _project(
        tmp_path, run_mode, ["multi_choice", "true_false", "matching"], default="filter", enum=None
    )

    transcript = _run_to_the_end(root, "--fresh")

    assert len(_rows(root, "format_router")) == 2, transcript
    assert len(_rows(root, "bank")) == 2
    assert _dispositions(root, "format_router").count(("filtered", "guard_filter")) == 1


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_a_second_run_finds_the_routed_workflow_complete_and_retry_has_nothing(tmp_path, run_mode):
    root = _project(tmp_path, run_mode, ["multi_choice", "matching", "true_false"])
    _run_to_the_end(root, "--fresh")

    code, output = _agac(root, "run")
    assert code == 0, output
    assert " records in " not in output, output
    code, output = _agac(root, "retry")
    assert code == 0, output
    assert "Nothing to retry" in output, output


def test_7_3_inspect_reports_a_case_value_outside_the_fields_enum(tmp_path):
    root = _project(tmp_path, "online", ["multi_choice"], first_case="multichoice")

    code, output = _agac(root, "inspect")

    assert code != 0, output
    assert "case 'multichoice' is not a value of route_focus.format" in output, output


def test_inspect_shows_the_router_its_cases_and_its_default_and_the_join(tmp_path):
    root = _project(tmp_path, "online", ["multi_choice"])

    code, output = _agac(root, "inspect")

    assert code == 0, output
    assert (
        "format_router route on route_focus.format: multi_choice → mc_write · "
        "matching → m__write · fill_blank → fb_write · default → other_write"
    ) in output, output
    assert "bank join of mc_write, m__finalize, fb_write, other_write" in output, output


@pytest.mark.parametrize("default", ["filter", "[other_write]"])
def test_a_source_value_that_is_no_string_fails_its_record_naming_the_type(tmp_path, default):
    root = _project(tmp_path, "online", ["multi_choice", "matching"], default=default, enum=None)
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().replace("on: route_focus.format", "on: source.format"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "items.json"
    staging.write_text(
        json.dumps(
            [{"text": "topic 0", "format": "multi_choice"}, {"text": "topic 1", "format": 1}]
        )
    )

    _code, output = _agac(root, "run", "--fresh")

    assert "source.format holds 1 (int); a router matches strings only" in output, output
    assert [row for row in _rows(root, "format_router") if not row.get("_tombstone")] != []
    assert len([row for row in _rows(root, "format_router") if row.get("_tombstone")]) == 1
    assert _dispositions(root, "format_router").count(("filtered", "guard_filter")) == 0
