"""
Entropy CLI -- full-featured terminal interface for engineers.

Commands:
    entropy init <path>               Register and first-scan a repo
    entropy scan <path>               Run scan now, update DB
    entropy scan <path> --lang js     Scan a JavaScript/TypeScript repo
    entropy report                    All modules sorted by entropy score
    entropy report --top 10           Worst 10 modules
    entropy inspect <file>            Full breakdown + forecast
    entropy trend --last 90days       Repo entropy trajectory
    entropy diff --since 7days        Which modules got worse
    entropy diff --fail-above 75      Fail CI if any changed file scores above 75
    entropy forecast <file>           Projected entropy at 30/60/90 days
    entropy simulate --author-leaves  Show risk if an engineer leaves
    entropy report --format html      Export as HTML (utf-8)
    entropy server                    Start the FastAPI server (requires [server] extra)
"""

from __future__ import annotations

import json
import os
import sys

# Fix Windows terminal encoding — must happen before any Rich output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from entropy import __version__

app = typer.Typer(
    name="entropy",
    help="Entropy - A Code Aging & Decay Tracker",
    add_completion=True,
    no_args_is_help=True,
)

console = Console()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _severity_color(severity: str) -> str:
    return {
        "CRITICAL": "bold red",
        "HIGH": "bold yellow",
        "MEDIUM": "bold cyan",
        "HEALTHY": "bold green",
    }.get(severity, "white")


def _severity_icon(severity: str) -> str:
    return {"CRITICAL": "!", "HIGH": "^", "MEDIUM": "~", "HEALTHY": "+"}.get(severity, ".")


def _trend_arrow(trend: float) -> str:
    if trend > 3:
        return "up++"
    elif trend > 0:
        return "up"
    elif trend < -1:
        return "dn"
    else:
        return "--"


