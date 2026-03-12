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
    # Scan the qanalabs project for real prompts and schemas
    qanalabs_path = "/Users/muizz/Documents/codeshop/qanalabs/qanalabs-actions/qanalabs"

    if not Path(qanalabs_path).exists():
        print(f"❌ Path not found: {qanalabs_path}")
        return

    scanner = ProjectScanner(qanalabs_path)
    prompts = scanner.scan_prompts()
    schemas = scanner.scan_schemas()

    print(f"Found {len(prompts)} prompts")
    print(f"Found {len(schemas)} schemas")

    # Update the sample catalog.json
    catalog_path = (
        Path(__file__).parent / "agent_actions/docs/docs_site/sample_artefact/catalog.json"
    )

    with open(catalog_path) as f:
        catalog = json.load(f)

    # Add prompts and schemas collections
    catalog["prompts"] = prompts
    catalog["schemas"] = schemas

    # Update stats
    catalog["stats"]["total_prompts"] = len(prompts)
    catalog["stats"]["total_schemas"] = len(schemas)

    # Write back
    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2)

    print("✅ Updated catalog")
    print(f"   - {len(prompts)} prompts")
    print(f"   - {len(schemas)} schemas")
    print(f"   Catalog: {catalog_path}")


if __name__ == "__main__":
    main()
