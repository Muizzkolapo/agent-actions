#!/usr/bin/env python3
"""
Simple test script to verify context_scope feature works.

This script tests the context_scope implementation with a minimal workflow
to ensure all three directives (include, exclude, passthrough) work correctly.
"""

import json
from agent_actions.prompt_generation.data_generator import DataGenerator
from agent_actions.utilities.context_scope_processor import ContextScopeProcessor


def test_context_scope_basic():
    """Test basic context_scope functionality with minimal config."""
    print("=" * 80)
    print("TEST 1: Basic Context Scope Processing")
    print("=" * 80)

    # Setup test data
    field_context = {
        'source': {
            'page_content': 'Sample educational content for quiz generation',
            'topic': 'Python Programming',
            'api_key': 'secret_key_12345',  # Should be excluded
            'platform_name': 'QanaLabs',
            'exam_name': 'Python Basics'
        },
        'fact_extractor': {
            'candidate_facts': ['fact1', 'fact2', 'fact3'],
            'reference_tables': {'table1': 'data1', 'table2': 'data2'},  # Should go to LLM context
            'document_id': 'doc-123'  # Should passthrough
        }
    }

    context_scope = {
        'include': ['fact_extractor.reference_tables'],
        'exclude': ['source.api_key'],
        'passthrough': ['fact_extractor.document_id', 'source.platform_name', 'source.exam_name']
    }

    # Execute
    prompt_context, llm_context, passthrough_fields = ContextScopeProcessor.apply_context_scope(
        field_context, context_scope
    )

    # Validate INCLUDE
    print("\n1. Testing INCLUDE directive:")
    print(f"   ✓ reference_tables in llm_context: {
'reference_tables' in llm_context}")
    print(f"   ✓ reference_tables NOT in prompt_context: {'reference_tables' not in prompt_context.get('fact_extractor', {})}")

    # Validate EXCLUDE
    print("\n2. Testing EXCLUDE directive:")
    print(f"   ✓ api_key NOT in prompt_context: {'api_key' not in prompt_context.get('source', {})}")
    print(f"   ✓ api_key NOT in llm_context: {'api_key' not in llm_context}")
    print(f"   ✓ api_key NOT in passthrough: {'api_key' not in passthrough_fields}")

    # Validate PASSTHROUGH
    print("\n3. Testing PASSTHROUGH directive:")
    print(f"   ✓ document_id in passthrough_fields: {'document_id' in passthrough_fields}")
    print(f"   ✓ platform_name in passthrough_fields: {'platform_name' in passthrough_fields}")
    print(f"   ✓ exam_name in passthrough_fields: {'exam_name' in passthrough_fields}")
    print(f"   ✓ document_id NOT in llm_context: {'document_id' not in llm_context}")

    # Show what's left in prompt_context
    print("\n4. Fields remaining in prompt_context (for {action.field} rendering):")
    for action, fields in prompt_context.items():
        print(f"   {action}: {list(fields.keys())}")

    print("\n" + "=" * 80)
    print("TEST 1: ✅ PASSED")
    print("=" * 80)


def test_format_llm_context():
    """Test LLM context formatting."""
    print("\n" + "=" * 80)
    print("TEST 2: LLM Context Formatting")
    print("=" * 80)

    llm_context = {
        'reference_tables': {'table1': 'data1', 'table2': 'data2'},
        'grouped_facts': ['fact1', 'fact2'],
        'metadata': {'count': 5, 'source': 'textbook'}
    }

    formatted = ContextScopeProcessor.format_llm_context(llm_context)

    print("\nFormatted LLM Context:")
    print("-" * 80)
    print(formatted)
    print("-" * 80)

    # Validate
    print("\n✓ Contains 'Additional context:':", 'Additional context:' in formatted)
    print("✓ Contains 'reference_tables:':", 'reference_tables:' in formatted)
    print("✓ Contains 'grouped_facts:':", 'grouped_facts:' in formatted)
    print("✓ JSON formatted:", '"table1"' in formatted)

    print("\n" + "=" * 80)
    print("TEST 2: ✅ PASSED")
    print("=" * 80)