def _run_full_scan(repo_path: str, lang: str = "auto"):
    """Run the complete analysis pipeline.

    Parameters
    ----------
    repo_path : str
        Path to the git repository to scan.
    lang : str
        Language hint: "python", "js" (JavaScript/TypeScript), or "auto" (detect both).

    Each step prints a permanent completion line to the terminal so you
    can see all 4 steps after the scan finishes, not just a transient spinner.
    """
    from entropy.analyzers.ast_analyzer import ASTAnalyzer
    from entropy.analyzers.dep_analyzer import DepAnalyzer
    from entropy.analyzers.git_analyzer import GitAnalyzer
    from entropy.analyzers.npm_analyzer import NpmAnalyzer
    from entropy.scoring.alerts import AlertEngine
    from entropy.scoring.scorer import EntropyScorer

    git: GitAnalyzer | None = None
    git_data = {}
    dep_data = {}
    import_graph = None
    scores = {}
    alerts = []

    # ── Step 1: Git history ──────────────────────────────────────────────────
    git = GitAnalyzer(repo_path)
    total_commits = git._total_commits
    total_str = f"/{total_commits}" if total_commits > 0 else ""

    with Progress(
        SpinnerColumn(style="bold cyan"),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task(
            f"  [dim]Step 1/4[/dim] Analyzing git history[dim]{total_str and f' (~{total_commits} commits)'}[/dim]…",
            total=None,
        )

        def git_progress(commits, total, files):
            total_label = f"/{total}" if total > 0 else ""
            progress.update(
                task_id,
                description=(
                    f"  [dim]Step 1/4[/dim] Git history — [bold]{commits}{total_label}[/bold] commits · {files} files"
                ),
            )

        git_data = git.analyze(progress_callback=git_progress)

    # Print permanent summary line for step 1
    total_label = f"/{total_commits}" if total_commits > 0 else ""
    console.print(
        f"  [bold green]✔[/bold green] [dim]Step 1/4[/dim]  Git history  "
        f"[bold]{len(git_data)} files[/bold] tracked across [bold]{git._total_commits or '?'}[/bold] commits"
    )
    if getattr(git, "_using_full_history", False):
        console.print(
            "  [yellow]Note:[/yellow] [dim]Repo has no commits in past 36 months — "
            "using full git history for decay signals[/dim]"
        )

    # ── Step 2: Dependency analysis ──────────────────────────────────────────
    pkg_count_holder = [0]
    with Progress(
        SpinnerColumn(style="bold cyan"),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("  [dim]Step 2/4[/dim] Analyzing dependencies…", total=None)

        def dep_progress(msg: str):
            # extract package count from message if possible
            import re as _re

            m = _re.search(r"(\d+)", msg)
            if m:
                pkg_count_holder[0] = int(m.group(1))
            progress.update(task_id, description=f"  [dim]Step 2/4[/dim] Dependencies — [dim]{msg}[/dim]")

        dep_data = DepAnalyzer(repo_path).analyze(progress_callback=dep_progress)

    console.print(
        f"  [bold green]+[/bold green] [dim]Step 2/4[/dim]  Dependencies  "
        f"[bold]{len(dep_data)} files[/bold] · [bold]{pkg_count_holder[0]}[/bold] unique packages queried"
    )

    # ── Step 2b: NPM dependency analysis (JS/TS repos) ───────────────────────
    if lang in ("js", "auto"):
        npm_pkg_count = [0]
        with Progress(
            SpinnerColumn(style="bold cyan"),
            TextColumn("{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task_id = progress.add_task("  [dim]Step 2b [/dim] NPM dependencies…", total=None)

            def npm_progress(msg: str):
                import re as _re

                m = _re.search(r"(\d+)", msg)
                if m:
                    npm_pkg_count[0] = int(m.group(1))
                progress.update(task_id, description=f"  [dim]Step 2b [/dim] NPM -- [dim]{msg}[/dim]")

            npm_data = NpmAnalyzer(repo_path).analyze(progress_callback=npm_progress)

        if npm_data:
            # Merge npm dep scores into dep_data so the scorer picks them up
            for path, npm_fd in npm_data.items():
                if path not in dep_data:
                    # Create a compatible FileDepData stub with the npm dep score
                    from entropy.analyzers.dep_analyzer import FileDepData

                    dep_data[path] = FileDepData(path=path, dep_score=npm_fd.dep_score)
                else:
                    # JS file already in dep_data (unusual but possible) — take max
                    dep_data[path].dep_score = max(dep_data[path].dep_score, npm_fd.dep_score)
            console.print(
                f"  [bold green]+[/bold green] [dim]Step 2b [/dim]  NPM  "
                f"[bold]{npm_pkg_count[0]} packages[/bold] queried across [bold]{len(npm_data)} JS/TS files[/bold]"
            )
        else:
            console.print("  [dim]Step 2b  NPM -- no package.json found, skipping[/dim]")

    # ── Step 3: AST import graph ─────────────────────────────────────────────
    with Progress(
        SpinnerColumn(style="bold cyan"),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("  [dim]Step 3/4[/dim] Building import graph…", total=None)
        import_graph = ASTAnalyzer(repo_path).analyze()

    console.print(
        f"  [bold green]✔[/bold green] [dim]Step 3/4[/dim]  Import graph  "
        f"[bold]{len(import_graph.all_modules)} modules[/bold] mapped"
    )

    # ── Step 4: Scoring ───────────────────────────────────────────────────────
    with Progress(
        SpinnerColumn(style="bold cyan"),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("  [dim]Step 4/4[/dim] Computing entropy scores…", total=None)
        scores = EntropyScorer().score_all(git_data, dep_data, import_graph, git.compute_bus_factor)
        alerts = AlertEngine().evaluate(scores)

    console.print(
        f"  [bold green]✔[/bold green] [dim]Step 4/4[/dim]  Scoring  "
        f"[bold]{len(scores)} modules[/bold] scored · [bold]{len(alerts)} alerts[/bold] fired"
    )
    console.print()

    return scores, alerts, git_data


def _persist_scores(repo_name: str, repo_path: str, scores, alerts):
    """Save scores and alerts to database. Falls back to SQLite automatically."""
    from entropy.storage.db import get_session, init_db, save_alerts, save_module_scores, save_repo

    try:
        init_db()
        with get_session() as session:
            repo = save_repo(session, repo_name, repo_path)
            save_module_scores(session, repo.id, scores)
            save_alerts(session, repo.id, alerts)
            repo.last_scan_at = datetime.now(timezone.utc)
        from entropy.storage.db import get_database_url

        db_url = get_database_url()
        db_label = "PostgreSQL" if "postgresql" in db_url else "SQLite (entropy.db)"
        console.print(f"  [dim]Results saved to {db_label}[/dim]")
        return True
    except Exception as e:
        console.print(f"  [dim]Note: Could not persist results ({e})[/dim]")
        return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def init(
    path: str = typer.Argument(..., help="Path to git repository"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Repository name"),
):
    """Register a repository and run the first scan."""
    repo_path = Path(path).resolve()
    if not repo_path.is_dir():
        console.print(f"[red]Error: Path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)
    if not (repo_path / ".git").is_dir():
        console.print(f"[red]Error: Not a git repository: {repo_path}[/red]")
        raise typer.Exit(1)

    repo_name = name or repo_path.name
    console.print(f"\n[bold]Entropy Init   {repo_name}[/bold]\n")

    scores, alerts, _ = _run_full_scan(str(repo_path))
    _persist_scores(repo_name, str(repo_path), scores, alerts)
    _print_summary(repo_name, scores, alerts)


@app.command()
def scan(
    path: str = typer.Argument(".", help="Path to git repository"),
):
    """Run an entropy scan on a repository and update results."""
    repo_path = Path(path).resolve()
    repo_name = repo_path.name
    console.print(f"\n[bold]Entropy Scan   {repo_name}[/bold]\n")

    scores, alerts, _ = _run_full_scan(str(repo_path))
    _persist_scores(repo_name, str(repo_path), scores, alerts)
    _print_summary(repo_name, scores, alerts)


@app.command()
def report(
    path: str = typer.Argument(".", help="Path to git repository"),
    top: int = typer.Option(50, "--top", "-t", help="Show only top N worst modules (0 = all)"),
    format: str = typer.Option("table", "--format", "-f", help="table, json, or html"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full signal breakdown"),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Exclude path prefixes (e.g. tests/)"),
):
    """Show all modules sorted by entropy score."""
    repo_path = Path(path).resolve()
    scores, alerts, _ = _run_full_scan(str(repo_path))

    if top == 0 and len(scores) > 100:
        console.print(f"\n[yellow]Generating full report for {len(scores)} modules.[/yellow]")
        console.print("[yellow]This may be slow. Use --top 50 for a focused view.[/yellow]\n")

    sorted_scores = sorted(scores.values(), key=lambda s: s.entropy_score, reverse=True)

    # Apply --exclude filters
    # Each exclude pattern is matched against:
    #   1. The full normalized path (prefix match from root)
    #   2. Any individual path segment (catches nested test dirs like boto/fps/test/)
    if exclude:

        def _is_excluded(module_path: str, excludes: list[str]) -> bool:
            norm = module_path.replace("\\", "/")
            segments = norm.split("/")
            for ex in excludes:
                ex = ex.replace("\\", "/").strip("/")
                # Root-prefix match: tests/ matches tests/unit/foo.py
                if norm.startswith(ex + "/") or norm == ex:
                    return True
                # Segment match: tests/ matches boto/fps/tests/foo.py
                if ex in segments:
                    return True
                # Partial segment match: test matches boto/test_connection.py
                if any(seg.startswith(ex) for seg in segments):
                    return True
            return False

        sorted_scores = [s for s in sorted_scores if not _is_excluded(s.module_path, list(exclude))]
        console.print(f"  [dim]Excluded prefixes: {', '.join(exclude)}[/dim]")

    if top > 0:
        sorted_scores = sorted_scores[:top]

    if format == "json":
        console.print_json(json.dumps([s.to_dict() for s in sorted_scores], indent=2))
        return

    if format == "html":
        _export_html(repo_path.name, sorted_scores)
        return

    _print_report_table(repo_path.name, sorted_scores, verbose)


@app.command()
def inspect(
    file_path: str = typer.Argument(..., help="Module file path (relative to repo root)"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to repository"),
):
    """Full signal breakdown, forecast, blast radius for a single module."""
    repo_path = Path(repo).resolve()
    scores, _, _ = _run_full_scan(str(repo_path))

    target = None
    # Normalize the query path for matching
    query_normalized = file_path.replace("\\", "/")
    for path, score in scores.items():
        norm_path = path.replace("\\", "/")
        if query_normalized in norm_path or norm_path.endswith(query_normalized):
            target = score
            break

    if target is None:
        console.print(f"[red]Module not found: {file_path}[/red]")
        console.print("[dim]Tip: Use the exact relative path shown in 'entropy report'[/dim]")
        raise typer.Exit(1)

    from entropy.scoring.forecaster import build_forecast

    fc = build_forecast(target.entropy_score, trend_override=target.trend_per_month)
    _print_inspect(target, fc)


@app.command()
def trend(
    path: str = typer.Argument(".", help="Path to git repository"),
    last: str = typer.Option("90days", "--last", "-l", help="Time period: 30days, 90days, 1year"),
):
    """Show repo entropy trend (severity distribution ASCII chart)."""
    repo_path = Path(path).resolve()
    scores, _, _ = _run_full_scan(str(repo_path))

    if not scores:
        console.print("[yellow]No scored modules found.[/yellow]")
        return

    avg = sum(s.entropy_score for s in scores.values()) / len(scores)
    critical = sum(1 for s in scores.values() if s.severity() == "CRITICAL")
    high = sum(1 for s in scores.values() if s.severity() == "HIGH")
    medium = sum(1 for s in scores.values() if s.severity() == "MEDIUM")
    healthy = sum(1 for s in scores.values() if s.severity() == "HEALTHY")
    total = len(scores)

    console.print(f"\n[bold]Entropy Trend -- {repo_path.name}[/bold]")
    console.print(f"   Window: {last}\n")

    for label, count, color in [
        ("Critical", critical, "red"),
        ("High", high, "yellow"),
        ("Medium", medium, "cyan"),
        ("Healthy", healthy, "green"),
    ]:
        bar_len = int(count / total * 40) if total else 0
        bar = "#" * bar_len + "." * (40 - bar_len)
        pct = f"{count / total * 100:.0f}%" if total else "0%"
        console.print(f"  [{color}]{label:>10}[/{color}]  [{color}]{bar}[/{color}]  {count} ({pct})")

    console.print(f"\n  Average Entropy Score: [bold]{avg:.1f}[/bold] / 100")
    console.print(f"  Total Modules:         {total}\n")


@app.command()
def diff(
    path: str = typer.Argument(".", help="Path to git repository"),
    base: str = typer.Option("main", "--base", "-b", help="Base branch to compare against"),
    fail_above: int = typer.Option(
        0,
        "--fail-above",
        "-f",
        help="Exit with code 1 if any changed file has entropy score above this threshold. "
        "Set to e.g. 75 to block PRs that touch high-risk modules. 0 = never fail.",
    ),
):
    """Diff entropy scores for files changed between current branch and base branch."""
    import os
    import subprocess
    import tempfile

    repo_path = Path(path).resolve()

    # 1. Get changed files (only Python files)
    try:
        cmd = ["git", "diff", "--name-only", f"{base}...HEAD"]
        output = subprocess.check_output(cmd, cwd=repo_path, text=True, stderr=subprocess.STDOUT)
        changed_files = [f for f in output.splitlines() if f.endswith(".py")]
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error comparing branches:[/red] {e.output}")
        raise typer.Exit(1)

    if not changed_files:
        console.print(f"[green]No Python files changed against {base}.[/green]")
        return

    console.print(f"\n[bold]Entropy Diff  [{base} -> HEAD][/bold]\n")

    # 2. Score current branch (HEAD)
    console.print("[dim]Analyzing current branch (HEAD)...[/dim]")
    head_scores, _, _ = _run_full_scan(str(repo_path))

    # 3. Score base branch via temporary worktree
    console.print(f"\n[dim]Analyzing base branch ({base})...[/dim]")
    base_scores = {}
    with tempfile.TemporaryDirectory() as td:
        # worktree add requires the dir to not exist
        os.rmdir(td)
        try:
            subprocess.run(
                ["git", "worktree", "add", td, base],
                cwd=repo_path,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            base_scores, _, _ = _run_full_scan(td)
        except subprocess.CalledProcessError:
            console.print(f"[red]Failed to create worktree for branch '{base}'. Does it exist?[/red]")
            raise typer.Exit(1)
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", td],
                cwd=repo_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    # 4. Compute deltas
    results = []
    total_delta = 0.0

    # Normalize changed files (git diff returns forward slashes)
    changed_normalized = {f.replace("\\", "/") for f in changed_files}

    for f_path in changed_normalized:
        head_score = 0.0
        base_score = 0.0

        # Find in HEAD
        for hp, score_obj in head_scores.items():
            if hp.replace("\\", "/") == f_path:
                head_score = score_obj.entropy_score
                break

        # Find in BASE
        for bp, score_obj in base_scores.items():
            if bp.replace("\\", "/") == f_path:
                base_score = score_obj.entropy_score
                break

        delta = head_score - base_score
        total_delta += delta
        results.append((f_path, base_score, head_score, delta))

    # Sort by worst actual head_score
    results.sort(key=lambda x: x[2], reverse=True)

    console.print(f"\n[bold]Entropy delta for current branch vs {base}:[/bold]\n")

    table = Table(box=box.ROUNDED)
    table.add_column("Changed File", max_width=55)
    table.add_column("Delta", justify="right", width=8)
    table.add_column("Scores", justify="center", width=12)
    table.add_column("Severity", justify="center", width=10)

    failing_files = []
    for f_path, b_score, h_score, delta in results:
        from entropy.scoring.scorer import ModuleScore

        severity = ModuleScore(module_path="", entropy_score=h_score).severity()
        color = _severity_color(severity)

        delta_str = (
            f"[red]+{delta:.1f}[/red]"
            if delta > 0
            else (f"[green]{delta:+.1f}[/green]" if delta < 0 else f"[dim]{delta:+.1f}[/dim]")
        )
        score_str = f"{b_score:.0f} -> [{color}]{h_score:.0f}[/{color}]"

        # Track files that breach the --fail-above threshold
        if fail_above > 0 and h_score > fail_above:
            failing_files.append((f_path, h_score))

        table.add_row(f_path, delta_str, score_str, f"[{color}]{severity}[/{color}]")

    console.print(table)

    net_color = "red" if total_delta > 0 else "green"
    console.print(
        f"\n  Net branch entropy delta: [{net_color}]{total_delta:+.1f}[/{net_color}] points across {len(results)} changed files"
    )

    if results:
        worst_file = results[0]
        if worst_file[2] >= 50:
            console.print(f"  Highest risk: [bold]{worst_file[0]}[/bold] -- review carefully")

    # 5. CI gate — exit non-zero if threshold breached
    if failing_files:
        console.print(
            f"\n  [bold red]ENTROPY GATE FAILED[/bold red]  "
            f"--fail-above {fail_above} threshold breached by {len(failing_files)} file(s):"
        )
        for fp, score in failing_files:
            console.print(f"    [red]{fp}[/red]  score={score:.0f}")
        console.print(
            "\n  [dim]These files have high decay scores. Refactor or add documentation before merging.[/dim]\n"
        )
        raise typer.Exit(1)

    console.print()


@app.command()
def forecast(
    file_path: str = typer.Argument(..., help="Module file path"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to repository"),
):
    """Project entropy score at 30/60/90 days for a module."""
    repo_path = Path(repo).resolve()
    scores, _, _ = _run_full_scan(str(repo_path))

    query_normalized = file_path.replace("\\", "/")
    target = None
    for path, score in scores.items():
        norm_path = path.replace("\\", "/")
        if query_normalized in norm_path or norm_path.endswith(query_normalized):
            target = score
            break

    if target is None:
        console.print(f"[red]Module not found: {file_path}[/red]")
        raise typer.Exit(1)

    from entropy.scoring.forecaster import build_forecast

    fc = build_forecast(target.entropy_score, trend_override=target.trend_per_month)

    console.print(f"\n[bold]Forecast -- {target.module_path}[/bold]\n")
    console.print(f"  Current Score : [bold]{fc.current_score:.0f}[/bold] / 100")
    console.print(f"  Trend         : {fc.trend_per_month:+.2f} / month\n")

    table = Table(box=box.SIMPLE_HEAVY, show_header=True)
    table.add_column("Period", style="bold")
    table.add_column("Projected Score", justify="right")
    table.add_column("Severity", justify="center")

    for label, score in [("30 days", fc.score_30d), ("60 days", fc.score_60d), ("90 days", fc.score_90d)]:
        from entropy.scoring.scorer import ModuleScore

        dummy = ModuleScore(module_path="", entropy_score=score)
        sev = dummy.severity()
        color = _severity_color(sev)
        table.add_row(label, f"[{color}]{score:.0f}[/{color}]", f"[{color}]{sev}[/{color}]")

    console.print(table)

    if fc.days_to_unmaintainable:
        console.print(
            f"\n  [bold red]WARNING: Estimated unmaintainable "
            f"in ~{fc.days_to_unmaintainable} days "
            f"({fc.days_to_unmaintainable // 30} months)[/bold red]"
        )
    console.print()


@app.command()
def simulate(
    path: str = typer.Argument(".", help="Path to git repository"),
    author_leaves: str = typer.Option(..., "--author-leaves", "-a", help="Author email to simulate leaving"),
):
    """Simulate the risk impact of an engineer leaving the team.

    Re-computes bus factor for every module as if the specified author
    no longer exists. Shows which files become single points of failure.
    """
    repo_path = Path(path).resolve()
    console.print(f"\n[bold]Entropy Simulate  --author-leaves {author_leaves}[/bold]\n")
    console.print("[dim]Running full scan to build author map...[/dim]\n")

    scores, _, git_data = _run_full_scan(str(repo_path))

    at_risk = []
    for module_path, ms in scores.items():
        gd = git_data.get(module_path)
        if not gd:
            continue

        # Authors active in the window, before and after simulated departure
        active_before: set = gd.authors_active if hasattr(gd, "authors_active") else set()
        active_after = active_before - {author_leaves}

        bus_before = ms.bus_factor
        bus_after = len(active_after) if active_after else 0

        # Only surface modules where the departure actually changes the risk picture
        if bus_after < bus_before or (bus_after <= 1 and author_leaves in (gd.authors_all_time or set())):
            at_risk.append((module_path, ms, bus_before, bus_after))

    if not at_risk:
        console.print(f"[green]No modules become single points of failure if {author_leaves} leaves.[/green]")
        console.print("[dim](Either they authored nothing critical, or every file has multiple active owners.)[/dim]\n")
        return

    # Sort by worst final bus factor, then by entropy score
    at_risk.sort(key=lambda x: (x[3], -x[2].entropy_score))

    console.print(
        f"  [bold yellow]Warning:[/bold yellow] {len(at_risk)} module(s) become higher risk if [bold]{author_leaves}[/bold] leaves.\n"
    )

    table = Table(box=box.ROUNDED, show_lines=False)
    table.add_column("Module", max_width=55, no_wrap=True)
    table.add_column("Entropy", justify="right", width=8)
    table.add_column("Bus Factor Before", justify="center", width=18)
    table.add_column("Bus Factor After", justify="center", width=17)
    table.add_column("Risk", justify="center", width=10)

    critical_count = 0
    for module_path, ms, bus_before, bus_after in at_risk:
        severity = ms.severity()
        color = _severity_color(severity)
        after_color = "bold red" if bus_after <= 1 else "yellow"
        if bus_after <= 1:
            critical_count += 1
        table.add_row(
            module_path,
            f"[{color}]{ms.entropy_score:.0f}[/{color}]",
            str(bus_before),
            f"[{after_color}]{bus_after}[/{after_color}]",
            f"[{after_color}]{'CRITICAL' if bus_after <= 1 else 'HIGH'}[/{after_color}]",
        )

    console.print(table)
    console.print(f"\n  [bold red]{critical_count} file(s) become sole-ownership (bus factor 0 or 1)[/bold red]")
    console.print(
        f"  [dim]Recommendation: schedule knowledge transfer sessions for these modules before {author_leaves} leaves.[/dim]\n"
    )


@app.command()
def server(
    host: str = typer.Option("0.0.0.0", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload"),
):
    """Start the Entropy API server and dashboard."""
    try:
        import uvicorn
    except ImportError:
        console.print(
            "\n[bold red]Server dependencies not installed.[/bold red]\n"
            "  The [bold]entropy server[/bold] command requires the server extras:\n\n"
            '    [bold cyan]pip install "entropy-tracker[server]"[/bold cyan]\n'
        )
        raise typer.Exit(1)
    console.print(f"\n[bold]Entropy Server[/bold]  http://{host}:{port}")
    console.print(f"  Swagger docs:  http://localhost:{port}/api/docs\n")
    uvicorn.run("entropy.api.main:app", host=host, port=port, reload=reload)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context = typer.Option(None),
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit"),
):
    if version:
        console.print(f"entropy {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Rich output helpers
# ---------------------------------------------------------------------------


def _print_summary(repo_name: str, scores, alerts):
    """Print the scan summary panel."""
    critical = sum(1 for s in scores.values() if s.severity() == "CRITICAL")
    high = sum(1 for s in scores.values() if s.severity() == "HIGH")
    medium = sum(1 for s in scores.values() if s.severity() == "MEDIUM")
    healthy = sum(1 for s in scores.values() if s.severity() == "HEALTHY")
    total = len(scores)

    def bar(n, max_n=10):
        filled = min(int(n / max(total, 1) * max_n), max_n)
        return "#" * filled + "." * (max_n - filled)

    header = f"ENTROPY REPORT  {repo_name}  {datetime.now().strftime('%Y-%m-%d')}"
    panel_text = (
        f"  [bold red]Critical (>85): [/bold red] {bar(critical)}  {critical}\n"
        f"  [bold yellow]High    (70-85):[/bold yellow] {bar(high)}  {high}\n"
        f"  [bold cyan]Medium  (50-70):[/bold cyan] {bar(medium)}  {medium}\n"
        f"  [bold green]Healthy  (<50): [/bold green] {bar(healthy)}  {healthy}\n"
    )

    console.print(Panel(panel_text, title=f"[bold]{header}[/bold]", box=box.DOUBLE, expand=False))

    # Show worst modules (critical + high only)
    worst = sorted(scores.values(), key=lambda s: s.entropy_score, reverse=True)
    shown = 0
    for s in worst:
        if shown >= 10:
            break
        severity = s.severity()
        if severity not in ("CRITICAL", "HIGH"):
            continue
        color = _severity_color(severity)
        arrow = _trend_arrow(s.trend_per_month)
        console.print(
            f"  {s.module_path:<55} [{color}][{s.entropy_score:.0f}] "
            f"{_severity_icon(severity)} {severity}[/{color}] "
            f"{arrow} {s.trend_per_month:+.1f}/mo"
        )
        shown += 1

    console.print(f"\n  [bold]{len(alerts)} alerts fired[/bold]")
    console.print(f"  [dim]Scanned {total} modules[/dim]\n")


def _get_primary_fault(s) -> str:
    factors = {
        "Knowledge Decay": s.knowledge_score,
        "Legacy code": s.age_score,
        "High Churn": s.churn_score,
        "Dependency Drift": s.dep_score,
    }
    primary = max(factors, key=lambda k: factors[k])
    if factors[primary] < 20:
        return "None"
    return primary


def _print_report_table(repo_name: str, sorted_scores, verbose: bool = False):
    """Full module table sorted by entropy score."""
    console.print(f"\n[bold]Entropy Report -- {repo_name}[/bold]\n")

    table = Table(box=box.ROUNDED, show_lines=False)
    table.add_column("Module", max_width=55, no_wrap=True)
    table.add_column("Score", justify="right", width=6)
    if verbose:
        table.add_column("Knowl.", justify="right", width=7)
        table.add_column("Deps", justify="right", width=5)
        table.add_column("Churn", justify="right", width=6)
        table.add_column("Age", justify="right", width=5)
        table.add_column("Blast", justify="right", width=6)
        table.add_column("Bus", justify="right", width=4)
        table.add_column("Severity", justify="center", width=11)
        table.add_column("Primary Fault", justify="left")
    else:
        table.add_column("Severity", justify="center", width=11)
        table.add_column("Blast", justify="right", width=6)
        table.add_column("Trend", justify="right", width=6)
        table.add_column("Primary Fault", justify="left")

    shown = 0
    for s in sorted_scores:
        # Skip zero-score modules (files with no git history — e.g. docs)
        if s.entropy_score == 0 and s.knowledge_score == 0:
            continue
        severity = s.severity()
        color = _severity_color(severity)
        primary_fault = _get_primary_fault(s)
        norm_path = s.module_path.replace("\\", "/")
        is_test = any(part in norm_path for part in ("/tests/", "/test/", "test_", "_test.py"))
        # Add [T] badge to visually distinguish test files
        test_badge = " [dim][T][/dim]" if is_test else ""
        path_display = s.module_path + test_badge

        row = [
            path_display,
            f"[{color}]{s.entropy_score:.0f}[/{color}]",
        ]

        if verbose:
            row.extend(
                [
                    f"{s.knowledge_score:.0f}",
                    f"{s.dep_score:.0f}",
                    f"{s.churn_score:.0f}",
                    f"{s.age_score:.0f}",
                    str(s.blast_radius),
                    str(s.bus_factor),
                    f"[{color}]{severity}[/{color}]",
                    f"[{color}]{primary_fault}[/{color}]",
                ]
            )
        else:
            arrow = _trend_arrow(s.trend_per_month)
            trend_str = f"{arrow} {s.trend_per_month:+.1f}" if s.trend_per_month else "--"
            row.extend(
                [
                    f"[{color}]{severity}[/{color}]",
                    str(s.blast_radius),
                    trend_str,
                    f"[{color}]{primary_fault}[/{color}]",
                ]
            )

        table.add_row(*row)
        shown += 1

    console.print(table)
    if not verbose:
        console.print("  [dim]Tip: Use --verbose to see full signal breakdown[/dim]")
    console.print(f"  [dim]{shown} modules shown[/dim]\n")


def _print_inspect(score, fc):
    """Full module inspection output."""
    severity = score.severity()
    color = _severity_color(severity)

    console.print(f"\n[bold]Module: {score.module_path}[/bold]")
    console.print("-" * 60)
    console.print(
        f"  Entropy Score       [{color}]{score.entropy_score:.0f} / 100  "
        f"{_severity_icon(severity)} {severity}[/{color}]"
    )
    console.print(
        f"  Knowledge Decay     {score.knowledge_score:.0f} / 100  "
        f"({score.authors_active} of {score.authors_total} authors active)"
    )
    console.print(f"  Dependency Decay    {score.dep_score:.0f} / 100")
    console.print(
        f"  Churn-to-Touch      {score.churn_score:.0f} / 100  "
        f"({score.churn_commits} churn / {score.refactor_commits} refactor)"
    )
    console.print(f"  Age w/o Refactor    {score.age_score:.0f} / 100  ({score.months_since_refactor:.1f} months)")
    console.print(f"  Trend               {score.trend_per_month:+.1f} pts/month")
    console.print()
    console.print("  Forecast:")
    console.print(f"    30 days -> {fc.score_30d:.0f}")
    console.print(f"    60 days -> {fc.score_60d:.0f}")
    console.print(f"    90 days -> {fc.score_90d:.0f}")

    if fc.days_to_unmaintainable:
        console.print(f"\n  [bold red]WARNING: Unmaintainable in ~{fc.days_to_unmaintainable // 30} months[/bold red]")

    console.print(f"\n  Blast Radius  {score.blast_radius} modules depend on this file")
    if score.bus_factor <= 1:
        console.print(f"  Bus Factor    [bold red]{score.bus_factor} <- CRITICAL: single point of knowledge[/bold red]")
    else:
        console.print(f"  Bus Factor    {score.bus_factor} engineers own this file")
    console.print()


def _export_html(repo_name: str, sorted_scores):
    """Export a clean, minimal, professional engineering-report HTML (UTF-8)."""
    # Compute summary stats
    # Filter out unscored files (e.g. docs without git history)
    valid_scores = [s for s in sorted_scores if not (s.entropy_score == 0 and s.knowledge_score == 0)]
    total = len(valid_scores)
    critical = sum(1 for s in valid_scores if s.severity() == "CRITICAL")
    high = sum(1 for s in valid_scores if s.severity() == "HIGH")
    medium = sum(1 for s in valid_scores if s.severity() == "MEDIUM")
    healthy = sum(1 for s in valid_scores if s.severity() == "HEALTHY")

    # Severity bar segments (proportional widths)
    def pct(n):
        return round(n / max(total, 1) * 100, 1)

    severity_bar = (
        f'<span class="seg-critical" style="width:{pct(critical)}%" title="Critical: {critical}"></span>'
        f'<span class="seg-high" style="width:{pct(high)}%" title="High: {high}"></span>'
        f'<span class="seg-medium" style="width:{pct(medium)}%" title="Medium: {medium}"></span>'
        f'<span class="seg-healthy" style="width:{pct(healthy)}%" title="Healthy: {healthy}"></span>'
    )

    # Table rows
    rows = ""
    for s in sorted_scores:
        if s.entropy_score == 0 and s.knowledge_score == 0:
            continue
        sev = s.severity()
        sev_class = sev.lower()
        bus_warn = " bus-warn" if s.bus_factor <= 1 else ""
        rows += f"""
        <tr>
          <td class="col-path"><span class="path">{s.module_path}</span></td>
          <td class="col-num"><span class="score-pill {sev_class}">{s.entropy_score:.0f}</span></td>
          <td class="col-num">{s.knowledge_score:.0f}</td>
          <td class="col-num">{s.dep_score:.0f}</td>
          <td class="col-num">{s.churn_score:.0f}</td>
          <td class="col-num">{s.age_score:.0f}</td>
          <td class="col-num">{s.blast_radius}</td>
          <td class="col-num{bus_warn}">{s.bus_factor}</td>
          <td><span class="badge {sev_class}">{sev}</span></td>
        </tr>"""

    # Average score for context
    all_scores = [s.entropy_score for s in sorted_scores if not (s.entropy_score == 0 and s.knowledge_score == 0)]
    avg_score = sum(all_scores) / max(len(all_scores), 1)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Entropy Report &mdash; {repo_name}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:        #0c0c10;
      --bg-card:   #13131a;
      --bg-row:    #16161f;
      --bg-row-alt:#111118;
      --border:    #1f1f2e;
      --text:      #d4d4e8;
      --text-dim:  #5a5a78;
      --text-label:#9090b0;
      --accent:    #5b5bd6;
      --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', ui-monospace, monospace;
      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      /* severity */
      --c-critical:#f87171;
      --c-high:    #fb923c;
      --c-medium:  #38bdf8;
      --c-healthy: #34d399;
    }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      font-size: 14px;
      line-height: 1.6;
      min-height: 100vh;
    }}

    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* ── layout ── */
    .page {{ max-width: 1200px; margin: 0 auto; padding: 48px 32px 80px; }}

    /* ── header ── */
    .header {{
      border-bottom: 1px solid var(--border);
      padding-bottom: 24px;
      margin-bottom: 32px;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      flex-wrap: wrap;
      gap: 16px;
    }}
    .header-left h1 {{
      font-size: 1.4rem;
      font-weight: 600;
      color: #fff;
      letter-spacing: -0.02em;
    }}
    .header-left .repo-path {{
      font-family: var(--font-mono);
      font-size: 0.78rem;
      color: var(--text-dim);
      margin-top: 4px;
    }}
    .header-right {{
      text-align: right;
      font-size: 0.78rem;
      color: var(--text-dim);
      line-height: 1.8;
    }}
    .header-right .tool-badge {{
      display: inline-block;
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 2px 8px;
      font-family: var(--font-mono);
      font-size: 0.72rem;
      color: var(--accent);
      margin-bottom: 4px;
    }}

    /* ── severity bar ── */
    .sev-bar-wrap {{ margin-bottom: 32px; }}
    .sev-bar-label {{
      font-size: 0.72rem;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
    }}
    .sev-bar {{
      display: flex;
      height: 6px;
      border-radius: 3px;
      overflow: hidden;
      background: var(--border);
    }}
    .sev-bar span {{ display: block; min-width: 2px; transition: width 0.3s; }}
    .seg-critical {{ background: var(--c-critical); }}
    .seg-high     {{ background: var(--c-high); }}
    .seg-medium   {{ background: var(--c-medium); }}
    .seg-healthy  {{ background: var(--c-healthy); }}

    /* ── stats grid ── */
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 40px;
    }}
    .stat {{
      background: var(--bg-card);
      padding: 18px 20px;
    }}
    .stat-label {{
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-dim);
      margin-bottom: 6px;
    }}
    .stat-value {{
      font-family: var(--font-mono);
      font-size: 1.6rem;
      font-weight: 700;
      line-height: 1;
      color: #fff;
    }}
    .stat-value.critical {{ color: var(--c-critical); }}
    .stat-value.high     {{ color: var(--c-high); }}
    .stat-value.medium   {{ color: var(--c-medium); }}
    .stat-value.healthy  {{ color: var(--c-healthy); }}

    /* ── section title ── */
    .section-title {{
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--text-dim);
      margin-bottom: 12px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }}

    /* ── table ── */
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-bottom: 40px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }}
    thead th {{
      background: var(--bg-card);
      padding: 10px 14px;
      text-align: left;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-label);
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }}
    thead th:not(:first-child) {{ text-align: right; }}
    tbody tr {{ border-bottom: 1px solid var(--border); }}
    tbody tr:last-child {{ border-bottom: none; }}
    tbody tr:nth-child(odd)  {{ background: var(--bg-row-alt); }}
    tbody tr:nth-child(even) {{ background: var(--bg-row); }}
    tbody tr:hover {{ background: #1c1c28; }}
    td {{
      padding: 9px 14px;
      vertical-align: middle;
    }}
    .col-path {{ width: 42%; }}
    .col-num  {{ text-align: right; font-family: var(--font-mono); font-size: 0.78rem; color: var(--text-label); }}
    .path {{
      font-family: var(--font-mono);
      font-size: 0.76rem;
      color: var(--text);
      word-break: break-all;
    }}
    .bus-warn {{ color: var(--c-critical) !important; font-weight: 700; }}

    /* score pill in Score column */
    .score-pill {{
      display: inline-block;
      font-family: var(--font-mono);
      font-size: 0.8rem;
      font-weight: 700;
      min-width: 30px;
      text-align: center;
    }}
    .score-pill.critical {{ color: var(--c-critical); }}
    .score-pill.high     {{ color: var(--c-high); }}
    .score-pill.medium   {{ color: var(--c-medium); }}
    .score-pill.healthy  {{ color: var(--text-label); }}

    /* severity badge */
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 3px;
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      font-family: var(--font-mono);
    }}
    .badge.critical {{ background: rgba(248,113,113,0.12); color: var(--c-critical); }}
    .badge.high     {{ background: rgba(251,146, 60,0.12); color: var(--c-high); }}
    .badge.medium   {{ background: rgba( 56,189,248,0.12); color: var(--c-medium); }}
    .badge.healthy  {{ background: rgba( 52,211,153,0.10); color: var(--c-healthy); }}

    /* ── column legend ── */
    .legend {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 1px;
      background: var(--border);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 40px;
    }}
    .legend-item {{
      background: var(--bg-card);
      padding: 14px 18px;
    }}
    .legend-key {{
      font-family: var(--font-mono);
      font-size: 0.72rem;
      font-weight: 700;
      color: var(--accent);
      margin-bottom: 4px;
    }}
    .legend-desc {{
      font-size: 0.78rem;
      color: var(--text-label);
      line-height: 1.5;
    }}

    /* ── about strip ── */
    .about {{
      border-top: 1px solid var(--border);
      padding-top: 24px;
      margin-top: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .about-text {{
      font-size: 0.78rem;
      color: var(--text-dim);
      max-width: 560px;
      line-height: 1.6;
    }}
    .about-text strong {{ color: var(--text-label); }}
    .about-links {{
      font-size: 0.75rem;
      color: var(--text-dim);
      text-align: right;
    }}
  </style>
</head>
<body>
<div class="page">

  <!-- ── HEADER ──────────────────────────────────────── -->
  <header class="header">
    <div class="header-left">
      <h1>Entropy Report - {repo_name}</h1>
      <div class="repo-path">{repo_name}/</div>
    </div>
    <div class="header-right">
      <div class="tool-badge">entropy {__version__}</div><br>
      <span>Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</span><br>
      <span>Analysis window: last 24 months of commits</span>
    </div>
  </header>

  <!-- ── SEVERITY BAR ─────────────────────────────────── -->
  <div class="sev-bar-wrap">
    <div class="sev-bar-label">Overall health distribution</div>
    <div class="sev-bar">{severity_bar}</div>
  </div>

  <!-- ── STATS GRID ───────────────────────────────────── -->
  <div class="stats-grid">
    <div class="stat">
      <div class="stat-label">Total Modules</div>
      <div class="stat-value">{total}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Avg Score</div>
      <div class="stat-value">{avg_score:.1f}<span style="font-size:1rem;color:var(--text-dim)">/100</span></div>
    </div>
    <div class="stat">
      <div class="stat-label">Critical</div>
      <div class="stat-value critical">{critical}</div>
    </div>
    <div class="stat">
      <div class="stat-label">High</div>
      <div class="stat-value high">{high}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Medium</div>
      <div class="stat-value medium">{medium}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Healthy</div>
      <div class="stat-value healthy">{healthy}</div>
    </div>
  </div>

  <!-- ── MODULE TABLE ─────────────────────────────────── -->
  <div class="section-title">Module Scores (sorted by entropy)</div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Module Path</th>
          <th title="Composite entropy score 0-100">Score</th>
          <th title="Knowledge Decay: % of all-time contributors who are no longer active">Knowledge</th>
          <th title="Dependency Decay: staleness of third-party packages used by this module">Deps</th>
          <th title="Churn: ratio of churn commits to refactor commits">Churn</th>
          <th title="Age: months since the last meaningful refactor">Age</th>
          <th title="Blast Radius: how many modules transitively import this one">Blast</th>
          <th title="Bus Factor: active engineers with &gt;10% ownership — red = 1 (single point of failure)">Bus</th>
          <th>Severity</th>
        </tr>
      </thead>
      <tbody>{rows}
      </tbody>
    </table>
  </div>

  <!-- ── COLUMN LEGEND ────────────────────────────────── -->
  <div class="section-title">Column Reference</div>
  <div class="legend">
    <div class="legend-item">
      <div class="legend-key">Score (0 &ndash; 100)</div>
      <div class="legend-desc">Composite entropy. Weighted sum of all four signals. Higher = more decayed, harder to safely modify.</div>
    </div>
    <div class="legend-item">
      <div class="legend-key">Knowledge</div>
      <div class="legend-desc">What fraction of a file&rsquo;s all-time contributors are still active (past 180 days). 100 = nobody who wrote this is still around.</div>
    </div>
    <div class="legend-item">
      <div class="legend-key">Deps</div>
      <div class="legend-desc">Staleness of third-party packages imported by this file. Based on months behind latest PyPI release &times; release velocity.</div>
    </div>
    <div class="legend-item">
      <div class="legend-key">Churn</div>
      <div class="legend-desc">Ratio of churn commits (large, unfocused changes) to refactor commits (structural improvements). High churn = instability.</div>
    </div>
    <div class="legend-item">
      <div class="legend-key">Age</div>
      <div class="legend-desc">Months since the last meaningful refactor commit. Files that grow old without being restructured accumulate hidden complexity.</div>
    </div>
    <div class="legend-item">
      <div class="legend-key">Blast</div>
      <div class="legend-desc">Blast radius: number of modules that transitively import this one. A high-entropy file with a large blast radius can cascade failures widely.</div>
    </div>
    <div class="legend-item">
      <div class="legend-key">Bus</div>
      <div class="legend-desc">Bus factor: active contributors with &gt;10% code ownership. <strong style="color:var(--c-critical)">1 = single point of knowledge failure</strong> &mdash; if that person leaves, institutional memory is lost.</div>
    </div>
    <div class="legend-item">
      <div class="legend-key">Severity Thresholds</div>
      <div class="legend-desc">
        <span class="badge critical">Critical</span> &ge;85 &nbsp;
        <span class="badge high">High</span> &ge;70 &nbsp;
        <span class="badge medium">Medium</span> &ge;50 &nbsp;
        <span class="badge healthy">Healthy</span> &lt;50
      </div>
    </div>
  </div>

  <!-- ── ABOUT ────────────────────────────────────────── -->
  <footer class="about">
    <div class="about-text">
      <strong>What is Entropy?</strong> Entropy is a code aging &amp; decay tracker. It measures how risky each module in a codebase has become over time &mdash; not by static analysis, but by reading the project&rsquo;s actual git history. It surfaces which files are losing their maintainers, accumulating dependencies nobody updates, being churned without refactoring, and approaching the point where no engineer fully understands them anymore.
    </div>
    <div class="about-links">
      entropy-tracker &middot; v{__version__}<br>
      <span style="color:var(--text-dim)">pip install -e .</span>
    </div>
  </footer>

</div>
</body>
</html>"""

    output_path = f"entropy-report-{repo_name}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    console.print(f"  [green]Report exported:[/green] {output_path}\n")


if __name__ == "__main__":
    app()
