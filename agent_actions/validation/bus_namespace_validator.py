"""Flag UDF reads of `data.get("X")` / `data["X"]` where X is not a bus namespace."""

from __future__ import annotations

import ast


def _bus_key(node: ast.AST) -> str | None:
    """Return the literal key of a `data.get("X")` / `data["X"]` read, else None."""
    # data.get("literal")
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "data"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    # data["literal"]
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "data"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    ):
        return node.slice.value
    return None


class _BusKeyCollector(ast.NodeVisitor):
    """Collect (enclosing-function, literal bus key) pairs; innermost function wins."""

    def __init__(self, fallback: str) -> None:
        self._fallback = fallback
        self._func_stack: list[str] = []
        self.reads: list[tuple[str, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _record(self, node: ast.AST) -> None:
        key = _bus_key(node)
        if key is not None:
            owner = self._func_stack[-1] if self._func_stack else self._fallback
            self.reads.append((owner, key))

    def visit_Call(self, node: ast.Call) -> None:
        self._record(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self._record(node)
        self.generic_visit(node)


def find_unknown_bus_namespaces(sources: dict[str, str], valid_namespaces: set[str]) -> list[str]:
    """Return one warning per literal bus key that is not a valid namespace.

    Findings are attributed to the enclosing UDF, so a source file holding several
    UDFs never cross-attributes; a `sources` key is only the fallback label for a
    read outside any function. Non-literal keys (`data.get(var)`) are skipped.
    """
    findings: list[str] = []
    seen: set[tuple[str, str]] = set()
    for label, src in sources.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        collector = _BusKeyCollector(label)
        collector.visit(tree)
        for owner, key in collector.reads:
            if key in valid_namespaces or (owner, key) in seen:
                continue
            seen.add((owner, key))
            findings.append(
                f"{owner}: reads bus namespace '{key}' which is not an action name "
                f"in the workflow. The bus is keyed by action name — check for an "
                f"impl-name/action-name mismatch (a wrong key reads an empty dict silently)."
            )
    return findings
