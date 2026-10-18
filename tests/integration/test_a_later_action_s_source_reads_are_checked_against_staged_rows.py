"""An action below the first reading a `source` field no staged row holds is refused (1537).

The first action's reads are checked against the rows staging prepares (1518, 1522),
but an action below it that observed, prompted or guarded on a `source` field no
staged row holds passed pre-flight and then failed (or filtered) every record. Those
reads are now checked against the same rows, before any record is stored or sent,
naming the action, the field and the staged file.

Where another staged file may hold the field, or the read is a passthrough (which
leaves a missing field out, for a first action too), it is a warning instead.

Every case is a real `agac run` through the CLI, with the mock provider for LLM actions.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "later_source"
TEXT = "Hello there. This is a short document.\n"
API_URL = "https://example.invalid/rows"

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def later_source_echo(data: Any, *args) -> list[dict]:
    return [{"got": repr(data)}]
"""

FIRST = """  - name: first
    kind: tool
    intent: "Echo"
    impl: later_source_echo
    schema: echo_out
    context_scope: { observe: [source.*] }
"""


def _project(
    base: Path,
    later: str,
    *,
    run_mode: str = "online",
    staged: dict[str, str] | None = None,
    file_type: str = "txt",
    data_source: str | None = None,
) -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    staging = directory / "agent_io" / "staging"
    staging.mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    # Character splits, so chunking needs no tokenizer download.
    (root / "agent_actions.yml").write_text(
        'tool_path: ["tools"]\nschema_path: schema\n'
        "default_agent_config:\n  model_name: gpt-4o-mini\n"
        "  chunk_config: {split_method: chars, chunk_size: 2000, chunk_overlap: 10}\n"
    )
    (root / "tools" / WORKFLOW / "later_source_tools.py").write_text(TOOLS)
    (root / "schema" / WORKFLOW / "echo_out.yml").write_text(
        "name: echo_out\nfields:\n  - id: got\n    type: string\nadditionalProperties: true\n"
    )
    source = data_source or f"{{ type: local, folder: ./staging, file_type: [{file_type}] }}"
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "A later action reading the source namespace"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {source}
actions:
{FIRST}{later}"""
    )
    for name, text in (staged if staged is not None else {"doc.txt": TEXT}).items():
        (staging / name).write_text(text)
    return root


def _later_tool(observe: str = "first.got", passthrough: str | None = None) -> str:
    extra = f", passthrough: [{passthrough}]" if passthrough else ""
    return f"""  - name: second
    kind: tool
    intent: "Echo again"
    impl: later_source_echo
    schema: echo_out
    dependencies: [first]
    context_scope: {{ observe: [{observe}]{extra} }}
"""


def _later_llm(field: str, observe: str = "first.got, source.*", prompt: str = "") -> str:
    prompt = prompt or f"Text: {{{{ {field} }}}}"
    return f"""  - name: second
    intent: "Answer"
    prompt: "{prompt}"
    schema: {{ answer: string }}
    dependencies: [first]
    context_scope: {{ observe: [{observe}] }}
"""


def _later_guard(clause: str) -> str:
    return f"""  - name: second
    kind: tool
    intent: "Echo again"
    impl: later_source_echo
    schema: echo_out
    dependencies: [first]
    guard: {{ condition: "{clause}", on_false: filter }}
    context_scope: {{ observe: [first.got] }}
