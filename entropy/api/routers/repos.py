"""
Repos router — manage tracked repositories.

Endpoints:
- POST   /repos              Register a new repo
- GET    /repos              List all tracked repos
- GET    /repos/{id}         Get single repo details
- POST   /repos/{id}/scan    Trigger immediate re-scan
- GET    /repos/{id}/trend   Repo-level average entropy over time
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from entropy.analyzers.ast_analyzer import ASTAnalyzer
from entropy.analyzers.dep_analyzer import DepAnalyzer
from entropy.analyzers.git_analyzer import GitAnalyzer
from entropy.scoring.alerts import AlertEngine
from entropy.scoring.scorer import EntropyScorer
from entropy.storage.db import (
    get_latest_scores,
    get_session,
    save_alerts,
    save_module_scores,
    save_repo,
)
from entropy.storage.models import ModuleEntropy, Repo

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateRepoRequest(BaseModel):
    name: str
    path: str
    language: str = "python"


class RepoResponse(BaseModel):
    id: str
    name: str
    path: str
    language: str
    created_at: str | None = None
    last_scan_at: str | None = None
    module_count: int = 0
    avg_entropy: float | None = None


class TrendPoint(BaseModel):
    date: str
    avg_entropy: float
    module_count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/repos", response_model=RepoResponse)
async def create_repo(req: CreateRepoRequest):
    """Register a new repo path for tracking."""
    repo_path = Path(req.path)
    if not repo_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {req.path}")

    with get_session() as session:
        repo = save_repo(session, req.name, req.path, req.language)
        return RepoResponse(
            id=str(repo.id),
            name=repo.name,
            path=repo.path,
            language=repo.language,
            created_at=repo.created_at.isoformat() if repo.created_at else None,
        )


@router.get("/repos")
async def list_repos() -> list[dict[str, Any]]:
    """List all tracked repos with latest entropy summary."""
    with get_session() as session:
        repos = session.query(Repo).all()
        results = []
        for repo in repos:
            scores = get_latest_scores(session, repo.id)
            avg = sum(s.entropy_score for s in scores) / len(scores) if scores else None
            results.append({
                **repo.to_dict(),
                "module_count": len(scores),
                "avg_entropy": round(avg, 1) if avg else None,
            })
        return results


@router.get("/repos/{repo_id}")
async def get_repo(repo_id: str) -> dict[str, Any]:
    """Get a single repo with summary stats."""
    try:
        rid = uuid.UUID(repo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    with get_session() as session:
        repo = session.query(Repo).filter_by(id=rid).first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repo not found")
        scores = get_latest_scores(session, repo.id)
        avg = sum(s.entropy_score for s in scores) / len(scores) if scores else None
        return {
            **repo.to_dict(),
            "module_count": len(scores),
            "avg_entropy": round(avg, 1) if avg else None,
        }


@router.post("/repos/{repo_id}/scan")
async def scan_repo(repo_id: str) -> dict[str, Any]:
    """Trigger an immediate re-scan of a repository."""
    try:
        rid = uuid.UUID(repo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    with get_session() as session:
        repo = session.query(Repo).filter_by(id=rid).first()
        if not repo:
            raise HTTPException(status_code=404, detail="Repo not found")

        repo_path = repo.path
        repo_name = repo.name

    # Run full analysis pipeline
    result = _run_scan(rid, repo_path)

    # Update last_scan_at
    with get_session() as session:
        repo = session.query(Repo).filter_by(id=rid).first()
        if repo:
            repo.last_scan_at = datetime.now(timezone.utc)

    return result


@router.get("/repos/{repo_id}/trend")
async def get_trend(repo_id: str, days: int = 90) -> list[dict]:
    """Repo-level average entropy over time."""
    try:
        rid = uuid.UUID(repo_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    with get_session() as session:
        from sqlalchemy import func

        results = (
            session.query(
                func.date(ModuleEntropy.time).label("date"),
                func.avg(ModuleEntropy.entropy_score).label("avg_entropy"),
                func.count(ModuleEntropy.module_path.distinct()).label("module_count"),
            )
            .filter(ModuleEntropy.repo_id == rid)
            .group_by(func.date(ModuleEntropy.time))
            .order_by(func.date(ModuleEntropy.time).desc())
            .limit(days)
            .all()
        )

        return [
            {
                "date": str(r.date),
                "avg_entropy": round(float(r.avg_entropy), 1),
                "module_count": r.module_count,
            }
            for r in reversed(results)
        ]


# ---------------------------------------------------------------------------
# Scan pipeline
# ---------------------------------------------------------------------------


def _run_scan(repo_id: uuid.UUID, repo_path: str) -> dict[str, Any]:
    """Run the full analysis pipeline for a repository."""
    # 1. Git analysis
    git = GitAnalyzer(repo_path)
    git_data = git.analyze()

    # 2. Dependency analysis
    dep = DepAnalyzer(repo_path)
    dep_data = dep.analyze()

    # 3. Import graph / blast radius
    ast_analyzer = ASTAnalyzer(repo_path)
    import_graph = ast_analyzer.analyze()

    # 4. Score all modules
    scorer = EntropyScorer()
    scores = scorer.score_all(git_data, dep_data, import_graph, git.compute_bus_factor)

    # 5. Evaluate alerts
    alert_engine = AlertEngine()
    alerts = alert_engine.evaluate(scores)

    # 6. Persist to database
    with get_session() as session:
        save_module_scores(session, repo_id, scores)
        save_alerts(session, repo_id, alerts)

    # Summary
    critical = sum(1 for s in scores.values() if s.severity() == "CRITICAL")
    high = sum(1 for s in scores.values() if s.severity() == "HIGH")

    return {
        "status": "completed",
        "modules_scanned": len(scores),
        "critical_count": critical,
        "high_count": high,
        "alerts_fired": len(alerts),
    }
