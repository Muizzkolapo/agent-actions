#!/usr/bin/env python3
"""Debug script to see what config is loaded."""

import sys
import yaml
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agent_actions.core.parser.format_converter import WorkflowFormatConverter
from agent_actions.tasks.services.config_renderer import ConfigRenderer


def debug_config_loading():
    """Debug the config loading process."""

    config_path = Path("qanalabs/agent_workflow/qanalabs-quiz-gen/qanalabs-quiz-gen.yml")

    # 1. Load raw YAML
    with open(config_path, 'r') as f:
        raw_yaml = f.read()

    print("=== RAW YAML (first 10 lines) ===")
    for i, line in enumerate(raw_yaml.split('\n')[:10], 1):
        print(f"{i:2d}: {line}")

    # 2. Parse YAML
    raw_config = yaml.safe_load(raw_yaml)
    print(f"\n=== PARSED YAML ===")
    print(f"Top-level keys: {list(raw_config.keys())}")
    print(f"First key: {next(iter(raw_config))}")

    # 3. Format detection
    format_type = WorkflowFormatConverter.detect_format(raw_config)
    print(f"Detected format: {format_type}")

    # 4. Conversion
    if format_type == "new":
        converted_config = WorkflowFormatConverter.convert_new_to_old(raw_config)
        print(f"\n=== CONVERTED CONFIG ===")
        print(f"Top-level keys: {list(converted_config.keys())}")
        print(f"First key: {next(iter(converted_config))}")
    else:
        converted_config = raw_config
        print(f"\n=== NO CONVERSION NEEDED ===")

    # 5. Test the full pipeline
    print(f"\n=== TESTING CONFIG RENDERER ===")
    try:
        # This is how the actual system loads config
        service = ConfigRenderer()
        result = service._safe_load_yaml(raw_yaml, config_path)
        print(f"Config renderer result keys: {list(result.keys())}")
        print(f"Config renderer first key: {next(iter(result))}")
    except Exception as e:
        print(f"Config renderer error: {e}")


if __name__ == "__main__":
    debug_config_loading()