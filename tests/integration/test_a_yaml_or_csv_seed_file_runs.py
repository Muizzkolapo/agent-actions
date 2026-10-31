"""A YAML or CSV seed file passes pre-flight and runs, as the runtime loader reads it (1533).

Pre-flight parsed every seed file with `json.loads`, so `$file:rubric.yaml`, which the docs
show, stopped `agac run` with "failed to parse: Expecting value", and so did a `.csv`.
Pre-flight now parses a seed file with the loader the run uses. The seed CSV reader keeps
a byte order mark out of the first key and a quoted `\\r\\n` as written.
"""

from __future__ import annotations

import json
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
    rows = trace_rows(project, "select compiled_prompt from prompt_trace")
    return sorted(p.strip() for (p,) in rows if "Say " in p)


_SELECTED = "{ select_by: source.page_id, files: { p1: $file:p1.yaml, p2: $file:p2.yaml } }"


@pytest.mark.parametrize(
    ("seed", "files", "extra", "expected"),
    [
        pytest.param(
            "$file:rubric.yaml",
            {"rubric.yaml": b"code: X1\nnote: plain\n"},
            "{{ seed.conf.code }}/{{ seed.conf.note }}",
            ["Say one X1/plain", "Say two X1/plain"],
            id="yaml",
        ),
        pytest.param(
            "$file:codes.csv",
            {"codes.csv": b"code,note\nX1,plain\nX2,other\n"},
            "{{ seed.conf[0].code }}/{{ seed.conf[1].note }}",
            ["Say one X1/other", "Say two X1/other"],
            id="csv-as-a-list-of-rows",
        ),
        pytest.param(
            "$file:codes.csv",
            {"codes.csv": '\ufeffcode,note\r\nX1,"line one\r\nline two"\r\n'.encode()},
            "[{{ seed.conf[0].code }}|{{ seed.conf[0].note }}]",
            ["Say one [X1|line one\r\nline two]", "Say two [X1|line one\r\nline two]"],
            id="csv-with-a-bom-and-a-quoted-line-break",
        ),
        pytest.param(
            _SELECTED,
            {"p1.yaml": b"code: X1\n", "p2.yaml": b"code: X2\n"},
            "{{ seed.conf.code }}",
            ["Say one X2", "Say two X1"],
            id="selected-yaml-gives-each-record-its-file",
        ),
    ],
)
def test_a_seed_file_runs(tmp_path, seed, files, extra, expected):
    project = _project(tmp_path, seed, files, extra)

    _run(project)

    assert _prompts(project) == expected


@pytest.mark.parametrize(
    ("seed", "files", "extra", "says"),
    [
        pytest.param(
            "$file:rubric.yaml",
            {"rubric.yaml": b"code: X1\n"},
            "{{ seed.conf.cod }}",
            ["Seed field 'conf.cod' referenced in action 'consumer' does not exist"],
            id="yaml-field-the-file-lacks",
        ),
        pytest.param(
            _SELECTED,
            {"p1.yaml": b"code: X1\nextra: e\n", "p2.yaml": b"code: X2\n"},
            "{{ seed.conf.code }}{{ seed.conf.extra }}",
            ["Seed field 'conf.extra'", "(files: p2.yaml)"],
            id="selected-yaml-field-one-file-lacks-names-that-file",
        ),
    ],
)
def test_a_seed_field_the_file_lacks_is_reported(tmp_path, seed, files, extra, says):
    project = _project(tmp_path, seed, files, extra)

    output = " ".join(_output(project).split())

    for message in says:
        assert message in output


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
