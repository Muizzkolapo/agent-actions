"""Manual repro for spec 088: PassthroughEnricher with namespaced content.

Run: python -m tests.manual.repro_088_enrichment
"""

from agent_actions.processing.enrichment import (
    LineageEnricher,
    MetadataEnricher,
    PassthroughEnricher,
    RecoveryEnricher,
)
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)


def _make_context(action_name="action_c"):
    return ProcessingContext(
        agent_config={"agent_type": action_name, "kind": "llm", "granularity": "record"},
        agent_name=action_name,
        is_first_stage=False,
    )


def scenario_1_passthrough_enricher_namespaced():
    """PassthroughEnricher should merge passthrough fields INTO action namespace."""
    print("\n=== Scenario 1: PassthroughEnricher with namespaced content ===")

    result = ProcessingResult(
        status=ProcessingStatus.SUCCESS,
        data=[
            {
                "content": {
                    "action_a": {"field_a": "val_a"},
                    "action_b": {"field_b": "val_b"},
                    "action_c": {"llm_field": "llm_output"},
                },
            }
        ],
        passthrough_fields={"passthrough_field": "preserved_value"},
    )
    context = _make_context("action_c")

    enricher = PassthroughEnricher()
    enriched = enricher.enrich(result, context)

    content = enriched.data[0]["content"]
    print(f"  Content after enrichment: {content}")

    # EXPECTED: passthrough_field inside action_c namespace
    expected_in_ns = "passthrough_field" in content.get("action_c", {})
    # BUG: passthrough_field at top level (alongside action_a, action_b, action_c)
    at_top_level = "passthrough_field" in content and "passthrough_field" not in content.get(
        "action_c", {}
    )

    if at_top_level:
        print("  RESULT: BUG — passthrough_field merged at TOP LEVEL (alongside namespaces)")
    elif expected_in_ns:
        print("  RESULT: FIXED — passthrough_field merged INTO action_c namespace")
    else:
        print(f"  RESULT: UNEXPECTED — check content: {content}")


def scenario_2_lineage_enricher_record_level():
    """LineageEnricher should NOT modify content internals."""
    print("\n=== Scenario 2: LineageEnricher works at record level ===")

    namespaced_content = {
        "action_a": {"field_a": "val_a"},
        "action_b": {"field_b": "val_b"},
    }
    result = ProcessingResult(
        status=ProcessingStatus.SUCCESS,
        data=[{"content": dict(namespaced_content), "source_guid": "sg-1"}],
        source_guid="sg-1",
    )
    context = _make_context("action_c")
    context.is_first_stage = True

    enricher = LineageEnricher()
    enriched = enricher.enrich(result, context)

    item = enriched.data[0]
    content = item["content"]
    has_lineage = "lineage" in item
    has_node_id = "node_id" in item
    content_unchanged = set(content.keys()) == set(namespaced_content.keys())

    print(f"  lineage at record level: {has_lineage}")
    print(f"  node_id at record level: {has_node_id}")
    print(f"  content unchanged: {content_unchanged} (keys: {list(content.keys())})")

    if has_lineage and has_node_id and content_unchanged:
        print("  RESULT: OK — LineageEnricher works at record level, content untouched")
    else:
        print("  RESULT: UNEXPECTED")


def scenario_3_metadata_enricher_record_level():
    """MetadataEnricher should NOT modify content internals."""
    print("\n=== Scenario 3: MetadataEnricher works at record level ===")

    namespaced_content = {"action_a": {"field_a": "val_a"}}
    result = ProcessingResult(
        status=ProcessingStatus.SUCCESS,
        data=[{"content": dict(namespaced_content)}],
        pre_extracted_metadata={"model": "gpt-4", "tokens": 100},
    )
    context = _make_context("action_c")

    enricher = MetadataEnricher()
    enriched = enricher.enrich(result, context)

    item = enriched.data[0]
    has_metadata = "metadata" in item
    content_unchanged = set(item["content"].keys()) == set(namespaced_content.keys())

    print(f"  metadata at record level: {has_metadata}")
    print(f"  content unchanged: {content_unchanged}")

    if has_metadata and content_unchanged:
        print("  RESULT: OK — MetadataEnricher works at record level")
    else:
        print("  RESULT: UNEXPECTED")


def scenario_4_recovery_enricher_record_level():
    """RecoveryEnricher should NOT modify content internals."""
    print("\n=== Scenario 4: RecoveryEnricher works at record level ===")

    namespaced_content = {"action_a": {"field_a": "val_a"}}
    result = ProcessingResult(
        status=ProcessingStatus.SUCCESS,
        data=[{"content": dict(namespaced_content)}],
        recovery_metadata=RecoveryMetadata(
            retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="timeout")
        ),
    )
    context = _make_context("action_c")

    enricher = RecoveryEnricher()
    enriched = enricher.enrich(result, context)

    item = enriched.data[0]
    has_recovery = "_recovery" in item
    content_unchanged = set(item["content"].keys()) == set(namespaced_content.keys())

    print(f"  _recovery at record level: {has_recovery}")
    print(f"  content unchanged: {content_unchanged}")

    if has_recovery and content_unchanged:
        print("  RESULT: OK — RecoveryEnricher works at record level")
    else:
        print("  RESULT: UNEXPECTED")


def scenario_5_passthrough_builder():
    """passthrough_builder content extraction with namespaced content."""
    print("\n=== Scenario 5: PassthroughItemBuilder content extraction ===")

    from agent_actions.utils.passthrough_builder import PassthroughItemBuilder

    row = {
        "content": {"action_a": {"field_a": "val_a"}, "action_b": {"field_b": "val_b"}},
        "target_id": "tid-1",
        "source_guid": "sg-1",
    }
    item = PassthroughItemBuilder.build_item(
        row=row, reason="where_clause_not_matched", action_name="action_c"
    )

    content = item["content"]
    print(f"  tombstone content: {content}")

    # Content should be the namespaced dict, not the entire row
    if "action_a" in content and "action_b" in content:
        print("  RESULT: OK — namespaced content preserved in tombstone")
    else:
        print("  RESULT: UNEXPECTED")

    # Also test the fallback case (no content key)
    row_no_content = {"field1": "val1", "target_id": "tid-2"}
    item2 = PassthroughItemBuilder.build_item(
        row=row_no_content, reason="where_clause_not_matched", action_name="action_c"
    )
    content2 = item2["content"]
    print(f"  tombstone content (no content key): {content2}")

    if content2 is row_no_content:
        print("  RESULT: BUG — falls back to entire row (includes target_id etc)")
    elif content2 == {}:
        print("  RESULT: FIXED — empty dict when no content key")
    else:
        print(f"  RESULT: UNEXPECTED — {content2}")


if __name__ == "__main__":
    scenario_1_passthrough_enricher_namespaced()
    scenario_2_lineage_enricher_record_level()
    scenario_3_metadata_enricher_record_level()
    scenario_4_recovery_enricher_record_level()
    scenario_5_passthrough_builder()
    print("\n=== Done ===")
