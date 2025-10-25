#!/usr/bin/env python3
"""
Fix Import Paths - Update import statements after migration.

Analyzes all Python files and updates import paths to match the new
stage-based structure.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import json


def load_migration_map(plan_file: str) -> Dict[str, str]:
    """
    Create a mapping of old paths to new paths from migration plan.

    Returns: {old_module_path: new_module_path}
    """
    with open(plan_file) as f:
        plan = json.load(f)

    mapping = {}

    for rule in plan['rules']:
        source = Path(rule['source'])
        dest = Path(rule['destination'])

        # Convert file paths to module paths
        # e.g., agent_actions/core/parser/config.py → agent_actions.core.parser.config
        def path_to_module(p: Path) -> str:
            parts = p.parts
            # Find agent_actions index
            if 'agent_actions' in parts:
                idx = parts.index('agent_actions')
                module_parts = parts[idx:]
                # Remove .py extension
                if module_parts[-1].endswith('.py'):
                    module_parts = list(module_parts[:-1]) + [module_parts[-1][:-3]]
                return '.'.join(module_parts)
            return ''

        old_module = path_to_module(source)
        new_module = path_to_module(dest)

        if old_module and new_module:
            mapping[old_module] = new_module

    return mapping


def find_python_files(root: Path, include_tests: bool = False) -> List[Path]:
    """Find all Python files in the new structure."""
    files = []

    # Only search in stage directories
    stage_dirs = [
        'input_loading', 'preprocessing', 'validation', 'prompt_generation',
        'llm_invocation', 'response_processing', 'postprocessing',
        'orchestration', 'state_management', 'configuration',
        'cli', 'utilities', 'shared'
    ]

    for stage in stage_dirs:
        stage_path = root / stage
        if stage_path.exists():
            files.extend(stage_path.rglob('*.py'))

    # Include tests if requested
    if include_tests:
        tests_path = Path('tests')
        if tests_path.exists():
            files.extend(tests_path.rglob('*.py'))

    return files


def extract_imports(content: str) -> List[Tuple[str, str, str]]:
    """
    Extract import statements from file.

    Returns: [(full_line, module_path, imported_items), ...]
    """
    imports = []

    # Match: from agent_actions.x.y import z
    from_pattern = r'^(\s*from\s+(agent_actions\.[^\s]+)\s+import\s+(.+))$'

    # Match: import agent_actions.x.y
    import_pattern = r'^(\s*import\s+(agent_actions\.[^\s,]+))(.*)$'

    for line in content.split('\n'):
        # Try from ... import
        match = re.match(from_pattern, line)
        if match:
            full_line = match.group(1)
            module = match.group(2)
            items = match.group(3)
            imports.append((full_line, module, items))
            continue

        # Try import
        match = re.match(import_pattern, line)
        if match:
            full_line = match.group(1) + match.group(3)
            module = match.group(2)
            imports.append((full_line, module, ''))

    return imports


def fix_import(old_import: str, module: str, items: str, mapping: Dict[str, str]) -> str:
    """Fix a single import statement."""

    # Check if module needs updating
    # Try exact match first
    if module in mapping:
        new_module = mapping[module]
        if items:
            return f"from {new_module} import {items}"
        else:
            return f"import {new_module}"

    # Try partial matches (for submodules)
    for old_path, new_path in mapping.items():
        if module.startswith(old_path):
            # Replace the matching prefix
            new_module = module.replace(old_path, new_path, 1)
            if items:
                return f"from {new_module} import {items}"
            else:
                return f"import {new_module}"

    # No change needed
    return old_import


def fix_file_imports(file_path: Path, mapping: Dict[str, str], dry_run: bool = True) -> int:
    """Fix imports in a single file. Returns number of changes."""
    content = file_path.read_text()
    original_content = content

    imports = extract_imports(content)
    changes = 0

    for old_import, module, items in imports:
        new_import = fix_import(old_import, module, items, mapping)

        if new_import != old_import:
            # Replace in content
            content = content.replace(old_import, new_import)
            changes += 1

    if changes > 0 and not dry_run:
        file_path.write_text(content)

    return changes


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python fix_imports.py plan_final.json [--execute] [--tests]")
        sys.exit(1)

    plan_file = sys.argv[1]
    execute = '--execute' in sys.argv
    include_tests = '--tests' in sys.argv

    print("🔧 Fixing import paths...\n")

    # Load migration mapping
    print(f"📋 Loading migration mapping from {plan_file}...")
    mapping = load_migration_map(plan_file)
    print(f"   Loaded {len(mapping)} path mappings\n")

    # Find Python files
    root = Path('agent_actions')
    search_desc = "stage directories" + (" and tests" if include_tests else "")
    print(f"🔍 Finding Python files in {search_desc}...")
    python_files = find_python_files(root, include_tests=include_tests)
    print(f"   Found {len(python_files)} Python files\n")

    if not execute:
        print("⚠️  DRY RUN MODE - No files will be modified\n")

    # Fix imports in each file
    total_changes = 0
    files_changed = 0

    for file_path in python_files:
        changes = fix_file_imports(file_path, mapping, dry_run=not execute)

        if changes > 0:
            files_changed += 1
            total_changes += changes
            try:
                rel_path = file_path.relative_to(root)
            except ValueError:
                # File is in tests/, not agent_actions/
                rel_path = file_path
            print(f"   ✏️  {rel_path}: {changes} import(s) fixed")

    print(f"\n📊 Summary:")
    print(f"   Files scanned: {len(python_files)}")
    print(f"   Files changed: {files_changed}")
    print(f"   Total imports fixed: {total_changes}")

    if not execute and total_changes > 0:
        print(f"\n⚠️  To apply changes, run:")
        print(f"   python fix_imports.py {plan_file} --execute")
    elif execute and total_changes > 0:
        print(f"\n✅ Import paths updated successfully!")
    else:
        print(f"\n✅ No import changes needed!")


if __name__ == '__main__':
    main()
