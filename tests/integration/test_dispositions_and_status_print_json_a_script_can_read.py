"""`agac dispositions --json` and `agac status --json` print what a script reads.

A wrapper that retries while failures remain counted them by splitting the lines of
the dispositions table on its box character. Both commands now print one JSON
document on stdout, and the failed and exhausted counts in it are the records
`agac retry --dry-run` says it would retry.

Every command is a real `agac` process against one store. `summarize` asks a local
server standing in for an Ollama host: it answers 503 for two pages, whose retries
run out, and 400 for one, which fails at once. `tag` is a tool that raises for one
more page.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "json_counts"
PAGES = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
UNAVAILABLE = ("gamma", "delta")
REFUSED = ("epsilon",)
TOOL_FAILS = "beta"
COUNTS = {
    "success",
    "failed_checks",
    "failed",
    "exhausted",
    "guard_skipped",
    "unprocessed",
    "passthrough",
    "filtered",
    "skipped",
    "deferred",
}

CONFIG = """name: json_counts
description: "failed and exhausted records at two actions"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: ollama_local
  model_name: some-model
  base_url: %(url)s
  retry: { enabled: true, max_attempts: 2 }
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: summarize
    intent: "summarise each page"
    schema: page_summary
    prompt: $json_counts.Summarize
    context_scope: { observe: [source.page_content] }
  - name: tag
    kind: tool
    dependencies: [summarize]
    intent: "tag each summary"
    impl: json_counts_tag
    schema: page_summary
    context_scope: { observe: [source.page_content, summarize.summary] }
"""

PROMPTS = """{prompt Summarize}
Summarise the page in one sentence.
## PAGE
{{ source.page_content }}
```json
{"summary": "..."}
```
{end_prompt}
"""

TOOLS = f"""from typing import Any

from agent_actions import udf_tool


@udf_tool
def json_counts_tag(data: Any, *args) -> list[dict]:
    page = str(data["source"]["page_content"])
    if {TOOL_FAILS!r} in page:
        raise RuntimeError("the tool cannot tag this page")
    return [{{"summary": "tagged " + page}}]
"""


@pytest.fixture(scope="module")
def provider() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            asked = self.rfile.read(int(self.headers.get("content-length", 0))).decode()
            if any(page in asked for page in UNAVAILABLE):
                status, payload = 503, {"error": "service unavailable"}
            elif any(page in asked for page in REFUSED):
                status, payload = 400, {"error": "the model refuses this page"}
            else:
                status = 200
                payload = {
                    "model": "some-model",
                    "created_at": "2026-01-01T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"summary": "A page."}),
                    },
                    "done": True,
                }
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def project(tmp_path_factory, provider) -> Path:
    root = tmp_path_factory.mktemp("json_counts")
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_io" / "staging").mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n  api_key: OLLAMA_API_KEY\n  model_name: some-model\n"
        'tool_path: ["tools"]\nschema_path: schema\n'
    )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG % {"url": provider})
    (workflow / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_content": f"Page {page}."} for page in PAGES])
    )
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    (root / "tools" / WORKFLOW / "json_counts_tools.py").write_text(TOOLS)
    (root / "schema" / WORKFLOW / "page_summary.yml").write_text(
        "name: page_summary\nfields:\n  - id: summary\n    type: string\n"
    )
    result = run_agac(root, "run", "-w", WORKFLOW)
    assert "exhausted" in result.stdout + result.stderr, result.stdout + result.stderr
    return root


def _json(project: Path, *args: str) -> dict:
    """The whole of stdout, parsed: a warning or a banner on it would fail the parse."""
    result = run_agac(project, *args, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _counts(project: Path, action: str) -> dict[str, int]:
    report = _json(project, "dispositions", "-w", WORKFLOW)
    return next(entry for entry in report["actions"] if entry["name"] == action)["counts"]


def _retry_plan(project: Path, *args: str) -> tuple[str, int]:
    result = run_agac(project, "retry", "-w", WORKFLOW, "--dry-run", *args)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    action = re.search(r"From action: (\S+)", output)
    records = re.search(r"Records to retry: (\d+)", output)
    assert action and records, output
    return action.group(1), int(records.group(1))


@pytest.mark.parametrize("flag", ["-w", "-a"])
def test_dispositions_json_is_one_json_document_on_stdout(project, flag):
    report = _json(project, "dispositions", flag, WORKFLOW)

    assert set(report) == {"workflow", "actions"}
    assert report["workflow"] == WORKFLOW
    assert [entry["name"] for entry in report["actions"]] == ["summarize", "tag"]
    for entry in report["actions"]:
        assert set(entry) == {
            "name",
            "counts",
            "total",
            "sent_elsewhere",
            "records",
            "action_level",
        }
        assert set(entry["counts"]) == COUNTS
        assert sum(entry["counts"].values()) == entry["total"] == len(PAGES)


def test_dispositions_json_counts_each_disposition_of_each_action(project):
    summarize = _counts(project, "summarize")
    tag = _counts(project, "tag")

    assert (summarize["success"], summarize["failed"], summarize["exhausted"]) == (3, 1, 2)
    assert (tag["success"], tag["failed"], tag["unprocessed"]) == (2, 1, 3)


def test_failed_plus_exhausted_is_the_count_retry_dry_run_reports(project):
    action, records = _retry_plan(project)

    counts = _counts(project, action)
    assert action == "summarize"
    assert counts["failed"] + counts["exhausted"] == records == 3


def test_failed_plus_exhausted_is_the_count_retry_dry_run_reports_from_a_later_action(project):
    action, records = _retry_plan(project, "--from", "tag")

    counts = _counts(project, action)
    assert action == "tag"
    assert counts["failed"] + counts["exhausted"] == records == 1


def test_dispositions_json_of_one_action_holds_that_action_alone(project):
    report = _json(project, "dispositions", "-w", WORKFLOW, "-A", "tag")

    assert [entry["name"] for entry in report["actions"]] == ["tag"]


def test_status_json_is_each_actions_status_and_the_runs(project):
    report = _json(project, "status", "-w", WORKFLOW)

    assert report == {
        "workflow": WORKFLOW,
        "run_status": "SUCCESS",
        "actions": [
            {"name": "summarize", "status": "completed_with_failures", "error": None},
            {"name": "tag", "status": "completed_with_failures", "error": None},
        ],
    }
