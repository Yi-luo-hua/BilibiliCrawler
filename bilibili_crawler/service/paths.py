"""
Output directory resolution, shared by the desktop sidecar and the agent service.

Source checkouts keep their existing project output. Installed packages and
frozen applications use platform user directories, never site-packages/cwd.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_CHECKOUT = (
    not getattr(sys, "frozen", False)
    and (ROOT / "pyproject.toml").is_file()
    and (ROOT / "desktop" / "src-tauri" / "Cargo.toml").is_file()
    and (ROOT / "backend" / "agent.py").is_file()
)

PRODUCT_DIR_NAME = "BilibiliCrawler"
RUNS_DIR_NAME = "analysis-runs"
ASSETS_DIR_NAME = "analysis-assets"
RUNS_DIR_ENV = "BILIBILI_AGENT_RUNS_DIR"


def _absolute_env(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    candidate = Path(value).expanduser() if value else default
    return candidate if candidate.is_absolute() else default


def user_data_bases() -> list[Path]:
    """Pure path calculation; diagnostics must not create directories."""
    home = Path.home()
    if sys.platform == "win32":
        fallback = home / "AppData" / "Local" / PRODUCT_DIR_NAME
        preferred = _absolute_env("LOCALAPPDATA", home / "AppData" / "Local") / PRODUCT_DIR_NAME
        return list(dict.fromkeys((preferred, fallback)))
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / PRODUCT_DIR_NAME]
    return [_absolute_env("XDG_DATA_HOME", home / ".local" / "share") / "bilibili-crawler"]


def user_config_dir() -> Path:
    if sys.platform in {"win32", "darwin"}:
        return user_data_bases()[0] / "config"
    return _absolute_env("XDG_CONFIG_HOME", Path.home() / ".config") / "bilibili-crawler"


def user_cache_dir() -> Path:
    if sys.platform == "win32":
        return user_data_bases()[0] / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / PRODUCT_DIR_NAME
    return _absolute_env("XDG_CACHE_HOME", Path.home() / ".cache") / "bilibili-crawler"


def configure_matplotlib_cache() -> None:
    # Matplotlib creates this directory lazily. Preserve an explicit override.
    if not os.environ.get("MPLCONFIGDIR"):
        os.environ["MPLCONFIGDIR"] = str(user_cache_dir() / "matplotlib")


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

    probe = Path(name)
    try:
        os.close(handle)
    except OSError:
        # Already closed or invalid; removal below still decides the verdict.
        pass
    try:
        probe.unlink(missing_ok=True)
    except (OSError, PermissionError):
        # A directory we cannot clean up after is not one to write into: an
        # antivirus scanner holding the file, or a directory that denies
        # deletes, would otherwise raise out of here instead of falling back,
        # and leave the probe behind.
        return False
    return True


def candidate_bases() -> list[Path]:
    """Bases to try, most preferred first."""
    # In a PyInstaller build ROOT points inside sidecar/_internal. That bundle
    # is replaced during upgrades and removed during uninstall, so user output
    # must never be created there even when it happens to be writable.
    bases = [ROOT] if SOURCE_CHECKOUT and not getattr(sys, "frozen", False) else []
    bases.extend(user_data_bases())
    return bases


def _migrate_frozen_output(name: str, target: Path) -> None:
    """Copy legacy PyInstaller output into stable storage without overwrites."""
    if not getattr(sys, "frozen", False):
        return
    legacy = ROOT / name
    try:
        if not legacy.is_dir() or legacy.resolve() == target.resolve():
            return
        sources = list(legacy.iterdir())
    except OSError:
        return

    for source in sources:
        staging = None
        try:
            if not source.is_dir():
                continue
            destination = target / source.name
            if destination.exists():
                continue
            staging = Path(tempfile.mkdtemp(dir=target, prefix=f".migrate-{source.name}-"))
            shutil.copytree(source, staging, dirs_exist_ok=True)
            if not destination.exists():
                staging.rename(destination)
        except OSError:
            # The legacy copy remains untouched and can be retried next start.
            pass
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)


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
            _migrate_frozen_output(name, target)
            return target
    # Nothing was writable; hand back the last resort so the caller surfaces a
    # real error at write time rather than a confusing empty path.
    return bases[-1] / name


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
