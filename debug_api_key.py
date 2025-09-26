#!/usr/bin/env python3
"""
Debug script to reproduce the exact agent configuration flow that's failing.
"""
import os
import sys
sys.path.insert(0, '/Users/muizz/Documents/codeshop/agent-actions')

from agent_actions.integrations.providers.vendor_base import BaseVendorHandler
from agent_actions.integrations.providers.anthropic.vendor import ClaudeHandler

def test_api_key_resolution():
    """Test how the agent configuration resolves the API key."""

    print("=== Environment Check ===")
    claude_key = os.getenv('CLAUDE_API_KEY')
    print(f"CLAUDE_API_KEY env var: {claude_key[:20] if claude_key else 'NOT SET'}...")
    print(f"CLAUDE_API_KEY length: {len(claude_key) if claude_key else 0}")

    # This mimics the agent configuration after action expander transformation
    print("\n=== Agent Configuration Test ===")
    agent_config = {
        'model_vendor': 'anthropic',
        'model_name': 'claude-3-5-haiku-20241022',
        'api_key': 'CLAUDE_API_KEY',  # This should reference the env var name
        'json_mode': True
    }

    print(f"Agent config: {agent_config}")

    # Test the BaseVendorHandler.get_api_key method
    print("\n=== API Key Resolution Test ===")
    resolved_key = BaseVendorHandler.get_api_key(agent_config)
    print(f"Resolved API key: {resolved_key[:20] if resolved_key else 'NULL'}...")
    print(f"Resolved key length: {len(resolved_key) if resolved_key else 0}")
    print(f"Keys match: {resolved_key == claude_key}")

    # Test actual API call through ClaudeHandler
    print("\n=== ClaudeHandler Test ===")
    try:
        prompt_config = "Say 'API key works' in exactly those words"
        context_data = {"content": "test"}
        schema = None

        result = ClaudeHandler.call_json(resolved_key, agent_config, prompt_config, context_data, schema)
        print(f"✅ ClaudeHandler succeeded: {result}")
    except Exception as e:
        print(f"❌ ClaudeHandler failed: {e}")
        print(f"Error type: {type(e)}")

        # Let's also test direct anthropic client with same key
        print("\n=== Direct Anthropic Client Test ===")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=resolved_key)
            response = client.messages.create(
                model='claude-3-5-haiku-20241022',
                max_tokens=10,
                messages=[{"role": "user", "content": "Hello"}]
            )
            print(f"✅ Direct anthropic client succeeded: {response.content[0].text}")
        except Exception as direct_e:
            print(f"❌ Direct anthropic client failed: {direct_e}")

if __name__ == "__main__":
    test_api_key_resolution()