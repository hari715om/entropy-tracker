"""
Entropy CLI — the primary interface for engineers.

Built with Typer + Rich for professional terminal output.

Commands:
    entropy init <path>               Register and first-scan a repo
    entropy scan <path>               Run scan now, update DB
    entropy report                    All modules sorted by entropy
    entropy report --top 10           Worst 10 modules
    entropy inspect <path>            Full breakdown + forecast
    entropy trend --last 90days       Repo entropy trajectory (ASCII)
    entropy diff --since 7days        Which modules got worse
    entropy forecast <path>           Projected entropy at 30/60/90 days
    entropy report --format html      Export as HTML
    entropy server                    Start the FastAPI server
"""

from __future__ import annotations

import json
import os
import sys

# Fix Windows terminal encoding for Unicode/emoji support
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from entropy import __version__

app = typer.Typer(
    name="entropy",
    help="🔬 Entropy — A Code Aging & Decay Tracker",
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
        "WATCH": "bold magenta",
    }.get(severity, "white")


def _severity_icon(severity: str) -> str:
    return {
        "CRITICAL": "⚠",
        "HIGH": "▲",
        "MEDIUM": "●",
        "HEALTHY": "✓",
    }.get(severity, "·")


def _trend_arrow(trend: float) -> str:
    if trend > 3:
        return "↑↑"
    elif trend > 0:
        return "↑"
    elif trend < -1:
        return "↓"
    else:
        return "→"


def _run_full_scan(repo_path: str):
    """Run the complete analysis pipeline and return scores."""
    from entropy.analyzers.ast_analyzer import ASTAnalyzer
    from entropy.analyzers.dep_analyzer import DepAnalyzer
    from entropy.analyzers.git_analyzer import GitAnalyzer
    from entropy.scoring.alerts import AlertEngine
    from entropy.scoring.scorer import EntropyScorer

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing git history…", total=None)
        git = GitAnalyzer(repo_path)
        git_data = git.analyze()

        progress.update(task, description="Analyzing dependencies…")
        dep = DepAnalyzer(repo_path)
        dep_data = dep.analyze()

        progress.update(task, description="Building import graph…")
        ast_a = ASTAnalyzer(repo_path)
        import_graph = ast_a.analyze()

        progress.update(task, description="Computing entropy scores…")
        scorer = EntropyScorer()
        scores = scorer.score_all(git_data, dep_data, import_graph, git.compute_bus_factor)

        progress.update(task, description="Evaluating alerts…")
        alert_engine = AlertEngine()
        alerts = alert_engine.evaluate(scores)

    return scores, alerts, git_data


