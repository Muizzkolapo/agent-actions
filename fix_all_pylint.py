#!/usr/bin/env python3
"""Script to fix all remaining pylint issues in preprocessing directory."""

import re
import subprocess
from pathlib import Path

def run_command(cmd):
    """Run shell command and return output."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout + result.stderr

def fix_file(filepath, fixes):
    """Apply fixes to a file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    for old, new in fixes:
        content = content.replace(old, new)

    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed: {filepath}")
        return True
    return False

def main():
    preprocessing_dir = Path("agent_actions/preprocessing")

    # Fix all files
    fixes_map = {
        # field_chunking.py - Add docstrings
        str(preprocessing_dir / "chunking/field_chunking.py"): [
            ("    def analyze_record(self, record: Dict[str, Any]) -> FieldAnalysisResult:",
             "    def analyze_record(self, record: Dict[str, Any]) -> FieldAnalysisResult:\n        \"\"\"Analyze a record to determine chunking needs.\"\"\""),
            ("    def should_chunk_field(self, field_name: str, token_count: int) -> bool:",
             "    def should_chunk_field(self, field_name: str, token_count: int) -> bool:\n        \"\"\"Determine if a field should be chunked.\"\"\""),
        ],
    }

    for filepath, fixes in fixes_map.items():
        if Path(filepath).exists():
            fix_file(filepath, fixes)

    # Run pylint to check
    print("\nRunning pylint to verify fixes...")
    output = run_command("python -m pylint agent_actions/preprocessing --output-format=text 2>/dev/null | grep -E '^agent_actions' | wc -l")
    print(f"Remaining issues: {output.strip()}")

if __name__ == "__main__":
    main()
