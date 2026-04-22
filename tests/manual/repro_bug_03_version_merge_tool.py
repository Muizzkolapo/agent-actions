"""Reproduction script for version_consumption merge bug in FILE mode tools.

Bug 1: apply_observe_for_file_mode fails to expand version namespace fields
       because it either takes the fast path (skipping wildcard expansion) or
       tries historical lookup (which fails — version keys aren't ancestors).
       LLM actions work because build_field_context_with_history uses
       _detect_version_namespaces() which the FILE mode path lacks.

Bug 2: data.get("content", data) returns {} when content key exists but is
       empty, instead of falling back to the full record.

Run:  python tests/manual/repro_bug_03_version_merge_tool.py
Expected: FAIL before fix, PASS after fix.
"""

import sys
from pathlib import Path
from unittest.mock import patch

project_root = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, project_root)

from agent_actions.prompt.context.scope_file_mode import apply_observe_for_file_mode


def test_version_wildcard_expansion():
    """Bug 1a: Wildcard observe on version namespaces not expanded."""
    # Simulated version-correlated merged data (3 version sources).
    # This is what VersionOutputCorrelator._merge_with_pattern produces.
    data = [
        {
            "source_guid": "sg-001",
            "node_id": "node-1",
            "content": {
                "gen_code_1": {"code": "def foo(): pass", "language": "python"},
                "gen_code_2": {"code": "function bar() {}", "language": "javascript"},
                "gen_code_3": {"code": "fn baz() {}", "language": "rust"},
            },
            "lineage": ["lineage-1"],
        }
    ]

    agent_config = {
        "name": "aggregate",
        "dependencies": ["gen_code_1", "gen_code_2", "gen_code_3"],
        "context_scope": {
            "observe": ["gen_code_1.*", "gen_code_2.*", "gen_code_3.*"],
        },
    }

    agent_indices = {
        "source": 0,
        "gen_code_1": 1,
        "gen_code_2": 2,
        "gen_code_3": 3,
        "aggregate": 4,
    }

    # Patch historical loader to avoid filesystem access — it's irrelevant here
    # because version data lives in the record content, not in historical files.
    with patch(
        "agent_actions.prompt.context.scope_file_mode._load_historical_node",
        return_value=None,
    ):
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=agent_config,
            agent_name="aggregate",
            agent_indices=agent_indices,
            file_path="/tmp/test.json",
        )

    content = result[0].get("content", result[0])

    # With multiple wildcard namespaces, observe should expand to qualified keys:
    #   gen_code_1.code, gen_code_1.language, gen_code_2.code, etc.
    has_expanded_keys = "gen_code_1.code" in content or "gen_code_1.language" in content

    if not has_expanded_keys:
        print("BUG 1a CONFIRMED: Wildcard expansion did not produce qualified keys")
        print(f"  content keys: {sorted(content.keys())}")
        print("  Expected: gen_code_1.code, gen_code_1.language, gen_code_2.code, ...")
        return False

    print("BUG 1a FIXED: Wildcards correctly expanded from version namespace content")
    print(f"  content keys: {sorted(content.keys())}")
    return True


