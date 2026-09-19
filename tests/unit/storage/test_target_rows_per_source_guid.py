"""How many rows an action holds for each identity.

Asked once per action while a limit decides which records it may drop, so it
reads the rows as stored: reconstruction, lifecycle validation and the
downstream reset belong to reading content, not to reading an identity.
"""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "wf")
    b.initialize()
    yield b
    b.close()


class TestTargetRowsPerSourceGuid:
    def test_it_collects_across_every_file_of_the_action(self, backend):
        backend.write_target("act", "a.json", [{"source_guid": "g0"}, {"source_guid": "g1"}])
        backend.write_target("act", "b.json", [{"source_guid": "g2"}])

        assert backend.target_rows_per_source_guid("act") == {"g0": 1, "g1": 1, "g2": 1}

    def test_it_does_not_reach_into_another_action(self, backend):
        backend.write_target("act", "a.json", [{"source_guid": "g0"}])
        backend.write_target("other", "a.json", [{"source_guid": "g9"}])

        assert backend.target_rows_per_source_guid("act") == {"g0": 1}

    def test_a_guid_stored_under_two_files_is_counted_twice(self, backend):
        """source_guid is a content hash, so byte-identical rows share one — and
        two stored rows are two rows, whichever file they are in."""
        backend.write_target("act", "a.json", [{"source_guid": "g0"}])
        backend.write_target("act", "b.json", [{"source_guid": "g0"}])

        assert backend.target_rows_per_source_guid("act") == {"g0": 2}

    def test_rows_carrying_no_guid_are_not_an_identity(self, backend):
        """Admitting on a missing guid would admit every record that also lacks
        one, on the strength of a row that identifies nothing."""
        backend.write_target("act", "a.json", [{"summary": "x"}, {"source_guid": "g1"}])

        assert backend.target_rows_per_source_guid("act") == {"g1": 1}

    def test_an_action_that_wrote_nothing_holds_nothing(self, backend):
        assert backend.target_rows_per_source_guid("never_ran") == {}

    def test_it_does_not_raise_on_a_row_missing_lifecycle_state(self, backend):
        """`read_target` refuses such a store. Asking for an identity must not,
        or a limit slice becomes the place a bad store is first reported."""
        backend.write_target("act", "a.json", [{"source_guid": "g0", "content": {"a": 1}}])

        assert backend.target_rows_per_source_guid("act") == {"g0": 1}

    def test_several_rows_of_one_identity_in_one_file_are_counted(self, backend):
        """Three byte-identical staged records really are three stored rows."""
        backend.write_target("act", "a.json", [{"source_guid": "g0"}] * 3)

        assert backend.target_rows_per_source_guid("act") == {"g0": 3}
