"""A prompt-store prompt that calls `load_prompt`, as prompt-store.md "Load Other Prompts"
shows it, sends each record the loaded prompt filled from that record, in either run mode.

Driven through `agac run` against the agac provider mock; what each record was sent is
read back from the action's prompt traces.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "load_store"
PAGES = [
    {"title": "Alpha", "page_content": "Photosynthesis turns light into sugar."},
    {"title": "Beta", "page_content": "Volcanoes vent molten rock."},
]
MODES = ["online", "batch"]

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: gpt-oss:120b-cloud
tool_path: ["tools"]
schema_path: schema
seed_data_path: seed_data
"""

_HEAD = """\
name: load_store
description: "Store prompts that load other prompts"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {mode}
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: analyze
    intent: "Analyze the page"
    prompt: {prompt}
    schema: {{answer: string}}
    context_scope: {{ observe: [source.title, source.page_content] }}
"""

_STORE = """\
{prompt Standard_Header}
You are reviewing the page titled {{ source.title }}.
{end_prompt}

{prompt Main_Analysis}
{{ load_prompt("lp_wf.Standard_Header") }}

## Analysis Content
{{ source.page_content }}
{end_prompt}

{prompt Outer}
{{ load_prompt("lp_wf.Main_Analysis") }}
Be brief.
{end_prompt}

{prompt Header_Line}
{{ load_prompt("lp_wf.Standard_Header") }}
{end_prompt}

{prompt Loop_A}
{{ load_prompt("lp_wf.Loop_B") }}
{end_prompt}

{prompt Loop_B}
{{ load_prompt("lp_wf.Loop_A") }}
{end_prompt}

{prompt Two_Lines}
Line one.
Line two.
{end_prompt}

{prompt Two_Lines_Tagged}
Line one about {{ source.title }}.
  Line two, indented.
{end_prompt}
"""


def _project(tmp_path: Path, mode: str, prompt: str) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _HEAD.format(mode=mode, prompt=prompt)
    )
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    for folder in ("templates", "schema", "seed_data", "prompt_store", "tools"):
        (root / folder).mkdir()
    (root / "prompt_store" / "lp_wf.md").write_text(_STORE)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run(project: Path) -> tuple[int, str]:
    """`agac run --fresh`, then `agac run` while a batch is left to collect."""
    outputs = []
    args = ["run", "-a", WORKFLOW, "--fresh"]
    for _ in range(4):
        result = run_agac(project, *args, env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"})
        output = result.stdout + result.stderr
        outputs.append(output)
        if result.returncode != 0 or "run again" not in output:
            return result.returncode, "\n".join(outputs)
        args = ["run", "-a", WORKFLOW]
    pytest.fail("the workflow never stopped asking to be run again:\n" + "\n".join(outputs))


def _prompts(project: Path) -> list[str]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select compiled_prompt from prompt_trace where action_name = 'analyze' and attempt = 0"
        )
        return sorted(prompt for (prompt,) in rows)
    finally:
        con.close()


def _analysis(page: dict) -> str:
    return (
        f"You are reviewing the page titled {page['title']}.\n\n"
        f"## Analysis Content\n{page['page_content']}"
    )


@pytest.mark.parametrize("mode", MODES)
def test_a_store_prompt_sends_each_record_the_prompt_it_loads(tmp_path, mode):
    """prompt-store.md "Load Other Prompts": every record failed on 'load_prompt' is undefined."""
    project = _project(tmp_path, mode, "$lp_wf.Main_Analysis")

    code, output = _run(project)

    assert code == 0, output
    assert _prompts(project) == [_analysis(page) for page in PAGES]


@pytest.mark.parametrize("mode", MODES)
def test_a_loaded_prompt_that_loads_another_is_expanded_too(tmp_path, mode):
    project = _project(tmp_path, mode, "$lp_wf.Outer")

    code, output = _run(project)

    assert code == 0, output
    assert _prompts(project) == [_analysis(page) + "\nBe brief." for page in PAGES]


def test_an_inline_prompt_loading_a_store_prompt_that_loads_another_is_expanded(tmp_path):
    project = _project(
        tmp_path,
        "online",
        '|\n      {{ load_prompt("lp_wf.Header_Line") }}\n      Summarize the page.',
    )

    code, output = _run(project)

    assert code == 0, output
    assert _prompts(project) == [
        f"You are reviewing the page titled {page['title']}.\nSummarize the page.\n"
        for page in PAGES
    ]


def test_store_prompts_that_load_each_other_fail_the_load_naming_the_cycle(tmp_path):
    project = _project(tmp_path, "online", "$lp_wf.Loop_A")

    code, output = _run(project)

    assert code != 0, output
    assert "lp_wf.Loop_A -> lp_wf.Loop_B -> lp_wf.Loop_A" in output, output


@pytest.mark.parametrize("mode", MODES)
def test_an_inline_prompt_reading_a_record_loads_a_store_prompt_of_several_lines(tmp_path, mode):
    """The loaded lines were pasted unindented into the block, failing the load as YAML."""
    project = _project(
        tmp_path,
        mode,
        '|\n      {{ load_prompt("lp_wf.Two_Lines") }}\n      Summarize {{ source.title }}.',
    )

    code, output = _run(project)

    assert code == 0, output
    assert _prompts(project) == [
        f"Line one.\nLine two.\nSummarize {page['title']}.\n" for page in PAGES
    ]


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        pytest.param(
            '|\n      {{ load_prompt("lp_wf.Two_Lines") }}\n      Summarize the page.',
            "Line one.\nLine two.\nSummarize the page.\n",
            id="block-reading-no-record-field",
        ),
        pytest.param(
            '|\n      {{ load_prompt("lp_wf.Two_Lines_Tagged") }}\n      Summarize the page.',
            "Line one about {title}.\n  Line two, indented.\nSummarize the page.\n",
            id="loaded-text-with-tags",
        ),
        pytest.param(
            '|\n      Intro for {{ source.title }}:\n      {{ load_prompt("lp_wf.Two_Lines") }}'
            "\n      End.",
            "Intro for {title}:\nLine one.\nLine two.\nEnd.\n",
            id="block-reading-a-record-above-it",
        ),
        pytest.param(
            "\"{{ load_prompt('lp_wf.Two_Lines') }} Summarize {{ source.title }}.\"",
            "Line one.\nLine two. Summarize {title}.",
            id="double-quoted-keeps-the-line-break",
        ),
    ],
)
def test_an_inline_prompt_puts_a_loaded_prompt_of_several_lines_in_as_written(
    tmp_path, prompt, expected
):
    project = _project(tmp_path, "online", prompt)

    code, output = _run(project)

    assert code == 0, output
    assert _prompts(project) == [expected.format(title=page["title"]) for page in PAGES]
