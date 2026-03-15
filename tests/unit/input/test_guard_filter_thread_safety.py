"""Thread-safety tests for the global GuardFilter singleton."""

import threading
from unittest.mock import patch

import pytest

from agent_actions.input.preprocessing.filtering.guard_filter import (
    _GUARD_FILTER_LOCK,
    get_global_guard_filter,
    reset_global_guard_filter,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure a clean singleton state for every test."""
    reset_global_guard_filter()
    yield
    reset_global_guard_filter()


class TestGetGlobalGuardFilterThreadSafety:
    """Concurrent calls to get_global_guard_filter must produce a single instance."""

    def test_concurrent_init_returns_single_instance(self):
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        results: list[object] = [None] * num_threads

        def _get(index: int) -> None:
            barrier.wait()
            results[index] = get_global_guard_filter()

        threads = [threading.Thread(target=_get, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        instances = set(id(r) for r in results)
        assert len(instances) == 1, f"Expected 1 instance, got {len(instances)}"

    def test_reset_then_get_returns_new_instance(self):
        first = get_global_guard_filter()
        reset_global_guard_filter()
        second = get_global_guard_filter()
        assert first is not second

    def test_atexit_registered_once(self):
        with patch(
            "agent_actions.input.preprocessing.filtering.guard_filter.atexit"
        ) as mock_atexit:
            get_global_guard_filter()
            get_global_guard_filter()  # second call must not register again
            assert mock_atexit.register.call_count == 1

    def test_atexit_reregistered_after_reset(self):
        """After reset+reinit, a fresh atexit handler is registered."""
        with patch(
            "agent_actions.input.preprocessing.filtering.guard_filter.atexit"
        ) as mock_atexit:
            get_global_guard_filter()
            assert mock_atexit.register.call_count == 1
            reset_global_guard_filter()
            assert mock_atexit.unregister.call_count == 1
            get_global_guard_filter()
            assert mock_atexit.register.call_count == 2

    def test_init_exception_releases_lock(self):
        """If GuardFilter.__init__() raises, the lock is still released."""
        with patch(
            "agent_actions.input.preprocessing.filtering.guard_filter.GuardFilter",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                get_global_guard_filter()
        # Lock must not be stuck — a normal call should succeed.
        assert not _GUARD_FILTER_LOCK.locked()

    def test_lock_is_module_level(self):
        """The lock used for double-checked locking is a module-level Lock."""
        assert isinstance(_GUARD_FILTER_LOCK, type(threading.Lock()))
