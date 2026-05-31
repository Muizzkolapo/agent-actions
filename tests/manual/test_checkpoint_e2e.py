"""Manual end-to-end test: checkpoint + resume for first-stage online processing.

Calls the actual modules in the exact order the real pipeline does,
with a real SQLite backend, to verify checkpoint resume works.

Run: python tests/manual/test_checkpoint_e2e.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    import tempfile

    from agent_actions.processing.disposition_gate import DispositionGate, build_carry_forward
    from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
    from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
    from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
    from agent_actions.utils.id_generation import IDGenerator

    # ── Setup ──────────────────────────────────────────────────────────

    tmp = tempfile.mkdtemp()
    db_path = f"{tmp}/test.db"
    backend = SQLiteBackend.create(db_path=db_path, workflow_name="test_wf")
    backend.initialize()

    print(f"DB: {db_path}")
    print()

    INPUT_RECORDS = [
        {
            "id": "page1",
            "url": "https://example.com/1",
            "page_content": "Content about Python basics",
        },
        {
            "id": "page2",
            "url": "https://example.com/2",
            "page_content": "Content about async/await",
        },
        {"id": "page3", "url": "https://example.com/3", "page_content": "Content about testing"},
    ]

    ACTION_NAME = "summarize_page_content"
    RELATIVE_PATH = "combined_scraped.json"
    OUTPUT_DIR = f"{tmp}/output"
    FILE_PATH = f"{OUTPUT_DIR}/{RELATIVE_PATH}"

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    def make_context(records):
        return ProcessingContext(
            agent_config={},
            agent_name=ACTION_NAME,
            is_first_stage=True,
            storage_backend=backend,
            file_path=FILE_PATH,
            output_directory=OUTPUT_DIR,
            source_data=records,
        )

    def assign_deterministic_guids(records):
        for r in records:
            if not r.get("source_guid"):
                r["source_guid"] = IDGenerator.generate_content_hash(r)

    def simulate_llm_result(record, idx):
        return ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[
                {
                    "source_guid": record["source_guid"],
                    "content": {"summary": f"Summary of {record['id']}"},
                    "target_id": f"target_{idx}",
                    "node_id": ACTION_NAME,
                }
            ],
            source_guid=record["source_guid"],
        )

    # ══════════════════════════════════════════════════════════════════
    # STEP 1: First run — guid assignment
    # ══════════════════════════════════════════════════════════════════

    print("=" * 60)
    print("STEP 1: Assign deterministic guids (first run)")
    print("=" * 60)

    records_run1 = [r.copy() for r in INPUT_RECORDS]
    assign_deterministic_guids(records_run1)

    for r in records_run1:
        print(f"  {r['id']}: source_guid={r['source_guid'][:12]}...")

    guids = [r["source_guid"] for r in records_run1]
    print()

    # ══════════════════════════════════════════════════════════════════
    # STEP 2: Gate filter (first run — no terminal IDs)
    # ══════════════════════════════════════════════════════════════════

    print("=" * 60)
    print("STEP 2: DispositionGate filter (first run)")
    print("=" * 60)

    gate1 = DispositionGate(storage_backend=backend)
    to_process, carry_ids = gate1.filter(records_run1, ACTION_NAME)

    print(f"  Terminal IDs: {backend.get_terminal_record_ids(ACTION_NAME)}")
    print(f"  carry_ids: {carry_ids}")
    print(f"  to_process: {len(to_process)} records")
    assert len(carry_ids) == 0, "First run should have no carry-forward"
    assert len(to_process) == 3, "All 3 records should be processed"
    print("  PASS: all 3 records to process")
    print()

    # ══════════════════════════════════════════════════════════════════
    # STEP 3: Process record 0, checkpoint it, "crash" before record 1
    # ══════════════════════════════════════════════════════════════════

    print("=" * 60)
    print("STEP 3: Process record 0, checkpoint, simulate crash")
    print("=" * 60)

    result0 = simulate_llm_result(records_run1[0], 0)
    ctx = make_context(records_run1)

    OnlineLLMStrategy._checkpoint_record(result0, ctx)

    print(f"  Checkpointed: {result0.source_guid[:12]}... ({result0.status.value})")

    terminal_ids = backend.get_terminal_record_ids(ACTION_NAME)
    checkpoint_records = backend.read_checkpoint_records(ACTION_NAME, RELATIVE_PATH)
    print(f"  Terminal IDs in DB: {terminal_ids}")
    print(f"  Checkpoint records in DB: {len(checkpoint_records)}")
    assert result0.source_guid in terminal_ids, "Checkpointed guid should be terminal"
    assert len(checkpoint_records) == 1, "Should have 1 checkpoint record"
    print("  PASS: checkpoint persisted to SQLite")
    print()
    print("  --- SIMULATED CRASH (Ctrl+C) ---")
    print()

    # ══════════════════════════════════════════════════════════════════
    # STEP 4: Second run — assign guids again (deterministic = same)
    # ══════════════════════════════════════════════════════════════════

    print("=" * 60)
    print("STEP 4: Assign deterministic guids (second run)")
    print("=" * 60)

    records_run2 = [r.copy() for r in INPUT_RECORDS]
    assign_deterministic_guids(records_run2)

    for i, r in enumerate(records_run2):
        match = "SAME" if r["source_guid"] == guids[i] else "DIFFERENT"
        print(f"  {r['id']}: {r['source_guid'][:12]}... {match}")

    assert records_run2[0]["source_guid"] == guids[0], "Deterministic guid should match!"
    print("  PASS: guids are deterministic across runs")
    print()

    # ══════════════════════════════════════════════════════════════════
    # STEP 5: Gate filter (second run — should carry forward record 0)
    # ══════════════════════════════════════════════════════════════════

    print("=" * 60)
    print("STEP 5: DispositionGate filter (second run)")
    print("=" * 60)

    gate2 = DispositionGate(storage_backend=backend)
    to_process2, carry_ids2 = gate2.filter(records_run2, ACTION_NAME)

    print(f"  Terminal IDs: {backend.get_terminal_record_ids(ACTION_NAME)}")
    print(f"  carry_ids: {carry_ids2}")
    print(f"  to_process: {len(to_process2)} records")

    assert len(carry_ids2) == 1, f"Should carry forward 1 record, got {len(carry_ids2)}"
    assert guids[0] in carry_ids2, "Record 0 should be carried forward"
    assert len(to_process2) == 2, f"Should process 2 remaining records, got {len(to_process2)}"
    print("  PASS: 1 carried forward, 2 to process")
    print()

    # ══════════════════════════════════════════════════════════════════
    # STEP 6: build_carry_forward (read checkpoint data for carried record)
    # ══════════════════════════════════════════════════════════════════

    print("=" * 60)
    print("STEP 6: build_carry_forward (checkpoint fallback)")
    print("=" * 60)

    carry_data, missing = build_carry_forward(carry_ids2, ACTION_NAME, RELATIVE_PATH, backend)

    print(f"  Found: {len(carry_data)} records")
    print(f"  Missing: {missing}")

    assert len(carry_data) == 1, f"Should find 1 carried record, got {len(carry_data)}"
    assert len(missing) == 0, f"Should have 0 missing, got {len(missing)}"
    assert carry_data[0]["source_guid"] == guids[0], "Carried record should match"
    print("  PASS: checkpoint data recovered for carried record")
    print()

    # ══════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════

    print("=" * 60)
    print("ALL STEPS PASSED")
    print("=" * 60)
    print()
    print("Checkpoint resume works correctly:")
    print(f"  Record 0 ({guids[0][:12]}...): carried forward (no LLM call needed)")
    print(f"  Record 1 ({guids[1][:12]}...): would be reprocessed")
    print(f"  Record 2 ({guids[2][:12]}...): would be reprocessed")
    print()
    print("Saved 1 LLM call out of 3 on resume.")


if __name__ == "__main__":
    main()
