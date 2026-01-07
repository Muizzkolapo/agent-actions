#!/usr/bin/env python3
"""
Generate MODULE_MAP.md files for agent-actions folders.

This script walks the directory structure, parses Python files to extract:
1. Docstring summary (first line)
2. Key internal imports (signals)

It generates a MODULE_MAP.md in each folder containing a Python module.
"""

import ast
import os
from pathlib import Path
from typing import Dict, List, Set, Optional
from dataclasses import dataclass

# Constants
PROJECT_ROOT = Path("agent_actions")
OUTPUT_FILENAME = "_MANIFEST.md"
INTERNAL_PREFIX = "agent_actions"


@dataclass
class SymbolInfo:
    name: str
    type: str  # 'Class', 'Method', 'Function'
    description: str
    indent_level: int = 0


class ModuleInfo:
    def __init__(self, name: str, summary: str, signals: Set[str], symbols: List[SymbolInfo]):
        self.name = name
        self.summary = summary
        self.signals = signals
        self.symbols = symbols


class SymbolVisitor(ast.NodeVisitor):
    def __init__(self):
        self.symbols = []
        self.current_class = None

    def _get_docstring(self, node):
        doc = ast.get_docstring(node)
        if doc:
            lines = [l.strip() for l in doc.splitlines() if l.strip()]
            if lines:
                return lines[0].replace("\n", " ").replace("|", "\|")
        return "-"

    def visit_ClassDef(self, node):
        if not node.name.startswith("_"):
            desc = self._get_docstring(node)
            self.symbols.append(SymbolInfo(node.name, "Class", desc, 0))

            # Visit methods
            old_class = self.current_class
            self.current_class = node.name
            self.generic_visit(node)
            self.current_class = old_class

    def visit_FunctionDef(self, node):
        if not node.name.startswith("_"):
            desc = self._get_docstring(node)
            if self.current_class:
                self.symbols.append(SymbolInfo(node.name, "Method", desc, 1))
            else:
                self.symbols.append(SymbolInfo(node.name, "Function", desc, 0))

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)


def get_module_info(file_path: Path) -> Optional[ModuleInfo]:
    """Parse a Python file and extract info."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return None

    # Extract docstring summary
    docstring = ast.get_docstring(tree)
    summary = "-"
    if docstring:
        lines = [line.strip() for line in docstring.splitlines() if line.strip()]
        if lines:
            summary = lines[0].replace("\n", " ").replace("|", "\|")

    # Extract imports
    signals = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(INTERNAL_PREFIX):
                    parts = alias.name.split(".")
                    if len(parts) > 1:
                        signals.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith(INTERNAL_PREFIX):
                parts = node.module.split(".")
                if len(parts) > 1:
                    signals.add(parts[1])

    # Extract Symbols
    visitor = SymbolVisitor()
    visitor.visit(tree)
    symbols = visitor.symbols

    return ModuleInfo(name=file_path.name, summary=summary, signals=signals, symbols=symbols)


def get_submodule_info(folder_path: Path) -> Optional[ModuleInfo]:
    """Check if a folder is a python package and get its summary."""
    init_file = folder_path / "__init__.py"
    if not init_file.exists():
        has_py = any(f.endswith(".py") for f in os.listdir(folder_path))
        if not has_py:
            return None
        summary = "Folder containing modules."
    else:
        try:
            with open(init_file, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content)
            docstring = ast.get_docstring(tree)
            summary = "-"
            if docstring:
                lines = [l.strip() for l in docstring.splitlines() if l.strip()]
                if lines:
                    summary = lines[0].replace("\n", " ").replace("|", "\|")
        except Exception:
            summary = "Module folder."

    if not summary:
        summary = "-"

    return ModuleInfo(name=folder_path.name, summary=summary, signals=set(), symbols=[])


def generate_markdown(folder: Path, modules: List[ModuleInfo], submodules: List[ModuleInfo]):
    """Generate _MANIFEST.md content."""
    folder_name = folder.name.replace("_", " ").title()
    if folder_name == "Agent Actions":
        folder_name = "Root"

    lines = [f"# {folder_name} Manifest", ""]

    # Sub-Modules Table
    if submodules:
        lines.extend(
            [
                "## Sub-Modules",
                "",
                "| Sub-Module | Description |",
                "|------------|-------------|",
            ]
        )
        submodules.sort(key=lambda x: x.name)
        for sub in submodules:
            link = f"[{sub.name}]({sub.name}/{OUTPUT_FILENAME})"
            lines.append(f"| {link} | {sub.summary} |")
        lines.append("")

    # Modules Table (Detailed)
    if modules:
        lines.extend(
            [
                "## Modules",
                "",
                "| Name | Type | Description | Signals |",
                "|------|------|-------------|---------|",
            ]
        )

        # Sort by name
        modules.sort(key=lambda x: x.name)

        for mod in modules:
            # Format signals
            signals_str = ", ".join([f"`{s}`" for s in sorted(mod.signals)]) if mod.signals else "-"

            # Module Row
            lines.append(f"| `{mod.name}` | Module | {mod.summary} | {signals_str} |")

            # Symbol Rows
            for sym in mod.symbols:
                indent = ""
                if sym.indent_level > 0:
                    indent = "&nbsp;&nbsp;&nbsp;&nbsp;└─ "

                # Apply indent to name
                name_display = f"{indent}`{sym.name}`"
                lines.append(f"| {name_display} | {sym.type} | {sym.description} | - |")

    lines.append("")  # Trailing newline

    output_path = folder / OUTPUT_FILENAME
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Generated {output_path}")


def main():
    if not PROJECT_ROOT.exists():
        print(f"Error: {PROJECT_ROOT} not found. Run from project root.")
        return

    for root, dirs, files in os.walk(PROJECT_ROOT):
        py_files = [f for f in files if f.endswith(".py") and f != "__init__.py"]

        # Identify submodules (immediate subdirectories that are packages or valid folders)
        submodules_info = []
        for d in dirs:
            sub_path = Path(root) / d
            info = get_submodule_info(sub_path)
            if info:
                submodules_info.append(info)

        if not py_files and not submodules_info:
            continue

        root_path = Path(root)
        modules_info = []

        for py_file in py_files:
            info = get_module_info(root_path / py_file)
            if info:
                modules_info.append(info)

        # Generate if we have content (either modules or submodules)
        if modules_info or submodules_info:
            generate_markdown(root_path, modules_info, submodules_info)


if __name__ == "__main__":
    main()
