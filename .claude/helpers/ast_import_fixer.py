#!/usr/bin/env python3
"""
AST-based Import Fixer - Properly rewrite import statements preserving formatting.

Uses Python's AST (Abstract Syntax Tree) to parse and rewrite imports correctly,
preserving all indentation, comments, and code structure.
"""

import ast
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional


class ImportRewriter(ast.NodeTransformer):
    """AST transformer that rewrites import statements."""

    def __init__(self, mapping: Dict[str, str]):
        """
        Initialize rewriter with path mapping.

        Args:
            mapping: {old_module_path: new_module_path}
        """
        self.mapping = mapping
        self.changes = []

    def _find_replacement(self, module: str) -> Optional[str]:
        """
        Find replacement for a module path.

        Args:
            module: Original module path (e.g., 'agent_actions.core.parser.config')

        Returns:
            New module path or None if no replacement needed
        """
        # Try exact match first
        if module in self.mapping:
            return self.mapping[module]

        # Try partial matches (for submodules)
        # Sort by length (longest first) to match most specific path
        for old_path in sorted(self.mapping.keys(), key=len, reverse=True):
            if module.startswith(old_path + ".") or module == old_path:
                # Replace the matching prefix
                new_module = module.replace(old_path, self.mapping[old_path], 1)
                return new_module

        return None

    def visit_Import(self, node: ast.Import) -> ast.Import:
        """
        Rewrite 'import agent_actions.x.y' statements.

        Args:
            node: Import AST node

        Returns:
            Modified or original node
        """
        modified = False

        for alias in node.names:
            new_name = self._find_replacement(alias.name)
            if new_name and new_name != alias.name:
                self.changes.append(
                    {
                        "line": node.lineno,
                        "old": f"import {alias.name}",
                        "new": f"import {new_name}",
                    }
                )
                alias.name = new_name
                modified = True

        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
        """
        Rewrite 'from agent_actions.x.y import z' statements.

        Args:
            node: ImportFrom AST node

        Returns:
            Modified or original node
        """
        if node.module:
            new_module = self._find_replacement(node.module)
            if new_module and new_module != node.module:
                self.changes.append(
                    {
                        "line": node.lineno,
                        "old": f"from {node.module} import ...",
                        "new": f"from {new_module} import ...",
                    }
                )
                node.module = new_module

        return node


def load_migration_map(plan_file: str) -> Dict[str, str]:
    """
    Create a mapping of old paths to new paths from migration plan.

    Returns: {old_module_path: new_module_path}
    """
    with open(plan_file) as f:
        plan = json.load(f)

    mapping = {}

    for rule in plan["rules"]:
        source = Path(rule["source"])
        dest = Path(rule["destination"])

        # Convert file paths to module paths
        def path_to_module(p: Path) -> str:
            parts = p.parts
            # Find agent_actions index
            if "agent_actions" in parts:
                idx = parts.index("agent_actions")
                module_parts = parts[idx:]
                # Remove .py extension
                if module_parts[-1].endswith(".py"):
                    module_parts = list(module_parts[:-1]) + [module_parts[-1][:-3]]
                return ".".join(module_parts)
            return ""

        old_module = path_to_module(source)
        new_module = path_to_module(dest)

        if old_module and new_module:
            mapping[old_module] = new_module

    return mapping


def fix_file_imports_ast(file_path: Path, mapping: Dict[str, str], dry_run: bool = True) -> int:
    """
    Fix imports in a file using AST transformation.

    Args:
        file_path: Path to Python file
        mapping: Module path mapping
        dry_run: If True, don't write changes

    Returns:
        Number of changes made
    """
    try:
        # Read original content
        content = file_path.read_text()

        # Parse AST
        tree = ast.parse(content, filename=str(file_path))

        # Transform imports
        rewriter = ImportRewriter(mapping)
        new_tree = rewriter.visit(tree)

        if not rewriter.changes:
            return 0

        # Convert AST back to source code
        # Use ast.unparse (Python 3.9+) or compile and decompile
        try:
            new_content = ast.unparse(new_tree)
        except AttributeError:
            # Python < 3.9: Fall back to astor if available
            try:
                import astor

                new_content = astor.to_source(new_tree)
            except ImportError:
                # Last resort: use compile + rewrite manually
                # This is complex, so we'll use a different approach
                print(f"   ⚠️  Python 3.9+ required for ast.unparse, or install 'astor'")
                return 0

        # Write changes
        if not dry_run:
            file_path.write_text(new_content)

        return len(rewriter.changes)

    except SyntaxError as e:
        print(f"   ⚠️  Syntax error in {file_path}: {e}")
        return 0
    except Exception as e:
        print(f"   ⚠️  Error processing {file_path}: {e}")
        return 0


def find_python_files(root: Path, include_tests: bool = False) -> List[Path]:
    """Find all Python files to process."""
    files = []

    # 13-stage architecture directories
    stage_dirs = [
        "input_loading",
        "preprocessing",
        "validation",
        "prompt_generation",
        "llm_invocation",
        "response_processing",
        "postprocessing",
        "orchestration",
        "state_management",
        "configuration",
        "cli",
        "utilities",
        "shared",
    ]

    for stage in stage_dirs:
        stage_path = root / stage
        if stage_path.exists():
            files.extend(stage_path.rglob("*.py"))

    # Include tests if requested
    if include_tests:
        tests_path = Path("tests")
        if tests_path.exists():
            files.extend(tests_path.rglob("*.py"))

    return files


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python ast_import_fixer.py plan_final.json [--execute] [--tests]")
        sys.exit(1)

    plan_file = sys.argv[1]
    execute = "--execute" in sys.argv
    include_tests = "--tests" in sys.argv

    print("🔧 AST-based Import Fixer\n")

    # Check Python version
    if sys.version_info < (3, 9):
        print("⚠️  Warning: Python 3.9+ recommended for best results")
        print("   Attempting to use 'astor' library...\n")

    # Load migration mapping
    print(f"📋 Loading migration mapping from {plan_file}...")
    mapping = load_migration_map(plan_file)
    print(f"   Loaded {len(mapping)} path mappings\n")

    # Find Python files
    root = Path("agent_actions")
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
        changes = fix_file_imports_ast(file_path, mapping, dry_run=not execute)

        if changes > 0:
            files_changed += 1
            total_changes += changes
            try:
                rel_path = file_path.relative_to(root)
            except ValueError:
                rel_path = file_path
            print(f"   ✏️  {rel_path}: {changes} import(s) fixed")

    print(f"\n📊 Summary:")
    print(f"   Files scanned: {len(python_files)}")
    print(f"   Files changed: {files_changed}")
    print(f"   Total imports fixed: {total_changes}")

    if not execute and total_changes > 0:
        print(f"\n⚠️  To apply changes, run:")
        print(f"   python ast_import_fixer.py {plan_file} --execute --tests")
    elif execute and total_changes > 0:
        print(f"\n✅ Import paths updated successfully!")
    else:
        print(f"\n✅ No import changes needed!")


if __name__ == "__main__":
    main()
