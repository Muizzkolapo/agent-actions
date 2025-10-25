#!/usr/bin/env python3
"""
Fix Renamed Imports - Update imports for files that were renamed during migration.

Many files were renamed with prefixes (e.g., path_utils.py → utils_path_utils.py)
and imports need to be updated to reflect these new names.
"""

import re
import sys
from pathlib import Path
from typing import Dict


# Mapping of old import paths to new paths (accounting for renamed files)
RENAMED_MODULES = {
    # Utilities that were renamed
    'agent_actions.utilities.path_utils': 'agent_actions.utilities.utils_path_utils',
    'agent_actions.utilities.processor_utils': 'agent_actions.utilities.utils_processor_utils',
    'agent_actions.utilities.processor_helpers': 'agent_actions.utilities.utils_processor_helpers',

    # Core utilities that were moved
    'agent_actions.core.utils.path_utils': 'agent_actions.utilities.utils_path_utils',
    'agent_actions.core.utils.processor_utils': 'agent_actions.utilities.utils_processor_utils',
    'agent_actions.core.utils.processor_helpers': 'agent_actions.utilities.utils_processor_helpers',

    # Input loading files
    'agent_actions.core.loaders.data_loaders.base_loader': 'agent_actions.input_loading.base_base_loader',
    'agent_actions.agents.base.base_loader': 'agent_actions.input_loading.base_base_loader',
    'agent_actions.core.loaders.udf_loader': 'agent_actions.input_loading.udf_loader',

    # Agents that were moved
    'agent_actions.agents.base.agent_builder': 'agent_actions.llm_invocation.realtime.agent_builder',
    'agent_actions.agents.transformers.prompt_utils': 'agent_actions.preprocessing.prompt_utils',
    'agent_actions.agents.generators.data_generator': 'agent_actions.prompt_generation.data_generator',
    'agent_actions.agents.validators.input_signature_validator': 'agent_actions.validation.input_signature_validator',

    # State management
    'agent_actions.core.signatures': 'agent_actions.state_management.signatures',
    'agent_actions.core.context.signature_computer': 'agent_actions.state_management.signature_computer',
    'agent_actions.core.path_manager': 'agent_actions.state_management.path_manager',
    'agent_actions.core.context.path_manager': 'agent_actions.state_management.path_manager',

    # Tasks/CLI
    'agent_actions.tasks.validate_udfs': 'agent_actions.validation.validate_udfs',
    'agent_actions.tasks.services.batch_service': 'agent_actions.llm_invocation.batch.batch_service',

    # Configuration
    'agent_actions.core.bootstrap': 'agent_actions.configuration.bootstrap_bootstrap',

    # Orchestration
    'agent_actions.core.graph.agent_workflow': 'agent_actions.orchestration.agent_workflow',
    'agent_actions.core.graph.loop_correlator': 'agent_actions.orchestration.loop_correlator',
    'agent_actions.core.graph.dependency_injection': 'agent_actions.orchestration.dependency_injection',
    'agent_actions.core.runtime.agent_runner': 'agent_actions.orchestration.agent_runner',

    # Response processing / utilities
    'agent_actions.core.utils.guard_parser': 'agent_actions.response_processing.guard_parser',
    'agent_actions.utilities.guard_parser': 'agent_actions.response_processing.guard_parser',

    # Exceptions/Shared
    'agent_actions.core.exceptions': 'agent_actions.shared.exceptions',
}


def fix_imports_in_file(file_path: Path, dry_run: bool = True) -> int:
    """
    Fix imports in a single file.

    Returns:
        Number of changes made
    """
    try:
        content = file_path.read_text()
        original_content = content
        changes = 0

        # Fix each known renamed module
        for old_module, new_module in RENAMED_MODULES.items():
            # Pattern 1: from X import Y
            pattern1 = rf'from {re.escape(old_module)}(\s+import\s+)'
            replacement1 = rf'from {new_module}\1'
            new_content = re.sub(pattern1, replacement1, content)
            if new_content != content:
                changes += content.count(old_module) - new_content.count(old_module)
                content = new_content

            # Pattern 2: import X
            pattern2 = rf'(\s)import\s+{re.escape(old_module)}(\s|$)'
            replacement2 = rf'\1import {new_module}\2'
            new_content = re.sub(pattern2, replacement2, content)
            if new_content != content:
                changes += 1
                content = new_content

        if changes > 0 and not dry_run:
            file_path.write_text(content)

        return changes

    except Exception as e:
        print(f"   ⚠️  Error processing {file_path}: {e}")
        return 0


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python fix_renamed_imports.py <directory> [--execute]")
        sys.exit(1)

    directory = Path(sys.argv[1])
    execute = '--execute' in sys.argv

    print(f"🔧 Fixing renamed imports in {directory}/\n")

    if not execute:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    # Find all Python files
    python_files = list(directory.rglob('*.py'))

    total_changes = 0
    files_changed = 0

    for file_path in sorted(python_files):
        changes = fix_imports_in_file(file_path, dry_run=not execute)

        if changes > 0:
            files_changed += 1
            total_changes += changes
            rel_path = file_path.relative_to(directory)
            print(f"   ✏️  {rel_path}: {changes} import(s) fixed")

    print(f"\n📊 Summary:")
    print(f"   Files scanned: {len(python_files)}")
    print(f"   Files changed: {files_changed}")
    print(f"   Total imports fixed: {total_changes}")

    if not execute and total_changes > 0:
        print(f"\n⚠️  To apply changes, run:")
        print(f"   python fix_renamed_imports.py {directory} --execute")
    elif execute and total_changes > 0:
        print(f"\n✅ Import paths updated successfully!")
    else:
        print(f"\n✅ No import changes needed!")


if __name__ == '__main__':
    main()
