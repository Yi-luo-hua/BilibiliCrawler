"""
Output directory resolution for headless agent runs.

The policy intentionally mirrors ``Sidecar._analysis_asset_root`` in
backend/sidecar.py: prefer the project root so users can find their files, and
fall back to %LOCALAPPDATA% for installed layouts where the project root is not
writable. Keeping both roots identical means the desktop app and the agent drop
their output side by side instead of in two unrelated places.

TODO(v3.3.0): collapse this and Sidecar._analysis_asset_root into one helper
once the sidecar is migrated onto AgentService.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RUNS_DIR_NAME = "analysis-runs"
RUNS_DIR_ENV = "BILIBILI_AGENT_RUNS_DIR"


def _is_writable(candidate: Path) -> bool:
    """Probe writability with a unique, exclusively-created temp file.

    A fixed probe name (as in Sidecar._analysis_asset_root) would delete a real
    file that happened to share the name, and two processes probing at once
    would delete each other's probe.
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
