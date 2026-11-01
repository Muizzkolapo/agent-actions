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
    ((disposition, reason),) = _dispositions(root, "on_keyed")
    assert disposition == "failed"
    assert "401" in reason


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


def test_a_server_error_that_echoes_the_credential_is_masked_everywhere(tmp_path, servers):
    servers["keyed"].echo_headers = True
    servers["keyed"].statuses = [401]
    root = _project(tmp_path, _action("on_keyed", "keyed", "gpt-4o-mini"))

    output = _run(root, _env(servers), expect_exit=1)

    echoed = json.dumps(servers["keyed"].requests[0]["headers"])
    assert SECRET in echoed and TRACE in echoed  # the server did echo them
    assert SECRET not in output and TRACE not in output
    assert "[REDACTED]" in output
    texts = {
        str(path): path.read_text(errors="replace")
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl", ".log", ".txt", ".md", ".yml"}
    }
    leaks = sorted(name for name, text in texts.items() if SECRET in text or TRACE in text)
    assert leaks == []
    events = next(text for name, text in texts.items() if name.endswith("events.json"))
    assert "[REDACTED]" in events
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    assert SECRET.encode() not in db.read_bytes()
    ((disposition, reason),) = _dispositions(root, "on_keyed")
    assert disposition == "failed"
    assert SECRET not in reason


def test_command_auth_runs_once_per_run_and_recovers_from_a_401(tmp_path, servers):
    counter = tmp_path / "runs"
    script = (
        "import pathlib; "
        f"p = pathlib.Path({str(counter)!r}); "
        "n = len(p.read_text().splitlines()) + 1 if p.exists() else 1; "
        "p.open('a').write('run\\n'); "
        "print(f'cmd-token-number-{n}-abcdef')"
    )
    endpoints = f"""
endpoints:
  cmd:
    url: ${{LAB_URL}}
    auth:
      command: [python3, -c, {json.dumps(script)}]
"""
    servers["lab"].statuses = [401]
    root = _project(tmp_path, _action("on_cmd", "cmd", "local-7b"), endpoints=endpoints)
    pages = [{"page_id": f"p{i}", "page_content": f"Page {i}."} for i in range(3)]
    (root / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps(pages)
    )

    _run(root, _env(servers))

    assert _dispositions(root, "on_cmd") == [("success", "")] * 3
    assert len(counter.read_text().splitlines()) == 2
    sent = [r["headers"]["authorization"] for r in servers["lab"].requests]
    assert sent[0] == "Bearer cmd-token-number-1-abcdef"
    assert sent[1:] == ["Bearer cmd-token-number-2-abcdef"] * 3


def _run_verified(root: Path, env: dict[str, str], *, expect_exit: int) -> str:
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh", "--verify-keys", env=env)
    output = result.stdout + result.stderr
    assert result.returncode == expect_exit, output
    return output


def test_verify_keys_refuses_an_endpoint_that_ignores_the_schema_before_any_record(
    tmp_path, servers
):
    servers["lab"].mode = "ignore"
    root = _project(tmp_path, _action("on_lab", "lab", "local-7b"))

    output = " ".join(_run_verified(root, _env(servers), expect_exit=1).split())

    assert (
        "endpoint 'lab' does not honour response_format json_schema; "
        "agac supports only endpoints with OpenAI structured output"
    ) in output
    assert len(servers["lab"].requests) == 1  # the probe, and no record
    assert servers["lab"].requests[0]["body"]["max_tokens"] == 16


def test_verify_keys_lets_an_endpoint_that_honours_the_schema_run(tmp_path, servers):
    root = _project(tmp_path, _action("on_lab", "lab", "local-7b"))

    _run_verified(root, _env(servers), expect_exit=0)

    assert _dispositions(root, "on_lab") == [("success", "")]
    models = [r["body"]["model"] for r in servers["lab"].requests]
    assert models == ["local-7b", "local-7b"]  # the probe, then the record
    assert servers["lab"].requests[0]["body"]["response_format"]["json_schema"]["name"] == (
        "agac_probe"
    )


# Every clone carries the orchestrator's sample project as qanalabs-quiz-maker beside the repo.
_CLONE = Path(__file__).resolve().parents[3]
SAMPLE = next(
    (p for p in (_CLONE / "qanalabs-quiz-maker", _CLONE.parent / "sample-project") if p.exists()),
    _CLONE / "qanalabs-quiz-maker",
)


def _sample_probe_project(base: Path) -> Path:
    """The sample project's ql_endpoint_probe and only what it needs, in a scratch copy."""
    root = base / "sample"
    (root / "agent_workflow").mkdir(parents=True)
    shutil.copytree(
        SAMPLE / "agent_workflow" / "ql_endpoint_probe",
        root / "agent_workflow" / "ql_endpoint_probe",
        ignore=shutil.ignore_patterns("logs", "store", "target", ".agent_status.json"),
    )
    shutil.copy(SAMPLE / "agent_actions.yml", root / "agent_actions.yml")
    (root / "prompt_store").mkdir()
    shutil.copy(SAMPLE / "prompt_store" / "ql_endpoint_probe.md", root / "prompt_store")
    for folder in ("tools", "schema", "seed_data", "shared_seeds"):
        (root / folder).mkdir()
    return root


@pytest.mark.skipif(not SAMPLE.exists(), reason="the orchestrator's sample project is not here")
def test_the_sample_project_probe_shows_each_endpoint_its_own_credential(tmp_path):
    with FakeEndpoint(mode="honour") as honour, FakeEndpoint(mode="ignore") as ignore:
        root = _sample_probe_project(tmp_path)
        env = {
            "QL_HONOUR_URL": honour.base_url,
            "QL_IGNORE_URL": ignore.base_url,
            "QL_HONOUR_KEY": "honour-secret-value-0001",
            "QL_IGNORE_KEY": "ignore-secret-value-0002",
            "OPENAI_API_KEY": "sk-unused-control-key-00000000000",
        }
        result = run_agac(root, "run", "-a", "ql_endpoint_probe", "--fresh", env=env)
        output = result.stdout + result.stderr
        assert result.returncode == 1, output  # every on_ignore record fails

        (db,) = (root / "agent_workflow" / "ql_endpoint_probe" / "agent_io" / "store").glob("*.db")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = sorted(
                con.execute(
                    "select action_name, disposition, coalesce(reason, '') from record_disposition"
                    " where record_id != '__node__'"
                )
            )
        finally:
            con.close()
        assert (
            rows
            == [("on_honour", "success", "")] * 3 + [("on_ignore", "failed", "parse_error")] * 3
        )

        honour_headers = [r["headers"] for r in honour.requests]
        ignore_headers = [r["headers"] for r in ignore.requests]
        assert len(honour_headers) == 3 and len(ignore_headers) == 3
        assert {h["x-api-key"] for h in honour_headers} == {"honour-secret-value-0001"}
        assert all("authorization" not in h for h in honour_headers)
        assert {h["authorization"] for h in ignore_headers} == {"Bearer ignore-secret-value-0002"}
        assert all("x-api-key" not in h for h in ignore_headers)
        assert "honour-secret-value-0001" not in output
        assert "ignore-secret-value-0002" not in output

        stored = run_agac(root, "records", "-w", "ql_endpoint_probe", "-a", "on_honour").stdout
        assert all(f"row-{i}" in stored for i in (1, 2, 3))
