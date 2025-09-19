#!/usr/bin/env python3
"""Comprehensive import fixing script."""

import re
from pathlib import Path

def fix_all_imports():
    """Fix all problematic imports in the codebase."""

    # Find all Python files
    python_files = list(Path('agent_actions').rglob('*.py'))

    # Import mappings to fix
    mappings = [
        # Old processors.exceptions -> core.exceptions
        (r'from agent_actions\.processors\.exceptions', 'from agent_actions.core.exceptions'),

        # Old models.* -> agents.base.* or core.parser.*
        (r'from agent_actions\.models\.agent_builder', 'from agent_actions.agents.base.agent_builder'),
        (r'from agent_actions\.models\.config_schema', 'from agent_actions.core.parser.config_schema'),
        (r'from agent_actions\.models\.config_types', 'from agent_actions.core.parser.config_types'),
        (r'from agent_actions\.models\.pipeline_config', 'from agent_actions.core.parser.pipeline_config'),
        (r'from agent_actions\.models\.processor_config', 'from agent_actions.core.parser.processor_config'),
        (r'from agent_actions\.models\.vendor_config', 'from agent_actions.core.parser.vendor_config'),
        (r'from agent_actions\.models\.environment_config', 'from agent_actions.core.context.environment_config'),

        # Old vendors.* -> integrations.providers.*
        (r'from agent_actions\.vendors\.base_vendor', 'from agent_actions.integrations.providers.vendor_base'),
        (r'from agent_actions\.vendors\.anthropic_vendor', 'from agent_actions.integrations.providers.anthropic.vendor'),
        (r'from agent_actions\.vendors\.openai_vendor', 'from agent_actions.integrations.providers.openai.vendor'),
        (r'from agent_actions\.vendors\.gemini_vendor', 'from agent_actions.integrations.providers.gemini.vendor'),

        # Old providers.* -> integrations.providers.*
        (r'from agent_actions\.providers\.base', 'from agent_actions.integrations.providers.base'),
        (r'from agent_actions\.providers\.factory', 'from agent_actions.integrations.providers.factory'),

        # Old handlers.* -> agents.handlers.*
        (r'from agent_actions\.handlers\.', 'from agent_actions.agents.handlers.'),

        # Old loaders.* -> agents.extractors.* or integrations.loaders.*
        (r'from agent_actions\.loaders\.data_loaders\.base_loader', 'from agent_actions.agents.base.base_loader'),
        (r'from agent_actions\.loaders\.data_loaders\.', 'from agent_actions.agents.extractors.'),

        # Old validators.* -> agents.validators.*
        (r'from agent_actions\.validators\.', 'from agent_actions.agents.validators.'),

        # Old interceptors.* -> integrations.interceptors.*
        (r'from agent_actions\.interceptors\.', 'from agent_actions.integrations.interceptors.'),

        # Old workflow.* -> core.graph.*
        (r'from agent_actions\.workflow\.', 'from agent_actions.core.graph.'),

        # Old services.* -> tasks.services.*
        (r'from agent_actions\.services\.', 'from agent_actions.tasks.services.'),

        # Old utils.* -> _internal.utils.*
        (r'from agent_actions\.utils\.', 'from agent_actions._internal.utils.field_chunking.'),

        # Old common.* -> _internal.common.* or core.*
        (r'from agent_actions\.common\.interfaces\.', 'from agent_actions.core.contracts.'),
        (r'from agent_actions\.common\.utils\.', 'from agent_actions._internal.utils.field_chunking.'),
        (r'from agent_actions\.common\.', 'from agent_actions._internal.common.'),

        # Old generators.* -> agents.generators.*
        (r'from agent_actions\.generators\.', 'from agent_actions.agents.generators.'),
    ]

    fixed_count = 0

    for py_file in python_files:
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()

            original = content

            # Apply all mappings
            for pattern, replacement in mappings:
                content = re.sub(pattern, replacement, content)

            # Write back if changed
            if content != original:
                with open(py_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"Fixed: {py_file}")
                fixed_count += 1

        except Exception as e:
            print(f"Error processing {py_file}: {e}")

    print(f"\nFixed imports in {fixed_count} files")

if __name__ == "__main__":
    fix_all_imports()