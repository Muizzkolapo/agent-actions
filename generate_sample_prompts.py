#!/usr/bin/env python3
"""
Generate sample prompts for the documentation site.
"""
import json
import sys
from pathlib import Path

# Add agent_actions to path
sys.path.insert(0, str(Path(__file__).parent))

from agent_actions.docs.scanner import ProjectScanner

def main():
    # Scan the qanalabs project for real prompts
    qanalabs_path = "/Users/muizz/Documents/codeshop/qanalabs/qanalabs-actions/qanalabs"

    if not Path(qanalabs_path).exists():
        print(f"❌ Path not found: {qanalabs_path}")
        return

    scanner = ProjectScanner(qanalabs_path)
    prompts = scanner.scan_prompts()

    print(f"Found {len(prompts)} prompts")

    # Update the sample catalog.json
    catalog_path = Path(__file__).parent / "agent_actions/docs/docs_site/sample_artefact/catalog.json"

    with open(catalog_path, 'r') as f:
        catalog = json.load(f)

    # Add prompts collection
    catalog['prompts'] = prompts

    # Update stats
    catalog['stats']['total_prompts'] = len(prompts)

    # Write back
    with open(catalog_path, 'w') as f:
        json.dump(catalog, f, indent=2)

    print(f"✅ Updated catalog with {len(prompts)} prompts")
    print(f"   Catalog: {catalog_path}")

if __name__ == "__main__":
    main()
