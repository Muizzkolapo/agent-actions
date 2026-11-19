"""A provider that answers "the quota is used up" stops the run; the next run resumes it.

The answer was handled as a rate limit or as one record's error, so every record left
failed or exhausted its retries and the run went on to the next actions. Now nothing is
retried, no new record is sent, the records without an answer keep no failure, and the
run ends with one message and exit code 5. A plain `agac run` finishes them once the
quota is back, with no `agac retry`.

Every run is an `agac run` through the CLI against a stub server.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests._support.agac_cli import run_agac
from tests._support.fake_endpoint import FakeEndpoint

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "quota_probe"
PAGES = 6
QUOTA_STOP = 5
PROVIDER_TEXT = "You have reached your monthly usage limit. Add usage credits to continue."

SCHEMA = """name: classify
fields:
  - id: label
    type: string
"""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


@pytest.fixture
def provider() -> Iterator[FakeEndpoint]:
    with FakeEndpoint() as endpoint:
        endpoint.sdk_retries = False
        endpoint.error_message = PROVIDER_TEXT
        yield endpoint


def _project(base: Path, defaults: str = "") -> Path:
    root = base / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    project_file = root / "agent_actions.yml"
    project_file.write_text(
        project_file.read_text() + "\nendpoints:\n  lab:\n    url: ${LAB_URL}\n    auth: none\n"
    )
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW / "classify.yml").write_text(SCHEMA)
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"""name: {WORKFLOW}
description: "Two actions on a declared endpoint"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: lab
  model_name: local-7b
  retry: {{ enabled: true, max_attempts: 3, base_delay: 0.01 }}
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
{defaults}actions:
  - name: classify
    intent: "Classify"
    schema: classify
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
  - name: report
    dependencies: [classify]
    intent: "Report"
    schema: classify
    prompt: $p.Summarize
    context_scope: {{ observe: [classify.label, source.page_content] }}
