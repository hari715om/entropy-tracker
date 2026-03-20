"""
Entropy Scorer — the weighted composite formula.

Takes the raw signals from all analyzers and computes:
- Individual signal scores (knowledge, dependency, churn, age) — each 0–100
- Weighted composite entropy score — 0–100
- Bus factor (from git analyzer)
- Blast radius (from AST analyzer)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from entropy.analyzers.ast_analyzer import ImportGraphData
from entropy.analyzers.dep_analyzer import FileDepData
from entropy.analyzers.git_analyzer import FileGitData
from entropy.config import EntropyConfig, get_config

logger = logging.getLogger(__name__)


@dataclass
class ModuleScore:
    """Complete entropy score for a single module."""

    module_path: str
    entropy_score: float = 0.0

    # Individual signal scores (0–100)
    knowledge_score: float = 0.0
    dep_score: float = 0.0
    churn_score: float = 0.0
    age_score: float = 0.0

    # Metadata
    blast_radius: int = 0
    bus_factor: int = 0
    trend_per_month: float = 0.0

    # Details for drilldown
    authors_active: int = 0
    authors_total: int = 0
    months_since_refactor: float = 0.0
    churn_commits: int = 0
    refactor_commits: int = 0

    def severity(self, config: EntropyConfig | None = None) -> str:
        cfg = config or get_config()
        if self.entropy_score >= cfg.thresholds.critical:
            return "CRITICAL"
        elif self.entropy_score >= cfg.thresholds.high:
            return "HIGH"
        elif self.entropy_score >= cfg.thresholds.medium:
            return "MEDIUM"
        else:
            return "HEALTHY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_path": self.module_path,
            "entropy_score": round(self.entropy_score, 1),
            "knowledge_score": round(self.knowledge_score, 1),
            "dep_score": round(self.dep_score, 1),
            "churn_score": round(self.churn_score, 1),
            "age_score": round(self.age_score, 1),
            "blast_radius": self.blast_radius,
            "bus_factor": self.bus_factor,
            "trend_per_month": round(self.trend_per_month, 2),
            "severity": self.severity(),
            "authors_active": self.authors_active,
            "authors_total": self.authors_total,
            "months_since_refactor": round(self.months_since_refactor, 1),
            "churn_commits": self.churn_commits,
            "refactor_commits": self.refactor_commits,
        }


class EntropyScorer:
    """
    Compute entropy scores for all modules in a repository.

    Takes pre-computed analyzer data as inputs and returns scored modules.
    """

    MAX_CHURN_RATIO = 10.0  # normalization ceiling for churn ratio

    def __init__(self, config: EntropyConfig | None = None):
        self.config = config or get_config()

    def score_all(
        self,
        git_data: dict[str, FileGitData],
        dep_data: dict[str, FileDepData],
        import_graph: ImportGraphData,
        bus_factor_fn=None,
    ) -> dict[str, ModuleScore]:
        """
        Score every module and return ``{module_path: ModuleScore}``.

        Parameters
        ----------
        git_data : per-file git analysis results
        dep_data : per-file dependency analysis results
        import_graph : the import graph with blast radius
        bus_factor_fn : callable(file_path) → int (from GitAnalyzer.compute_bus_factor)
        """
        all_paths = set(git_data.keys()) | set(dep_data.keys()) | import_graph.all_modules
        # Only score Python files
        scorable = {p for p in all_paths if p.endswith(".py")}

        results: dict[str, ModuleScore] = {}
        for path in sorted(scorable):
            results[path] = self._score_module(path, git_data, dep_data, import_graph, bus_factor_fn)

        return results

    def _score_module(
        self,
        path: str,
        git_data: dict[str, FileGitData],
        dep_data: dict[str, FileDepData],
        import_graph: ImportGraphData,
        bus_factor_fn,
    ) -> ModuleScore:
        ms = ModuleScore(module_path=path)
        w = self.config.weights

        # ---- Knowledge Decay ------------------------------------------------
        gd = git_data.get(path)
        if gd:
            total = len(gd.authors_all_time)
            active = len(gd.authors_active)
            if total > 0:
                ms.knowledge_score = (1 - active / total) * 100
            ms.authors_active = active
            ms.authors_total = total
            ms.months_since_refactor = gd.months_since_refactor
            ms.churn_commits = gd.churn_commits
            ms.refactor_commits = gd.refactor_commits

            # ---- Churn-to-Touch Ratio ----------------------------------------
            churn_ratio = gd.churn_commits / max(gd.refactor_commits, 1)
            ms.churn_score = min(churn_ratio / self.MAX_CHURN_RATIO * 100, 100)

            # ---- Age Without Refactor ----------------------------------------
            ceiling = self.config.analysis.age_ceiling_months
            ms.age_score = min(gd.months_since_refactor / ceiling * 100, 100)

        # ---- Dependency Decay -----------------------------------------------
        dd = dep_data.get(path)
        if dd:
            ms.dep_score = dd.dep_score

        # ---- Composite Score ------------------------------------------------
        ms.entropy_score = (
            ms.knowledge_score * w.knowledge
            + ms.dep_score * w.dependency
            + ms.churn_score * w.churn
            + ms.age_score * w.age
        )

        # ---- Blast Radius ---------------------------------------------------
        ms.blast_radius = import_graph.blast_radius.get(path, 0)

        # ---- Bus Factor -----------------------------------------------------
        if bus_factor_fn:
            ms.bus_factor = bus_factor_fn(path)

        return ms
