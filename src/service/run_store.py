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
import os
import re
import secrets
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.exporter.csv_exporter import CSVExporter
from src.service.credentials import scrub
from src.service.models import ErrorCode, RunStatus, ServiceError
from src.service.paths import agent_runs_root

RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")

MANIFEST_NAME = "manifest.json"
COMMENTS_JSON = "comments.json"
COMMENTS_CSV = "comments.csv"
ANALYSIS_JSON = "analysis.json"
REPORT_MD = "report.md"
ASSETS_DIR = "assets"


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
        _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))

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
        _atomic_write_text(json_path, json.dumps(comments, ensure_ascii=False, indent=2))
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
    def save_analysis(self, run_id: str, result: dict[str, Any]) -> dict[str, str]:
        path = self.run_dir(run_id, create=True)
        payload = dict(result)
        artifacts: dict[str, str] = {}

        image_path = self._extract_word_cloud(path, payload)
        if image_path:
            artifacts["word_cloud_image"] = image_path

        report = str(payload.pop("report_markdown", "") or "")
        if report:
            report_path = path / REPORT_MD
            _atomic_write_text(report_path, scrub(report))
            artifacts["report_markdown"] = str(report_path)

        analysis_path = path / ANALYSIS_JSON
        _atomic_write_text(
            analysis_path, scrub(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        )
        artifacts["analysis_json"] = str(analysis_path)
        return artifacts

    @staticmethod
    def _extract_word_cloud(run_path: Path, payload: dict[str, Any]) -> str:
        """Move a base64 data URL out of the JSON and onto disk.

        Word cloud rendering is off by default for agents, but if a caller turns
        it back on the data URL must not be inlined into analysis.json where it
        would balloon the file by several megabytes.
        """
        data_url = str(payload.get("word_cloud_image") or "")
        if not data_url.startswith("data:image/"):
            return ""
        try:
            raw = base64.b64decode(data_url.split(",", 1)[1])
        except (IndexError, ValueError):
            payload.pop("word_cloud_image", None)
            return ""
        assets = run_path / ASSETS_DIR
        assets.mkdir(parents=True, exist_ok=True)
        image_path = assets / "word_cloud.png"
        _atomic_write_bytes(image_path, raw)
        payload["word_cloud_image"] = str(image_path)
        return str(image_path)

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


_SECRET_KEYS = {"api_key", "apikey", "key", "token", "secret", "password", "llm_config", "credentials"}


def sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Drop anything credential-shaped before it can reach the manifest."""
    clean: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if str(key).strip().lower() in _SECRET_KEYS:
            continue
        clean[key] = sanitize_params(value) if isinstance(value, dict) else value
    return clean
