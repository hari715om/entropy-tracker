"""
Celery Beat Scheduler — periodic scanning of all tracked repos.

Tasks:
- scan_all_repos: runs every 24 hours (configurable), re-analyzes all repos
- scan_single_repo: on-demand scan of a specific repo (triggered by API)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from entropy.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Beat schedule — runs all tracked repos daily
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    "scan-all-repos-daily": {
        "task": "entropy.tasks.scheduler.scan_all_repos",
        "schedule": 86400.0,  # 24 hours in seconds
    },
}


@celery_app.task(name="entropy.tasks.scheduler.scan_all_repos")
def scan_all_repos() -> dict:
    """Scan every tracked repository."""
    from entropy.storage.db import get_session
    from entropy.storage.models import Repo

    logger.info("Scheduled scan: starting…")
    results = {}

    with get_session() as session:
        repos = session.query(Repo).all()
        repo_list = [(str(r.id), r.path) for r in repos]

    for repo_id, repo_path in repo_list:
        try:
            result = scan_single_repo(repo_id, repo_path)
            results[repo_id] = result
        except Exception:
            logger.exception("Failed to scan repo %s at %s", repo_id, repo_path)
            results[repo_id] = {"status": "error"}

    logger.info("Scheduled scan: completed %d repos", len(results))
    return results


@celery_app.task(name="entropy.tasks.scheduler.scan_single_repo")
def scan_single_repo(repo_id: str, repo_path: str) -> dict:
    """Run full analysis pipeline for one repo."""
    import uuid

    from entropy.analyzers.ast_analyzer import ASTAnalyzer
    from entropy.analyzers.dep_analyzer import DepAnalyzer
    from entropy.analyzers.git_analyzer import GitAnalyzer
    from entropy.scoring.alerts import AlertEngine
    from entropy.scoring.scorer import EntropyScorer
    from entropy.storage.db import get_session, save_alerts, save_module_scores
    from entropy.storage.models import Repo

    rid = uuid.UUID(repo_id)
    logger.info("Scanning repo %s at %s", repo_id, repo_path)

    # 1. Git analysis
    git = GitAnalyzer(repo_path)
    git_data = git.analyze()

    # 2. Dependency analysis
    dep = DepAnalyzer(repo_path)
    dep_data = dep.analyze()

    # 3. Import graph
    ast_a = ASTAnalyzer(repo_path)
    import_graph = ast_a.analyze()

    # 4. Score
    scorer = EntropyScorer()
    scores = scorer.score_all(git_data, dep_data, import_graph, git.compute_bus_factor)

    # 5. Alerts
    engine = AlertEngine()
    alerts = engine.evaluate(scores)

    # 6. Persist
    with get_session() as session:
        save_module_scores(session, rid, scores)
        save_alerts(session, rid, alerts)
        repo = session.query(Repo).filter_by(id=rid).first()
        if repo:
            repo.last_scan_at = datetime.now(timezone.utc)

    critical = sum(1 for s in scores.values() if s.severity() == "CRITICAL")
    return {
        "status": "completed",
        "modules_scanned": len(scores),
        "critical_count": critical,
        "alerts_fired": len(alerts),
    }
