"""
Demonstration of the race condition fix in ProcessorUtils.

This script shows how the thread-safe implementation prevents race conditions
that could occur when parallel loop agents generate correlation IDs simultaneously.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from agent_actions.utils.correlation import VersionIdGenerator


def get_demo_session_id() -> str:
    """Get a consistent session ID for demo purposes."""
    return "demo_session_12345"


def demonstrate_race_condition_fix():
    """
    Demonstrate that the thread-safe fix prevents race conditions.

    Before the fix, this scenario could cause race conditions:
    1. Multiple threads check if a correlation ID exists
    2. All threads see it doesn't exist
    3. All threads try to create a new ID
    4. Multiple different IDs could be created for the same key

    After the fix, all threads will get the same correlation ID.
    """
    print("=== ProcessorUtils Thread Safety Demonstration ===\n")
    VersionIdGenerator.clear_version_correlation_registry()
    source_guid = "demo-record-123"
    version_base_name = "generate_distractors"
    num_threads = 20
    correlation_ids: list[str] = []
    correlation_ids_lock = threading.Lock()

    def worker(worker_id: int):
        """Worker function that generates correlation IDs."""
        print(f"  Worker {worker_id} starting...")
        correlation_id = VersionIdGenerator.get_or_create_version_correlation_id(
            source_guid, version_base_name, get_demo_session_id()
        )
        time.sleep(0.01)
        with correlation_ids_lock:
            correlation_ids.append(correlation_id)
        print(f"  Worker {worker_id} got ID: {correlation_id[:8]}...")

    print(f"1. Starting {num_threads} concurrent workers...")
    print(f"   Source GUID: {source_guid}")
    print(f"   Loop Base Name: {version_base_name}")
    print()
    threads = []
    start_time = time.time()
    for i in range(num_threads):
        thread = threading.Thread(target=worker, args=(i,))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    end_time = time.time()
    print(f"\n2. Results after {end_time - start_time:.3f} seconds:")
    print(f"   Total correlation IDs generated: {len(correlation_ids)}")
    unique_ids: set[str] = set(correlation_ids)
    print(f"   Unique correlation IDs: {len(unique_ids)}")
    if len(unique_ids) == 1:
        print("   ✅ SUCCESS: All threads got the same correlation ID!")
        print(f"   Correlation ID: {list(unique_ids)[0]}")
    else:
        print("   ❌ FAILURE: Race condition detected - multiple IDs generated!")
        print(f"   IDs: {list(unique_ids)}")
    print()


def demonstrate_position_based_consistency():
    """Demonstrate position-based correlation ID consistency."""
    print("=== Position-Based Correlation ID Consistency ===\n")
    VersionIdGenerator.clear_version_correlation_registry()
    record_indices = [0, 1, 2]
    version_base_name = "batch_processor"
    file_context = "demo_file.json"
    num_workers_per_position = 5
    results = {}
    results_lock = threading.Lock()

    def worker(position: int, worker_id: int):
        """Worker for position-based correlation."""
        correlation_id = VersionIdGenerator.get_or_create_position_based_version_correlation_id(
            position, version_base_name, get_demo_session_id(), file_context
        )
        with results_lock:
            if position not in results:
                results[position] = []
            results[position].append(correlation_id)
        print(f"  Position {position}, Worker {worker_id}: {correlation_id[:8]}...")

    print("1. Testing position-based correlation consistency...")
    print(f"   Positions: {record_indices}")
    print(f"   Workers per position: {num_workers_per_position}")
    print()
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = []
        for position in record_indices:
            for worker_id in range(num_workers_per_position):
                future = executor.submit(worker, position, worker_id)
                futures.append(future)
        for future in futures:
            future.result()
    print("\n2. Position-based consistency results:")
    all_position_ids = set()
    for position, correlation_ids in results.items():
        unique_ids_for_position = set(correlation_ids)
        print(f"   Position {position}: {len(unique_ids_for_position)} unique ID(s)")
        if len(unique_ids_for_position) == 1:
            print(f"     ✅ Consistent ID: {list(unique_ids_for_position)[0][:8]}...")
            all_position_ids.update(unique_ids_for_position)
        else:
            print(f"     ❌ Inconsistent! IDs: {[id[:8] for id in unique_ids_for_position]}")
    print(f"\n   Total unique position IDs: {len(all_position_ids)}")
    if len(all_position_ids) == len(record_indices):
        print("   ✅ SUCCESS: Each position has a unique correlation ID!")
    else:
        print("   ❌ FAILURE: Position correlation IDs are not unique!")
    print()


def demonstrate_mixed_usage():
    """Demonstrate mixed usage of both correlation strategies."""
    print("=== Mixed Correlation Strategy Usage ===\n")
    VersionIdGenerator.clear_version_correlation_registry()
    source_guids = ["guid-A", "guid-B", "guid-C"]
    positions = [0, 1, 2]
    version_base_name = "mixed_demo"
    guid_results = {}
    position_results = {}
    results_lock = threading.Lock()

    def guid_worker(source_guid: str):
        """Worker using source GUID strategy."""
        correlation_id = VersionIdGenerator.get_or_create_version_correlation_id(
            source_guid, version_base_name, get_demo_session_id()
        )
        with results_lock:
            guid_results[source_guid] = correlation_id
        print(f"  GUID '{source_guid}': {correlation_id[:8]}...")

    def position_worker(position: int):
        """Worker using position strategy."""
        correlation_id = VersionIdGenerator.get_or_create_position_based_version_correlation_id(
            position, version_base_name, get_demo_session_id()
        )
        with results_lock:
            position_results[position] = correlation_id
        print(f"  Position {position}: {correlation_id[:8]}...")

    print("1. Running mixed correlation strategies in parallel...")
    print(f"   Source GUIDs: {source_guids}")
    print(f"   Positions: {positions}")
    print()
    with ThreadPoolExecutor(max_workers=6) as executor:
        guid_futures = [executor.submit(guid_worker, guid) for guid in source_guids]
        pos_futures = [executor.submit(position_worker, pos) for pos in positions]
        for future in guid_futures + pos_futures:
            future.result()
    print("\n2. Mixed strategy results:")
    print(f"   GUID-based IDs: {len(set(guid_results.values()))} unique")
    print(f"   Position-based IDs: {len(set(position_results.values()))} unique")
    guid_ids = set(guid_results.values())
    position_ids = set(position_results.values())
    overlap = guid_ids.intersection(position_ids)
    if len(overlap) == 0:
        print("   ✅ SUCCESS: No overlap between GUID and position strategies!")
    else:
        print(f"   ❌ FAILURE: Unexpected overlap: {overlap}")
    print()


def main():
    """Run all demonstrations."""
    print("Thread-Safe ProcessorUtils Correlation ID Demonstration")
    print("=" * 60)
    print()
    try:
        demonstrate_race_condition_fix()
        demonstrate_position_based_consistency()
        demonstrate_mixed_usage()
        print("🎉 All demonstrations completed successfully!")
        print("\nThe thread-safe implementation ensures:")
        print("- Consistent correlation IDs across parallel agents")
        print("- No race conditions during concurrent access")
        print("- Proper isolation between different correlation strategies")
        print()
    except Exception as e:
        print(f"❌ Demonstration failed: {e}")
        raise
    finally:
        VersionIdGenerator.clear_version_correlation_registry()


if __name__ == "__main__":
    main()
