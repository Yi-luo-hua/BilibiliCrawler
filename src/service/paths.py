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

PRODUCT_DIR_NAME = "BilibiliCrawler"
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


def candidate_bases() -> list[Path]:
    """Bases to try, most preferred first."""
    bases = [ROOT]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        bases.append(Path(local_app_data) / PRODUCT_DIR_NAME)
    bases.append(Path.home() / "AppData" / "Local" / PRODUCT_DIR_NAME)
    return bases


def output_dir(name: str) -> Path:
    """Return the first base where `name` itself is writable.

    The probe targets the output directory, not its parent. On Windows an
    existing subdirectory can carry an ACL its parent does not, so a writable
    project root is no guarantee that analysis-assets/ inside it can be written
    -- checking only the parent would pick a directory that then fails on
    export instead of falling back to %LOCALAPPDATA%.
    """
    bases = candidate_bases()
    for base in bases:
        target = base / name
        if _is_writable(target):
            return target
    # Nothing was writable; hand back the last resort so the caller surfaces a
    # real error at write time rather than a confusing empty path.
    return bases[-1] / name


def user_output_root() -> Path:
    """Return the base directory that holds the output directories.

    Prefer output_dir(): this reports the base only, so it cannot account for a
    subdirectory whose permissions differ from its parent.
    """
    bases = candidate_bases()
    for base in bases:
        if _is_writable(base):
            return base
    return bases[-1]


def agent_runs_root() -> Path:
    """Return the directory that holds one sub-directory per run."""
    override = os.environ.get(RUNS_DIR_ENV, "").strip()
    if override:
        root = Path(override).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root.resolve()
    return output_dir(RUNS_DIR_NAME).resolve()


def analysis_assets_root() -> Path:
    """Return the directory holding the desktop app's per-analysis asset dirs.

    Used by backend/sidecar.py via Sidecar._analysis_asset_root.
    """
    return output_dir(ASSETS_DIR_NAME)
