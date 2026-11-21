"""`agac dispositions --json` prints one document a script reads without `.get`.

Every action is there, and under `counts` every key the summary can show, 0 where
the action holds none. The keys are the table's headers in snake_case; scripts read
them, so the exact set is pinned here.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from agent_actions.cli.dispositions import (
    COUNT_KEYS,
    TABLE_COUNTS,
    dispositions,
    dispositions_report,
)
from agent_actions.record.reasons import EXPECTATIONS_FAILED, HALTED_ON_EXHAUSTED
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID, VALID_DISPOSITIONS
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

WORKFLOW = "wf"
EVERY_COUNT = {
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


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store" / f"{WORKFLOW}.db"), WORKFLOW)
    store.initialize()
    yield store
    store.close()


def _counts(report: dict, action: str) -> dict[str, int]:
    return next(entry for entry in report["actions"] if entry["name"] == action)["counts"]


def test_the_document_holds_exactly_these_keys(backend):
    backend.set_disposition("extract", "r1", "success")

    report = dispositions_report(backend, WORKFLOW, ["extract"])

    assert set(report) == {"workflow", "actions"}
    assert report["workflow"] == WORKFLOW
    (entry,) = report["actions"]
    assert set(entry) == {"name", "counts", "total", "sent_elsewhere", "records", "action_level"}
    assert set(entry["counts"]) == EVERY_COUNT == set(COUNT_KEYS)


def test_an_action_with_no_disposition_is_listed_with_every_count_at_zero(backend):
    backend.set_disposition("extract", "r1", "success")

    report = dispositions_report(backend, WORKFLOW, ["extract", "publish"])

    assert [entry["name"] for entry in report["actions"]] == ["extract", "publish"]
    publish = report["actions"][1]
    assert publish["counts"] == dict.fromkeys(COUNT_KEYS, 0)
    assert publish["total"] == 0
    assert publish["records"] == 0
    assert publish["action_level"] == []


@pytest.mark.parametrize("disposition", sorted(VALID_DISPOSITIONS))
def test_every_disposition_the_store_takes_is_counted_under_one_key(backend, disposition):
    backend.set_disposition("extract", "r1", disposition)

    (entry,) = dispositions_report(backend, WORKFLOW, ["extract"])["actions"]

    assert sum(entry["counts"].values()) == entry["total"] == 1
    assert entry["counts"][disposition] == 1


def test_the_counts_are_the_ones_the_table_shows(backend):
    backend.set_disposition("rewrite", "r1", "success")
    backend.set_disposition("rewrite", "r2", "success", reason=EXPECTATIONS_FAILED)
    backend.set_disposition("rewrite", "r3", "failed", reason="boom")
    backend.set_disposition("rewrite", "r4", "exhausted", reason="worn out")
    backend.set_disposition("rewrite", "r5", "exhausted", reason="worn out")
    backend.set_disposition("rewrite", "r6", "unprocessed", reason="guard_skip")
    backend.set_disposition("rewrite", "r7", "unprocessed", reason="upstream_unprocessed")
    backend.set_disposition("rewrite", "r8", "filtered")
    backend.write_target("rewrite", "a.json", [{"source_guid": "r1"}], force_full=True)

    (entry,) = dispositions_report(backend, WORKFLOW, ["rewrite"])["actions"]

    assert entry["counts"] == {
        "success": 1,
        "failed_checks": 1,
        "failed": 1,
        "exhausted": 2,
        "guard_skipped": 1,
        "unprocessed": 1,
        "passthrough": 0,
        "filtered": 1,
        "skipped": 0,
        "deferred": 0,
    }
    assert entry["total"] == 8
    assert entry["records"] == 1


def test_an_actions_own_failure_is_not_a_record_and_is_listed_beside_the_counts(backend):
    backend.set_disposition("summarize", "r1", "exhausted", reason="worn out")
    backend.set_disposition(
        "summarize",
        NODE_LEVEL_RECORD_ID,
        "failed",
        reason="Retry exhausted for record r1",
        detail=HALTED_ON_EXHAUSTED,
    )
    backend.set_disposition("publish", NODE_LEVEL_RECORD_ID, "failed", reason="no input")

    summarize, publish = dispositions_report(backend, WORKFLOW, ["summarize", "publish"])["actions"]

    assert summarize["total"] == 1 and summarize["counts"]["failed"] == 0
    assert summarize["action_level"] == [
        {"state": "failed", "halted": True, "reason": "Retry exhausted for record r1"}
    ]
    assert publish["total"] == 0
    assert publish["action_level"] == [{"state": "failed", "halted": False, "reason": "no input"}]


def test_a_record_count_that_cannot_be_read_is_null_and_not_zero(backend, monkeypatch):
    backend.set_disposition("extract", "r1", "success")
    monkeypatch.setattr(backend, "get_storage_stats", lambda: 1 / 0)

    (entry,) = dispositions_report(backend, WORKFLOW, ["extract"])["actions"]

    assert entry["records"] is None


def test_json_does_not_take_quarantined(tmp_path, monkeypatch):
    (tmp_path / "agent_actions.yml").write_text("default_agent_config: {}\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(dispositions, ["-w", WORKFLOW, "--json", "--quarantined"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--json" in result.stderr and "--quarantined" in result.stderr


def test_each_count_key_is_its_table_header_in_snake_case():
    assert {key: header.lower().replace(" ", "_") for key, (header, _) in TABLE_COUNTS.items()} == {
        key: key for key in TABLE_COUNTS
    }
    assert COUNT_KEYS[: len(TABLE_COUNTS)] == tuple(TABLE_COUNTS)


def test_the_report_is_plain_json(backend):
    backend.set_disposition("extract", "r1", "success")
    report = dispositions_report(backend, WORKFLOW, ["extract"])

    assert json.loads(json.dumps(report)) == report
