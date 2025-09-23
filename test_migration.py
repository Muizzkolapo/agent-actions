#!/usr/bin/env python3
"""Test script for workflow migration."""

import sys
import os
import yaml
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agent_actions.core.migration.format_migrator import WorkflowMigrator


def test_migration():
    """Test the migration of sample.yml to new format."""

    # Initialize migrator
    migrator = WorkflowMigrator()

    # Input and output paths
    input_path = "sample.yml"
    output_path = "migrated_workflow.yml"

    try:
        print(f"Migrating {input_path}...")

        # Perform migration
        migrated_workflow = migrator.migrate_from_yaml_file(input_path)

        # Save result
        migrator.save_migrated_workflow(migrated_workflow, output_path)

        print(f"✅ Migration successful! Output saved to {output_path}")

        # Print summary
        print(f"\n📊 Migration Summary:")
        print(f"   Workflow: {migrated_workflow.name}")
        print(f"   Version: {migrated_workflow.version}")
        print(f"   Actions: {len(migrated_workflow.actions)}")
        print(f"   Plan steps: {len(migrated_workflow.plan)}")

        # Show defaults
        if migrated_workflow.defaults:
            print(f"\n⚙️  Defaults:")
            if migrated_workflow.defaults.vendor:
                print(f"   Vendor: {migrated_workflow.defaults.vendor}")
            if migrated_workflow.defaults.model:
                print(f"   Model: {migrated_workflow.defaults.model}")
            if migrated_workflow.defaults.json_mode:
                print(f"   JSON Mode: {migrated_workflow.defaults.json_mode}")

        # Show actions
        print(f"\n🔧 Actions:")
        for action in migrated_workflow.actions:
            deps = []
            for plan_item in migrated_workflow.plan:
                if plan_item.startswith(action.name + ' <-'):
                    deps = plan_item.split('<-')[1].strip().split(',')
                    deps = [d.strip() for d in deps]
                    break

            dep_str = f" (depends: {', '.join(deps)})" if deps else ""
            print(f"   {action.name}: {action.intent}{dep_str}")

        # Show execution plan
        print(f"\n📋 Execution Plan:")
        for i, step in enumerate(migrated_workflow.plan, 1):
            print(f"   {i}. {step}")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = test_migration()
    sys.exit(0 if success else 1)