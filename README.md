<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/logo-light.svg">
  <img alt="Entropy" src="assets/logo-light.svg" width="180">
</picture>

# Entropy - Code Aging & Decay Tracker

`boto/compat.py` scores **69**. 490 modules depend on it. Every author who wrote it is gone. Its dependencies are years out of date. Nobody flagged this. Until now.

[![PyPI](https://img.shields.io/pypi/v/entropy-tracker?color=2D6A4F)](https://pypi.org/project/entropy-tracker/)
[![Python](https://img.shields.io/badge/python-3.10%2B-2D6A4F)](https://pypi.org/project/entropy-tracker/)
[![License: MIT](https://img.shields.io/badge/license-MIT-2D6A4F)](LICENSE)
[![Demo](https://img.shields.io/badge/live%20demo-entropy.kwixlab.com-2D6A4F)](https://entropy.kwixlab.com)

---

Software does not just accumulate bugs. It **ages**. The library it depends on evolved. The engineers who wrote it have left. Entropy makes that risk visible — as a number, per module, before production goes down.

<!-- SCREENSHOT PLACEMENT 1 of 2 -->
<!-- Replace the line below with your boto report screenshot after generating it -->
<!-- Generation steps are in the CONTRIBUTING.md or see README instructions below -->
![Entropy Report — boto](assets/demo-boto.png)

---

## Install

```bash
pip install entropy-tracker
```

**Requirements:** Python 3.10+, Git in your system PATH.
**No API keys. No telemetry.** Code analysis runs entirely locally. Dependency checks query PyPI to detect version drift - no data about your code is sent anywhere.

---

## Quick Start

```bash
entropy init ./my-repo                 # register repo + first scan
entropy report --top 10                # worst modules by decay score
entropy inspect payments/gateway.py   # full breakdown + forecast
entropy diff --base main               # entropy delta for current branch
```

First results in under 60 seconds on most repositories.

---

## Sample Output

<!-- SCREENSHOT PLACEMENT 2 of 2 -->
<!-- Replace the terminal block below with a real terminal screenshot -->
<!-- once you have captured it. See screenshot steps in this file. -->

![Entropy Report](assets/demo-report.png)

![Module Inspect](assets/demo-inspect.png)
<!-- ```
Entropy Report - boto  (source modules only)

  Total: 938   Critical: 1   High: 31   Medium: 18   Healthy: 0

  Module                              Score   Severity   Blast
  boto/cloudsearch/search.py            82    HIGH        453
  boto/cloudsearch/document.py          83    HIGH        451
  boto/cloudsearch2/search.py           82    HIGH        451
  boto/compat.py                        69    MEDIUM      490
  boto/cloudfront/distribution.py       68    MEDIUM      451
```

```
entropy inspect boto/compat.py

  Entropy Score:        69 / 100
  Knowledge Decay:     100 / 100   (0 of 12 authors still active)
  Dependency Decay:    100 / 100   (years behind, multiple CVEs)
  Churn-to-Touch:       12 / 100
  Age Without Refactor: 100 / 100  (no refactor in 4+ years)

  Forecast:  if current trends continue - risk increasing
  Blast Radius:  490 modules depend on this file
  Bus Factor:    1
``` -->

---

## What It Measures

Four signals combine into one composite score (0–100):

| Signal | What it detects | Weight |
|--------|----------------|--------|
| **Knowledge Decay** | % of this file's authors who are still active in the repo | 35% |
| **Dependency Decay** | How far behind this module's direct dependencies are | 30% |
| **Churn-to-Touch Ratio** | Chaotic edits vs intentional refactors | 20% |
| **Age Without Refactor** | Months since the last deliberate restructure | 15% |

**How signals are computed:** Knowledge decay checks author activity within a 36-month window. Churn is classified by total lines touched (>200 = churn) vs net line change (<10 with multi-file changes = refactor) - not by commit messages, which are unreliable. Dependency checks query PyPI for current release history and pip-audit for CVE counts.

**Weights reflect recovery cost.** Knowledge decay has the highest weight because lost institutional knowledge is irreversible on any sprint timescale. You can update a dependency in an afternoon. You cannot rebuild three years of context in a sprint.

Scores above **85** are Critical. Above **70** are High. All weights are configurable via `entropy.toml`.

---

## Does It Actually Work?

We ran Entropy across Django, boto, and requests. Files scoring above 70 showed significantly more bug-fix and hotfix commits in their history than files below 50. The correlation is not causal - high-entropy files attract bugs and are touched repeatedly to fix them, which compounds the score over time. This is the pattern Entropy is designed to surface before it becomes an incident.

The tool processed Django's 2,903 modules across 2,782 commits in **34 seconds**.

---

## CI Integration

```bash
entropy diff --base main
# Shows entropy delta for every file changed in the current branch
```

```yaml
# .github/workflows/entropy.yml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0        # full history required — do not use fetch-depth: 1
- run: pip install entropy-tracker && entropy diff --base main
```

---

## Performance

| Repository | Modules | Scan Time |
|-----------|---------|-----------|
| click | 62 | ~11s |
| Django | 2,903 | ~34s |
| boto (full history) | 938 | ~45s |

Subsequent scans are faster — PyPI responses are cached locally for 24 hours.

---

## Why Not SonarQube / Dependabot / CodeScene?

| Tool | Prevents bugs | Surfaces knowledge loss risk |
|------|--------------|------------------------------|
| SonarQube | ✅ | ❌ |
| Dependabot | ✅ | ❌ |
| CodeScene | Partially | Partially (no dep drift, no CI diff, enterprise pricing) |
| **Entropy** | — | ✅ |

Entropy's focus is not code quality. It is the risk that comes from **a module nobody fully understands anymore** — which no other tool in this list measures.

---

<!-- ## Live Demo

**[entropy.kwixlab.com](https://entropy.kwixlab.com)** - pre-loaded scans of Django, FastAPI, and boto. No login required. -->

---

## Roadmap

- `entropy simulate --author-leaves alice@company.com`
- JavaScript / TypeScript support
- GitHub Actions marketplace integration
- Validation dataset: entropy score vs production incident correlation

---

*Built by [Hari om Singh](https://github.com/hari715om) · [PyPI](https://pypi.org/project/entropy-tracker/) · MIT License*