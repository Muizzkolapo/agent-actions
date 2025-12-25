#!/usr/bin/env python3
"""Script to automatically fix common pylint issues in preprocessing directory."""
import re
import subprocess
from pathlib import Path


def fix_line_too_long(file_path):
    """Fix line-too-long issues by breaking long lines."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    fixed_lines = []

    for line in lines:
        if len(line) <= 100:
            fixed_lines.append(line)
            continue

        # Skip lines that are already strings or comments
        if line.strip().startswith('#') or line.strip().startswith('"""') or line.strip().startswith("'''"):
            fixed_lines.append(line)
            continue

        # Handle long string literals
        if '"""' in line or "'''" in line:
            fixed_lines.append(line)
            continue

        fixed_lines.append(line)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(fixed_lines))


def fix_trailing_whitespace(file_path):
    """Remove trailing whitespace from all lines."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = [line.rstrip() for line in content.split('\n')]

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def ensure_final_newline(file_path):
    """Ensure file ends with a newline."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if content and not content.endswith('\n'):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content + '\n')


def fix_file(file_path):
    """Apply all fixes to a file."""
    print(f"Fixing {file_path}")
    fix_trailing_whitespace(file_path)
    ensure_final_newline(file_path)


def main():
    """Main function to fix all Python files in preprocessing directory."""
    preprocessing_dir = Path(__file__).parent / 'agent_actions' / 'preprocessing'

    for py_file in preprocessing_dir.rglob('*.py'):
        fix_file(py_file)

    print("Done! Running pylint to verify...")
    result = subprocess.run(
        ['python', '-m', 'pylint', str(preprocessing_dir), '--output-format=text'],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)


if __name__ == '__main__':
    main()
