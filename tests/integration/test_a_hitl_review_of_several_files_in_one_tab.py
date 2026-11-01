"""One browser tab reviews every file of a HITL action, one after another (1604).

Each file is reviewed on its own server at the same address. The page used to send
``/api/shutdown`` 1.5s after a submit and then say "Complete": the shutdown reached the
next file's server, which marked that file timed out unseen, and the file after it
waited out its whole timeout with no tab open. The run still ended cleanly completed.
Here a reviewer thread drives the real review servers over HTTP while ``agac run``
waits on them, as the page does: it sends its session with each write, sends the old
page's delayed shutdown too, and loads the next file when a new session is up.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

WORKFLOW = "hitl_files"
ACTION = "review_data"
FILES = {"a.json": ["one", "two"], "b.json": ["three"], "c.json": ["four"]}
SESSION = re.compile(r'<meta name="hitl-session" content="([^"]*)">')


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _project(base: Path, port: int, timeout: int, files: dict[str, list[str]]) -> Path:
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
description: "A HITL review of several files"
version: "0.1.0"
defaults:
  json_mode: true
  run_mode: online
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
      timeout: {timeout}
      instructions: "Review"
    context_scope:
      observe: [extract_data.summary, source.text]
""")
    for name, texts in files.items():
        (directory / "agent_io" / "staging" / name).write_text(
            json.dumps([{"text": text} for text in texts])
        )
    return root


class _Tab(threading.Thread):
    """One browser tab on the review address, reviewing *files* files in turn."""

    def __init__(self, port: int, files: int):
        super().__init__(daemon=True)
        self.base = f"http://127.0.0.1:{port}"
        self.files = files
        self.reviewed: list[list[str]] = []
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            session = self._wait_for_session(None, deadline=time.monotonic() + 240)
            while True:
                self._review(session)
                if len(self.reviewed) == self.files:
                    return
                session = self._wait_for_session(session, deadline=time.monotonic() + 60)
        except BaseException as exc:  # reported by the test thread
            self.error = exc

    def _wait_for_session(self, current: str | None, deadline: float) -> str:
        """The session of the page served now, once it is not *current*."""
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{self.base}/", timeout=5) as response:
                    match = SESSION.search(response.read().decode())
                session = match.group(1) if match else ""
                if current is None or (session and session != current):
                    return session
            except OSError:
                pass
            time.sleep(0.2)
        raise TimeoutError(f"the tab never found the next file after {len(self.reviewed)}")

    def _post(self, path: str, body: dict, session: str) -> dict:
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-HITL-Session": session},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read())

    def _review(self, session: str) -> None:
        with urllib.request.urlopen(f"{self.base}/api/context", timeout=5) as response:
            records = json.loads(response.read())["data"]
        reply = self._post(
            "/api/submit",
            {"record_reviews": [{"hitl_status": "approved", "user_comment": "ok"}] * len(records)},
            session,
        )
        assert reply["success"] is True, reply
        self.reviewed.append([record["text"] for record in records])
        # What the page sent before 1604, which reached the next file's server.
        time.sleep(1.5)
        try:
            self._post("/api/shutdown", {}, session)
        except OSError:
            pass


def _decisions(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Each source text's stored HITL status, and each record's disposition."""
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        statuses = {
            row["content"]["source"]["text"]: row["content"][ACTION]["hitl_status"]
            for name in backend.list_target_files(ACTION)
            for row in backend.read_target(ACTION, name)
            if ACTION in row.get("content", {})
        }
        dispositions = {
            row["record_id"]: row["disposition"] for row in backend.get_disposition(ACTION)
        }
        return statuses, dispositions
    finally:
        backend.close()


def _run(root: Path):
    env = {"OPENAI_API_KEY": "sk-not-used", "AGAC_HITL_AUTO_APPROVE": ""}
    return run_agac(root, "run", "-a", WORKFLOW, "--fresh", env=env)


def _status(root: Path) -> str:
    status_file = root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(status_file.read_text())[ACTION]["status"]


def test_one_tab_reviews_every_file_and_none_is_timed_out_by_it(tmp_path):
    port = _free_port()
    root = _project(tmp_path, port, timeout=20, files=FILES)
    tab = _Tab(port, files=len(FILES))
    tab.start()

    started = time.monotonic()
    result = _run(root)
    took = time.monotonic() - started
    tab.join(timeout=10)

    output = (result.stdout + result.stderr)[-4000:]
    assert result.returncode == 0, output
    assert tab.error is None, (tab.error, output)
    assert tab.reviewed == list(FILES.values()), output
    assert "timed out" not in output, output
    statuses, dispositions = _decisions(root)
    assert statuses == dict.fromkeys(("one", "two", "three", "four"), "approved"), output
    assert set(dispositions.values()) == {"success"}, dispositions
    assert _status(root) == "completed"
    # No file waited out its timeout.
    assert took < 20, (took, output)


def test_a_file_left_unreviewed_is_reported_and_its_records_failed(tmp_path):
    port = _free_port()
    files = {"a.json": ["one", "two"], "b.json": ["three"]}
    root = _project(tmp_path, port, timeout=5, files=files)
    tab = _Tab(port, files=1)  # closed after the first file
    tab.start()

    result = _run(root)
    tab.join(timeout=10)

    # The console wraps lines at its width.
    output = " ".join((result.stdout + result.stderr).split())
    assert tab.error is None, (tab.error, output[-4000:])
    assert "HITL review timed out (0/1 records reviewed) in b.json" in output, output[-4000:]
    assert "b.json left unreviewed" in output, output[-4000:]
    statuses, dispositions = _decisions(root)
    assert statuses == {"one": "approved", "two": "approved"}, output[-4000:]
    assert sorted(dispositions.values()) == ["failed", "success", "success"], dispositions
    assert _status(root) == "completed_with_failures"