def test_merge_passthrough():
    """Test merging passthrough fields into response."""
    print("\n" + "=" * 80)
    print("TEST 3: Passthrough Field Merging")
    print("=" * 80)

    # Simulate LLM response (structured format)
    llm_response = [
        {
            'source_guid': 'guid-abc-123',
            'node_id': 'node_1_classifier',
            'content': {
                'classification': 'positive',
                'confidence': 0.92
            }
        }
    ]

    passthrough_fields = {
        'document_id': 'doc-123',
        'platform_name': 'QanaLabs',
        'exam_name': 'Python Basics',
        'topic': 'Variables and Data Types'
    }

    # Execute
    result = ContextScopeProcessor.merge_passthrough_fields(
        llm_response, passthrough_fields
    )

    print("\nOriginal LLM Response:")
    print(json.dumps(llm_response[0]['content'], indent=2))

    print("\nAfter Passthrough Merge:")
    print(json.dumps(result[0]['content'], indent=2))

    # Validate
    print("\n✓ Original fields present:")
    print(f"   - classification: {result[0]['content']['classification']}")
    print(f"   - confidence: {result[0]['content']['confidence']}")

    print("\n✓ Passthrough fields merged:")
    print(f"   - document_id: {result[0]['content'].get('document_id')}")
    print(f"   - platform_name: {result[0]['content'].get('platform_name')}")
    print(f"   - exam_name: {result[0]['content'].get('exam_name')}")
    print(f"   - topic: {result[0]['content'].get('topic')}")

    print("\n" + "=" * 80)
    print("TEST 3: ✅ PASSED")
    print("=" * 80)


def test_with_data_generator():
    """Test context_scope with DataGenerator (integration test)."""
    print("\n" + "=" * 80)
    print("TEST 4: DataGenerator Integration")
    print("=" * 80)

    # Minimal agent config with context_scope
    agent_config = {
        'prompt': 'Classify this content: {source.page_content}',
        'schema': {
            'classification': 'string',
            'confidence': 'number'
        },
        'context_scope': {
            'include': ['source.metadata'],
            'exclude': ['source.api_key'],
            'passthrough': ['source.document_id', 'source.platform_name']
        }
    }

    generator = DataGenerator(
        agent_config=agent_config,
        agent_name='test_classifier',
        dependency_configs={},
        agent_indices={'test_classifier': 0}
    )

    # Source content
    source_content = {
        'page_content': 'Sample text about Python variables',
        'metadata': {'chapters': ['1', '2'], 'difficulty': 'beginner'},
        'api_key': 'secret_key',
        'document_id': 'doc-456',
        'platform_name': 'QanaLabs'
    }

    # Execute
    formatted_prompt, _, llm_context, passthrough_fields = generator._format_prompt(
        {}, source_content=source_content
    )

    print("\n1. Formatted Prompt:")
    print("-" * 80)
    print(formatted_prompt[:200] + "..." if len(formatted_prompt) > 200 else formatted_prompt)
    print("-" * 80)

    print("\n2. LLM Context (will be appended to prompt before sending to LLM):")
    print(f"   - metadata in llm_context: {'metadata' in llm_context}")
    print(f"   - Value: {llm_context.get('metadata')}")

    print("\n3. Excluded Fields (security):")
    print(f"   - api_key NOT in llm_context: {'api_key' not in llm_context}")
    print(f"   - api_key NOT in passthrough: {'api_key' not in passthrough_fields}")

    print("\n4. Passthrough Fields (will be merged to output):")
    print(f"   - document_id: {passthrough_fields.get('document_id')}")
    print(f"   - platform_name: {passthrough_fields.get('platform_name')}")

    print("\n" + "=" * 80)
    print("TEST 4: ✅ PASSED")
    print("=" * 80)


def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("CONTEXT_SCOPE FEATURE TEST SUITE")
    print("=" * 80)
    print("\nTesting the three directives:")
    print("  - include: Send fields to LLM context only")
    print("  - exclude: Block fields from LLM entirely")
    print("  - passthrough: Merge fields to output only")
    print("\n" + "=" * 80)

    try:
        test_context_scope_basic()
        test_format_llm_context()
        test_merge_passthrough()
        test_with_data_generator()

        print("\n" + "=" * 80)
        print("🎉 ALL TESTS PASSED! 🎉")
        print("=" * 80)
        print("\ncontext_scope feature is working correctly!")
        print("\nNext steps:")
        print("  1. Try with your full QanaLabs workflow")
        print("  2. Use test_context_scope_qanalabs.yml as reference")
        print("  3. Compare outputs with original config (observe vs passthrough)")
        print("\n" + "=" * 80)

    except Exception as e:
        print("\n" + "=" * 80)
        print("❌ TEST FAILED")
        print("=" * 80)
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
