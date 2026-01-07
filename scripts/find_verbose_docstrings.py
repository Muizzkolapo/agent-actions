import ast
import os
from pathlib import Path


def count_docstring_lines(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content)
        docstring = ast.get_docstring(tree)
        if docstring:
            # simple splitlines is enough
            lines = [l for l in docstring.splitlines() if l.strip()]
            return len(lines)
        return 0
    except Exception:
        return 0


results = []
for root, _, files in os.walk("agent_actions"):
    for file in files:
        if file.endswith(".py"):
            path = Path(root) / file
            count = count_docstring_lines(path)
            if count > 3:  # New Strict Threshold
                results.append((count, str(path)))

results.sort(key=lambda x: x[0], reverse=True)

print(f"Found {len(results)} files with docstrings > 3 lines.")
print("\nTop 20 Longest:")
for count, path in results[:20]:
    print(f"{count} lines: {path}")