"""


def _run(root: Path, run_mode: str = "online"):
    env = {"OPENAI_API_KEY": "sk-not-used", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh", env=env)
    if run_mode == "batch" and result.returncode == 0:
        # The first run submits the batch; the next collects it.
        result = run_agac(root, "run", "-a", WORKFLOW, env=env)
    return result


def _query(root: Path, sql: str) -> list[tuple]:
    store = root / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    dbs = sorted(store.glob("*.db"))
    if not dbs:
        return []
    con = sqlite3.connect(f"file:{dbs[0]}?mode=ro", uri=True)
    try:
        return con.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def _stored(root: Path, action: str) -> list[dict]:
    rows = _query(root, f"select data from target_data where action_name = '{action}'")
    return [record for (data,) in rows for record in json.loads(data)]


def _output(result) -> str:
    return " ".join((result.stdout + result.stderr).split())


def _assert_refused(result, root: Path, field: str, staged: str = "doc.txt") -> str:
    output = _output(result)
    assert result.returncode != 0, output
    assert "Action 'second'" in output, output
    assert f"source.{field}" in output, output
    assert staged in output, output
    assert _stored(root, "first") == [], output
    assert _stored(root, "second") == [], output
    return output


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize(
    "later",
    [
        _later_tool(observe="first.got, source.page_content"),
        _later_llm("source.page_content"),
        _later_llm("source.page_content", observe="first.got, source.page_content"),
        _later_llm("source.page_content | upper"),
        # The render reads the field to test it, and fails without it.
        _later_llm("", prompt="{% if source.page_content %}x{% endif %}{{ source.content }}"),
    ],
    ids=["observe", "prompt", "llm-observe", "prompt-filter", "prompt-if"],
)
def test_a_later_read_of_a_field_no_text_chunk_holds_is_refused(tmp_path, later, run_mode):
    root = _project(tmp_path, later, run_mode=run_mode)

    result = _run(root, run_mode)

    output = _assert_refused(result, root, "page_content")
    assert "read it as source.content" in output, output


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_a_later_read_of_a_column_no_json_row_holds_is_refused(tmp_path, run_mode):
    rows = json.dumps([{"title": "a"}, {"title": "b"}])
    root = _project(
        tmp_path,
        _later_tool(observe="first.got, source.body"),
        run_mode=run_mode,
        staged={"doc.json": rows},
        file_type="json",
    )

    result = _run(root, run_mode)

    output = _assert_refused(result, root, "body", staged="doc.json")
    assert "Its records hold: title." in output, output


def test_a_read_below_an_action_below_the_first_is_refused(tmp_path):
    third = _later_tool(observe="second.got, source.page_content").replace(
        "name: second", "name: third"
    )
    third = third.replace("dependencies: [first]", "dependencies: [second]")
    # Declared above the action it depends on, so it is reached only through that one.
    root = _project(tmp_path, third + _later_tool())

    result = _run(root)

    output = _output(result)
    assert result.returncode != 0, output
    assert "Action 'third' observes source.page_content" in output, output
    assert _stored(root, "first") == [], output


def test_a_read_below_a_version_merge_is_refused(tmp_path):
    versions = _later_tool().replace(
        "dependencies: [first]", "versions: { param: n, range: [1, 2] }\n    dependencies: [first]"
    )
    merged = (
        _later_tool(observe="second_1.got, second_2.got, source.page_content")
        .replace("name: second", "name: merged")
        .replace(
            "dependencies: [first]",
            "dependencies: [second]\n    version_consumption: { source: second, pattern: merge }",
        )
    )
    root = _project(tmp_path, versions + merged)

    result = _run(root)

    output = _output(result)
    assert result.returncode != 0, output
    assert "Action 'merged' observes source.page_content" in output, output
    assert _stored(root, "first") == [], output


def test_every_text_file_staged_is_refused_alike(tmp_path):
    root = _project(
        tmp_path,
        _later_tool(observe="first.got, source.page_content"),
        staged={"a.txt": TEXT, "b.txt": TEXT},
    )

    result = _run(root)

    output = _assert_refused(result, root, "page_content", staged="a.txt")
    assert "read it as source.content" in output, output


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_a_later_read_of_a_text_chunk_as_source_content_runs(tmp_path, run_mode):
    root = _project(tmp_path, _later_tool(observe="first.got, source.content"), run_mode=run_mode)

    result = _run(root, run_mode)

    output = _output(result)
    assert result.returncode == 0, output
    assert "no record staged" not in output, output
    (record,) = _stored(root, "second")
    got = record["content"]["second"]["got"]
    assert repr({"content": TEXT}) in got, got


def test_a_passthrough_of_a_field_no_row_holds_warns_and_runs(tmp_path):
    root = _project(tmp_path, _later_tool(passthrough="source.page_content"))

    result = _run(root)

    output = _output(result)
    assert result.returncode == 0, output
    assert "Action 'second' passes through source.page_content" in output, output
    assert len(_stored(root, "second")) == 1, output


@pytest.mark.parametrize(
    ("clause", "passed"),
    [("source.page_content == 'x'", 0), ("source.page_content IS NULL", 1)],
    ids=["compare", "is-null"],
)
def test_a_guard_on_a_field_no_row_holds_warns_and_runs(tmp_path, clause, passed):
    """A guard can test for the field, so the run goes on and the guard decides."""
    root = _project(tmp_path, _later_guard(clause))

    result = _run(root)

    output = _output(result)
    assert result.returncode == 0, output
    assert "Action 'second' guards on source.page_content" in output, output
    assert len(_stored(root, "first")) == 1, output
    assert len(_stored(root, "second")) == passed, output


@pytest.mark.parametrize(
    "prompt",
    [
        "{{ source.get('page_content', source.content) }}",
        "{{ source.page_content | default(source.content) }}",
        "{% if source.page_content is defined %}{{ source.page_content }}{% endif %}",
        "{{ source.page_content if source.page_content is defined else source.content }}",
    ],
    ids=["get", "default", "if-defined", "is-defined"],
)
def test_a_prompt_reading_a_field_conditionally_warns_and_runs(tmp_path, prompt):
    root = _project(tmp_path, _later_llm("", prompt=prompt))

    result = _run(root)

    output = _output(result)
    assert result.returncode == 0, output
    assert "reads conditionally in its prompt source.page_content" in output, output
    assert len(_stored(root, "second")) == 1, output


def test_a_column_only_some_rows_hold_is_not_refused(tmp_path):
    rows = json.dumps([{"title": "a"}, {"title": "b", "body": "text"}])
    root = _project(
        tmp_path,
        _later_tool(observe="first.got, source.body"),
        staged={"doc.json": rows},
        file_type="json",
    )

    result = _run(root)

    output = _output(result)
    assert "no record staged" not in output, output
    assert len(_stored(root, "first")) == 2, output
    # The row holding the field runs; the other fails on it, as it always did.
    (record,) = [r for r in _stored(root, "second") if (r.get("content") or {}).get("second")]
    assert "'body': 'text'" in record["content"]["second"]["got"]


def test_a_column_another_staged_file_holds_warns_rather_than_refuses(tmp_path):
    root = _project(
        tmp_path,
        _later_tool(observe="first.got, source.body"),
        staged={
            "a.json": json.dumps([{"title": "a"}]),
            "b.json": json.dumps([{"title": "b", "body": "text"}]),
        },
        file_type="json",
    )

    result = _run(root)

    output = _output(result)
    assert "Action 'second' observes source.body, but no record staged from" in output, output
    assert "a.json" in output, output
    assert len(_stored(root, "first")) == 2, output
    (record,) = [r for r in _stored(root, "second") if (r.get("content") or {}).get("second")]
    assert "'body': 'text'" in record["content"]["second"]["got"]


def test_an_empty_staging_folder_is_not_refused_for_a_later_read(tmp_path):
    root = _project(tmp_path, _later_tool(observe="first.got, source.page_content"), staged={})

    result = _run(root)

    assert "no record staged" not in _output(result), _output(result)


def _api_cache(root: Path, rows: list[dict]) -> None:
    """The response an API source fetched, cached where the next run reads it."""
    fingerprint = hashlib.sha256(API_URL.encode()).hexdigest()[:12]
    cache = root / "agent_workflow" / WORKFLOW / "agent_io" / "_remote_cache" / "api"
    (cache / fingerprint / "data").mkdir(parents=True)
    (cache / fingerprint / "data" / "first.json").write_text(json.dumps(rows))


@pytest.mark.parametrize(("observe", "refused"), [("source.body", True), ("source.title", False)])
def test_an_api_source_is_checked_against_the_rows_it_fetched(tmp_path, observe, refused):
    root = _project(
        tmp_path,
        _later_tool(observe=f"first.got, {observe}"),
        staged={},
        data_source=f'{{ type: api, url: "{API_URL}" }}',
    )
    _api_cache(root, [{"title": "a"}])

    result = _run(root)

    if refused:
        _assert_refused(result, root, "body", staged="first.json")
    else:
        assert result.returncode == 0, _output(result)
        assert len(_stored(root, "second")) == 1, _output(result)
