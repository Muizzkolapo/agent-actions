"""Keeping one record per identity, the way the store keeps one row per identity.

The rule lives in two places that cannot share code: here, in Python, over the
list about to be processed; and in SQL, as UNIQUE(relative_path, source_guid)
with INSERT OR IGNORE. They have to agree, so the agreement is asserted rather
than assumed.
"""

import pytest

from agent_actions.record.envelope import first_record_per_identity
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def _rec(guid, **extra):
    return {"source_guid": guid, **extra}


class TestFirstRecordPerIdentity:
    def test_distinct_identities_are_all_kept(self):
        records = [_rec("a"), _rec("b"), _rec("c")]

        assert first_record_per_identity(records)[0] == records

    def test_the_first_record_of_an_identity_wins(self):
        records = [_rec("a", n=1), _rec("a", n=2), _rec("b", n=3)]

        kept, _ = first_record_per_identity(records)

        assert kept == [_rec("a", n=1), _rec("b", n=3)]

    def test_an_aligned_list_is_kept_in_step(self):
        records = [_rec("a"), _rec("a"), _rec("b")]

        kept, aligned = first_record_per_identity(records, ["ta", "ta2", "tb"])

        assert len(kept) == len(aligned) == 2
        assert aligned == ["ta", "tb"]

    def test_nothing_to_drop_returns_the_list_unchanged(self):
        records = [_rec("a"), _rec("b")]
        aligned = ["x", "y"]

        kept, kept_aligned = first_record_per_identity(records, aligned)

        assert kept == records
        assert kept_aligned == aligned

    def test_a_record_with_no_identity_is_passed_through(self):
        """Identity is not ours to invent; the storage boundary refuses it loudly."""
        records = [_rec("a"), {"no": "guid"}, {"no": "guid"}]

        kept, _ = first_record_per_identity(records)

        assert kept == records

    def test_an_absent_aligned_list_stays_absent(self):
        kept, aligned = first_record_per_identity([_rec("a"), _rec("a")], None)

        assert kept == [_rec("a")]
        assert aligned is None


class TestItAgreesWithTheStore:
    """The two implementations of one rule, on the same input."""

    @pytest.fixture
    def backend(self, tmp_path):
        b = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "wf")
        b.initialize()
        yield b
        b.close()

    @pytest.mark.parametrize(
        "records",
        [
            [_rec("a"), _rec("b"), _rec("c")],
            [_rec("a", n=1), _rec("a", n=2)],
            [_rec("a", n=1), _rec("b"), _rec("a", n=2), _rec("b")],
            [_rec("a")] * 5,
        ],
    )
    def test_the_same_records_survive_both(self, backend, records):
        backend.write_source("f", records, enable_deduplication=True)
        stored = {r["source_guid"] for r in backend.read_source("f")}

        kept, _ = first_record_per_identity(records)

        assert {r["source_guid"] for r in kept} == stored
        assert len(kept) == len(stored), "one record per identity, on both sides"

    def test_the_store_also_keeps_the_first_of_an_identity(self, backend):
        """Not merely the same count — the same record."""
        records = [_rec("a", n="first"), _rec("a", n="second")]
        backend.write_source("f", records, enable_deduplication=True)

        stored = backend.read_source("f")
        kept, _ = first_record_per_identity(records)

        assert [r["n"] for r in stored] == ["first"]
        assert [r["n"] for r in kept] == ["first"]
