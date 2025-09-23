#!/usr/bin/env python3
"""Debug script to see preprocessed template content."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agent_actions.core.migration.template_yaml_loader import TemplateYamlLoader


def debug_preprocessing():
    """Debug the template preprocessing."""

    loader = TemplateYamlLoader()

    # Read raw content
    with open("sample.yml", "r") as f:
        raw_content = f.read()

    print("=== RAW CONTENT (first 30 lines) ===")
    raw_lines = raw_content.split('\n')[:30]
    for i, line in enumerate(raw_lines, 1):
        print(f"{i:2d}: {line}")

    print("\n=== PROCESSED CONTENT ===")
    processed_content = loader._preprocess_templates(raw_content)
    processed_lines = processed_content.split('\n')[:30]
    for i, line in enumerate(processed_lines, 1):
        print(f"{i:2d}: {line}")


if __name__ == "__main__":
    debug_preprocessing()