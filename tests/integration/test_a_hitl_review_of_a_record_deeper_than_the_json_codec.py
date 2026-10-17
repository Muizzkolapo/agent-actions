"""A HITL action reviews a record nested deeper than the JSON codec can recurse (1487).

The run reads, stores and writes such a record through ``deep_json``; the HITL provider
still decoded its context, fingerprinted it, redacted it and served it to the review page
with the recursive codec, so the action failed with a bare ``RecursionError`` before a
reviewer saw anything. Here a reviewer thread drives the real review server over HTTP while
``agac run`` waits on it, as a person in a browser would.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from agent_actions.utils import deep_json
from tests._support.agac_cli import run_agac

WORKFLOW = "hitl_deep"
ACTION = "review_data"
DEPTH = 20_000
LEAF = "leaf at the bottom"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _project(base: Path, run_mode: str, port: int) -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\n"
    )
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(f"""\
name: {WORKFLOW}
description: "A HITL review of a deep record"
version: "0.1.0"
defaults:
  json_mode: true
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: extract_data
    intent: "Extract"
    prompt: "Answer."
    schema: {{ summary: string }}
    context_scope: {{ observe: [source.text] }}
  - name: {ACTION}
    kind: hitl
    dependencies: [extract_data]
    intent: "Review"
    hitl:
      port: {port}
      timeout: 300
      instructions: "Review"
    context_scope:
      observe: [extract_data.summary, source.deep]
""")
    deep = "[" * DEPTH + json.dumps(LEAF) + "]" * DEPTH
    (directory / "agent_io" / "staging" / "rows.json").write_text(
        '[{"text": "one", "deep": ' + deep + '}, {"text": "two", "deep": "flat"}]'
    )
    return root


def _is_this_tests_review(context: object) -> bool:
    records = context.get("data") if isinstance(context, dict) else None
    return (
        isinstance(records, list)
        and len(records) == 2
        and isinstance(records[1], dict)
        and records[1].get("deep") == "flat"
    )


class _Reviewer(threading.Thread):
    """Reads the review page's data and submits one decision per record."""

    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.context: object = None
        self.error: BaseException | None = None

    def run(self) -> None:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            for port in range(self.port, self.port + 5):
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/context", timeout=5
                    ) as response:
                        context = deep_json.loads(response.read())
                except (OSError, ValueError):
                    continue
                # Other tests' review servers may hold a nearby port.
                if not _is_this_tests_review(context):
                    continue
                self.context = context
                self._submit(port)
                return
            time.sleep(0.2)
        self.error = TimeoutError("the review server never answered")

    def _submit(self, port: int) -> None:
        body = json.dumps(
            {
                "record_reviews": [
                    {"hitl_status": "approved", "user_comment": "deep one is fine"},
                    {"hitl_status": "rejected", "user_comment": "flat one is not"},
                ]
            }
        ).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/submit",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                assert json.loads(response.read())["success"] is True
        except BaseException as exc:  # reported by the test thread
            self.error = exc


def _run_to_completion(root: Path):
    """``agac run``, again while a batch the run sent is still to be collected."""
    env = {
        "OPENAI_API_KEY": "sk-not-used",
        "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0",
        "AGAC_HITL_AUTO_APPROVE": "",
    }
    result = run_agac(root, "run", "-a", WORKFLOW, "--fresh", env=env)
    for _ in range(3):
        if result.returncode != 0 or "run again" not in result.stdout + result.stderr:
            break
        result = run_agac(root, "run", "-a", WORKFLOW, env=env)
    return result


def _depth_and_leaf(node) -> tuple[int, object]:
    depth = 0
    while isinstance(node, list) and len(node) == 1:
        node = node[0]
        depth += 1
    return depth, node


def _stored(root: Path) -> list[dict]:
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return backend.read_target(ACTION, "rows.json")
    finally:
        backend.close()


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_the_reviewer_sees_the_deep_record_and_the_decisions_are_stored(tmp_path, run_mode):
    port = _free_port()
    root = _project(tmp_path, run_mode, port)
    reviewer = _Reviewer(port)
    reviewer.start()

    result = _run_to_completion(root)
    reviewer.join(timeout=10)

    output = (result.stdout + result.stderr)[-3000:]
    assert result.returncode == 0, output
    assert reviewer.error is None, (reviewer.error, output)
    served = reviewer.context["data"]
    assert [_depth_and_leaf(record["deep"]) for record in served] == [
        (DEPTH, LEAF),
        (0, "flat"),
    ]
    decisions = {
        _depth_and_leaf(row["content"]["source"]["deep"]): (
            row["content"][ACTION]["hitl_status"],
            row["content"][ACTION]["user_comment"],
        )
        for row in _stored(root)
    }
    assert decisions == {
        (DEPTH, LEAF): ("approved", "deep one is fine"),
        (0, "flat"): ("rejected", "flat one is not"),
    }
