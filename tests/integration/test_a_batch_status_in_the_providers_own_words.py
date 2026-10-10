"""A batch the provider reports in its SDK's own words is asked about until it ends.

The batch registry knows only agac's own statuses. A status outside them was stored as the
SDK gave it, and the run after failed the action without asking the provider; the run
after that sent the action's files again. Every Gemini batch got there, through the state
name stored at submit, and so did an OpenAI batch that expired or was being cancelled.

Each `agac` process imports a stand-in for the SDK's client from a sitecustomize. It
reports whatever state a test gives a batch, and logs every call. GeminiBatchClient and
OpenAIBatchClient run unchanged over it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from tests._support.agac_cli import run_agac
from tests.integration.test_a_batch_the_provider_ends_without_results import _dispositions
from tests.integration.test_a_batch_the_provider_refuses import (
    FIXTURE,
    WORKFLOW,
    _answered,
    _batch_ids,
    _registry,
    _stored_rows,
)

IN_FLIGHT = {status.value for status in BatchStatus.in_flight_states()}

_SDK = """
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

_DIR = Path(os.environ["OFFLINE_SDK_DIR"])


def _log(event, **kw):
    with open(_DIR / "calls.log", "a") as f:
        f.write(json.dumps({"event": event, **kw}) + "\\n")


def _record(batch_id):
    return _DIR / (batch_id.replace("/", "_") + ".json")


def _answer(key):
    return json.dumps({"summary": f"summary of {key}", "exam_density": "low"})


from google import genai
from google.genai import types


class _GeminiFiles:
    def upload(self, file, config=None):
        name = f"files/in-{uuid.uuid4().hex[:8]}"
        (_DIR / (name.replace("/", "_") + ".jsonl")).write_text(Path(file).read_text())
        return NS(name=name)

    def download(self, file):
        sent = file.replace("files/out-", "files/in-").replace("/", "_") + ".jsonl"
        lines = []
        for line in (_DIR / sent).read_text().splitlines():
            key = json.loads(line)["key"]
            lines.append(json.dumps({"key": key, "response": {
                "candidates": [{"content": {"parts": [{"text": _answer(key)}]}}]}}))
        return ("\\n".join(lines) + "\\n").encode()


class _GeminiBatches:
    def create(self, model, src, config=None):
        name = f"batches/{uuid.uuid4().hex[:10]}"
        sent_as = (config or {}).get("display_name")
        _record(name).write_text(json.dumps({"src": src, "state": "JOB_STATE_PENDING"}))
        _log("gemini.batches.create", id=name, file=sent_as)
        return NS(name=name, state=types.JobState.JOB_STATE_PENDING)

    def get(self, name):
        batch = json.loads(_record(name).read_text())
        _log("gemini.batches.get", id=name)
        out = NS(file_name=batch["src"].replace("files/in-", "files/out-"))
        return NS(name=name, state=types.JobState[batch["state"]], dest=out)


class _GeminiClient:
    def __init__(self, *args, **kwargs):
        self.files = _GeminiFiles()
        self.batches = _GeminiBatches()


genai.Client = _GeminiClient

import openai


