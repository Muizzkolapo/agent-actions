#!/usr/bin/env python3
"""
Workflow Migration CLI Tool

Converts workflow configurations from old format to new format.
"""

import sys
import argparse
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agent_actions.core.migration.format_migrator import WorkflowMigrator


def main():
    """Main CLI function."""
    parser = argparse.ArgumentParser(
        description="Migrate workflow configurations from old format to new format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate a single workflow file
  python migrate_workflow.py sample.yml -o migrated.yml

  # Migrate with automatic output naming
  python migrate_workflow.py old_workflow.yml

  # Show what would be migrated without saving
  python migrate_workflow.py sample.yml --dry-run
        """
    )

    parser.add_argument(
        'input_file',
        help='Path to the old format workflow YAML file'
    )

    parser.add_argument(
        '-o', '--output',
        help='Output file path (default: {input_file}_v2.yml)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show migration results without saving to file'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output showing detailed migration information'
    )

    args = parser.parse_args()

    # Validate input file
    if not os.path.exists(args.input_file):
        print(f"❌ Error: Input file '{args.input_file}' not found")
        sys.exit(1)

    # Determine output file
    if not args.output:
        input_path = Path(args.input_file)
        args.output = input_path.parent / f"{input_path.stem}_v2{input_path.suffix}"

    try:
        # Initialize migrator
        migrator = WorkflowMigrator()

        if args.verbose:
            print(f"🔄 Migrating {args.input_file}...")

        # Perform migration
        migrated_workflow = migrator.migrate_from_yaml_file(args.input_file)

        if args.dry_run:
            print("🔍 DRY RUN - Migration Preview:")
        else:
            # Save result
            migrator.save_migrated_workflow(migrated_workflow, args.output)
            print(f"✅ Migration successful! Output saved to {args.output}")

        # Print summary
        print(f"\n📊 Migration Summary:")
        print(f"   Workflow: {migrated_workflow.name}")
        print(f"   Description: {migrated_workflow.description}")
        print(f"   Version: {migrated_workflow.version}")
        print(f"   Actions: {len(migrated_workflow.actions)}")
        print(f"   Plan steps: {len(migrated_workflow.plan)}")

        # Show defaults
        if migrated_workflow.defaults and args.verbose:
            print(f"\n⚙️  Defaults:")
            defaults = migrated_workflow.defaults
            if defaults.vendor:
                print(f"   Vendor: {defaults.vendor}")
            if defaults.model:
                print(f"   Model: {defaults.model}")
            if defaults.json_mode is not None:
                print(f"   JSON Mode: {defaults.json_mode}")
            if defaults.granularity:
                print(f"   Granularity: {defaults.granularity}")
            if defaults.run_mode:
                print(f"   Run Mode: {defaults.run_mode}")

        # Show actions
        if args.verbose:
            print(f"\n🔧 Actions:")
            dep_graph = migrated_workflow.get_dependency_graph()

            for action in migrated_workflow.actions:
                deps = dep_graph.get(action.name, [])
                dep_str = f" (depends: {', '.join(deps)})" if deps else ""
                kind_str = f" [{action.kind}]" if action.kind != 'llm' else ""
                print(f"   {action.name}{kind_str}: {action.intent}{dep_str}")

        # Show execution plan
        if args.verbose:
            print(f"\n📋 Execution Plan:")
            for i, step in enumerate(migrated_workflow.plan, 1):
                print(f"   {i}. {step}")

        # Show potential issues
        issues = _analyze_migration_issues(migrated_workflow)
        if issues:
            print(f"\n⚠️  Potential Issues:")
            for issue in issues:
                print(f"   • {issue}")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def _analyze_migration_issues(workflow):
    """Analyze the migrated workflow for potential issues."""
    issues = []

    # Check for actions with no writes
    for action in workflow.actions:
        if not action.writes:
            issues.append(f"Action '{action.name}' has no output fields (writes)")

    # Check for missing dependencies in plan
    dep_graph = workflow.get_dependency_graph()
    all_actions = {action.name for action in workflow.actions}

    for action_name, deps in dep_graph.items():
        for dep in deps:
            if dep not in all_actions:
                issues.append(f"Action '{action_name}' depends on undefined action '{dep}'")

    # Check for circular dependencies (basic check)
    visited = set()
    rec_stack = set()

    def has_cycle(node):
        visited.add(node)
        rec_stack.add(node)

        for neighbor in dep_graph.get(node, []):
            if neighbor not in visited:
                if has_cycle(neighbor):
                    return True
            elif neighbor in rec_stack:
                return True

        rec_stack.remove(node)
        return False

    for action in workflow.actions:
        if action.name not in visited:
            if has_cycle(action.name):
                issues.append("Circular dependency detected in workflow")
                break

    return issues


if __name__ == "__main__":
    main()