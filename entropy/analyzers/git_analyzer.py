"""
Git Analyzer — extracts decay signals from git history.

Walks every commit in the repo via PyDriller to build per-file metadata:
- Author registry (all-time vs still-active)
- Commit classification (churn vs refactor)
- Timestamps (first/last commit, last refactor)
- Bus factor computation
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydriller import Repository

from entropy.config import AnalysisConfig, get_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FileGitData:
    """Aggregated git data for a single file."""

    path: str
    authors_all_time: set[str] = field(default_factory=set)
    authors_active: set[str] = field(default_factory=set)
    first_commit: datetime | None = None
    last_commit: datetime | None = None
    last_refactor_commit: datetime | None = None
    churn_commits: int = 0
    refactor_commits: int = 0
    total_commits: int = 0
    lines_added_total: int = 0
    lines_deleted_total: int = 0
    # For bus factor: author → lines in last blame
    author_line_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def months_since_refactor(self) -> float:
        """Months since the last refactor commit (or first commit if never refactored)."""
        ref_date = self.last_refactor_commit or self.first_commit
        if ref_date is None:
            return 0.0
        now = datetime.now(timezone.utc)
        if ref_date.tzinfo is None:
            ref_date = ref_date.replace(tzinfo=timezone.utc)
        delta = now - ref_date
        return delta.days / 30.44  # average days per month

    def to_dict(self) -> dict[str, Any]:
        fmt = "%Y-%m-%d"
        return {
            "path": self.path,
            "authors_all_time": sorted(self.authors_all_time),
            "authors_active": sorted(self.authors_active),
            "first_commit": self.first_commit.strftime(fmt) if self.first_commit else None,
            "last_commit": self.last_commit.strftime(fmt) if self.last_commit else None,
            "last_refactor_commit": (
                self.last_refactor_commit.strftime(fmt) if self.last_refactor_commit else None
            ),
            "churn_commits": self.churn_commits,
            "refactor_commits": self.refactor_commits,
            "total_commits": self.total_commits,
            "months_since_refactor": round(self.months_since_refactor, 1),
        }


# ---------------------------------------------------------------------------
# Commit classification helpers
# ---------------------------------------------------------------------------

def _is_churn_commit(
    added: int,
    deleted: int,
    churn_threshold: int,
) -> bool:
    """A churn commit has a large absolute change in lines."""
    return abs(added - deleted) > churn_threshold


def _is_refactor_commit(
    added: int,
    deleted: int,
    files_touched: int,
    refactor_threshold: int,
) -> bool:
    """
    A refactor commit:
    - Net lines changed < threshold (structural reorganisation, not new code)
    - Touches more than 1 file
    """
    net = abs(added - deleted)
    return net < refactor_threshold and files_touched > 1


# ---------------------------------------------------------------------------
# Main analyzer
# ---------------------------------------------------------------------------

class GitAnalyzer:
    """Analyze a git repository and extract per-file decay signals."""

    def __init__(self, repo_path: str | Path, config: AnalysisConfig | None = None):
        self.repo_path = str(repo_path)
        self.cfg = config or get_config().analysis
        self._cutoff = datetime.now(timezone.utc) - timedelta(days=self.cfg.active_author_window_days)
        self._file_data: dict[str, FileGitData] = {}
        self._global_active_authors: set[str] = set()

    # ---- public API --------------------------------------------------------

    def analyze(self) -> dict[str, FileGitData]:
        """
        Walk every commit in the repo and build per-file git data.
        Returns a dict of ``{file_path: FileGitData}``.
        """
        logger.info("GitAnalyzer: scanning %s …", self.repo_path)
        self._file_data.clear()
        self._global_active_authors.clear()

        try:
            repo = Repository(self.repo_path)
            commit_count = 0

            for commit in repo.traverse_commits():
                commit_count += 1
                author = commit.author.email or commit.author.name
                commit_date = commit.author_date
                if commit_date.tzinfo is None:
                    commit_date = commit_date.replace(tzinfo=timezone.utc)

                # Track global active authors
                if commit_date > self._cutoff:
                    self._global_active_authors.add(author)

                files_in_commit = len(commit.modified_files)

                for mod in commit.modified_files:
                    file_path = mod.new_path or mod.old_path
                    if file_path is None:
                        continue

                    fd = self._get_or_create(file_path)
                    fd.total_commits += 1
                    fd.authors_all_time.add(author)

                    # Track active authors per file
                    if commit_date > self._cutoff:
                        fd.authors_active.add(author)

                    # Timestamps
                    if fd.first_commit is None or commit_date < fd.first_commit:
                        fd.first_commit = commit_date
                    if fd.last_commit is None or commit_date > fd.last_commit:
                        fd.last_commit = commit_date

                    # Line counts
                    added = mod.added_lines or 0
                    deleted = mod.deleted_lines or 0
                    fd.lines_added_total += added
                    fd.lines_deleted_total += deleted

                    # Classify commit
                    if _is_churn_commit(added, deleted, self.cfg.churn_line_threshold):
                        fd.churn_commits += 1

                    if _is_refactor_commit(
                        added, deleted, files_in_commit, self.cfg.refactor_net_line_threshold
                    ):
                        fd.refactor_commits += 1
                        if fd.last_refactor_commit is None or commit_date > fd.last_refactor_commit:
                            fd.last_refactor_commit = commit_date

                    # Author line contribution (approximate with additions)
                    fd.author_line_counts[author] += added

            logger.info("GitAnalyzer: processed %d commits, found %d files", commit_count, len(self._file_data))

        except Exception:
            logger.exception("GitAnalyzer: failed to scan %s", self.repo_path)
            raise

        return self._file_data

    def compute_bus_factor(self, file_path: str) -> int:
        """
        Bus factor for a file: number of *active* authors who contributed >10% of lines.
        """
        fd = self._file_data.get(file_path)
        if fd is None:
            return 0

        total_lines = sum(fd.author_line_counts.values())
        if total_lines == 0:
            return 0

        threshold = total_lines * 0.10
        significant_active = 0
        for author, lines in fd.author_line_counts.items():
            if lines >= threshold and author in fd.authors_active:
                significant_active += 1

        return significant_active

    # ---- internal ----------------------------------------------------------

    def _get_or_create(self, path: str) -> FileGitData:
        if path not in self._file_data:
            self._file_data[path] = FileGitData(path=path)
        return self._file_data[path]