class _OpenAIFiles:
    def create(self, file, purpose):
        file_id = f"file-in-{uuid.uuid4().hex[:8]}"
        (_DIR / f"{file_id}.jsonl").write_bytes(file.read())
        return NS(id=file_id)

    def content(self, file_id):
        lines = []
        for line in (_DIR / f"{file_id.replace('file-out-', 'file-in-')}.jsonl").read_text().splitlines():
            custom_id = json.loads(line)["custom_id"]
            lines.append(json.dumps({"custom_id": custom_id, "error": None, "response": {
                "status_code": 200,
                "body": {"id": "c", "model": "gpt-4o-mini", "choices": [{
                    "index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": _answer(custom_id)}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}}}))
        return NS(content=("\\n".join(lines) + "\\n").encode())


class _OpenAIBatches:
    def create(self, input_file_id, endpoint, completion_window, **kwargs):
        batch_id = f"batch_{uuid.uuid4().hex[:10]}"
        _record(batch_id).write_text(json.dumps({"src": input_file_id, "state": "validating"}))
        _log("openai.batches.create", id=batch_id)
        return NS(id=batch_id, status="validating")

    def retrieve(self, batch_id):
        batch = json.loads(_record(batch_id).read_text())
        _log("openai.batches.retrieve", id=batch_id)
        finished = batch["state"] == "completed"
        out = batch["src"].replace("file-in-", "file-out-") if finished else None
        return NS(id=batch_id, status=batch["state"], output_file_id=out, error_file_id=None)


class _OpenAIClient:
    def __init__(self, *args, **kwargs):
        self.files = _OpenAIFiles()
        self.batches = _OpenAIBatches()


openai.OpenAI = _OpenAIClient
"""


class _Project:
    """The fixture project on *vendor*, staging two pages in each of a_pages.json and
    b_pages.json, with the SDK's client stood in for."""

    def __init__(self, base: Path, vendor: str, model: str, key: str) -> None:
        self.root = base / "project"
        shutil.copytree(FIXTURE, self.root, ignore=shutil.ignore_patterns("logs"))
        for config in self.root.glob("agent_workflow/*/agent_config/*.yml"):
            config.write_text(
                config.read_text()
                .replace("model_vendor: ollama_cloud", f"model_vendor: {vendor}")
                .replace("model_name: gpt-oss:120b-cloud", f"model_name: {model}")
                .replace("api_key: OLLAMA_API_KEY", f"api_key: {key}")
            )
        (self.root / ".env").write_text(f"{key}=not-used\nOLLAMA_API_KEY=not-used\n")
        staging = self.root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
        for stale in staging.glob("*.json"):
            stale.unlink()
        for prefix in ("a", "b"):
            pages = [
                {"page_id": f"{prefix}{n}", "page_content": f"Page {prefix}{n}."} for n in (1, 2)
            ]
            (staging / f"{prefix}_pages.json").write_text(json.dumps(pages))
        self.sdk = base / "sdk"
        self.sdk.mkdir()
        (self.sdk / "sitecustomize.py").write_text(_SDK)
        self.provider = base / "provider"
        self.provider.mkdir()

    def agac(self, command: str, *args: str) -> SimpleNamespace:
        result = run_agac(
            self.root,
            command,
            "-a",
            WORKFLOW,
            *args,
            env={
                "PYTHONPATH": str(self.sdk),
                "OFFLINE_SDK_DIR": str(self.provider),
                # A wrapped line would split the phrases asserted below.
                "COLUMNS": "240",
            },
        )
        io_dir = self.root / "agent_workflow" / WORKFLOW / "agent_io"
        status = json.loads((io_dir / ".agent_status.json").read_text())["summarize"]["status"]
        return SimpleNamespace(
            code=result.returncode, output=result.stdout + result.stderr, status=status
        )

    def reports(self, batch_id: str, state: str) -> None:
        """Have the provider report *state* for the batch from now on."""
        record = self.provider / (batch_id.replace("/", "_") + ".json")
        batch = json.loads(record.read_text())
        batch["state"] = state
        record.write_text(json.dumps(batch))

    def calls(self, event: str) -> list[dict]:
        log = self.provider / "calls.log"
        lines = log.read_text().splitlines() if log.exists() else []
        return [call for call in map(json.loads, lines) if call["event"] == event]


class TestEveryGeminiBatch:
    """Gemini's SDK names a batch it has just taken JOB_STATE_PENDING."""

    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _Project(
            tmp_path_factory.mktemp("gemini"), "gemini", "gemini-2.5-flash", "GEMINI_API_KEY"
        )
        submitted = project.agac("run", "--fresh")
        recorded = _registry(project.root)
        for batch_id in _batch_ids(project.root).values():
            project.reports(batch_id, "JOB_STATE_SUCCEEDED")
        finished = project.agac("run")
        asked = project.calls("gemini.batches.get")
        again = project.agac("run")
        return SimpleNamespace(
            project=project,
            submitted=submitted,
            recorded=recorded,
            finished=finished,
            asked=asked,
            again=again,
        )

    def test_each_batch_sent_is_recorded_in_flight(self, runs):
        assert runs.submitted.status == "batch_submitted", runs.submitted.output
        assert {entry["status"] for entry in runs.recorded.values()} <= IN_FLIGHT, runs.recorded

    def test_the_run_after_they_finish_asks_gemini_and_completes(self, runs):
        assert {call["id"] for call in runs.asked} == {
            entry["batch_id"] for entry in runs.recorded.values()
        }
        assert runs.finished.code == 0, runs.finished.output
        assert runs.finished.status == "completed", runs.finished.output

    def test_every_record_is_answered(self, runs):
        assert _stored_rows(runs.project.root) == _answered("a", "b")

    def test_no_file_is_sent_twice(self, runs):
        assert runs.again.code == 0, runs.again.output
        sent = sorted(call["file"] for call in runs.project.calls("gemini.batches.create"))
        assert sent == ["a_pages.json", "b_pages.json"]


def _openai_project(base: Path) -> _Project:
    return _Project(base, "openai", "gpt-4o-mini", "OPENAI_API_KEY")


class TestAnOpenAIBatchThatExpiredBesideOneThatFinished:
    """a_pages.json's batch finishes; b_pages.json's runs out of its 24 hours."""

    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        project = _openai_project(tmp_path_factory.mktemp("expired"))
        project.agac("run", "--fresh")
        sent = _batch_ids(project.root)
        project.reports(sent["a_pages.json"], "completed")
        project.reports(sent["b_pages.json"], "expired")
        ended = project.agac("run")
        stored = _stored_rows(project.root)
        dispositions = _dispositions(project.root)
        retried = project.agac("retry")
        resent = {
            name: batch_id
            for name, batch_id in _batch_ids(project.root).items()
            if batch_id not in sent.values()
        }
        for batch_id in resent.values():
            project.reports(batch_id, "completed")
        collected = project.agac("run")
        return SimpleNamespace(
            project=project,
            sent=sent,
            ended=ended,
            stored=stored,
            dispositions=dispositions,
            retried=retried,
            resent=resent,
            collected=collected,
        )

    def test_the_run_that_finds_it_collects_the_file_beside_it(self, runs):
        assert runs.ended.code == 0, runs.ended.output
        assert runs.ended.status == "completed_with_failures", runs.ended.output
        assert runs.stored == _answered("a")

    def test_its_records_are_marked_failed_naming_the_batch(self, runs):
        assert [disposition for disposition, _ in runs.dispositions] == [
            "failed",
            "failed",
            "success",
            "success",
        ]
        reasons = [reason for disposition, reason in runs.dispositions if disposition == "failed"]
        assert all(runs.sent["b_pages.json"] in reason for reason in reasons), reasons

    def test_the_run_names_the_file_and_its_batch(self, runs):
        assert f"Could not read b_pages.json (batch {runs.sent['b_pages.json']})" in (
            runs.ended.output
        )

    def test_agac_retry_sends_only_its_file_and_every_record_ends_answered(self, runs):
        assert runs.retried.code == 0, runs.retried.output
        assert list(runs.resent) == ["b_pages.json"], runs.retried.output
        assert runs.collected.status == "completed", runs.collected.output
        assert _stored_rows(runs.project.root) == _answered("a", "b")


class TestAnOpenAIBatchTheProviderHasNotEndedBesideOneThatFinished:
    """a_pages.json's batch finishes. A run asks about b_pages.json's while it is being
    cancelled, or while the provider reports a status no mapping knows, as an SDK can
    add; the run after asks again, once it has ended."""

    @pytest.fixture(
        scope="class",
        params=[
            pytest.param(
                ("cancelling", "cancelled", "completed_with_failures", "a", False), id="cancel"
            ),
            pytest.param(("on_hold", "completed", "completed", "ab", True), id="unmapped"),
        ],
    )
    def runs(self, request, tmp_path_factory):
        reported, ended_as, finishes_as, answered, unmapped = request.param
        project = _openai_project(tmp_path_factory.mktemp(reported))
        project.agac("run", "--fresh")
        sent = _batch_ids(project.root)
        project.reports(sent["a_pages.json"], "completed")
        project.reports(sent["b_pages.json"], reported)
        waiting = project.agac("run")
        recorded = _registry(project.root)["b_pages.json"]["status"]
        project.reports(sent["b_pages.json"], ended_as)
        asked_before = len(project.calls("openai.batches.retrieve"))
        ended = project.agac("run")
        asked = project.calls("openai.batches.retrieve")[asked_before:]
        return SimpleNamespace(
            project=project,
            sent=sent,
            reported=reported,
            waiting=waiting,
            recorded=recorded,
            ended=ended,
            asked=asked,
            finishes_as=finishes_as,
            answered=answered,
            unmapped=unmapped,
        )

    def test_the_run_that_finds_it_waits_for_it(self, runs):
        assert runs.waiting.code == 0, runs.waiting.output
        assert runs.waiting.status == "batch_submitted", runs.waiting.output
        assert runs.recorded in IN_FLIGHT

    def test_the_run_after_asks_the_provider_and_finishes_the_action(self, runs):
        assert runs.sent["b_pages.json"] in {call["id"] for call in runs.asked}
        assert runs.ended.code == 0, runs.ended.output
        assert runs.ended.status == runs.finishes_as, runs.ended.output
        assert _stored_rows(runs.project.root) == _answered(*runs.answered)

    def test_only_a_status_no_mapping_knows_is_named_with_its_batch(self, runs):
        named = [line for line in runs.waiting.output.splitlines() if f"'{runs.reported}'" in line]
        if runs.unmapped:
            assert any(runs.sent["b_pages.json"] in line for line in named), runs.waiting.output
        else:
            assert named == [], runs.waiting.output