def _persist_scores(repo_name: str, repo_path: str, scores, alerts):
    """Save scores and alerts to database."""
    from entropy.storage.db import get_session, init_db, save_alerts, save_module_scores, save_repo

    try:
        init_db()
        with get_session() as session:
            repo = save_repo(session, repo_name, repo_path)
            save_module_scores(session, repo.id, scores)
            save_alerts(session, repo.id, alerts)
            repo.last_scan_at = datetime.now(timezone.utc)
            return repo.id
    except Exception as e:
        console.print(f"[dim]Note: Could not persist to database ({e}). Results shown but not stored.[/dim]")
        return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def init(
    path: str = typer.Argument(..., help="Path to git repository"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Repository name (defaults to directory name)"),
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
    console.print(f"\n[bold]🔬 Initializing Entropy for [cyan]{repo_name}[/cyan][/bold]\n")

    scores, alerts, _ = _run_full_scan(str(repo_path))
    _persist_scores(repo_name, str(repo_path), scores, alerts)

    _print_summary(repo_name, scores, alerts)


@app.command()
def scan(
    path: str = typer.Argument(".", help="Path to git repository"),
):
    """Run an entropy scan on a repository."""
    repo_path = Path(path).resolve()
    if not repo_path.is_dir():
        console.print(f"[red]Error: Path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)

    repo_name = repo_path.name
    console.print(f"\n[bold]🔬 Scanning [cyan]{repo_name}[/cyan][/bold]\n")

    scores, alerts, _ = _run_full_scan(str(repo_path))
    _persist_scores(repo_name, str(repo_path), scores, alerts)

    _print_summary(repo_name, scores, alerts)


@app.command()
def report(
    path: str = typer.Argument(".", help="Path to git repository"),
    top: int = typer.Option(0, "--top", "-t", help="Show only top N worst modules"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table, json, html"),
):
    """Show all modules sorted by entropy score."""
    repo_path = Path(path).resolve()
    scores, alerts, _ = _run_full_scan(str(repo_path))

    sorted_scores = sorted(scores.values(), key=lambda s: s.entropy_score, reverse=True)
    if top > 0:
        sorted_scores = sorted_scores[:top]

    if format == "json":
        data = [s.to_dict() for s in sorted_scores]
        console.print_json(json.dumps(data, indent=2))
        return

    if format == "html":
        _export_html(repo_path.name, sorted_scores)
        return

    _print_report_table(repo_path.name, sorted_scores)


@app.command()
def inspect(
    file_path: str = typer.Argument(..., help="Path to module file (relative to repo root)"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to repository"),
):
    """Full breakdown: signals, forecast, blast radius for a single module."""
    repo_path = Path(repo).resolve()
    scores, _, git_data = _run_full_scan(str(repo_path))

    # Find the matching module
    target = None
    for path, score in scores.items():
        if file_path in path or path.endswith(file_path):
            target = score
            break

    if target is None:
        console.print(f"[red]Module not found: {file_path}[/red]")
        raise typer.Exit(1)

    from entropy.scoring.forecaster import build_forecast

    fc = build_forecast(target.entropy_score, trend_override=target.trend_per_month)

    _print_inspect(target, fc)


@app.command()
def trend(
    path: str = typer.Argument(".", help="Path to git repository"),
    last: str = typer.Option("90days", "--last", "-l", help="Time period: 30days, 90days, 1year"),
):
    """Show repo entropy trajectory (ASCII chart)."""
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

    console.print(f"\n[bold]📊 Entropy Trend — {repo_path.name}[/bold]")
    console.print(f"   Period: {last}\n")

    # ASCII bar chart of severity distribution
    total = len(scores)
    bars = {
        "Critical": (critical, "red"),
        "High": (high, "yellow"),
        "Medium": (medium, "cyan"),
        "Healthy": (healthy, "green"),
    }

    for label, (count, color) in bars.items():
        bar_len = int(count / total * 40) if total else 0
        bar = "█" * bar_len + "░" * (40 - bar_len)
        console.print(f"  [{color}]{label:>10}[/{color}]  [{color}]{bar}[/{color}]  {count}")

    console.print(f"\n  Average Entropy: [bold]{avg:.1f}[/bold]  |  Modules: {total}\n")


@app.command()
def diff(
    path: str = typer.Argument(".", help="Path to git repository"),
    since: str = typer.Option("7days", "--since", "-s", help="Time period: 7days, 30days"),
):
    """Show which modules got worse recently."""
    repo_path = Path(path).resolve()
    scores, _, _ = _run_full_scan(str(repo_path))

    worsened = [
        s for s in scores.values()
        if s.trend_per_month > 0
    ]
    worsened.sort(key=lambda s: s.trend_per_month, reverse=True)

    if not worsened:
        console.print("[green]✓ No modules are getting worse![/green]")
        return

    console.print(f"\n[bold]📉 Modules Getting Worse — {repo_path.name}[/bold]")
    console.print(f"   Since: {since}\n")

    table = Table(box=box.ROUNDED)
    table.add_column("Module", style="white", max_width=50)
    table.add_column("Score", justify="right")
    table.add_column("Trend", justify="right")
    table.add_column("Severity", justify="center")

    for s in worsened[:20]:
        severity = s.severity()
        color = _severity_color(severity)
        table.add_row(
            s.module_path,
            f"[{color}]{s.entropy_score:.0f}[/{color}]",
            f"[red]+{s.trend_per_month:.1f}/mo[/red]",
            f"[{color}]{severity}[/{color}]",
        )

    console.print(table)


@app.command()
def forecast(
    file_path: str = typer.Argument(..., help="Path to module file"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to repository"),
):
    """Project entropy score at 30/60/90 days."""
    repo_path = Path(repo).resolve()
    scores, _, _ = _run_full_scan(str(repo_path))

    target = None
    for path, score in scores.items():
        if file_path in path or path.endswith(file_path):
            target = score
            break

    if target is None:
        console.print(f"[red]Module not found: {file_path}[/red]")
        raise typer.Exit(1)

    from entropy.scoring.forecaster import build_forecast

    fc = build_forecast(target.entropy_score, trend_override=target.trend_per_month)

    console.print(f"\n[bold]🔮 Forecast — {target.module_path}[/bold]\n")
    console.print(f"  Current Score: [bold]{fc.current_score:.0f}[/bold]")
    console.print(f"  Trend:         {fc.trend_per_month:+.2f} per month\n")

    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("Period", style="bold")
    table.add_column("Projected Score", justify="right")

    for label, score in [("30 days", fc.score_30d), ("60 days", fc.score_60d), ("90 days", fc.score_90d)]:
        color = "red" if score >= 85 else "yellow" if score >= 70 else "cyan" if score >= 50 else "green"
        table.add_row(label, f"[{color}]{score:.0f}[/{color}]")

    console.print(table)

    if fc.days_to_unmaintainable:
        console.print(f"\n  [bold red]⚠ Estimated unmaintainable in ~{fc.days_to_unmaintainable} days[/bold red]")
    console.print()


@app.command()
def server(
    host: str = typer.Option("0.0.0.0", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload"),
):
    """Start the Entropy API server."""
    import uvicorn

    console.print(f"\n[bold]🚀 Starting Entropy API at http://{host}:{port}[/bold]")
    console.print(f"   Docs: http://{host}:{port}/api/docs\n")
    uvicorn.run("entropy.api.main:app", host=host, port=port, reload=reload)


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
):
    if version:
        console.print(f"entropy {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print_summary(repo_name: str, scores, alerts):
    """Print the scan summary panel."""
    critical = sum(1 for s in scores.values() if s.severity() == "CRITICAL")
    high = sum(1 for s in scores.values() if s.severity() == "HIGH")
    medium = sum(1 for s in scores.values() if s.severity() == "MEDIUM")
    healthy = sum(1 for s in scores.values() if s.severity() == "HEALTHY")
    total = len(scores)

    # Top panel with counts
    c_bar = "█" * min(critical, 10) + "░" * max(10 - critical, 0)
    h_bar = "█" * min(high, 10) + "░" * max(10 - high, 0)
    m_bar = "█" * min(medium, 10) + "░" * max(10 - medium, 0)
    g_bar = "█" * min(healthy, 10) + "░" * max(10 - healthy, 0)

    header = f"ENTROPY REPORT · {repo_name} · {datetime.now().strftime('%Y-%m-%d')}"

    panel_text = (
        f"  [bold red]Critical (>85):[/bold red]  {c_bar}  {critical}\n"
        f"  [bold yellow]High    (70-85):[/bold yellow]  {h_bar}  {high}\n"
        f"  [bold cyan]Medium  (50-70):[/bold cyan]  {m_bar}  {medium}\n"
        f"  [bold green]Healthy  (<50):[/bold green]  {g_bar}  {healthy}\n"
    )

    console.print(Panel(panel_text, title=f"[bold]{header}[/bold]", box=box.DOUBLE, expand=False))

    # Show top critical/high modules
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
            f"  {s.module_path:<50} [{color}][{s.entropy_score:.0f}] {_severity_icon(severity)} "
            f"{severity}[/{color}] {arrow} {s.trend_per_month:+.1f}/mo"
        )
        shown += 1

    if alerts:
        console.print(f"\n  [bold]{len(alerts)} alerts fired[/bold]")

    console.print(f"\n  [dim]Scanned {total} modules[/dim]\n")


def _print_report_table(repo_name: str, sorted_scores):
    """Print a full report table."""
    console.print(f"\n[bold]📊 Entropy Report — {repo_name}[/bold]\n")

    table = Table(box=box.ROUNDED, show_lines=False)
    table.add_column("Module", style="white", max_width=50)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Knowledge", justify="right", width=10)
    table.add_column("Deps", justify="right", width=6)
    table.add_column("Churn", justify="right", width=6)
    table.add_column("Age", justify="right", width=6)
    table.add_column("Blast", justify="right", width=6)
    table.add_column("Bus", justify="right", width=4)
    table.add_column("Severity", justify="center", width=10)

    for s in sorted_scores:
        severity = s.severity()
        color = _severity_color(severity)
        table.add_row(
            s.module_path,
            f"[{color}]{s.entropy_score:.0f}[/{color}]",
            f"{s.knowledge_score:.0f}",
            f"{s.dep_score:.0f}",
            f"{s.churn_score:.0f}",
            f"{s.age_score:.0f}",
            str(s.blast_radius),
            str(s.bus_factor),
            f"[{color}]{severity}[/{color}]",
        )

    console.print(table)
    console.print()


def _print_inspect(score, fc):
    """Print full module inspection output."""
    severity = score.severity()
    color = _severity_color(severity)

    console.print(f"\n[bold]Module: {score.module_path}[/bold]")
    console.print("─" * 60)
    console.print(f"  Entropy Score:       [{color}]{score.entropy_score:.0f} / 100 {_severity_icon(severity)} {severity}[/{color}]")
    console.print(f"  Knowledge Decay:     {score.knowledge_score:.0f} / 100  ({score.authors_active} of {score.authors_total} authors active)")
    console.print(f"  Dependency Decay:    {score.dep_score:.0f} / 100")
    console.print(f"  Churn-to-Touch:      {score.churn_score:.0f} / 100  ({score.churn_commits} churn / {score.refactor_commits} refactor)")
    console.print(f"  Age Without Refactor:{score.age_score:.0f} / 100  ({score.months_since_refactor:.1f} months)")
    console.print(f"  Trajectory:          {score.trend_per_month:+.1f} entropy points / month")
    console.print()
    console.print("  Forecast:")
    console.print(f"    30 days → {fc.score_30d:.0f}")
    console.print(f"    60 days → {fc.score_60d:.0f}")
    console.print(f"    90 days → {fc.score_90d:.0f}")

    if fc.days_to_unmaintainable:
        console.print(f"\n  [bold red]Estimated unmaintainable: ~{fc.days_to_unmaintainable // 30} months[/bold red]")

    console.print(f"\n  Blast Radius: {score.blast_radius} modules import this file")
    if score.bus_factor <= 1:
        console.print(f"  Bus Factor:   [bold red]{score.bus_factor} ← CRITICAL single point of knowledge[/bold red]")
    else:
        console.print(f"  Bus Factor:   {score.bus_factor}")
    console.print()


def _export_html(repo_name: str, sorted_scores):
    """Export a full report as an HTML file."""
    rows = ""
    for s in sorted_scores:
        severity = s.severity()
        color_map = {"CRITICAL": "#ef4444", "HIGH": "#f59e0b", "MEDIUM": "#06b6d4", "HEALTHY": "#22c55e"}
        color = color_map.get(severity, "#ffffff")
        rows += f"""
        <tr>
            <td>{s.module_path}</td>
            <td style="color:{color};font-weight:bold;">{s.entropy_score:.0f}</td>
            <td>{s.knowledge_score:.0f}</td>
            <td>{s.dep_score:.0f}</td>
            <td>{s.churn_score:.0f}</td>
            <td>{s.age_score:.0f}</td>
            <td>{s.blast_radius}</td>
            <td>{s.bus_factor}</td>
            <td style="color:{color};font-weight:bold;">{severity}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Entropy Report — {repo_name}</title>
    <style>
        body {{ font-family: 'Inter', -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; }}
        h1 {{ color: #f8fafc; font-size: 1.5rem; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
        th {{ background: #1e293b; padding: 0.75rem; text-align: left; font-weight: 600; border-bottom: 2px solid #334155; }}
        td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid #1e293b; }}
        tr:hover {{ background: #1e293b; }}
        .meta {{ color: #94a3b8; font-size: 0.875rem; margin-top: 0.5rem; }}
    </style>
</head>
<body>
    <h1>🔬 Entropy Report — {repo_name}</h1>
    <p class="meta">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
    <table>
        <thead>
            <tr>
                <th>Module</th>
                <th>Score</th>
                <th>Knowledge</th>
                <th>Deps</th>
                <th>Churn</th>
                <th>Age</th>
                <th>Blast</th>
                <th>Bus</th>
                <th>Severity</th>
            </tr>
        </thead>
        <tbody>{rows}
        </tbody>
    </table>
</body>
</html>"""

    output_path = f"entropy-report-{repo_name}.html"
    with open(output_path, "w") as f:
        f.write(html)
    console.print(f"\n[green]✓ Report exported to {output_path}[/green]\n")


if __name__ == "__main__":
    app()
