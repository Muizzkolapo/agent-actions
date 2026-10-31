"""`model_vendor: <endpoint>` sends an action's requests to the endpoint it names.

Every run is an `agac run` through the CLI against stub servers that record what they
were handed, so an assertion on a server's log is an assertion on what agac sent:
the path, the model, the schema in `response_format`, and which credential header.
The built-in `openai` action beside them is sent to its own stub through
`OPENAI_BASE_URL`, so the routing assertions can tell the servers apart.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests._support.fake_endpoint import CHAT_PATH, FakeEndpoint

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "endpoints_probe"
SECRET = "keyed-secret-value-0123456789"
TRACE = "trace-token-value-9876543210"

SCHEMA = """name: classify
fields:
  - id: label
    type: string
  - id: score
    type: integer
"""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("AGAC_RECORD_LIMIT", "OPENAI_BASE_URL", "OLLAMA_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def servers() -> Iterator[dict[str, FakeEndpoint]]:
    with (
        FakeEndpoint() as lab,
        FakeEndpoint() as keyed,
        FakeEndpoint() as cloud,
    ):
        yield {"lab": lab, "keyed": keyed, "cloud": cloud}


ENDPOINTS = """
endpoints:
  lab:
    url: ${LAB_URL}
    auth: none
  keyed:
    url: ${KEYED_URL}
    timeout_seconds: 10
    auth: { env: KEYED_SECRET, header: api-key }
    headers:
      X-Trace: ${TRACE_TOKEN}
      api-version: "2024-10-21"
"""


def _project(base: Path, actions: str, endpoints: str = ENDPOINTS) -> Path:
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    project_file = root / "agent_actions.yml"
    project_file.write_text(project_file.read_text() + endpoints)
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "classify.yml").write_text(SCHEMA)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "Actions on declared endpoints"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
{actions}"""
    )
    pages = [{"page_id": "p0", "page_content": "Page text."}]
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(pages))
    return root


def _action(name: str, vendor: str, model: str, extra: str = "") -> str:
    return f"""  - name: {name}
    intent: "Classify"
    model_vendor: {vendor}
    model_name: {model}
    schema: classify
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
{extra}"""


def _env(servers: dict[str, FakeEndpoint]) -> dict[str, str]:
    return {
        "LAB_URL": servers["lab"].base_url,
        "KEYED_URL": servers["keyed"].base_url,
        "KEYED_SECRET": SECRET,
        "TRACE_TOKEN": TRACE,
        "OPENAI_API_KEY": "sk-openai-control-key-000000000",
        "OPENAI_BASE_URL": servers["cloud"].base_url,
    }


def _run(root: Path, env: dict[str, str], *, expect_exit: int = 0) -> str:
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh", env=env)
    output = result.stdout + result.stderr
    assert result.returncode == expect_exit, output
    return output


def _dispositions(root: Path, action: str) -> list[tuple[str, str]]:
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select disposition, coalesce(reason, '') from record_disposition"
            " where action_name = ? and record_id != '__node__'",
            (action,),
        )
        return sorted(rows)
    finally:
        con.close()


def test_each_action_reaches_its_own_endpoint_with_its_own_credential(tmp_path, servers):
    actions = (
        _action("on_lab", "lab", "local-7b")
        + _action("on_keyed", "keyed", "gpt-4o-mini")
        + _action("on_cloud", "openai", "gpt-4o-mini", "    api_key: OPENAI_API_KEY\n")
    )
    root = _project(tmp_path, actions)

    _run(root, _env(servers))

    lab, keyed, cloud = (servers[k].requests for k in ("lab", "keyed", "cloud"))
    assert [r["body"]["model"] for r in lab] == ["local-7b"]
    assert [r["body"]["model"] for r in keyed] == ["gpt-4o-mini"]
    assert [r["body"]["model"] for r in cloud] == ["gpt-4o-mini"]
    assert lab[0]["path"] == keyed[0]["path"] == CHAT_PATH

    # The schema goes as OpenAI structured output, never as json_object.
    sent = lab[0]["body"]["response_format"]
    assert sent["type"] == "json_schema"
    assert set(sent["json_schema"]["schema"]["properties"]) == {"label", "score"}

    # auth: none sends the placeholder; a non-Authorization auth header replaces it.
    assert lab[0]["headers"]["authorization"] == "Bearer no-key-required"
    assert keyed[0]["headers"]["api-key"] == SECRET
    assert "authorization" not in keyed[0]["headers"]
    assert keyed[0]["headers"]["x-trace"] == TRACE
    assert keyed[0]["headers"]["api-version"] == "2024-10-21"

    # The project-wide api_key reaches the openai action and no endpoint.
    assert cloud[0]["headers"]["authorization"] == "Bearer sk-openai-control-key-000000000"
    for request in lab + keyed:
        assert "sk-openai" not in json.dumps(request["headers"])
        assert "OLLAMA" not in json.dumps(request["headers"])

    for action in ("on_lab", "on_keyed", "on_cloud"):
        assert _dispositions(root, action) == [("success", "")]


