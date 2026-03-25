"""Python AST parser — extracts classes, functions, imports, calls, inheritance."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SymbolInfo:
    name: str
    kind: str  # class, function, import, variable
    file_path: str
    start_line: int
    end_line: int = 0
    signature: str = ""
    docstring: str = ""


@dataclass
class EdgeInfo:
    src_name: str
    src_kind: str
    dst_name: str
    dst_kind: str
    edge_type: str  # import, call, inheritance, depends_on


@dataclass
class ParseResult:
    symbols: list[SymbolInfo] = field(default_factory=list)
    edges: list[EdgeInfo] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


class PythonASTVisitor(ast.NodeVisitor):
    """Walk Python AST to extract symbols and relationships."""

    def __init__(self, file_path: str, source: str):
        self.file_path = file_path
        self.source = source
        self.source_lines = source.splitlines()
        self.result = ParseResult()
        self._current_class: str | None = None

    def _get_docstring(self, node) -> str:
        try:
            return ast.get_docstring(node) or ""
        except Exception:
            return ""

    def _get_end_line(self, node) -> int:
        return getattr(node, "end_lineno", node.lineno)

    def _get_signature(self, node: ast.FunctionDef) -> str:
        args = []
        for arg in node.args.args:
            annotation = ""
            if arg.annotation:
                try:
                    annotation = f": {ast.unparse(arg.annotation)}"
                except Exception:
                    pass
            args.append(f"{arg.arg}{annotation}")
        ret = ""
        if node.returns:
            try:
                ret = f" -> {ast.unparse(node.returns)}"
            except Exception:
                pass
        return f"({', '.join(args)}){ret}"

    def visit_ClassDef(self, node: ast.ClassDef):
        sym = SymbolInfo(
            name=node.name,
            kind="class",
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=self._get_end_line(node),
            docstring=self._get_docstring(node),
        )
        # Bases → inheritance edges
        for base in node.bases:
            base_name = ""
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                try:
                    base_name = ast.unparse(base)
                except Exception:
                    pass
            if base_name:
                self.result.edges.append(EdgeInfo(
                    src_name=node.name, src_kind="class",
                    dst_name=base_name, dst_kind="class",
                    edge_type="inheritance",
                ))

        self.result.symbols.append(sym)
        old_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        name = node.name
        if self._current_class:
            name = f"{self._current_class}.{node.name}"

        sym = SymbolInfo(
            name=name,
            kind="function",
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=self._get_end_line(node),
            signature=self._get_signature(node),
            docstring=self._get_docstring(node),
        )
        self.result.symbols.append(sym)

        # Scan function body for calls
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_name = self._resolve_call_name(child)
                if call_name:
                    self.result.edges.append(EdgeInfo(
                        src_name=name, src_kind="function",
                        dst_name=call_name, dst_kind="function",
                        edge_type="call",
                    ))

        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.result.imports.append(alias.name)
            self.result.symbols.append(SymbolInfo(
                name=alias.asname or alias.name,
                kind="import",
                file_path=self.file_path,
                start_line=node.lineno,
                end_line=node.lineno,
            ))
            self.result.edges.append(EdgeInfo(
                src_name=self.file_path, src_kind="file",
                dst_name=alias.name, dst_kind="module",
                edge_type="import",
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        level = node.level  # relative import level
        for alias in node.names:
            full_name = f"{module}.{alias.name}" if module else alias.name
            self.result.imports.append(full_name)
            self.result.symbols.append(SymbolInfo(
                name=alias.asname or alias.name,
                kind="import",
                file_path=self.file_path,
                start_line=node.lineno,
                end_line=node.lineno,
            ))
            self.result.edges.append(EdgeInfo(
                src_name=self.file_path, src_kind="file",
                dst_name=full_name, dst_kind="module",
                edge_type="import",
            ))

    def _resolve_call_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            try:
                return ast.unparse(node.func)
            except Exception:
                return node.func.attr
        return ""


def parse_python(file_path: str, source: str) -> ParseResult:
    """Parse Python source code and extract symbols + edges."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        logger.warning(f"Syntax error in {file_path}: {e}")
        return ParseResult()

    visitor = PythonASTVisitor(file_path, source)
    visitor.visit(tree)
    return visitor.result
