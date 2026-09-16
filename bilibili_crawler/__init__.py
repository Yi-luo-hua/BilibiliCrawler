# B站评论爬虫工具
"""Package metadata shared by the CLI, the MCP server and diagnostics.

Version resolution is deliberately lazy. importlib.metadata.version() scans
sys.path for dist-info and measured ~280ms in an installed venv; paying that on
every `import bilibili_crawler.*` would put it on the desktop sidecar's startup
path, which needs the version for nothing.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

__all__ = ["__version__", "resolve_version"]

UNKNOWN_VERSION = "0.0.0+unknown"


def _checkout_version() -> str:
    """Read Cargo's package.version, which setup.py treats as the authority.

    A regex keeps this free of tomllib (absent on 3.10) without adding a
    runtime dependency. Only a line that starts with `version` matches, so the
    inline `{ version = "2" }` of a dependency table cannot win: in a Cargo
    manifest the first such line is [package]'s.
    """
    root = Path(__file__).resolve().parents[1]
    if not (root / "pyproject.toml").is_file():
        return ""
    try:
        text = (root / "desktop" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        match = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if match:
            return match.group(1)
    return ""


@lru_cache(maxsize=1)
def resolve_version() -> str:
    """Report this build's version.

    A source checkout answers from Cargo.toml first: an unrelated installed
    copy of the distribution must not make the checkout report its number.
    Installed builds carry what setup.py derived at build time, so their
    distribution metadata is authoritative.
    """
    checkout = _checkout_version()
    if checkout:
        return checkout
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("bilibili-crawler")
        except PackageNotFoundError:
            return UNKNOWN_VERSION
    except Exception:  # noqa: BLE001 - metadata must never break an import
        return UNKNOWN_VERSION


def __getattr__(name: str) -> str:
    """Resolve `bilibili_crawler.__version__` on first access, not on import."""
    if name == "__version__":
        return resolve_version()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
