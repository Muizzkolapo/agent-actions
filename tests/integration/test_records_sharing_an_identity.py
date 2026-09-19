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
    # Anchor the number: without it a run that stored nothing satisfies every
    # "the tables agree" assertion below with zero on all three sides.
    assert _counts(root)["source"] == 4, "six staged records are four identities"
    return root


def _disposition(project, record_id, action=ACTION):
    db = glob.glob(str(project / "agent_workflow" / WORKFLOW / "agent_io" / "store" / "*.db"))[0]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = con.execute(
            "select disposition from record_disposition where action_name = ? and record_id = ?",
            (action, record_id),
        ).fetchone()
    finally:
        con.close()
    return row[0] if row else None


def _an_identity(project, action=ACTION):
    db = glob.glob(str(project / "agent_workflow" / WORKFLOW / "agent_io" / "store" / "*.db"))[0]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(
            "select record_id from record_disposition where action_name = ? and record_id != ?",
            (action, "__node__"),
        ).fetchone()[0]
    finally:
        con.close()


def _fail(project, record_id, action=ACTION):
    db = glob.glob(str(project / "agent_workflow" / WORKFLOW / "agent_io" / "store" / "*.db"))[0]
    con = sqlite3.connect(db)
    try:
        con.execute(
            "update record_disposition set disposition = 'failed' "
            "where action_name = ? and record_id = ?",
            (action, record_id),
        )
        con.commit()
    finally:
        con.close()


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

    def test_the_tables_agree_within_one_input_file(self, duplicated):
        """The tables that constrain identity already say four. The one that
        cannot constrain it must not say something else.

        Within one file. `source_data` is unique per (path, guid) and the list is
        reduced per file, but `record_disposition` is unique on (action, record_id)
        with no path — so across files the disposition count is the number of
        distinct identities overall, not the sum per file. See the two-file case
        below."""
        counts = _counts(duplicated)

        assert counts["target"] == counts["source"] == counts["dispositions"], counts


class TestARetryChangesNothing:
    def test_the_row_count_is_the_same_afterwards(self, duplicated):
        """Carry-forward rebuilds an action keyed by identity. It can only leave
        the count alone if the count was per identity to begin with."""
        before = _counts(duplicated)
        rid = _an_identity(duplicated)
        _fail(duplicated, rid)

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", rid])

        assert retry.exit_code == 0, retry.output
        assert "Nothing to retry" not in retry.output, retry.output
        assert _disposition(duplicated, rid) == "success", "the retry did not run"
        assert _counts(duplicated) == before


class TestARetryUnderALimit:
    """The limit dimension the replaced class carried. A limit keeps positions;
    after dedup those positions are identities, so a repair under one neither
    grows nor shrinks the action."""

    def test_the_row_count_is_unchanged(self, duplicated, monkeypatch):
        before = _counts(duplicated)
        rid = _an_identity(duplicated)
        _fail(duplicated, rid)
        monkeypatch.setenv("AGAC_RECORD_LIMIT", "1")

        retry = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", rid])

        assert retry.exit_code == 0, retry.output
        assert _disposition(duplicated, rid) == "success", "the retry did not run"
        assert _counts(duplicated) == before


class TestTheSameRecordInTwoFiles:
    """Identity is scoped per input file on both sides — the store's constraint is
    UNIQUE(relative_path, source_guid), and the list is reduced per file because
    that is the unit it is saved as. A record staged in two files is two records."""

    @pytest.fixture
    def across_files(self, tmp_path, monkeypatch):
        root = tmp_path / "project"
        shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
        staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for name in ("a_pages.json", "b_pages.json"):
            # duplicated within the file as well as across the two, so the
            # assertion distinguishes "reduced per file" from "not reduced"
            staging.joinpath(name).write_text(
                json.dumps([{"page_content": "shared"}] * 2 + [{"page_content": f"only in {name}"}])
            )
        monkeypatch.chdir(root)
        monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
        result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
        assert result.exit_code == 0, result.output
        return root

    def test_it_is_kept_once_per_file_not_once_overall(self, across_files):
        """Six staged across two files, two identities in each: four rows. Not six,
        which is no reduction, and not three, which would be reducing globally."""
        counts = _counts(across_files)

        assert counts["target"] == 4, counts

    def test_target_and_source_agree_per_file(self, across_files):
        counts = _counts(across_files)

        assert counts["target"] == counts["source"] == 4, counts

    def test_dispositions_count_identities_not_rows(self, across_files):
        """Not a disagreement to fix — `record_disposition` carries no
        `relative_path`, so an identity staged in two files has one disposition
        and two rows. Pinned so the per-file claim above is not read as global."""
        counts = _counts(across_files)

        assert counts["dispositions"] == 3, counts
