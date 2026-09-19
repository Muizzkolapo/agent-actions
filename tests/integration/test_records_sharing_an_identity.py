"""A record staged twice is two records, and every table has to say so.

`source_guid` is derived from a record's content, so two byte-identical staged
records land on one identity. The store is keyed on it — `source_data` is unique
on (path, guid), `record_disposition` on (action, record_id) — so the second
record is dropped on write and never gets a disposition, while the output blob,
which has no such constraint, keeps both.

The tables then disagree about how many records exist, and the identity-keyed
paths rewrite the action to what they believe: carry-forward emits one row per
identity, so a retry drops the extra rows.

What the user staged is what they get back. Repeating content is not an error to
correct on their behalf, so a repeat is given its own identity, keeping the
content hash as its parent — the same move an expansion makes for its children,
for the same reason.
"""

import glob
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "tool_action"
ACTION = "flatten"


@pytest.fixture
def duplicated(tmp_path, monkeypatch):
    """Six staged records, three of them byte-identical: four identities."""
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(
        json.dumps([{"page_content": "same"}] * 3 + [{"page_content": c} for c in ("a", "b", "c")])
    )
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return root


def _counts(project):
    db = glob.glob(str(project / "agent_workflow" / WORKFLOW / "agent_io" / "store" / "*.db"))[0]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        source = con.execute("select count(*) from source_data").fetchone()[0]
        dispositions = con.execute(
            "select count(*) from record_disposition where action_name = ? and record_id != ?",
            (ACTION, "__node__"),
        ).fetchone()[0]
        target = 0
        for (blob,) in con.execute("select data from target_data where action_name = ?", (ACTION,)):
            rows = json.loads(blob)
            target += len(rows) if isinstance(rows, list) else 1
    finally:
        con.close()
    return {"source": source, "dispositions": dispositions, "target": target}


class TestARunKeepsEveryStagedRecord:
    def test_the_source_holds_every_staged_record(self, duplicated):
        """The one the store dropped. Six staged, six kept."""
        assert _counts(duplicated)["source"] == 6

    def test_every_staged_record_gets_a_disposition(self, duplicated):
        assert _counts(duplicated)["dispositions"] == 6

    def test_the_target_holds_every_staged_record(self, duplicated):
        assert _counts(duplicated)["target"] == 6

    def test_every_table_agrees_how_many_records_there_are(self, duplicated):
        """Six, on every side. A table that cannot hold a repeat is the reason
        the repeat needs an identity of its own, not a reason to drop it."""
        counts = _counts(duplicated)

        assert counts == {"source": 6, "dispositions": 6, "target": 6}, counts

    def test_a_repeat_keeps_the_content_hash_as_its_parent(self, duplicated):
        """Lineage, so the repeat is still resolvable to the content it repeats."""
        db = glob.glob(
            str(duplicated / "agent_workflow" / WORKFLOW / "agent_io" / "store" / "*.db")
        )[0]
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = [json.loads(d) for (d,) in con.execute("select data from source_data")]
        finally:
            con.close()

        parents = [r.get("parent_source_guid") for r in rows if r.get("parent_source_guid")]
        assert len(parents) == 2, "two of the three identical records are repeats"
        assert len(set(parents)) == 1, "both point at the identity they repeat"
        assert set(parents) <= {r["source_guid"] for r in rows}, "the parent is a real record"


class TestARetryChangesNothing:
    def test_the_row_count_is_the_same_afterwards(self, duplicated):
        """Carry-forward rebuilds an action keyed by identity. It can only leave
        the count alone if the count was per identity to begin with."""
        before = _counts(duplicated)
        db = glob.glob(
            str(duplicated / "agent_workflow" / WORKFLOW / "agent_io" / "store" / "*.db")
        )[0]
        con = sqlite3.connect(db)
        rid = con.execute(
            "select record_id from record_disposition where action_name = ? and record_id != ?",
            (ACTION, "__node__"),
        ).fetchone()[0]
        con.execute(
            "update record_disposition set disposition = 'failed' where record_id = ?", (rid,)
        )
        con.commit()
        con.close()

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", rid])

        assert retry.exit_code == 0, retry.output
        assert _counts(duplicated) == before
