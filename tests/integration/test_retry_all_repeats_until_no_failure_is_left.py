"""`agac retry --all` retries again while a pass closes an open failure.

One `agac retry` starts at the earliest action that holds a failure, so a failure of
another record in a sibling action stays, and each project wrote its own loop around
the command. `--all` is that loop: after each pass it reads the failures again, prints
how many are open, and stops when none is left, when a pass closed none of them, or
after `--max-passes`.

Every command is run through the CLI against a stub server. Two sibling actions read
the same pages; the server can refuse one page for each of them.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests._support.agac_cli import run_agac
from tests._support.fake_endpoint import FakeEndpoint

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "retry_all_probe"
PAGES = 3
MAX_ATTEMPTS = 2
RECORD_FAILURES = 3
QUOTA_STOP = 5
# (model, page) the provider answers with 429 while it is refusing.
REFUSED = (("model-a", "Page 1."), ("model-b", "Page 2."))

SCHEMA = """name: classify
fields:
  - id: label
    type: string
"""


class _Provider(FakeEndpoint):
    """Refuses one page for each sibling action while `refusing`; `status` is what it answers."""

    def __init__(self) -> None:
        super().__init__()
        self.sdk_retries = False
        self.refusing = True
        self.status = 429

    def answer(self, body: Any, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        text = json.dumps(body)
        if self.refusing and any(model in text and page in text for model, page in REFUSED):
            return self.status, {"error": {"message": "the provider said no", "type": "stub"}}
        return super().answer(body, headers)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


@pytest.fixture
def provider() -> Iterator[_Provider]:
    with _Provider() as endpoint:
        yield endpoint


def _sibling(name: str, model: str) -> str:
    return f"""  - name: {name}
    intent: "Verify"
    model_name: {model}
    schema: classify
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
"""


@pytest.fixture
def project(tmp_path, provider) -> Path:
    """A finished run that left one exhausted record in each of two sibling actions."""
    root = tmp_path / "project"
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
description: "Two sibling actions on a declared endpoint"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: lab
  retry: {{ enabled: true, max_attempts: {MAX_ATTEMPTS}, base_delay: 0.01 }}
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
{_sibling("verify_a", "model-a")}{_sibling("verify_b", "model-b")}"""
    )
    rows = [{"page_id": f"p{i}", "page_content": f"Page {i}."} for i in range(PAGES)]
    (directory / "agent_io" / "staging" / "pages.json").write_text(json.dumps(rows))

    code, output = _agac(root, provider, "run", "--fresh", "--execution-mode", "sequential")
    assert code == RECORD_FAILURES, output
    assert _open_failures(root) == {"verify_a": 1, "verify_b": 1}, output
    return root


def _agac(root: Path, provider: FakeEndpoint, command: str, *args: str) -> tuple[int, str]:
    """The exit code and the output, as one line: the console wraps a long message."""
    result = run_agac(root, command, "-a", WORKFLOW, *args, env={"LAB_URL": provider.base_url})
    return result.returncode, " ".join((result.stdout + result.stderr).split())


def _open_failures(root: Path) -> dict[str, int]:
    (db,) = (root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select action_name, count(*) from record_disposition"
            " where disposition in ('failed', 'exhausted') group by action_name"
        )
        return dict(rows)
    finally:
        con.close()


def test_one_plain_retry_leaves_the_failure_in_the_sibling_action(project, provider):
    """What `--all` is for: the retry starts at one sibling and never names the other's record."""
    provider.refusing = False

    code, output = _agac(project, provider, "retry")

    assert sorted(_open_failures(project).values()) == [1], output
    assert code == RECORD_FAILURES, output
    assert "or use --all" in output, output


def test_exhausted_records_in_two_sibling_actions_are_all_repaired_by_one_retry_all(
    project, provider
):
    provider.refusing = False

    code, output = _agac(project, provider, "retry", "--all")

    assert _open_failures(project) == {}, output
    assert code == 0, output
    assert "Pass 1: 1 open failure(s) left" in output, output
    assert "Pass 2: 0 open failure(s) left" in output, output


def test_with_a_provider_that_always_fails_it_stops_after_one_pass_with_no_progress(
    project, provider
):
    code, output = _agac(project, provider, "retry", "--all")

    assert _open_failures(project) == {"verify_a": 1, "verify_b": 1}, output
    assert code == RECORD_FAILURES, output
    assert "Pass 1: 2 open failure(s) left" in output, output
    assert "Pass 2" not in output, output
    assert "closed none of the open failures" in output, output


def test_max_passes_stops_it_while_failures_remain(project, provider):
    provider.refusing = False

    code, output = _agac(project, provider, "retry", "--all", "--max-passes", "1")

    assert sorted(_open_failures(project).values()) == [1], output
    assert code == RECORD_FAILURES, output
    assert "Pass 1: 1 open failure(s) left" in output, output
    assert "Pass 2" not in output, output
    assert "--max-passes 1" in output, output


def test_with_nothing_to_retry_it_exits_0_without_a_pass(project, provider):
    provider.refusing = False
    _agac(project, provider, "retry", "--all")

    code, output = _agac(project, provider, "retry", "--all")

    assert code == 0, output
    assert "Nothing to retry" in output, output
    assert "Pass 1" not in output, output


def test_a_quota_stop_ends_it_with_exit_5(project, provider):
    provider.status = 402

    code, output = _agac(project, provider, "retry", "--all")

    assert code == QUOTA_STOP, output
    assert "Provider quota or billing stop (lab)" in output, output
    assert "Pass 2" not in output, output


def test_a_dry_run_counts_the_open_failures_and_changes_nothing(project, provider):
    sent_before = len(provider.requests)

    code, output = _agac(project, provider, "retry", "--all", "--dry-run")

    assert code == 0, output
    assert "2 open failure(s)" in output, output
    assert "Dry run" in output, output
    assert _open_failures(project) == {"verify_a": 1, "verify_b": 1}
    assert len(provider.requests) == sent_before


@pytest.mark.parametrize(
    ("args", "named"),
    [
        (["--all", "--from", "verify_b"], "--from"),
        (["--all", "--record", "some-guid"], "--record"),
        (["--all", "--filter", "verify_a:some-guid", "--reason", "known bad"], "--filter"),
        (["--max-passes", "2"], "--all"),
    ],
)
def test_a_combination_with_no_clear_meaning_is_a_usage_error(project, provider, args, named):
    code, output = _agac(project, provider, "retry", *args)

    assert code == 2, output
    assert named in output, output
    assert _open_failures(project) == {"verify_a": 1, "verify_b": 1}
