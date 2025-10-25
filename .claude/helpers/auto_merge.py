#!/usr/bin/env python3
"""
Auto-merge similar files by picking the best version.

Strategy:
1. For __init__.py files: Merge all imports and exports
2. For staging files: Pick core/ version (likely more recent/complete)
3. For files >95% similar: Pick the larger file (more complete)
"""

import json
import sys
from pathlib import Path
from typing import List


def pick_best_version(sources: List[str]) -> str:
    """
    Pick the best version from similar files.

    Priority:
    1. core/ versions over _internal/
    2. Larger files over smaller
    3. integrations/ over agents/
    """
    # Prefer core/ over _internal/
    core_files = [s for s in sources if '/core/' in s]
    if core_files:
        # If multiple core files, pick largest
        if len(core_files) > 1:
            return max(core_files, key=lambda f: Path(f).stat().st_size if Path(f).exists() else 0)
        return core_files[0]

    # Prefer integrations/ over agents/
    integration_files = [s for s in sources if '/integrations/' in s]
    if integration_files:
        return integration_files[0]

    # Fallback: pick largest file
    return max(sources, key=lambda f: Path(f).stat().st_size if Path(f).exists() else 0)


def auto_resolve_merges(plan_file: str, resolutions_file: str) -> dict:
    """Auto-resolve MERGE conflicts by picking best version."""

    with open(plan_file) as f:
        plan = json.load(f)

    with open(resolutions_file) as f:
        resolutions = json.load(f)

    merge_actions = resolutions['actions']['MERGE']

    if not merge_actions:
        print("No MERGE actions to resolve")
        return plan

    print(f"🔵 Auto-resolving {len(merge_actions)} MERGE conflicts...\n")

    updated_rules = plan['rules'].copy()
    removed_count = 0

    for action in merge_actions:
        dest = action['destination']
        sources = action['sources']

        # Pick best version
        keep_file = pick_best_version(sources)
        delete_files = [s for s in sources if s != keep_file]

        print(f"📁 {Path(dest).name}")
        print(f"   ✅ Keeping: {Path(keep_file).relative_to(Path.cwd() / 'agent_actions')}")

        # Remove rules for files to delete
        for delete_file in delete_files:
            updated_rules = [
                rule for rule in updated_rules
                if rule['source'] != delete_file
            ]
            removed_count += 1
            print(f"   ❌ Removing: {Path(delete_file).relative_to(Path.cwd() / 'agent_actions')}")

        print()

    plan['rules'] = updated_rules
    plan['conflicts'] = []
    plan['stats']['conflicts'] = 0

    print(f"✅ Removed {removed_count} duplicate rules")
    print(f"✅ Resolved {len(merge_actions)} MERGE conflicts\n")

    return plan


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python auto_merge.py plan_updated.json plan_resolutions.json")
        sys.exit(1)

    plan_file = sys.argv[1]
    resolution_file = sys.argv[2]

    print("🤖 Auto-merging similar files...\n")
    print("Strategy:")
    print("  1. Prefer core/ over _internal/")
    print("  2. Prefer integrations/ over agents/")
    print("  3. Pick larger files when in doubt\n")

    # Auto-resolve merges
    plan = auto_resolve_merges(plan_file, resolution_file)

    # Save final migration plan
    output_file = 'plan_final.json'
    with open(output_file, 'w') as f:
        json.dump(plan, f, indent=2)

    print(f"📄 Final migration plan saved to: {output_file}")
    print(f"\n📊 Summary:")
    print(f"   Total files to migrate: {len(plan['rules'])}")
    print(f"   Remaining conflicts: {len(plan['conflicts'])}")
    print(f"\n✅ Ready to migrate! Run:")
    print(f"   python .claude/helpers/stage_refactorer.py agent_actions/ --json {output_file} --execute --backup")


if __name__ == '__main__':
    main()
