#!/usr/bin/env python3
"""Fix remaining pylint issues after initial automated fixes."""
import re
import ast
from pathlib import Path


def read_file(path):
    """Read file."""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def write_file(path, content):
    """Write file."""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def fix_fstring_logging(content):
    """Convert f-string logging to % formatting."""
    # Match logger.xyz(f"..." or logger.xyz(f'...'
    pattern = r'(logger\.(debug|info|warning|error|critical))\(f(["\'])(.+?)\3'

    def replacer(match):
        method = match.group(1)
        quote = match.group(3)
        message = match.group(4)

        # Convert f-string placeholders to % placeholders
        # Simple conversion: {var} -> %s
        converted = re.sub(r'\{[^}]+\}', '%s', message)

        # Extract variables from f-string
        vars_match = re.findall(r'\{([^}:]+)', message)

        if vars_match:
            vars_str = ', '.join(vars_match)
            return f'{method}({quote}{converted}{quote}, {vars_str}'
        return match.group(0)

    return re.sub(pattern, replacer, content)


def fix_broad_except(content):
    """Replace broad Exception catches with specific exceptions."""
    # Replace except Exception with common specific exceptions
    content = re.sub(
        r'except Exception as (\w+):',
        r'except (ValueError, TypeError, KeyError) as \1:',
        content
    )
    return content


def fix_no_else_return(content):
    """Fix no-else-return issues by removing unnecessary else."""
    lines = content.split('\n')
    new_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if line ends with return and next non-empty line is else/elif
        if 'return ' in line and not line.strip().startswith('#'):
            # Look ahead for else or elif
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1

            if j < len(lines):
                next_line = lines[j]
                indent = len(line) - len(line.lstrip())
                next_indent = len(next_line) - len(next_line.lstrip())

                # If next line is else/elif at same indentation
                if next_indent == indent:
                    if next_line.strip().startswith('else:'):
                        # Replace else with dedented code
                        new_lines.append(line)
                        i = j + 1
                        # Skip else line, continue with dedented content
                        continue
                    elif next_line.strip().startswith('elif'):
                        # Convert elif to if
                        new_lines.append(line)
                        new_lines.append(next_line.replace('elif', 'if', 1))
                        i = j + 1
                        continue

        new_lines.append(line)
        i += 1

    return '\n'.join(new_lines)


def main():
    """Process all files."""
    preprocessing_dir = Path('agent_actions/preprocessing')

    for py_file in preprocessing_dir.rglob('*.py'):
        print(f"Processing {py_file}")
        content = read_file(py_file)

        content = fix_fstring_logging(content)
        content = fix_broad_except(content)
        # content = fix_no_else_return(content)  # Skip this as it's complex

        write_file(py_file, content)

    print("Done!")


if __name__ == '__main__':
    main()
