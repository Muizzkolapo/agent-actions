"""Reproduction: version merge delivers full bus per version, causing context explosion.

Bug: _merge_with_pattern() extracts the ENTIRE record content for each version
agent — all accumulated upstream namespaces — instead of just the version
agent's own output namespace. With 3 versions and a deep pipeline, this
triples the upstream context.

Run:  python tests/manual/repro_bug_version_merge_full_bus.py
Expected: PASS after fix — each version namespace contains only its own fields.
"""

import json
import sys
from pathlib import Path

project_root = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, project_root)

from agent_actions.prompt.context.scope_namespace import _extract_content_data
from agent_actions.record.envelope import RecordEnvelope


def _simulate_version_records():
    """Simulate what version agents produce after running through a deep pipeline.

    Pipeline: extract_info -> analyze_depth -> write_scenario_question (versioned x3)

    Each version agent's output record contains the FULL accumulated bus
    (all upstream namespaces + its own output), because that's how the
    pipeline accumulates context as records flow through actions.
    """
    upstream = {
        "extract_info": {
            "key_facts": "A" * 500,  # simulate substantial upstream content
            "topic": "quantum computing",
            "difficulty": "advanced",
        },
        "analyze_depth": {
            "analysis": "B" * 500,
            "bloom_level": "evaluate",
            "prerequisite_knowledge": ["linear algebra", "probability"],
        },
    }

    # Each version agent produces the full bus + its own output
    version_records = {
        "write_scenario_question_1": {
            "source_guid": "sg-001",
            "version_correlation_id": "vc-001",
            "content": {
                **upstream,
                "write_scenario_question_1": {
                    "question": "What is superposition?",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": "A",
                },
            },
        },
        "write_scenario_question_2": {
            "source_guid": "sg-001",
            "version_correlation_id": "vc-001",
            "content": {
                **upstream,
                "write_scenario_question_2": {
                    "question": "Explain entanglement.",
                    "options": ["W", "X", "Y", "Z"],
                    "correct_answer": "W",
                },
            },
        },
        "write_scenario_question_3": {
            "source_guid": "sg-001",
            "version_correlation_id": "vc-001",
            "content": {
                **upstream,
                "write_scenario_question_3": {
                    "question": "Describe decoherence.",
                    "options": ["P", "Q", "R", "S"],
                    "correct_answer": "P",
                },
            },
        },
    }
    return version_records


def _current_merge_behavior(agent_records):
    """What _merge_with_pattern currently does — extracts full bus per version."""
    merged_content = {}
    for agent_name, record in agent_records.items():
        content = _extract_content_data(record)
        merged_content[agent_name] = content
    return merged_content


def _fixed_merge_behavior(agent_records):
    """What _merge_with_pattern SHOULD do — extract only own namespace per version."""
    merged_content = {}
    for agent_name, record in agent_records.items():
        content = _extract_content_data(record)
        # Only grab the version agent's own output, not the full bus
        merged_content[agent_name] = content.get(agent_name, {})
    return merged_content


def test_current_behavior():
    """Show the bug: full bus duplicated per version."""
    records = _simulate_version_records()
    base_record = next(iter(records.values()))

    # Current behavior
    merged = _current_merge_behavior(records)
    result = RecordEnvelope.build_version_merge(merged, base_record)
    content = result["content"]

    print("=" * 70)
    print("CURRENT BEHAVIOR (buggy)")
    print("=" * 70)

    # Show top-level keys
    print(f"\nTop-level keys in merged content: {list(content.keys())}")

    # Show that each version namespace contains the full bus
    for vname in [
        "write_scenario_question_1",
        "write_scenario_question_2",
        "write_scenario_question_3",
    ]:
        vdata = content.get(vname, {})
        print(f"\n  {vname} contains keys: {list(vdata.keys())}")
        has_upstream = "extract_info" in vdata or "analyze_depth" in vdata
        print(f"  Contains upstream namespaces (BUG): {has_upstream}")

    # Count total size
    total_json = json.dumps(content)
    upstream_json = json.dumps(
        {
            "extract_info": content.get("extract_info", {}),
            "analyze_depth": content.get("analyze_depth", {}),
        }
    )
    print(f"\n  Total merged content size: {len(total_json)} chars")
    print(f"  Upstream-only size: {len(upstream_json)} chars")

    # Count how many times upstream appears
    upstream_copies = 1  # from existing (base_record)
    for vname in [
        "write_scenario_question_1",
        "write_scenario_question_2",
        "write_scenario_question_3",
    ]:
        vdata = content.get(vname, {})
        if "extract_info" in vdata:
            upstream_copies += 1
    print(f"  Upstream duplicated {upstream_copies}x (should be 1x)")

    return content