def test_a_reply_that_does_not_match_the_schema_fails_the_record(tmp_path, servers):
    servers["lab"].mode = "ignore"
    root = _project(tmp_path, _action("on_lab", "lab", "local-7b"))

    # The only record fails, so the run reports failure; the run log carries why.
    output = " ".join(_run(root, _env(servers), expect_exit=1).split())  # the console wraps

    assert _dispositions(root, "on_lab") == [("failed", "parse_error")]
    assert "endpoint 'lab' returned JSON that does not match schema 'classify'" in output
    assert "label" in output


def test_a_prose_reply_fails_the_record_as_a_parse_error(tmp_path, servers):
    servers["lab"].mode = "prose"
    root = _project(tmp_path, _action("on_lab", "lab", "local-7b"))

    output = _run(root, _env(servers), expect_exit=1)

    assert _dispositions(root, "on_lab") == [("failed", "parse_error")]
    assert "contains _parse_error" in output


def test_a_429_is_retried_and_a_401_is_not(tmp_path, servers):
    servers["lab"].statuses = [429]
    servers["keyed"].statuses = [401]
    actions = _action("on_lab", "lab", "local-7b") + _action("on_keyed", "keyed", "gpt-4o-mini")
    root = _project(tmp_path, actions)

    _run(root, _env(servers), expect_exit=1)

    assert len(servers["lab"].requests) == 2
    assert _dispositions(root, "on_lab") == [("success", "")]
    assert len(servers["keyed"].requests) == 1
    ((disposition, _reason),) = _dispositions(root, "on_keyed")
    assert disposition == "failed"


def test_no_secret_reaches_the_logs_the_store_or_the_output(tmp_path, servers):
    root = _project(tmp_path, _action("on_keyed", "keyed", "gpt-4o-mini"))

    _run(root, _env(servers) | {"AGAC_LOG_LEVEL": "DEBUG"})

    texts = [
        path.read_text(errors="replace")
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl", ".log", ".txt", ".md", ".yml"}
    ]
    assert texts, "the run wrote nothing to read"
    assert any("gpt-4o-mini" in text for text in texts)  # the search finds what is there
    assert not any(SECRET in text for text in texts)
    assert not any(TRACE in text for text in texts)
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    assert SECRET.encode() not in db.read_bytes()


def test_batch_on_an_endpoint_action_is_refused_at_preflight(tmp_path, servers):
    root = _project(tmp_path, _action("on_lab", "lab", "local-7b", "    run_mode: batch\n"))

    output = _run(root, _env(servers), expect_exit=1)

    assert "Action 'on_lab': vendor 'lab' does not support run_mode: batch." in output
    assert servers["lab"].requests == []


def test_api_key_written_on_an_endpoint_action_is_refused(tmp_path, servers):
    root = _project(tmp_path, _action("on_lab", "lab", "local-7b", "    api_key: OPENAI_API_KEY\n"))

    output = _run(root, _env(servers), expect_exit=1)

    assert (
        "Action 'on_lab': endpoint 'lab' takes its credential from endpoints.lab.auth; "
        "remove api_key from the action"
    ) in output


def test_base_url_written_on_an_endpoint_action_is_refused(tmp_path, servers):
    root = _project(tmp_path, _action("on_lab", "lab", "local-7b", "    base_url: http://x/v1\n"))

    output = _run(root, _env(servers), expect_exit=1)

    assert (
        "Action 'on_lab': endpoint 'lab' takes its URL from endpoints.lab.url; "
        "remove base_url from the action"
    ) in output


def test_an_endpoint_with_no_credential_needs_no_api_key_anywhere(tmp_path, servers):
    root = _project(tmp_path, _action("on_lab", "lab", "local-7b"))
    project_file = root / "agent_actions.yml"
    project_file.write_text(project_file.read_text().replace("  api_key: OLLAMA_API_KEY\n", ""))

    _run(root, _env(servers))

    assert _dispositions(root, "on_lab") == [("success", "")]
