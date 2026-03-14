"""Tests for async-safe token usage tracking.

Regression coverage for Task 18: concurrent asyncio tasks must not
cross-contaminate each other's token usage counters.
"""

import asyncio

import pytest

from agent_actions.llm.providers.usage_tracker import (
    clear_usage,
    get_last_usage,
    set_last_usage,
)


class TestUsageTrackerBasics:
    """Basic get/set/clear semantics."""

    def test_set_and_get(self):
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        set_last_usage(usage)
        assert get_last_usage() == usage

    def test_default_is_none(self):
        clear_usage()
        assert get_last_usage() is None

    def test_clear(self):
        set_last_usage({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
        clear_usage()
        assert get_last_usage() is None

    def test_set_none_clears(self):
        set_last_usage({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
        set_last_usage(None)
        assert get_last_usage() is None


class TestUsageTrackerAsyncIsolation:
    """Concurrent asyncio tasks must have isolated usage counters."""

    @pytest.mark.asyncio
    async def test_concurrent_tasks_do_not_contaminate(self):
        """Two concurrent tasks writing different usage must each read their own."""
        barrier = asyncio.Barrier(2)
        results: dict[str, dict | None] = {}

        async def task_a():
            set_last_usage({"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})
            await barrier.wait()  # force interleaving
            results["a"] = get_last_usage()

        async def task_b():
            set_last_usage({"input_tokens": 200, "output_tokens": 80, "total_tokens": 280})
            await barrier.wait()
            results["b"] = get_last_usage()

        await asyncio.gather(
            asyncio.create_task(task_a()),
            asyncio.create_task(task_b()),
        )

        assert results["a"] == {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
        assert results["b"] == {"input_tokens": 200, "output_tokens": 80, "total_tokens": 280}

    @pytest.mark.asyncio
    async def test_many_concurrent_tasks_isolated(self):
        """Scale test: N concurrent tasks each get their own usage."""
        n = 20
        results: dict[int, dict | None] = {}
        barrier = asyncio.Barrier(n)

        async def worker(task_id: int):
            usage = {
                "input_tokens": task_id * 10,
                "output_tokens": task_id * 5,
                "total_tokens": task_id * 15,
            }
            set_last_usage(usage)
            await barrier.wait()
            results[task_id] = get_last_usage()

        await asyncio.gather(*(asyncio.create_task(worker(i)) for i in range(n)))

        for i in range(n):
            assert results[i] == {
                "input_tokens": i * 10,
                "output_tokens": i * 5,
                "total_tokens": i * 15,
            }, f"Task {i} got contaminated usage"

    @pytest.mark.asyncio
    async def test_clear_in_one_task_does_not_affect_another(self):
        """Clearing usage in one task must not clear it in a sibling."""
        barrier = asyncio.Barrier(2)
        results: dict[str, dict | None] = {}

        async def task_setter():
            set_last_usage({"input_tokens": 42, "output_tokens": 0, "total_tokens": 42})
            await barrier.wait()
            results["setter"] = get_last_usage()

        async def task_clearer():
            set_last_usage({"input_tokens": 99, "output_tokens": 0, "total_tokens": 99})
            clear_usage()
            await barrier.wait()
            results["clearer"] = get_last_usage()

        await asyncio.gather(
            asyncio.create_task(task_setter()),
            asyncio.create_task(task_clearer()),
        )

        assert results["setter"] == {"input_tokens": 42, "output_tokens": 0, "total_tokens": 42}
        assert results["clearer"] is None