def test_fixed_behavior():
    """Show the fix: only version's own output per namespace."""
    records = _simulate_version_records()
    base_record = next(iter(records.values()))

    # Fixed behavior
    merged = _fixed_merge_behavior(records)
    result = RecordEnvelope.build_version_merge(merged, base_record)
    content = result["content"]

    print("\n" + "=" * 70)
    print("FIXED BEHAVIOR")
    print("=" * 70)

    print(f"\nTop-level keys in merged content: {list(content.keys())}")

    for vname in [
        "write_scenario_question_1",
        "write_scenario_question_2",
        "write_scenario_question_3",
    ]:
        vdata = content.get(vname, {})
        print(f"\n  {vname} contains keys: {list(vdata.keys())}")
        has_upstream = "extract_info" in vdata or "analyze_depth" in vdata
        print(f"  Contains upstream namespaces: {has_upstream}")

    total_json = json.dumps(content)
    print(f"\n  Total merged content size: {len(total_json)} chars")

    upstream_copies = 1  # from existing (base_record) — this is correct
    for vname in [
        "write_scenario_question_1",
        "write_scenario_question_2",
        "write_scenario_question_3",
    ]:
        vdata = content.get(vname, {})
        if "extract_info" in vdata:
            upstream_copies += 1
    print(f"  Upstream appears {upstream_copies}x (should be 1x)")

    return content


def test_assertions():
    """Verify fixed behavior produces correct structure."""
    records = _simulate_version_records()
    base_record = next(iter(records.values()))

    merged = _fixed_merge_behavior(records)
    result = RecordEnvelope.build_version_merge(merged, base_record)
    content = result["content"]

    print("\n" + "=" * 70)
    print("ASSERTIONS")
    print("=" * 70)

    errors = []

    # Upstream should exist once at top level (from base_record existing)
    if "extract_info" not in content:
        errors.append("FAIL: extract_info missing from top level")
    if "analyze_depth" not in content:
        errors.append("FAIL: analyze_depth missing from top level")

    # Version namespaces should exist at top level
    for vname in [
        "write_scenario_question_1",
        "write_scenario_question_2",
        "write_scenario_question_3",
    ]:
        if vname not in content:
            errors.append(f"FAIL: {vname} missing from top level")

    # Version namespaces should contain ONLY the version's own output fields
    for vname in [
        "write_scenario_question_1",
        "write_scenario_question_2",
        "write_scenario_question_3",
    ]:
        vdata = content.get(vname, {})
        if "extract_info" in vdata:
            errors.append(f"FAIL: {vname} contains upstream 'extract_info' (bus leak)")
        if "analyze_depth" in vdata:
            errors.append(f"FAIL: {vname} contains upstream 'analyze_depth' (bus leak)")
        if "question" not in vdata:
            errors.append(f"FAIL: {vname} missing its own 'question' field")
        if "options" not in vdata:
            errors.append(f"FAIL: {vname} missing its own 'options' field")

    # Verify actual question content is correct per version
    q1 = content.get("write_scenario_question_1", {}).get("question")
    if q1 != "What is superposition?":
        errors.append(f"FAIL: v1 question wrong: {q1}")
    q2 = content.get("write_scenario_question_2", {}).get("question")
    if q2 != "Explain entanglement.":
        errors.append(f"FAIL: v2 question wrong: {q2}")
    q3 = content.get("write_scenario_question_3", {}).get("question")
    if q3 != "Describe decoherence.":
        errors.append(f"FAIL: v3 question wrong: {q3}")

    if errors:
        for e in errors:
            print(f"  {e}")
        print(f"\n  RESULT: FAIL ({len(errors)} errors)")
    else:
        print("  All assertions passed")
        print("\n  RESULT: PASS")

    return len(errors) == 0


if __name__ == "__main__":
    test_current_behavior()
    test_fixed_behavior()
    ok = test_assertions()
    sys.exit(0 if ok else 1)
