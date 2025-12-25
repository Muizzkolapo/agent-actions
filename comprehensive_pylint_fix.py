#!/usr/bin/env python3
"""
Comprehensive pylint fixer for agent_actions/preprocessing directory.
Fixes all common pylint issues without using pylint disable comments.
"""
import re
from pathlib import Path
from typing import List


def read_file(file_path: Path) -> str:
    """Read file with utf-8 encoding."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


def write_file(file_path: Path, content: str):
    """Write file with utf-8 encoding."""
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def fix_trailing_whitespace(content: str) -> str:
    """Remove trailing whitespace from all lines."""
    lines = [line.rstrip() for line in content.split('\n')]
    return '\n'.join(lines)


def ensure_final_newline(content: str) -> str:
    """Ensure file ends with exactly one newline."""
    content = content.rstrip('\n')
    return content + '\n'


def fix_unnecessary_pass(content: str) -> str:
    """Remove unnecessary pass statements after docstrings."""
    # Remove pass statements that are alone in a block with just a docstring
    pattern = r'(\s+)("""[^"]*"""|\'\'\'[^\']*\'\'\')\n\1pass\n'
    content = re.sub(pattern, r'\1\2\n', content)
    return content


def fix_unspecified_encoding(content: str) -> str:
    """Add encoding='utf-8' to open() calls."""
    # Match open( with 'w' or 'r' mode without encoding
    pattern = r"open\(([^)]+),\s*['\"]([rwa])['\"]([^)]*)\)"

    def replacer(match):
        path = match.group(1)
        mode = match.group(2)
        rest = match.group(3)
        if 'encoding' not in rest:
            if rest.strip():
                return f"open({path}, '{mode}', encoding='utf-8'{rest})"
            return f"open({path}, '{mode}', encoding='utf-8')"
        return match.group(0)

    return re.sub(pattern, replacer, content)


def fix_import_order(content: str) -> str:
    """Fix import ordering: stdlib, third-party, first-party, local."""
    lines = content.split('\n')

    # Find module docstring end
    in_docstring = False
    docstring_end = 0
    for i, line in enumerate(lines):
        if '"""' in line or "'''" in line:
            if not in_docstring:
                in_docstring = True
            else:
                docstring_end = i + 1
                break

    # Find all imports
    import_start = None
    import_end = None
    imports = []

    for i in range(docstring_end, len(lines)):
        line = lines[i].strip()
        if line.startswith('import ') or line.startswith('from '):
            if import_start is None:
                import_start = i
            imports.append(lines[i])
            import_end = i
        elif line and not line.startswith('#') and import_start is not None:
            break

    if not imports:
        return content

    # Categorize imports
    stdlib_imports = []
    third_party_imports = []
    first_party_imports = []
    local_imports = []

    stdlib_modules = {
        'abc', 'asyncio', 'collections', 'copy', 'dataclasses', 'datetime',
        'enum', 'functools', 'hashlib', 'io', 'json', 'logging', 'os',
        'pathlib', 'random', 're', 'sys', 'time', 'typing', 'uuid', 'warnings'
    }

    for imp in imports:
        if imp.startswith('from .') or imp.startswith('import .'):
            local_imports.append(imp)
        elif 'agent_actions' in imp:
            first_party_imports.append(imp)
        else:
            # Check if stdlib
            module = None
            if imp.startswith('import '):
                module = imp.split()[1].split('.')[0]
            elif imp.startswith('from '):
                module = imp.split()[1].split('.')[0]

            if module in stdlib_modules:
                stdlib_imports.append(imp)
            else:
                third_party_imports.append(imp)

    # Sort each category
    stdlib_imports.sort()
    third_party_imports.sort()
    first_party_imports.sort()
    local_imports.sort()

    # Rebuild imports with blank lines between categories
    sorted_imports = []
    if stdlib_imports:
        sorted_imports.extend(stdlib_imports)
    if third_party_imports:
        if sorted_imports:
            sorted_imports.append('')
        sorted_imports.extend(third_party_imports)
    if first_party_imports:
        if sorted_imports:
            sorted_imports.append('')
        sorted_imports.extend(first_party_imports)
    if local_imports:
        if sorted_imports:
            sorted_imports.append('')
        sorted_imports.extend(local_imports)

    # Replace imports in content
    new_lines = lines[:import_start] + sorted_imports + lines[import_end + 1:]
    return '\n'.join(new_lines)


def fix_no_else_return(content: str) -> str:
    """Remove else/elif after return statements where possible."""
    # This is complex and context-dependent, so we'll skip automated fix
    return content


def apply_all_fixes(file_path: Path):
    """Apply all fixes to a single file."""
    print(f"Processing: {file_path}")

    content = read_file(file_path)

    # Apply fixes in order
    content = fix_trailing_whitespace(content)
    content = fix_unspecified_encoding(content)
    content = fix_unnecessary_pass(content)
    content = fix_import_order(content)
    content = ensure_final_newline(content)

    write_file(file_path, content)


def main():
    """Main function to process all files."""
    preprocessing_dir = Path('agent_actions/preprocessing')

    if not preprocessing_dir.exists():
        print(f"Error: {preprocessing_dir} not found!")
        return

    python_files = list(preprocessing_dir.rglob('*.py'))
    print(f"Found {len(python_files)} Python files to process\n")

    for py_file in sorted(python_files):
        try:
            apply_all_fixes(py_file)
        except Exception as e:
            print(f"ERROR processing {py_file}: {e}")

    print("\nDone! Please run pylint to verify the fixes.")


if __name__ == '__main__':
    main()