def test_version_specific_field_resolution():
    """Bug 1b: Specific field observe on version namespaces not resolved."""
    data = [
        {
            "source_guid": "sg-001",
            "node_id": "node-1",
            "content": {
                "gen_code_1": {"code": "def foo(): pass", "language": "python"},
                "gen_code_2": {"code": "function bar() {}", "language": "javascript"},
            },
            "lineage": ["lineage-1"],
        }
    ]

    agent_config = {
        "name": "aggregate",
        "dependencies": ["gen_code_1", "gen_code_2"],
        "context_scope": {
            "observe": ["gen_code_1.code", "gen_code_2.code"],
        },
    }

    agent_indices = {
        "source": 0,
        "gen_code_1": 1,
        "gen_code_2": 2,
        "aggregate": 3,
    }

    with patch(
        "agent_actions.prompt.context.scope_file_mode._load_historical_node",
        return_value=None,
    ):
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=agent_config,
            agent_name="aggregate",
            agent_indices=agent_indices,
            file_path="/tmp/test.json",
        )

    content = result[0].get("content", result[0])

    # "code" collides across namespaces → qualified keys: gen_code_1.code, gen_code_2.code
    has_resolved = "gen_code_1.code" in content or "gen_code_2.code" in content

    if not has_resolved:
        print("BUG 1b CONFIRMED: Specific version namespace fields not resolved")
        print(f"  content keys: {sorted(content.keys())}")
        print("  Expected: gen_code_1.code, gen_code_2.code")
        return False

    # Verify values are correct
    assert content.get("gen_code_1.code") == "def foo(): pass", (
        f"gen_code_1.code mismatch: {content.get('gen_code_1.code')}"
    )
    assert content.get("gen_code_2.code") == "function bar() {}", (
        f"gen_code_2.code mismatch: {content.get('gen_code_2.code')}"
    )

    print("BUG 1b FIXED: Specific version fields correctly resolved")
    print(f"  gen_code_1.code = {content['gen_code_1.code']!r}")
    print(f"  gen_code_2.code = {content['gen_code_2.code']!r}")
    return True


def test_content_empty_fallback_trap():
    """Bug 2: Empty content {} should fall back to item-level keys.

    Previously, scope_file_mode.py used:
        content = item.get("content", item) if isinstance(item.get("content"), dict) else item
    which returns {} when content exists but is empty, instead of falling
    back to item.  The fix checks for non-empty dict before accepting content.

    Uses a source.* observe ref so the per-record loop runs (not fast path).
    """
    source_data = [{"source_guid": "sg-001", "content": {"url": "https://example.com"}}]

    # Record with empty content wrapper but meaningful top-level data.
    data = [
        {
            "source_guid": "sg-001",
            "node_id": "node-1",
            "content": {},
            "question": "What is 2+2?",
            "lineage": ["lineage-1"],
        }
    ]

    agent_config = {
        "name": "downstream",
        "dependencies": ["upstream"],
        "context_scope": {
            "observe": ["source.url", "upstream.question"],
        },
    }

    agent_indices = {"source": 0, "upstream": 1, "downstream": 2}

    with patch(
        "agent_actions.prompt.context.scope_file_mode._load_historical_node",
        return_value=None,
    ):
        result = apply_observe_for_file_mode(
            data=data,
            agent_config=agent_config,
            agent_name="downstream",
            agent_indices=agent_indices,
            file_path="/tmp/test.json",
            source_data=source_data,
        )

    result_item = result[0]
    content = result_item.get("content", {})

    # The old code extracted content={} from the record and never found
    # "question" during field resolution.  The fix falls back to the full
    # item when content is empty, making "question" visible.
    if isinstance(content, dict) and "question" in content:
        print("BUG 2 FIXED: Empty content falls back to item-level keys")
        print(f"  content has 'question': {content.get('question')!r}")
        print(f"  content has 'url' (from source): {content.get('url')!r}")
        return True

    print("BUG 2 CONFIRMED: Empty content did not fall back to item-level keys")
    print(f"  content keys: {sorted(content.keys()) if isinstance(content, dict) else 'NOT DICT'}")
    return False


def main():
    print("=" * 70)
    print("Reproduction: version_consumption merge bug in FILE mode tools")
    print("=" * 70)

    results = []

    print("\n--- Bug 1a: Wildcard expansion on version namespaces ---")
    results.append(test_version_wildcard_expansion())

    print("\n--- Bug 1b: Specific field resolution on version namespaces ---")
    results.append(test_version_specific_field_resolution())

    print("\n--- Bug 2: Empty content fallback trap ---")
    results.append(test_content_empty_fallback_trap())

    print("\n" + "=" * 70)
    if all(results):
        print("ALL TESTS PASS — bugs are fixed")
        return 0
    else:
        failed = sum(1 for r in results if not r)
        print(f"{failed} bug(s) still present")
        return 1


if __name__ == "__main__":
    sys.exit(main())
