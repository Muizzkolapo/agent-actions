#!/usr/bin/env python3
"""Fix import paths in _internal modules."""

import re
from pathlib import Path

# Mapping of old relative imports to new absolute imports
import_mappings = {
    # From _internal/filters/
    'from ..monitoring.metrics': 'from agent_actions._internal.common.monitoring.metrics',
    'from ..monitoring.logging': 'from agent_actions._internal.common.monitoring.logging',
    'from ..resilience.circuit_breaker': 'from agent_actions._internal.common.resilience.circuit_breaker',
    'from ..resilience.retry': 'from agent_actions._internal.common.resilience.retry',
    'from ..feature_flags.manager': 'from agent_actions._internal.common.feature_flags.manager',

    # From _internal/staging/
    'from ..prompt_processor.sample_enricher': 'from agent_actions.agents.transformers.pp_sample_enricher',
    'from ..prompt_processor.prompt_formatter': 'from agent_actions.agents.transformers.prompt_formatter',
    'from ..prompt_processor.response_transformer': 'from agent_actions.agents.transformers.pp_response_transformer',
    'from ..prompt_processor.context_preprocessor': 'from agent_actions.agents.transformers.pp_context_preprocessor',

    # From _internal/bootstrap/
    'from ..common.interfaces.interfaces': 'from agent_actions.core.contracts.interfaces',
}

def fix_imports():
    """Fix all relative imports in _internal modules."""
    internal_dir = Path('agent_actions/_internal')

    for py_file in internal_dir.rglob('*.py'):
        try:
            with open(py_file, 'r') as f:
                content = f.read()

            original = content

            # Apply all mappings
            for old_import, new_import in import_mappings.items():
                content = re.sub(re.escape(old_import), new_import, content)

            # Write back if changed
            if content != original:
                with open(py_file, 'w') as f:
                    f.write(content)
                print(f"Fixed imports in: {py_file}")

        except Exception as e:
            print(f"Error processing {py_file}: {e}")

if __name__ == "__main__":
    fix_imports()
    print("Import fixing complete!")