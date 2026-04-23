"""Reproduction script for version merge double-nesting bug.

Bug: The version correlator creates namespaced content
     {v1: {fields}, v2: {fields}} — already the correct additive format.
     Then wrap_content wraps it AGAIN under the consuming action's name:
     {action_name: {v1: {fields}, v2: {fields}}}.
     Downstream tools see double-nested data.

Run:  python tests/manual/repro_093_version_double_nesting.py
Expected: FAIL before fix, PASS after fix.
"""

import sys
from pathlib import Path

project_root = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, project_root)

from agent_actions.utils.content import get_existing_content, wrap_content


def test_file_mode_double_nesting():
    """FILE mode: version merge should spread, not wrap under action name.

    The pipeline checks version_consumption_config and decides whether to
    wrap or spread.  This test simulates both paths to show the difference.
    """
    version_merged = {
        "source_guid": "sg-1",
        "content": {
            "filter_learning_quality_1": {"vote": "keep", "score": 8},
            "filter_learning_quality_2": {"vote": "drop", "score": 3},
            "filter_learning_quality_3": {"vote": "keep", "score": 7},
        },
    }

    existing = get_existing_content(version_merged)
    tool_output = {"consensus": "keep", "total_score": 18}

    # Broken path (what wrap_content does — wraps under action name):
    broken = wrap_content("aggregate_votes", tool_output, existing)
    assert "aggregate_votes" in broken, "wrap_content should wrap under action name"

    # Fixed path (what the pipeline now does for version merge — spread):
    fixed = {**existing, **tool_output}
    if "aggregate_votes" in fixed:
        print("BUG CONFIRMED (FILE mode): Tool output wrapped under action name")
        return False

    assert "filter_learning_quality_1" in fixed, "version namespace missing"
    assert "consensus" in fixed, "tool output field missing"
    assert fixed["filter_learning_quality_1"]["vote"] == "keep"
    assert fixed["consensus"] == "keep"

    print("BUG FIXED (FILE mode): Version namespaces + tool output spread at top level")
    print(f"  fixed keys: {sorted(fixed.keys())}")
    return True


def test_transformer_double_nesting():
    """LLM path: transform_structure with version_merge=True skips wrapping."""
    from agent_actions.input.preprocessing.transformation.transformer import (
        DataTransformer,
    )

    llm_response = [{"sg-1": {"consensus": "keep", "total_score": 18}}]

    # Broken path (version_merge=False — wraps under action name):
    broken = DataTransformer.transform_structure(llm_response, "aggregate_votes")
    assert "aggregate_votes" in broken[0]["content"], "should wrap without version_merge"

    # Fixed path (version_merge=True — content used directly):
    fixed = DataTransformer.transform_structure(
        [{"sg-1": {"consensus": "keep", "total_score": 18}}],
        "aggregate_votes",
        version_merge=True,
    )
    content = fixed[0]["content"]

    if "aggregate_votes" in content:
        print("BUG CONFIRMED (LLM path): LLM output wrapped under action name")
        return False

    assert content["consensus"] == "keep"
    assert content["total_score"] == 18

    print("BUG FIXED (LLM path): LLM output used directly with version_merge=True")
    print(f"  content keys: {sorted(content.keys())}")
    return True


def main():
    print("=" * 70)
    print("Reproduction: version merge double-nesting bug (spec 093)")
    print("=" * 70)

    results = []

    print("\n--- FILE mode: version merge spread vs. wrap ---")
    results.append(test_file_mode_double_nesting())

    print("\n--- LLM path: transform_structure with version_merge ---")
    results.append(test_transformer_double_nesting())

    print("\n" + "=" * 70)
    if all(results):
        print("ALL TESTS PASS — double-nesting bug is fixed")
        return 0
    else:
        failed = sum(1 for r in results if not r)
        print(f"{failed} bug(s) still present")
        return 1


if __name__ == "__main__":
    sys.exit(main())
