"""
Dependency Analyzer — measures how far behind each module's dependencies are.

Workflow:
1. Parse requirements.txt / pyproject.toml to get pinned versions
2. Use Python ast module to extract imports per file
3. Map imports → PyPI packages
4. Query PyPI JSON API for latest release + release history → compute months_behind & velocity
5. Optionally run pip-audit for CVE counts
6. Compute per-module dep_risk scores
"""

from __future__ import annotations

import ast
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Common import-name → PyPI-package-name mappings (top-level imports that differ)
_IMPORT_TO_PACKAGE: dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "attr": "attrs",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "gi": "PyGObject",
    "jwt": "PyJWT",
    "serial": "pyserial",
    "usb": "pyusb",
    "wx": "wxPython",
    "Crypto": "pycryptodome",
    "lxml": "lxml",
    "flask": "Flask",
    "django": "Django",
    "celery": "celery",
    "redis": "redis",
    "sqlalchemy": "SQLAlchemy",
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "numpy": "numpy",
    "pandas": "pandas",
    "scipy": "scipy",
    "matplotlib": "matplotlib",
    "requests": "requests",
    "typer": "typer",
    "rich": "rich",
    "pydriller": "pydriller",
    "git": "gitpython",
    "alembic": "alembic",
    "uvicorn": "uvicorn",
    "toml": "toml",
}

# Stdlib top-level modules (Python 3.11+) — skip these
_STDLIB_MODULES: set[str] = {
    "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio", "asyncore",
    "atexit", "audioop", "base64", "bdb", "binascii", "binhex", "bisect",
    "builtins", "bz2", "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd",
    "code", "codecs", "codeop", "collections", "colorsys", "compileall",
    "concurrent", "configparser", "contextlib", "contextvars", "copy", "copyreg",
    "cProfile", "crypt", "csv", "ctypes", "curses", "dataclasses", "datetime",
    "dbm", "decimal", "difflib", "dis", "distutils", "doctest", "email",
    "encodings", "enum", "errno", "faulthandler", "fcntl", "filecmp", "fileinput",
    "fnmatch", "fractions", "ftplib", "functools", "gc", "getopt", "getpass",
    "gettext", "glob", "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac",
    "html", "http", "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect",
    "io", "ipaddress", "itertools", "json", "keyword", "lib2to3", "linecache",
    "locale", "logging", "lzma", "mailbox", "mailcap", "marshal", "math",
    "mimetypes", "mmap", "modulefinder", "multiprocessing", "netrc", "nis",
    "nntplib", "numbers", "operator", "optparse", "os", "ossaudiodev",
    "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform",
    "plistlib", "poplib", "posix", "posixpath", "pprint", "profile", "pstats",
    "pty", "pwd", "py_compile", "pyclbr", "pydoc", "queue", "quopri", "random",
    "re", "readline", "reprlib", "resource", "rlcompleter", "runpy", "sched",
    "secrets", "select", "selectors", "shelve", "shlex", "shutil", "signal",
    "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver", "spwd",
    "sqlite3", "ssl", "stat", "statistics", "string", "stringprep", "struct",
    "subprocess", "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny",
    "tarfile", "telnetlib", "tempfile", "termios", "test", "textwrap", "threading",
    "time", "timeit", "tkinter", "token", "tokenize", "tomllib", "trace",
    "traceback", "tracemalloc", "tty", "turtle", "turtledemo", "types",
    "typing", "unicodedata", "unittest", "urllib", "uu", "uuid", "venv",
    "warnings", "wave", "weakref", "webbrowser", "winreg", "winsound", "wsgiref",
    "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    "_thread", "__future__",
}


@dataclass
class PackageInfo:
    """Information about a single PyPI package."""

    name: str
    installed_version: str = ""
    latest_version: str = ""
    installed_release_date: datetime | None = None
    latest_release_date: datetime | None = None
    months_behind: float = 0.0
    releases_per_month: float = 0.0  # velocity
    cve_count: int = 0
    dep_risk: float = 0.0


@dataclass
class FileDepData:
    """Dependency data for a single source file."""

    path: str
    imports: list[str] = field(default_factory=list)
    third_party_imports: list[str] = field(default_factory=list)
    packages: list[PackageInfo] = field(default_factory=list)
    dep_score: float = 0.0


