"""
On-disk persistence for headless runs.

Each run owns one directory so an MCP process that restarts can still resume
work by run_id instead of relying on in-memory "last result" state:

    <runs_root>/<run_id>/
      manifest.json
      comments.json
      comments.csv
      analysis.json
      report.md
      assets/            (only when chart rendering is enabled)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.exporter.csv_exporter import CSVExporter
from src.service.models import ErrorCode, RunStatus, ServiceError
from src.service.paths import agent_runs_root

logger = logging.getLogger(__name__)

RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")

MANIFEST_NAME = "manifest.json"
COMMENTS_JSON = "comments.json"
COMMENTS_CSV = "comments.csv"
ANALYSIS_JSON = "analysis.json"
REPORT_MD = "report.md"
ASSETS_DIR = "assets"
ARCHIVE_DIR = "archive"


def new_run_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write via a sibling temp file and os.replace.

    A direct write leaves a truncated file if the process dies mid-write, and a
    half-written manifest.json turns the whole restart-recovery story into a
    NOT_FOUND. os.replace is atomic on both Windows and POSIX.
    """
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_dump_json(path: Path, obj: Any) -> None:
    """Stream-serialize JSON straight to the temp file.

    json.dumps followed by encode would hold both the full string and its
    bytes at once; a desktop crawl with no page ceiling can be tens of
    megabytes of comments, and this halves that peak.
    """
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            json.dump(obj, stream, ensure_ascii=False, indent=2, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


class RunStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root).resolve() if root is not None else agent_runs_root()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # -- path safety -------------------------------------------------------
    def run_dir(self, run_id: str, create: bool = False) -> Path:
        """Resolve a run directory, rejecting anything outside the store root.

        Two independent checks: the id must match the generated format, and the
        resolved path must still live under the root. Either alone would do;
        both together mean a bug in one cannot open a traversal.
        """
        candidate_id = str(run_id or "").strip()
        if not RUN_ID_RE.match(candidate_id):
            raise ServiceError(ErrorCode.INVALID_INPUT, f"run_id 格式不合法: {candidate_id!r}")
        path = (self._root / candidate_id).resolve()
        if self._root not in path.parents:
            raise ServiceError(ErrorCode.INVALID_INPUT, f"run_id 越界: {candidate_id!r}")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        elif not path.is_dir():
            raise ServiceError(ErrorCode.NOT_FOUND, f"找不到 run: {candidate_id}")
        return path

    # -- manifest ----------------------------------------------------------
    def create_run(self, run_id: str, kind: str, params: dict[str, Any]) -> Path:
        path = self.run_dir(run_id, create=True)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.write_manifest(
            run_id,
            {
                "run_id": run_id,
                "kind": kind,
                "status": RunStatus.QUEUED,
                "stage": "",
                "created_at": now,
                "params": sanitize_params(params),
                "counts": {},
                "artifacts": {},
                "warnings": [],
                "error": None,
                "error_code": None,
            },
        )
        return path

    def write_manifest(self, run_id: str, manifest: dict[str, Any]) -> None:
        path = self.run_dir(run_id, create=True) / MANIFEST_NAME
        payload = dict(manifest)
        payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload["params"] = sanitize_params(payload.get("params") or {})
        payload["artifacts"] = self._relative_artifacts(run_id, payload.get("artifacts") or {})
        _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))

    def _relative_artifacts(self, run_id: str, artifacts: dict[str, Any]) -> dict[str, str]:
        """Store artifact paths relative to the run directory.

        Absolute paths break the moment the run directory is copied to another
        machine or drive; consumers resolve them against run_dir() at read
        time, so the manifest itself stays portable.
        """
        try:
            base = self.run_dir(run_id)
        except ServiceError:
            return {str(k): str(v) for k, v in artifacts.items()}
        relative: dict[str, str] = {}
        for key, value in artifacts.items():
            text = str(value)
            candidate = Path(text)
            if candidate.is_absolute():
                try:
                    text = str(candidate.relative_to(base))
                except ValueError:
                    pass  # not under this run; keep the absolute path as-is
            relative[str(key)] = text
        return relative

    def read_manifest(self, run_id: str) -> dict[str, Any]:
        path = self.run_dir(run_id) / MANIFEST_NAME
        if not path.is_file():
            raise ServiceError(ErrorCode.NOT_FOUND, f"run 缺少 manifest: {run_id}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ServiceError(ErrorCode.NOT_FOUND, f"run manifest 无法读取: {run_id}") from exc

    def update_manifest(self, run_id: str, **changes: Any) -> dict[str, Any]:
        manifest = self.read_manifest(run_id)
        manifest.update(changes)
        self.write_manifest(run_id, manifest)
        return manifest

    # -- comments ----------------------------------------------------------
    def save_comments(self, run_id: str, comments: list[dict[str, Any]]) -> dict[str, str]:
        path = self.run_dir(run_id, create=True)
        json_path = path / COMMENTS_JSON
        _atomic_dump_json(json_path, comments)
        artifacts = {"comments_json": str(json_path)}

        # CSVExporter writes directly and swallows its own errors, so it is
        # pointed at a temp file and promoted only on success. That keeps the
        # whole run directory atomic, not just the JSON parts.
        csv_path = path / COMMENTS_CSV
        handle, temp_name = tempfile.mkstemp(dir=str(path), prefix=f".{COMMENTS_CSV}.", suffix=".tmp")
        os.close(handle)
        temp_path = Path(temp_name)
        try:
            if CSVExporter.export(comments, str(temp_path)):
                os.replace(temp_path, csv_path)
                artifacts["comments_csv"] = str(csv_path)
        finally:
            temp_path.unlink(missing_ok=True)
        return artifacts

    def load_comments(self, run_id: str) -> list[dict[str, Any]]:
        json_path = self.run_dir(run_id) / COMMENTS_JSON
        if not json_path.is_file():
            raise ServiceError(ErrorCode.NOT_FOUND, f"run {run_id} 尚无评论数据，请先完成爬取")
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ServiceError(ErrorCode.NOT_FOUND, f"run {run_id} 的评论数据损坏") from exc
        if not isinstance(data, list):
            raise ServiceError(ErrorCode.NOT_FOUND, f"run {run_id} 的评论数据格式异常")
        return data

    # -- analysis ----------------------------------------------------------
    def save_analysis(
        self, run_id: str, result: dict[str, Any], warnings: list[str] | None = None
    ) -> dict[str, str]:
        path = self.run_dir(run_id, create=True)
        self._archive_previous_analysis(path)
        payload = dict(result)
        artifacts: dict[str, str] = {}

        image_path, decode_failed = self._extract_word_cloud(path, payload)
        if image_path:
            artifacts["word_cloud_image"] = image_path
        elif decode_failed and warnings is not None:
            # A word cloud that cannot be decoded must not vanish silently:
            # the CSV half warns on the same kind of loss.
            warnings.append("词云图片解析失败，未写入 assets/word_cloud.png。")

        report = str(payload.pop("report_markdown", "") or "")
        if decode_failed:
            # The service renders the report before this decode happens, so a
            # broken data URL leaves behind an image link that will never
            # resolve. Drop it rather than shipping a dead reference.
            report = re.sub(r"!\[[^\]]*\]\(assets/word_cloud\.png\)\n?", "", report)
        if report:
            report_path = path / REPORT_MD
            _atomic_write_text(report_path, report)
            artifacts["report_markdown"] = str(report_path)

        analysis_path = path / ANALYSIS_JSON
        _atomic_dump_json(analysis_path, payload)
        artifacts["analysis_json"] = str(analysis_path)
        return artifacts

    @staticmethod
    def _archive_previous_analysis(run_path: Path) -> None:
        """Move a previous analysis out of the way instead of overwriting it.

        Fixed filenames mean a re-analysis would silently destroy the previous
        report; archiving keeps it comparable while the newest result keeps
        the canonical names the artifacts map points at.
        """
        stale = [
            run_path / ANALYSIS_JSON,
            run_path / REPORT_MD,
            run_path / ASSETS_DIR / "word_cloud.png",
        ]
        if not any(item.exists() for item in stale):
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = run_path / ARCHIVE_DIR / stamp
        dest.mkdir(parents=True, exist_ok=True)
        for item in stale:
            if item.is_file():
                # The archived report references its word cloud at
                # assets/word_cloud.png; mirroring that layout under dest/
                # keeps the archived copy self-contained.
                target = dest / ASSETS_DIR / item.name if item.parent.name == ASSETS_DIR else dest / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                item.replace(target)
        assets = run_path / ASSETS_DIR
        if assets.is_dir() and not any(assets.iterdir()):
            assets.rmdir()

    @staticmethod
    def _extract_word_cloud(run_path: Path, payload: dict[str, Any]) -> tuple[str, bool]:
        """Move a base64 data URL out of the JSON and onto disk.

        Word cloud rendering is off by default for agents, but if a caller turns
        it back on the data URL must not be inlined into analysis.json where it
        would balloon the file by several megabytes.

        Returns (image_path, decode_failed); a data URL was present but its
        payload was not valid base64 exactly when decode_failed is True.
        """
        data_url = str(payload.get("word_cloud_image") or "")
        if not data_url.startswith("data:image/"):
            return "", False
        try:
            raw = base64.b64decode(data_url.split(",", 1)[1])
        except (IndexError, ValueError):
            payload.pop("word_cloud_image", None)
            return "", True
        assets = run_path / ASSETS_DIR
        assets.mkdir(parents=True, exist_ok=True)
        image_path = assets / "word_cloud.png"
        _atomic_write_bytes(image_path, raw)
        payload["word_cloud_image"] = str(image_path)
        return str(image_path), False

    def load_analysis(self, run_id: str) -> dict[str, Any]:
        analysis_path = self.run_dir(run_id) / ANALYSIS_JSON
        if not analysis_path.is_file():
            raise ServiceError(ErrorCode.NOT_FOUND, f"run {run_id} 尚无分析结果")
        try:
            return json.loads(analysis_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ServiceError(ErrorCode.NOT_FOUND, f"run {run_id} 的分析结果损坏") from exc

    # -- misc --------------------------------------------------------------
    def artifacts(self, run_id: str) -> dict[str, str]:
        path = self.run_dir(run_id)
        known = {
            "comments_json": path / COMMENTS_JSON,
            "comments_csv": path / COMMENTS_CSV,
            "analysis_json": path / ANALYSIS_JSON,
            "report_markdown": path / REPORT_MD,
            "word_cloud_image": path / ASSETS_DIR / "word_cloud.png",
        }
        return {key: str(value) for key, value in known.items() if value.is_file()}

    def list_runs(self, limit: int = 20) -> list[str]:
        entries = [
            item.name
            for item in self._root.iterdir()
            if item.is_dir() and RUN_ID_RE.match(item.name)
        ]
        return sorted(entries, reverse=True)[:limit]

    def delete_run(self, run_id: str) -> None:
        """Remove a run directory entirely.

        The same double validation as run_dir() applies, so a crafted run_id
        cannot aim shutil.rmtree at anything outside the store root.
        """
        path = self.run_dir(run_id)  # raises NOT_FOUND for unknown/foreign ids
        shutil.rmtree(path)

    def prune_runs(self, keep: int, skip_run_ids: set[str] | None = None) -> list[str]:
        """Delete all but the newest `keep` runs, returning the removed ids.

        An explicit "how much history to keep" knob, so an unattended desktop
        or agent usage cannot accumulate run directories forever. Runs listed
        in skip_run_ids are treated as newest: deleting a run whose task is
        still writing would let the worker re-create the directory as a
        manifest-less zombie.
        """
        keep = max(0, int(keep))
        skip = set(skip_run_ids or ())
        removed: list[str] = []
        candidates = self.list_runs(limit=10**9)
        # Skipped runs are held back before slicing, so they never occupy a
        # "keep" slot either -- preserving a running run at the cost of
        # deleting one more old run surprises the caller far less than a
        # manifest-less zombie directory would.
        rest = [run_id for run_id in candidates if run_id not in skip]
        for run_id in rest[max(0, keep - len(skip)) :]:
            try:
                self.delete_run(run_id)
                removed.append(run_id)
            except (ServiceError, OSError):
                logger.warning("could not prune run %s", run_id)
        return removed


_SECRET_KEYS = {"api_key", "apikey", "key", "token", "secret", "password", "llm_config", "credentials"}


def sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Drop anything credential-shaped before it can reach the manifest."""
    clean: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if str(key).strip().lower() in _SECRET_KEYS:
            continue
        clean[key] = sanitize_params(value) if isinstance(value, dict) else value
    return clean
