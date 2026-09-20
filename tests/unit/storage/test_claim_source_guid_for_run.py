"""claim_source_guid_for_run: an in-memory, per-process claim, never persisted.

Finds the next free occurrence when content is staged under a different
relative_path. Never backed by `source_data`: a persisted check can't tell a
still-live duplicate from this file's own row from before it was renamed.
Scoped by relative_path, not just the guid: independent actions can share one
staging file, and re-claiming it under the SAME path is not a collision.
"""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    db_path = tmp_path / "agent_io" / "test.db"
    backend = SQLiteBackend(str(db_path), "test_workflow")
    backend.initialize()
    yield backend
    backend.close()


class TestClaimingWithinOneBackend:
    def test_the_first_claim_succeeds(self, backend):
        assert backend.claim_source_guid_for_run("g1", "a") is False

    def test_a_second_claim_under_a_different_path_is_reported_taken(self, backend):
        backend.claim_source_guid_for_run("g1", "a")
        assert backend.claim_source_guid_for_run("g1", "b") is True

    def test_a_second_claim_under_the_same_path_is_not_a_collision(self, backend):
        """Two independent actions reading the same staged file legitimately
        claim the same guid under the same relative_path — not a duplicate."""
        backend.claim_source_guid_for_run("g1", "a")
        assert backend.claim_source_guid_for_run("g1", "a") is False

    def test_different_guids_do_not_collide(self, backend):
        assert backend.claim_source_guid_for_run("g1", "a") is False
        assert backend.claim_source_guid_for_run("g2", "a") is False


class TestClaimsDoNotPersist:
    def test_a_claim_is_not_written_to_source_data(self, backend):
        backend.claim_source_guid_for_run("g1", "a")

        with backend._lock:
            cursor = backend.connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM source_data")
            (count,) = cursor.fetchone()
        assert count == 0

    def test_a_fresh_backend_instance_does_not_see_a_prior_instance_claim(self, tmp_path):
        """A new process (a new backend instance over the same db file) starts
        with no memory of what an earlier run claimed — the guarantee that
        keeps a renamed or simply re-staged file from colliding with its own
        past self."""
        db_path = tmp_path / "agent_io" / "test.db"

        first = SQLiteBackend(str(db_path), "test_workflow")
        first.initialize()
        first.claim_source_guid_for_run("g1", "a")
        first.close()

        second = SQLiteBackend(str(db_path), "test_workflow")
        second.initialize()
        try:
            assert second.claim_source_guid_for_run("g1", "renamed") is False
        finally:
            second.close()
