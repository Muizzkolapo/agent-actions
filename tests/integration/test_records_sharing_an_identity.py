"""Byte-identical records are one record, and every table has to say so.

`source_guid` is a content hash and the store is built around that: `source_data`
is unique on (path, guid) and `record_disposition` on (action, record_id), so
three byte-identical staged records are one source row and one disposition.

`target_data` is a JSON blob with no such constraint, and the list handed to
processing is not deduplicated, so a run writes one output row per *staged
record* while every other table counts one per *identity*. The tables disagree,
and the identity-keyed paths — carry-forward, retry — then rewrite the action to
what they believe, which looks like rows being deleted.
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


class TestARunStoresOneRowPerIdentity:
    def test_the_target_holds_one_row_per_identity(self, duplicated):
        assert _counts(duplicated)["target"] == 4

    def test_every_table_agrees_how_many_records_there_are(self, duplicated):
        """The tables that constrain identity already say four. The one that
        cannot constrain it must not say something else."""
        counts = _counts(duplicated)

        assert counts["target"] == counts["source"] == counts["dispositions"], counts


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
