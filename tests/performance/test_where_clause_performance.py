import pytest
import time
import random
import string
from agent_actions.common.filters.where_parser import WhereClauseParser


class TestWhereClausePerformance:
    """Performance tests for WHERE clause parsing and evaluation"""

    def generate_test_data(self, size: int) -> list:
        data = []
        categories = ["tech", "science", "art", "business", "health"]
        statuses = ["active", "inactive", "pending", "archived"]
        for i in range(size):
            item = {
                "id": f"item_{i}",
                "category": random.choice(categories),
                "status": random.choice(statuses),
                "score": random.randint(1, 100),
                "title": ''.join(random.choices(string.ascii_letters, k=50)),
                "metadata": {
                    "quality_score": random.randint(1, 100),
                    "word_count": random.randint(100, 5000),
                    "source": random.choice(["trusted", "unverified", "flagged"])
                }
            }
            data.append(item)
        return data

    def test_large_dataset_filtering_performance(self):
        sizes = [1000, 5000, 10000]
        for size in sizes:
            data = self.generate_test_data(size)
            start_time = time.time()
            conditions = WhereClauseParser.parse('status == "active"')
            filtered_count = 0
            for item in data:
                if WhereClauseParser.evaluate(item, conditions):
                    filtered_count += 1
            elapsed_time = time.time() - start_time
            print(f"Filtered {size} items in {elapsed_time:.4f} seconds")
            print(f"Found {filtered_count} matching items")
            assert (size / elapsed_time) > 1000

    def test_complex_query_performance(self):
        data = self.generate_test_data(5000)
        complex_clause = 'status == "active" AND score > 50 AND metadata.quality_score >= 70'
        start_time = time.time()
        conditions = WhereClauseParser.parse(complex_clause)
        filtered_data = [
            item for item in data
            if WhereClauseParser.evaluate(item, conditions)
        ]
        elapsed_time = time.time() - start_time
        print(f"Complex query on 5000 items: {elapsed_time:.4f} seconds")
        print(f"Results: {len(filtered_data)} items")
        assert elapsed_time < 1.0

    def test_parsing_performance(self):
        test_clauses = [
            'field == "value"',
            'field != "value" AND other_field > 50',
            'category IN ["a", "b", "c"] AND score >= 80 AND metadata.source != "spam"',
            'title CONTAINS "important" AND status NOT IN ["deleted", "archived"] AND metadata.quality_score > 75'
        ]
        for clause in test_clauses:
            start_time = time.time()
            for _ in range(1000):
                WhereClauseParser.parse(clause)
            elapsed_time = time.time() - start_time
            print(f"Parsed '{clause}' 1000 times in {elapsed_time:.4f} seconds")
            assert elapsed_time < 0.5

    def test_memory_usage_with_large_datasets(self):
        try:
            import psutil
            import os
        except ImportError:
            pytest.skip("psutil not installed")
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024
        data = self.generate_test_data(10000)
        conditions = WhereClauseParser.parse('score > 50 AND status == "active"')
        filtered_data = [
            item for item in data
            if WhereClauseParser.evaluate(item, conditions)
        ]
        final_memory = process.memory_info().rss / 1024 / 1024
        memory_increase = final_memory - initial_memory
        print(f"Memory increase: {memory_increase:.2f} MB for 10k items")
        assert memory_increase < 100


class TestConcurrentFiltering:
    """Test concurrent/parallel filtering operations"""

    def test_thread_safety(self):
        import threading
        import queue

        def worker(test_queue, result_queue):
            while True:
                try:
                    clause = test_queue.get(timeout=1)
                    conditions = WhereClauseParser.parse(clause)
                    result_queue.put(len(conditions))
                    test_queue.task_done()
                except queue.Empty:
                    break

        test_clauses = [
            'field == "value"',
            'other != "test"',
            'score > 50',
            'category IN ["a", "b"]'
        ] * 25

        test_queue = queue.Queue()
        result_queue = queue.Queue()
        for clause in test_clauses:
            test_queue.put(clause)

        threads = []
        for i in range(4):
            t = threading.Thread(target=worker, args=(test_queue, result_queue))
            t.start()
            threads.append(t)

        test_queue.join()
        results = []
        while not result_queue.empty():
            results.append(result_queue.get())
        assert len(results) == 100
        assert all(r == 1 for r in results)
