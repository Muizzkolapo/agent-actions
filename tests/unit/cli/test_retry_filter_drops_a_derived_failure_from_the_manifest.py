"""`agac retry --filter` rewrites a live retry manifest by the rule it applies to the store.

Below the filtered action, a reader's `unprocessed` row for the record goes, and so does a
failure row at a reader holding a stored row (a tombstone) for the record, which the
command removes: once filtered the reader drops the record, so no retry could reach that
failure (1907). A failure at a reader holding no tombstone for the record stays.
"""

import json

from agent_actions.cli.retry_filter import RetryFilterCommand

FILTERED = ("extract", "r1", "filtered", "refused", "pages.json", None, "by hand")


def _row(action: str, record_id: str, disposition: str) -> dict:
    return {"action_name": action, "record_id": record_id, "disposition": disposition}


def _rewrite(tmp_path, dispositions: list[dict], tombstoned: set[tuple[str, str]]) -> list:
    manifest_file = tmp_path / "_retry_manifest.json"
    manifest = {"created_at": "t0", "dispositions": dispositions}
    manifest_file.write_text(json.dumps(manifest))

    RetryFilterCommand._filter_the_manifest(
        manifest_file, manifest, [FILTERED], {"extract": ["review", "publish"]}, tombstoned
    )

    return [
        (row["action_name"], row["record_id"], row["disposition"])
        for row in json.loads(manifest_file.read_text())["dispositions"]
    ]


def test_a_failure_beside_the_tombstone_removed_goes(tmp_path):
    kept = _rewrite(
        tmp_path,
        [
            _row("extract", "r1", "failed"),
            _row("review", "r1", "failed"),
            _row("publish", "r1", "unprocessed"),
            _row("review", "r2", "failed"),
        ],
        tombstoned={("review", "r1"), ("publish", "r1")},
    )

    assert kept == [("extract", "r1", "filtered"), ("review", "r2", "failed")]


def test_a_failure_at_a_reader_holding_no_tombstone_for_the_record_stays(tmp_path):
    kept = _rewrite(
        tmp_path,
        [_row("extract", "r1", "failed"), _row("review", "r1", "exhausted")],
        tombstoned=set(),
    )

    assert kept == [("extract", "r1", "filtered"), ("review", "r1", "exhausted")]