class DepAnalyzer:
    """Analyze dependency staleness for a Python repository."""

    MAX_DEP_RISK = 50.0  # normalization ceiling

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path)
        self._installed_versions: dict[str, str] = {}
        self._package_cache: dict[str, PackageInfo] = {}
        self._local_modules: set[str] = set()

    def analyze(self) -> dict[str, FileDepData]:
        """
        Full dependency analysis pipeline.
        Returns dict of ``{file_path: FileDepData}``.
        """
        logger.info("DepAnalyzer: scanning %s …", self.repo_path)

        # Step 1: Parse installed versions
        self._installed_versions = self._parse_requirements()

        # Step 2: Discover local modules (to exclude from third-party)
        self._local_modules = self._discover_local_modules()

        # Step 3: Scan all Python files for imports
        results: dict[str, FileDepData] = {}
        python_files = list(self.repo_path.rglob("*.py"))

        for py_file in python_files:
            try:
                rel_path = str(py_file.relative_to(self.repo_path))
            except ValueError:
                rel_path = str(py_file)

            imports = self._extract_imports(py_file)
            third_party = self._filter_third_party(imports)

            fd = FileDepData(path=rel_path, imports=imports, third_party_imports=third_party)
            results[rel_path] = fd

        # Step 4: Query PyPI for all unique third-party packages
        all_packages: set[str] = set()
        for fd in results.values():
            for imp in fd.third_party_imports:
                pkg_name = self._import_to_package(imp)
                all_packages.add(pkg_name)

        for pkg_name in all_packages:
            if pkg_name not in self._package_cache:
                info = self._query_pypi(pkg_name)
                self._package_cache[pkg_name] = info

        # Step 5: Run pip-audit for CVEs
        cve_counts = self._run_pip_audit()
        for pkg_name, count in cve_counts.items():
            if pkg_name in self._package_cache:
                self._package_cache[pkg_name].cve_count = count

        # Step 6: Compute per-file dep scores
        for fd in results.values():
            risks: list[float] = []
            for imp in fd.third_party_imports:
                pkg_name = self._import_to_package(imp)
                info = self._package_cache.get(pkg_name)
                if info is None:
                    continue

                # dep_risk = months_behind * velocity * (1 + cve_count)
                risk = info.months_behind * info.releases_per_month * (1 + info.cve_count)
                info.dep_risk = risk
                risks.append(risk)
                fd.packages.append(info)

            if risks:
                mean_risk = sum(risks) / len(risks)
                fd.dep_score = min(mean_risk / self.MAX_DEP_RISK * 100, 100)

        logger.info("DepAnalyzer: analyzed %d files, %d unique packages", len(results), len(all_packages))
        return results

    # ---- requirements parsing -----------------------------------------------

    def _parse_requirements(self) -> dict[str, str]:
        """Parse requirements.txt or pyproject.toml for installed versions."""
        versions: dict[str, str] = {}

        # Try requirements.txt
        req_file = self.repo_path / "requirements.txt"
        if req_file.is_file():
            for line in req_file.read_text(errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                match = re.match(r"([a-zA-Z0-9_.-]+)\s*[=~><!]=?\s*([0-9][^\s,;]*)", line)
                if match:
                    versions[match.group(1).lower()] = match.group(2)

        # Try pyproject.toml
        pyproject = self.repo_path / "pyproject.toml"
        if pyproject.is_file():
            try:
                import sys
                if sys.version_info >= (3, 11):
                    import tomllib
                else:
                    import tomli as tomllib  # type: ignore
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                deps = data.get("project", {}).get("dependencies", [])
                for dep in deps:
                    match = re.match(r"([a-zA-Z0-9_.-]+)\s*[=~><!]=?\s*([0-9][^\s,;\"']*)", dep)
                    if match:
                        versions[match.group(1).lower()] = match.group(2)
            except Exception:
                logger.debug("Failed to parse pyproject.toml for deps")

        return versions

    # ---- import extraction --------------------------------------------------

    @staticmethod
    def _extract_imports(filepath: Path) -> list[str]:
        """Extract top-level import names from a Python file using AST."""
        try:
            source = filepath.read_text(errors="replace")
            tree = ast.parse(source, filename=str(filepath))
        except (SyntaxError, UnicodeDecodeError):
            return []

        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in imports:
                        imports.append(top)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top not in imports:
                        imports.append(top)
        return imports

    def _discover_local_modules(self) -> set[str]:
        """Discover local package names (directories with __init__.py or standalone .py)."""
        local: set[str] = set()
        for item in self.repo_path.iterdir():
            if item.is_dir() and (item / "__init__.py").exists():
                local.add(item.name)
            elif item.is_file() and item.suffix == ".py":
                local.add(item.stem)
        return local

    def _filter_third_party(self, imports: list[str]) -> list[str]:
        """Filter out stdlib and local imports, keeping only third-party."""
        return [
            imp
            for imp in imports
            if imp not in _STDLIB_MODULES and imp not in self._local_modules
        ]

    @staticmethod
    def _import_to_package(import_name: str) -> str:
        """Map an import name to its PyPI package name."""
        return _IMPORT_TO_PACKAGE.get(import_name, import_name).lower()

    # ---- PyPI queries -------------------------------------------------------

    def _query_pypi(self, package_name: str) -> PackageInfo:
        """Query the PyPI JSON API for release information."""
        info = PackageInfo(name=package_name)
        installed_ver = self._installed_versions.get(package_name, "")
        info.installed_version = installed_ver

        try:
            url = f"https://pypi.org/pypi/{package_name}/json"
            resp = httpx.get(url, timeout=10, follow_redirects=True)
            if resp.status_code != 200:
                logger.debug("PyPI returned %d for %s", resp.status_code, package_name)
                return info

            data = resp.json()
            info.latest_version = data.get("info", {}).get("version", "")

            # Parse release dates
            releases = data.get("releases", {})
            if not releases:
                return info

            # Get latest release date
            latest_ver = info.latest_version
            if latest_ver in releases and releases[latest_ver]:
                upload = releases[latest_ver][0].get("upload_time_iso_8601", "")
                if upload:
                    info.latest_release_date = datetime.fromisoformat(upload.replace("Z", "+00:00"))

            # Get installed release date
            if installed_ver and installed_ver in releases and releases[installed_ver]:
                upload = releases[installed_ver][0].get("upload_time_iso_8601", "")
                if upload:
                    info.installed_release_date = datetime.fromisoformat(upload.replace("Z", "+00:00"))

            # Compute months_behind
            if info.latest_release_date and info.installed_release_date:
                delta = info.latest_release_date - info.installed_release_date
                info.months_behind = max(delta.days / 30.44, 0)
            elif info.latest_release_date and installed_ver:
                # If we couldn't find exact version, estimate 6 months
                info.months_behind = 6.0

            # Compute velocity (releases per month)
            release_dates: list[datetime] = []
            for ver, files in releases.items():
                if files:
                    upload = files[0].get("upload_time_iso_8601", "")
                    if upload:
                        try:
                            release_dates.append(
                                datetime.fromisoformat(upload.replace("Z", "+00:00"))
                            )
                        except ValueError:
                            pass

            if len(release_dates) >= 2:
                release_dates.sort()
                span_months = max((release_dates[-1] - release_dates[0]).days / 30.44, 1)
                info.releases_per_month = len(release_dates) / span_months

        except Exception:
            logger.debug("Failed to query PyPI for %s", package_name, exc_info=True)

        return info

    # ---- pip-audit ----------------------------------------------------------

    def _run_pip_audit(self) -> dict[str, int]:
        """Run pip-audit and return a dict of {package_name: cve_count}."""
        counts: dict[str, int] = {}
        try:
            result = subprocess.run(
                ["pip-audit", "--format", "json", "--output", "-"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self.repo_path),
            )
            if result.returncode == 0 or result.stdout:
                data = json.loads(result.stdout) if result.stdout else []
                # pip-audit JSON output is a list of vulnerability objects
                if isinstance(data, dict):
                    vulns = data.get("dependencies", [])
                else:
                    vulns = data
                for entry in vulns:
                    pkg = entry.get("name", "").lower()
                    vuln_list = entry.get("vulns", [])
                    if pkg and vuln_list:
                        counts[pkg] = counts.get(pkg, 0) + len(vuln_list)
        except FileNotFoundError:
            logger.debug("pip-audit not installed, skipping CVE analysis")
        except Exception:
            logger.debug("pip-audit failed", exc_info=True)

        return counts
