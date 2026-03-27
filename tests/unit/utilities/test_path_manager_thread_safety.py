"""Thread-safety tests for the global PathManager singleton."""

import threading
from unittest.mock import patch

import pytest

from agent_actions.utils.path_utils import (
    _path_manager_lock,
    get_path_manager,
    reset_path_manager,
    set_path_manager,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure a clean singleton state for every test."""
    reset_path_manager()
    yield
    reset_path_manager()


class TestGetPathManagerThreadSafety:
    """Concurrent calls to get_path_manager must produce a single instance."""

    def test_concurrent_init_returns_single_instance(self):
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        results: list[object] = [None] * num_threads

        def _get(index: int) -> None:
            barrier.wait()
            results[index] = get_path_manager()

        threads = [threading.Thread(target=_get, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        instances = set(id(r) for r in results)
        assert len(instances) == 1, f"Expected 1 instance, got {len(instances)}"

    def test_reset_then_get_returns_new_instance(self):
        first = get_path_manager()
        reset_path_manager()
        second = get_path_manager()
        assert first is not second

    def test_init_exception_releases_lock(self):
        """If PathManager.__init__() raises, the lock is still released."""
        with patch(
            "agent_actions.config.paths.PathManager",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                get_path_manager()
        # Lock must not be stuck — a normal call should succeed.
        assert not _path_manager_lock.locked()

    def test_lock_is_module_level(self):
        """The lock used for double-checked locking is a module-level Lock."""
        assert isinstance(_path_manager_lock, type(threading.Lock()))


class TestSetPathManager:
    """Tests for explicit DI via set_path_manager()."""

    def test_set_then_get_returns_same_instance(self):
        from agent_actions.config.paths import PathManager

        pm = PathManager()
        set_path_manager(pm)
        assert get_path_manager() is pm

    def test_set_overwrites_lazy_init(self):
        """set_path_manager replaces a previously lazy-initialized instance."""
        from agent_actions.config.paths import PathManager

        lazy = get_path_manager()
        explicit = PathManager()
        set_path_manager(explicit)
        assert get_path_manager() is explicit
        assert get_path_manager() is not lazy

    def test_set_overwrites_previous_set(self):
        from agent_actions.config.paths import PathManager

        first = PathManager()
        second = PathManager()
        set_path_manager(first)
        set_path_manager(second)
        assert get_path_manager() is second
