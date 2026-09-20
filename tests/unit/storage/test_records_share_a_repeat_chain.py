"""records_share_a_repeat_chain: does a repair need the whole staged tree (614)?

A repair narrowed to just the file(s) naming the retried record would leave out
a sibling file identity re-derivation needs, whenever the named record is
either side of a repeat chain — not just the repeat side.
"""

import pytest

from agent_actions.storage.backend import StorageBackend
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "agent_io" / "test.db"), "test_workflow")
    backend.initialize()
    yield backend
    backend.close()


def _write(backend, relative_path, source_guid, repeat_of_source_guid=None):
    row = {"source_guid": source_guid}
    if repeat_of_source_guid is not None:
        row["repeat_of_source_guid"] = repeat_of_source_guid
    backend.write_source(relative_path, [row])


class TestSQLiteBackend:
    def test_the_repeat_side_of_a_collision_is_true(self, backend):
        _write(backend, "a", "base")
        _write(backend, "b", "repeat", repeat_of_source_guid="base")

        assert backend.records_share_a_repeat_chain(["repeat"]) is True

    def test_the_original_side_of_a_collision_is_also_true(self, backend):
        """The base row itself carries no repeat_of_source_guid — only the
        OTHER row pointing back at it does, so this direction needs its own
        query, not just a reflection of the repeat-side check."""
        _write(backend, "a", "base")
        _write(backend, "b", "repeat", repeat_of_source_guid="base")

        assert backend.records_share_a_repeat_chain(["base"]) is True

    def test_an_ordinary_unrepeated_record_is_false(self, backend):
        _write(backend, "a", "solo")

        assert backend.records_share_a_repeat_chain(["solo"]) is False

    def test_empty_input_is_false(self, backend):
        assert backend.records_share_a_repeat_chain([]) is False

    def test_an_unknown_guid_is_false(self, backend):
        assert backend.records_share_a_repeat_chain(["nonexistent"]) is False


class TestBaseClassDefault:
    def test_defaults_true_so_an_unimplemented_backend_stays_safe(self):
        """Same safe-by-default posture as source_files_for_records: a backend
        that hasn't implemented this always falls back to walking everything,
        never silently narrows past a collision it can't detect."""

        class Bare(StorageBackend):
            @classmethod
            def create(cls, **kwargs):
                return cls()

            @property
            def backend_type(self):
                return "bare"

            def initialize(self):
                pass

            def _read_target_raw(self, *a, **kw):
                return []

            def _write_target_raw(self, *a, **kw):
                return ""

            def _save_metadata_raw(self, *a, **kw):
                pass

            def load_metadata(self, *a, **kw):
                return None

            def write_source(self, *a, **kw):
                return ""

            def read_source(self, *a, **kw):
                return []

            def claim_source_guid_for_run(self, *a, **kw):
                return False

            def list_target_files(self, *a, **kw):
                return []

            def list_source_files(self, *a, **kw):
                return []

            def preview_target(self, *a, **kw):
                return {}

            def get_storage_stats(self):
                return {}

        assert Bare().records_share_a_repeat_chain(["x"]) is True
