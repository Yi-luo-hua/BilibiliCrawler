"""
Output directory resolution, shared by the desktop sidecar and the agent service.

One policy, in one place: prefer the project root so users can find their files,
and fall back to %LOCALAPPDATA% for installed layouts where the project root is
not writable. Both front ends resolve through here, so the desktop app's assets
and the agent's runs land side by side and the two cannot drift apart.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RUNS_DIR_NAME = "analysis-runs"
ASSETS_DIR_NAME = "analysis-assets"
RUNS_DIR_ENV = "BILIBILI_AGENT_RUNS_DIR"


def _is_writable(candidate: Path) -> bool:
    """Probe writability with a unique, exclusively-created temp file.

    A fixed probe name would delete a real file that happened to share it, and
    two processes probing at once would delete each other's probe.
    """
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(dir=str(candidate), prefix=".write-probe-")
    except (OSError, PermissionError):
        return False
    os.close(handle)
    Path(name).unlink(missing_ok=True)
    return True


def user_output_root() -> Path:
    """Return the writable directory that holds agent output directories."""
    candidate = ROOT
    if _is_writable(candidate):
        return candidate

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "BilibiliCrawler"
    return Path.home() / "AppData" / "Local" / "BilibiliCrawler"


def agent_runs_root() -> Path:
    """Return the directory that holds one sub-directory per run."""
    override = os.environ.get(RUNS_DIR_ENV, "").strip()
    root = Path(override).expanduser() if override else user_output_root() / RUNS_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def analysis_assets_root() -> Path:
    """Return the directory holding the desktop app's per-analysis asset dirs.

    Used by backend/sidecar.py via Sidecar._analysis_asset_root.
    """
    root = user_output_root() / ASSETS_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root
