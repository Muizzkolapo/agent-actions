import ast
import os
from pathlib import Path


def trim_file_docstring(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)
        docstring = ast.get_docstring(tree)

        if not docstring:
            return False

        # Check line count
        lines = [l for l in docstring.splitlines() if l.strip()]
        if len(lines) <= 3:
            return False

        # Smart splitting: keep until first blank line (paragraph)
        # We need the raw docstring from content to preserve formatting details if needed,
        # but replacing the node is safer.

        # Strategy:
        # 1. Get the first paragraph of the text.
        # 2. Reconstruct the file content by replacing the docstring string literal.

        # AST-based replacement is tricky for preserving comments/formatting elsewhere.
        # Regex replacement of the *first* string literal is also risky if not careful.
        # But module docstring is always the first statement.

        chunks = docstring.split("\n\n")
        new_docstring = chunks[0].strip()

        # If the first chunk itself is > 3 lines, we might still be "verbose" but
        # user said "Stopping at first blank line" is acceptable.
        # Let's enforce the "Max 3 lines" preference if possible, but "First Paragraph"
        # is the agreed safe strategy.

        # We will use string replacement on the file content.
        # Find exact start/end of the docstring in the file.

        module_body = tree.body
        if not module_body or not isinstance(module_body[0], ast.Expr):
            return False

        doc_node = module_body[0].value
        if not isinstance(doc_node, ast.Constant) or not isinstance(doc_node.value, str):
            # Python < 3.8 uses ast.Str, 3.8+ uses ast.Constant
            if not isinstance(doc_node, ast.Str):
                return False

        # We rely on the fact that we read the file content.
        # Finding the byte range of the docstring is best done with `ast.get_source_segment` (Py 3.8+)
        # But we can also matches the string.

        # Let's use a simpler approach: Read lines, identify the docstring lines, replace them.
        # Or Just use the `ast` limit to identify files, and write a targeted string replacer.

        # Actually, let's just use the `ast` to find the node, and replace the text range.
        # `doc_node.lineno` (start 1-based) and `doc_node.end_lineno`.

        start_line = doc_node.lineno - 1
        end_line = doc_node.end_lineno

        file_lines = content.splitlines(keepends=True)

        # Extract existing indentation
        first_line = file_lines[start_line]
        indent = ""
        for char in first_line:
            if char.isspace():
                indent += char
            else:
                break

        # Create new formatted docstring
        # Use triple double quotes by default
        new_block = f'{indent}"""\n{indent}{new_docstring}\n{indent}"""\n'

        # Replace lines [start_line:end_line] with new_block
        # Note: end_line is inclusive in AST line numbers?
        # Yes, end_line is the last line of the node.
        # We need to slice list carefully.

        # Slicing is [start:stop], so to include end_line (index end_line-1), we use stop=end_line.

        new_content_lines = file_lines[:start_line] + [new_block] + file_lines[end_line:]

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(new_content_lines)

        return True

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False


count = 0
for root, _, files in os.walk("agent_actions"):
    for file in files:
        if file.endswith(".py"):
            path = Path(root) / file
            if trim_file_docstring(path):
                print(f"Trimmed: {path}")
                count += 1

print(f"Total files trimmed: {count}")
