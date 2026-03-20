# 🔬 Entropy — A Code Aging & Decay Tracker

**Your codebase is aging. Entropy shows you where.**

Entropy computes a **decay score per module** in your codebase by analyzing git history, dependency drift, churn patterns, and knowledge silos. It tells you which parts of your code are silently becoming dangerous — before they break.

```
$ entropy scan ./my-repo

┌─────────────────────────────────────────────────────────┐
│ ENTROPY REPORT · my-repo · 2024-06-01                   │
├─────────────────────────────────────────────────────────┤
│ Critical (>85):  3  ████░░░░░░                          │
│ High    (70-85): 8  ████████░░                          │
│ Medium  (50-70): 12                                     │
│ Healthy  (<50):  24                                     │
└─────────────────────────────────────────────────────────┘

payments/gateway.py       [87] ⚠ CRITICAL  ↑  +3.2/mo
auth/legacy_tokens.py     [91] ⚠ CRITICAL  ↑↑ +5.1/mo
core/database/connector.py[83] ▲ HIGH      →  +0.8/mo
```

## Quick Start

```bash
pip install entropy-tracker
entropy init ./my-repo
entropy report --top 10
```

## The Four Decay Signals

| Signal | What It Measures |
|--------|------------------|
| **Knowledge Decay** | % of authors who touched this module that are still active. A module where 5 of 6 authors have gone inactive is a knowledge silo. |
| **Dependency Decay** | How far behind this module's dependencies are, weighted by ecosystem velocity. |
| **Churn-to-Touch Ratio** | Ratio of chaotic edits to intentional refactors. High churn with no refactoring = invisible debt. |
| **Age Without Refactor** | Months since the last commit that was primarily restructuring. |

## CLI Commands

```bash
entropy init ./repo              # Register repo, run first scan
entropy scan ./repo              # Run scan now, update DB
entropy report                   # All modules sorted by entropy
entropy report --top 10          # Worst 10 modules
entropy inspect path/to/file.py  # Full breakdown: signals, forecast, blast radius
entropy trend --last 90days      # Repo entropy trajectory
entropy diff --since 7days       # Which modules got worse this week
entropy forecast path/to/file.py # Projected entropy at 30/60/90 days
entropy report --format html     # Export full report as HTML
entropy server                   # Start the dashboard on localhost:8000
```

## Architecture

```
┌──────────────────────────────────────────┐
│              ENTROPY ENGINE              │
│                                          │
│ ┌─────────────┐ ┌───────────┐ ┌────────┐│
│ │Git Analyzer  │ │Dep Analyzer│ │AST     ││
│ │(PyDriller)   │ │(PyPI API)  │ │Analyzer││
│ └──────┬───────┘ └─────┬─────┘ └───┬────┘│
│        └───────────────┼───────────┘     │
│                        ▼                 │
│              ┌─────────────────┐         │
│              │  Signal Merger  │         │
│              └────────┬────────┘         │
│                       ▼                  │
│              ┌─────────────────┐         │
│              │ Entropy Scorer  │         │
│              │  + Forecaster   │         │
│              └────────┬────────┘         │
│                       ▼                  │
│        ┌──────────────────────────┐      │
│        │ PostgreSQL + TimescaleDB │      │
│        └──────────────────────────┘      │
│                       ▼                  │
│  ┌───────────────────────────────────┐   │
│  │  FastAPI  │  Celery Beat Scheduler│   │
│  └───────────────────────────────────┘   │
│                       ▼                  │
│       ┌─────────────────────────┐        │
│       │  CLI (Typer + Rich)     │        │
│       │  Dashboard (React)      │        │
│       └─────────────────────────┘        │
└──────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Core Engine | Python 3.11+ |
| Git Analysis | PyDriller + GitPython |
| Dep Analysis | PyPI JSON API + pip-audit |
| Static Analysis | Python `ast` module |
| Time-Series DB | PostgreSQL + TimescaleDB |
| Background Jobs | Celery + Redis |
| API | FastAPI |
| CLI | Typer + Rich |
| Dashboard | React + Recharts |
| Containers | Docker + Docker Compose |

## Running with Docker

```bash
# Development
docker compose up

# Production
DB_PASSWORD=your_secret docker compose -f docker-compose.prod.yml up -d
```

## Configuration — `entropy.toml`

```toml
[scoring.weights]
knowledge = 0.35    # highest: lost knowledge is hardest to recover
dependency = 0.30   # CVEs and drift are measurable risk
churn = 0.20        # invisible debt accumulation
age = 0.15          # time since last deliberate attention

[scoring.thresholds]
critical = 85
high = 70
medium = 50

[analysis]
active_author_window_days = 180
age_ceiling_months = 36
```

## Roadmap

- [x] Dependency age decay score
- [x] Knowledge decay via git history
- [x] Churn-to-touch ratio
- [x] Entropy score per module
- [x] Trajectory prediction + forecast
- [x] Blast radius detection
- [x] Bus factor per module
- [x] CLI with Rich output
- [x] TimescaleDB time-series history
- [x] FastAPI + Celery scheduler
- [ ] React dashboard (v2)
- [ ] External API contract drift detection
- [ ] Test coverage decay over time
- [ ] JavaScript / TypeScript repo support

## License

MIT
