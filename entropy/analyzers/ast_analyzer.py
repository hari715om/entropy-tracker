"""
AST Analyzer — builds the import graph and computes blast radius.

Uses Python's built-in ``ast`` module to parse every .py file in the repo,
extract import statements, and build a directed graph of module dependencies.
From this graph we compute:
- Blast radius: how many modules transitively depend on a given module
- Import graph adjacency list (for visualization/API)
"""

from __future__ import annotations

import ast
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ImportGraphData:
    """Complete import graph for a repository."""

    # module_path → list of modules it imports (within-repo only)
    imports: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    # module_path → list of modules that import it (reverse edges)
    imported_by: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    # module_path → transitive blast radius count
    blast_radius: dict[str, int] = field(default_factory=dict)
    # all known module paths
    all_modules: set[str] = field(default_factory=set)


class ASTAnalyzer:
    """Build the import graph and compute blast radius for a Python repo."""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path)
        self._module_paths: dict[str, str] = {}  # dotted.name → relative/file/path

    def analyze(self) -> ImportGraphData:
        """
        1. Discover all .py files and build a dotted-name registry
        2. Parse each file's imports
        3. Resolve imports to local modules
        4. Build reverse graph and compute blast radius
        """
        logger.info("ASTAnalyzer: scanning %s …", self.repo_path)
        graph = ImportGraphData()

        # Step 1: Build module registry
        self._build_module_registry()
        graph.all_modules = set(self._module_paths.values())

        # Step 2: Parse imports from each file
        for dotted_name, rel_path in self._module_paths.items():
            full_path = self.repo_path / rel_path
            if not full_path.is_file():
                continue

            raw_imports = self._extract_imports(full_path)

            # Step 3: Resolve to local modules only
            for imp in raw_imports:
                resolved = self._resolve_import(imp)
                if resolved and resolved != rel_path:
                    graph.imports[rel_path].append(resolved)
                    graph.imported_by[resolved].append(rel_path)

        # Step 4: Compute blast radius for every module
        for module_path in graph.all_modules:
            radius = self._compute_blast_radius(module_path, graph)
            graph.blast_radius[module_path] = radius

        logger.info(
            "ASTAnalyzer: found %d modules, max blast radius = %d",
            len(graph.all_modules),
            max(graph.blast_radius.values()) if graph.blast_radius else 0,
        )
        return graph

    # ---- module registry ----------------------------------------------------

    def _build_module_registry(self) -> None:
        """Map dotted module names → relative file paths."""
        self._module_paths.clear()

        for py_file in self.repo_path.rglob("*.py"):
            try:
                rel = py_file.relative_to(self.repo_path)
            except ValueError:
                continue

            # Skip hidden dirs, __pycache__, venv, node_modules
            parts = rel.parts
            if any(p.startswith(".") or p in ("__pycache__", "venv", ".venv", "node_modules") for p in parts):
                continue

            rel_str = str(rel).replace("\\", "/")

            # Build dotted name: e.g. "entropy/analyzers/git_analyzer.py" → "entropy.analyzers.git_analyzer"
            if rel.name == "__init__.py":
                dotted = ".".join(parts[:-1])
            else:
                dotted = ".".join(parts[:-1] + (rel.stem,))

            if dotted:
                self._module_paths[dotted] = rel_str

    # ---- import extraction --------------------------------------------------

    @staticmethod
    def _extract_imports(filepath: Path) -> list[str]:
        """Extract all import statements as dotted names."""
        try:
            source = filepath.read_text(errors="replace")
            tree = ast.parse(source, filename=str(filepath))
        except (SyntaxError, UnicodeDecodeError):
            return []

        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return imports

    # ---- import resolution --------------------------------------------------

    def _resolve_import(self, import_name: str) -> str | None:
        """Resolve a dotted import name to a local module path, or None if external."""
        # Try exact match
        if import_name in self._module_paths:
            return self._module_paths[import_name]

        # Try prefix matches (e.g., "entropy.analyzers" might match "entropy.analyzers.__init__")
        parts = import_name.split(".")
        for i in range(len(parts), 0, -1):
            partial = ".".join(parts[:i])
            if partial in self._module_paths:
                return self._module_paths[partial]

        return None  # external or unresolvable

    # ---- blast radius -------------------------------------------------------

    def _compute_blast_radius(self, module_path: str, graph: ImportGraphData) -> int:
        """BFS to count all transitive dependents (modules that import this, directly or indirectly)."""
        visited: set[str] = set()
        queue = [module_path]

        while queue:
            current = queue.pop(0)
            for dependent in graph.imported_by.get(current, []):
                if dependent not in visited:
                    visited.add(dependent)
                    queue.append(dependent)

        return len(visited)
