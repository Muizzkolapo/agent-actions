"""A YAML or CSV seed file passes pre-flight and runs, as the runtime loader reads it (1533).

Pre-flight parsed every seed file with `json.loads`, so `$file:rubric.yaml`, which the docs
show, stopped `agac run` with "failed to parse: Expecting value", and so did a `.csv`.
Pre-flight now parses a seed file with the loader the run uses. The seed CSV reader keeps
a byte order mark out of the first key and a quoted `\\r\\n` as written.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests._support.agac_cli import run_agac

WORKFLOW = "w"
PAGES = [
    {"page_id": "p1", "page_content": "two"},
    {"page_id": "p2", "page_content": "one"},
]

_PROJECT = """\
default_agent_config:
  api_key: OLLAMA_API_KEY
  model_name: mock
schema_path: schema
"""

_WORKFLOW = """\
name: w
description: "An action reading a seed file"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: mock
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: consumer
    intent: "Consume"
    schema: fix1533_out
    prompt: $w.consumer
    context_scope:
      observe: [source.page_content]
      seed:
        conf: {seed}
"""

_PROMPT = """\
{{prompt consumer}}
Say {{{{ source.page_content }}}} {extra}
{{end_prompt}}
"""

_SCHEMA = """\
name: fix1533_out
fields:
  - id: summary
    type: string
"""


def _project(tmp_path: Path, seed: str, files: dict[str, bytes], extra: str) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_WORKFLOW.format(seed=seed))
    (workflow / "seed_data").mkdir()
    for name, data in files.items():
        (workflow / "seed_data" / name).write_bytes(data)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (workflow / "agent_io" / "staging" / "pages.json").write_text(json.dumps(PAGES))
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPT.format(extra=extra))
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "fix1533_out.yml").write_text(_SCHEMA)
    (root / "agent_actions.yml").write_text(_PROJECT)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _run(project: Path) -> str:
    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    return output


def _output(project: Path) -> str:
    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    return result.stdout + result.stderr


def _prompts(project: Path) -> list[str]:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("select compiled_prompt from prompt_trace")
        return sorted(p.strip() for (p,) in rows if "Say " in p)
    finally:
        con.close()


def test_a_yaml_seed_file_runs(tmp_path):
    project = _project(
        tmp_path,
        "$file:rubric.yaml",
        {"rubric.yaml": b"code: X1\nnote: plain\n"},
        "{{ seed.conf.code }}/{{ seed.conf.note }}",
    )

    _run(project)

    assert _prompts(project) == ["Say one X1/plain", "Say two X1/plain"]


def test_a_yaml_seed_field_the_file_lacks_is_still_reported(tmp_path):
    project = _project(
        tmp_path, "$file:rubric.yaml", {"rubric.yaml": b"code: X1\n"}, "{{ seed.conf.cod }}"
    )

    output = " ".join(_output(project).split())

    assert "Seed field 'conf.cod' referenced in action 'consumer' does not exist" in output


def test_a_broken_yaml_seed_file_is_refused_as_yaml(tmp_path):
    project = _project(
        tmp_path, "$file:rubric.yaml", {"rubric.yaml": b"code: [X1\n"}, "{{ seed.conf.code }}"
    )

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = " ".join((result.stdout + result.stderr).split())

    assert result.returncode != 0, output
    assert "Seed file '$file:rubric.yaml' failed to parse" in output
    assert "expected ',' or ']'" in output
    assert "valid YAML" in output
    assert "valid JSON" not in output


def test_a_csv_seed_file_runs_as_a_list_of_rows(tmp_path):
    project = _project(
        tmp_path,
        "$file:codes.csv",
        {"codes.csv": b"code,note\nX1,plain\nX2,other\n"},
        "{{ seed.conf[0].code }}/{{ seed.conf[1].note }}",
    )

    _run(project)

    assert _prompts(project) == ["Say one X1/other", "Say two X1/other"]


def test_a_csv_seed_with_a_bom_and_a_quoted_line_break_keeps_its_text(tmp_path):
    project = _project(
        tmp_path,
        "$file:codes.csv",
        {"codes.csv": '﻿code,note\r\nX1,"line one\r\nline two"\r\n'.encode()},
        "[{{ seed.conf[0].code }}|{{ seed.conf[0].note }}]",
    )

    _run(project)

    assert _prompts(project) == [
        "Say one [X1|line one\r\nline two]",
        "Say two [X1|line one\r\nline two]",
    ]


def test_a_selected_yaml_seed_gives_each_record_its_file(tmp_path):
    seed = "{ select_by: source.page_id, files: { p1: $file:p1.yaml, p2: $file:p2.yaml } }"
    project = _project(
        tmp_path,
        seed,
        {"p1.yaml": b"code: X1\n", "p2.yaml": b"code: X2\n"},
        "{{ seed.conf.code }}",
    )

    _run(project)

    assert _prompts(project) == ["Say one X2", "Say two X1"]


def test_a_selected_yaml_seed_field_one_file_lacks_names_that_file(tmp_path):
    seed = "{ select_by: source.page_id, files: { p1: $file:p1.yaml, p2: $file:p2.yaml } }"
    project = _project(
        tmp_path,
        seed,
        {"p1.yaml": b"code: X1\nextra: e\n", "p2.yaml": b"code: X2\n"},
        "{{ seed.conf.code }}{{ seed.conf.extra }}",
    )

    output = " ".join(_output(project).split())

    assert "Seed field 'conf.extra'" in output
    assert "(files: p2.yaml)" in output
