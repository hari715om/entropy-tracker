"""
Configuration loader for entropy.toml files.

Loads scoring weights, thresholds, analysis parameters, and alert settings.
Falls back to sensible defaults when no config file is found.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-untyped]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ScoringWeights:
    knowledge: float = 0.35
    dependency: float = 0.30
    churn: float = 0.20
    age: float = 0.15

    def __post_init__(self) -> None:
        total = self.knowledge + self.dependency + self.churn + self.age
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Scoring weights must sum to 1.0, got {total:.4f}")


@dataclass
class ScoringThresholds:
    critical: int = 85
    high: int = 70
    medium: int = 50


@dataclass
class AnalysisConfig:
    active_author_window_days: int = 180
    refactor_net_line_threshold: int = 10
    churn_line_threshold: int = 50
    age_ceiling_months: int = 36


@dataclass
class SchedulerConfig:
    scan_interval_hours: int = 24


@dataclass
class AlertConfig:
    notify_on: list[str] = field(default_factory=lambda: ["CRITICAL", "HIGH"])
    webhook_url: str = ""


@dataclass
class RepoConfig:
    name: str = ""
    path: str = ""
    language: str = "python"


@dataclass
class EntropyConfig:
    """Root configuration object."""

    repo: RepoConfig = field(default_factory=RepoConfig)
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    thresholds: ScoringThresholds = field(default_factory=ScoringThresholds)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_NAMES = ["entropy.toml", ".entropy.toml"]


def _find_config(start: Path | None = None) -> Path | None:
    """Walk up from *start* looking for an entropy config file."""
    search = start or Path.cwd()
    for parent in [search, *search.parents]:
        for name in _DEFAULT_CONFIG_NAMES:
            candidate = parent / name
            if candidate.is_file():
                return candidate
    return None


def _merge(section: dict[str, Any], target: Any) -> None:
    """Overwrite dataclass fields with values from a TOML section."""
    for key, value in section.items():
        if hasattr(target, key):
            setattr(target, key, value)


def load_config(path: Path | str | None = None) -> EntropyConfig:
    """
    Load an ``EntropyConfig`` from a TOML file.

    Resolution order:
    1. Explicit *path* argument
    2. Auto-discovery (``entropy.toml`` walking up from cwd)
    3. All-defaults
    """
    cfg = EntropyConfig()

    config_path: Path | None = None
    if path is not None:
        config_path = Path(path)
        if not config_path.is_file():
            raise FileNotFoundError(f"Config file not found: {config_path}")
    else:
        config_path = _find_config()

    if config_path is None:
        return cfg  # all defaults

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    if "repo" in data:
        _merge(data["repo"], cfg.repo)

    scoring = data.get("scoring", {})
    if "weights" in scoring:
        _merge(scoring["weights"], cfg.weights)
    if "thresholds" in scoring:
        _merge(scoring["thresholds"], cfg.thresholds)

    if "analysis" in data:
        _merge(data["analysis"], cfg.analysis)

    if "scheduler" in data:
        _merge(data["scheduler"], cfg.scheduler)

    if "alerts" in data:
        _merge(data["alerts"], cfg.alerts)

    return cfg


# Singleton-style default config — lazily populated
_config: EntropyConfig | None = None


def get_config() -> EntropyConfig:
    """Return the cached global config (loads on first call)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset the global config (useful for testing)."""
    global _config
    _config = None
