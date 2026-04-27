"""Reproduction script for version_consumption merge bug in FILE mode tools.

Bug 1: apply_context_scope_for_records failed to expand version namespace fields
       because it either took the fast path (skipping wildcard expansion) or
       tried historical lookup (which failed — version keys aren't ancestors).
       Fixed: unified apply_context_scope_for_records reads from record namespaces directly.

Bug 2: data.get("content", data) returned {} when content key existed but was
       empty, instead of falling back to the full record.
       Fixed: get_existing_content utility handles this correctly.

Run:  python tests/manual/repro_bug_03_version_merge_tool.py
Expected: PASS (both bugs are fixed).
"""

import sys
from pathlib import Path

project_root = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, project_root)

from agent_actions.prompt.context.scope_application import apply_context_scope_for_records


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

    context_scope = {
        "observe": ["gen_code_1.*", "gen_code_2.*", "gen_code_3.*"],
    }

    result = apply_context_scope_for_records(
        records=data,
        context_scope=context_scope,
        action_name="aggregate",
    )

    content = result[0]["content"]

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

    context_scope = {
        "observe": ["gen_code_1.code", "gen_code_2.code"],
    }

    result = apply_context_scope_for_records(
        records=data,
        context_scope=context_scope,
        action_name="aggregate",
    )

    content = result[0]["content"]

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
    """Bug 2: Empty content {} with source observe ref — wildcard on missing
    upstream namespace is graceful (no crash), source resolves correctly."""
    source_data = [{"source_guid": "sg-001", "content": {"url": "https://example.com"}}]

    # Record with empty content wrapper.
    data = [
        {
            "source_guid": "sg-001",
            "node_id": "node-1",
            "content": {},
            "lineage": ["lineage-1"],
        }
    ]

    context_scope = {
        "observe": ["source.url", "upstream.*"],
    }

    result = apply_context_scope_for_records(
        records=data,
        context_scope=context_scope,
        action_name="downstream",
        source_data=source_data,
    )

    result_item = result[0]
    content = result_item.get("content", {})

    # source.url should be resolved from source_data
    if isinstance(content, dict) and "url" in content:
        print("BUG 2 FIXED: Source namespace resolved on empty content record")
        print(f"  content has 'url' (from source): {content.get('url')!r}")
        return True

    print("BUG 2 CONFIRMED: Source resolve failed on empty content record")
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