"""
    )
    rows = [{"page_id": f"p{i}", "page_content": f"Page {i}."} for i in range(PAGES)]
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(rows))
    return root


def _run(root: Path, provider: FakeEndpoint, *args: str) -> tuple[int, str]:
    """The exit code and the output, as one line: the console wraps a long message."""
    result = run_agac(root, "run", "-a", WORKFLOW, *args, env={"LAB_URL": provider.base_url})
    return result.returncode, " ".join((result.stdout + result.stderr).split())


def _dispositions(root: Path, action: str) -> list[str]:
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select disposition from record_disposition"
            " where action_name = ? and record_id != '__node__'",
            (action,),
        )
        return sorted(row[0] for row in rows)
    finally:
        con.close()


def _statuses(root: Path) -> dict[str, str]:
    status_file = root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return {
        name: details["status"] for name, details in json.loads(status_file.read_text()).items()
    }


class TestAProviderThatAnswers402AfterThreeRecords:
    @pytest.fixture
    def stopped(self, tmp_path, provider) -> tuple[Path, int, str]:
        root = _project(tmp_path)
        provider.statuses = [200] * 3 + [402] * 50
        code, output = _run(root, provider, "--fresh")
        return root, code, output

    def test_the_run_stops_with_the_quota_exit_code(self, stopped):
        _, code, output = stopped

        assert code == QUOTA_STOP, output

    def test_three_records_are_success_and_the_rest_hold_no_disposition(self, stopped):
        root, _, output = stopped

        assert _dispositions(root, "classify") == ["success"] * 3, output

    def test_the_record_that_met_the_quota_is_not_retried_and_no_other_is_sent(
        self, stopped, provider
    ):
        assert len(provider.requests) == 4

    def test_the_run_does_not_go_on_to_the_next_action(self, stopped):
        root, _, output = stopped

        assert _statuses(root) == {"classify": "interrupted", "report": "pending"}, output
        assert _dispositions(root, "report") == []

    def test_it_ends_with_one_message_naming_the_provider_its_text_and_the_remedy(self, stopped):
        _, _, output = stopped

        assert output.count(PROVIDER_TEXT) == 1, output
        assert "Provider quota or billing stop (lab)" in output
        assert "Add credits, then run again to resume." in output

    def test_a_second_run_with_the_quota_back_finishes_with_no_retry(self, stopped, provider):
        root, _, _ = stopped
        provider.statuses = []
        sent_before = len(provider.requests)

        code, output = _run(root, provider)

        assert code == 0, output
        assert _dispositions(root, "classify") == ["success"] * PAGES
        assert _dispositions(root, "report") == ["success"] * PAGES
        assert _statuses(root) == {"classify": "completed", "report": "completed"}
        # The three it answered before the stop are not asked again.
        assert len(provider.requests) - sent_before == (PAGES - 3) + PAGES

    def test_a_second_run_while_the_quota_is_still_used_up_stops_again(self, stopped, provider):
        root, _, _ = stopped

        code, output = _run(root, provider)

        assert code == QUOTA_STOP, output
        assert _dispositions(root, "classify") == ["success"] * 3


def test_a_plain_429_is_still_retried_and_exhausts_its_record(tmp_path, provider):
    """The other side: a rate limit is retried as before and never stops the run."""
    root = _project(tmp_path)
    provider.error_message = "slow down"
    provider.statuses = [200, 429, 429, 429]

    code, output = _run(root, provider, "--fresh")

    assert code == 3, output
    assert _dispositions(root, "classify") == ["exhausted"] + ["success"] * (PAGES - 1)
    assert "quota or billing stop" not in output


class TestARetryThatMeetsTheQuota:
    @pytest.fixture
    def one_exhausted(self, tmp_path, provider) -> Path:
        root = _project(tmp_path)
        provider.error_message = "slow down"
        provider.statuses = [200, 429, 429, 429]
        code, output = _run(root, provider, "--fresh")
        assert code == 3, output
        provider.error_message = PROVIDER_TEXT
        return root

    def _retry(self, root: Path, provider: FakeEndpoint) -> tuple[int, str]:
        result = run_agac(root, "retry", "-a", WORKFLOW, env={"LAB_URL": provider.base_url})
        return result.returncode, " ".join((result.stdout + result.stderr).split())

    def test_it_stops_with_the_quota_exit_code_and_one_message(self, one_exhausted, provider):
        provider.statuses = [402] * 10

        code, output = self._retry(one_exhausted, provider)

        assert code == QUOTA_STOP, output
        assert output.count(PROVIDER_TEXT) == 1, output
        assert "Retry complete." not in output

    def test_the_next_retry_resumes_it_once_the_quota_is_back(self, one_exhausted, provider):
        provider.statuses = [402] * 10
        self._retry(one_exhausted, provider)
        provider.statuses = []

        code, output = self._retry(one_exhausted, provider)

        assert code == 0, output
        assert _dispositions(one_exhausted, "classify") == ["success"] * PAGES
        assert _dispositions(one_exhausted, "report") == ["success"] * PAGES


class _OneRecordMeetsTheQuotaWhileAnotherIsAnswered(FakeEndpoint):
    """Page 1 is refused at once; page 0, sent with it, is answered a moment later."""

    def answer(self, body: Any, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        text = json.dumps(body)
        if "Page 1." in text:
            return 402, {"error": {"message": PROVIDER_TEXT, "type": "stub"}}
        if "Page 0." in text:
            time.sleep(0.5)
        return super().answer(body, headers)


def test_records_in_flight_finish_and_no_new_record_is_sent(tmp_path):
    root = _project(tmp_path, defaults="  record_concurrency: 2\n")
    with _OneRecordMeetsTheQuotaWhileAnotherIsAnswered() as provider:
        provider.sdk_retries = False
        provider.gather = 2

        code, output = _run(root, provider, "--fresh")

        assert code == QUOTA_STOP, output
        assert len(provider.requests) == 2, "a record was sent after the quota answer"
        assert _dispositions(root, "classify") == ["success"], output
        assert output.count(PROVIDER_TEXT) == 1, output


class _OneModelIsOutOfQuota(FakeEndpoint):
    """Every request for `model-a` is refused; any other model is answered."""

    def answer(self, body: Any, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        if isinstance(body, dict) and body.get("model") == "model-a":
            return 402, {"error": {"message": PROVIDER_TEXT, "type": "stub"}}
        return super().answer(body, headers)


SIBLINGS = """actions:
  - name: on_a
    intent: "Classify"
    model_name: model-a
    schema: classify
    prompt: $p.Summarize
    context_scope: { observe: [source.page_content] }
  - name: on_b
    intent: "Classify"
    model_name: model-b
    schema: classify
    prompt: $p.Summarize
    context_scope: { observe: [source.page_content] }
  - name: report
    dependencies: [on_a, on_b]
    intent: "Report"
    schema: classify
    prompt: $p.Summarize
    context_scope: { observe: [on_a.label, on_b.label, source.page_content] }
"""


def test_an_action_running_beside_it_finishes_and_the_run_then_stops(tmp_path):
    """Two actions of one level run at once; only one of them meets the quota."""
    root = _project(tmp_path)
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    text = config.read_text()
    config.write_text(text[: text.index("actions:")] + SIBLINGS)
    with _OneModelIsOutOfQuota() as provider:
        provider.sdk_retries = False

        code, output = _run(root, provider, "--fresh", "--execution-mode", "parallel")

        assert code == QUOTA_STOP, output
        assert _statuses(root) == {
            "on_a": "interrupted",
            "on_b": "completed",
            "report": "pending",
        }, output
        assert _dispositions(root, "on_a") == []
        assert _dispositions(root, "on_b") == ["success"] * PAGES
        assert output.count(PROVIDER_TEXT) == 1, output
        assert "action(s) failed" not in output, output
