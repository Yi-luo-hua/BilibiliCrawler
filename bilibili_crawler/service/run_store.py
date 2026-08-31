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
import copy
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from bilibili_crawler.exporter.csv_exporter import CSVExporter
from bilibili_crawler.service.credentials import scrub
from bilibili_crawler.service.models import ErrorCode, RunStatus, ServiceError
from bilibili_crawler.service.paths import agent_runs_root

logger = logging.getLogger(__name__)

RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")

MANIFEST_NAME = "manifest.json"
COMMENTS_JSON = "comments.json"
COMMENTS_CSV = "comments.csv"
ANALYSIS_JSON = "analysis.json"
REPORT_MD = "report.md"
ASSETS_DIR = "assets"
ARCHIVE_DIR = "archive"
ATTEMPTS_DIR = "analysis-attempts"
ATTEMPT_ID_RE = re.compile(r"^(?:task|legacy)-[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
ANALYSIS_KEYS = ("analysis_json", "report_markdown", "word_cloud_image")


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


def _scrub_json_value(value: Any, memo: dict[int, Any] | None = None) -> Any:
    """Scrub registered secrets without materialising the encoded JSON text."""
    if isinstance(value, str):
        return scrub(value)
    if memo is None:
        memo = {}
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if isinstance(value, dict):
        clean: dict[Any, Any] = {}
        memo[identity] = clean
        for key, item in value.items():
            clean[_scrub_json_value(key, memo)] = _scrub_json_value(item, memo)
        return clean
    if isinstance(value, list):
        clean_list: list[Any] = []
        memo[identity] = clean_list
        clean_list.extend(_scrub_json_value(item, memo) for item in value)
        return clean_list
    if isinstance(value, tuple):
        clean_tuple: list[Any] = []
        memo[identity] = clean_tuple
        clean_tuple.extend(_scrub_json_value(item, memo) for item in value)
        return clean_tuple
    return value


def _atomic_dump_json(path: Path, obj: Any, *, scrub_secrets: bool = False) -> None:
    """Stream-serialize JSON straight to the temp file.

    json.dumps followed by encode would hold both the full string and its
    bytes at once; a desktop crawl with no page ceiling can be tens of
    megabytes of comments, and this halves that peak.
    """
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            payload = _scrub_json_value(obj) if scrub_secrets else obj
            fallback = (lambda value: scrub(str(value))) if scrub_secrets else str
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=fallback)
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
        now = datetime.now().isoformat(sep=" ", timespec="microseconds")
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
        payload = copy.deepcopy(manifest)
        payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload["params"] = sanitize_params(payload.get("params") or {})
        payload["artifacts"] = self._relative_artifacts(run_id, payload.get("artifacts") or {})
        for record in [payload.get("current_analysis"), *(payload.get("analysis_attempts") or [])]:
            if isinstance(record, dict):
                record["artifacts"] = self._relative_artifacts(run_id, record.get("artifacts") or {})
        _atomic_write_text(path, json.dumps(_scrub_json_value(payload), ensure_ascii=False, indent=2))

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
    def _attempt_dir(self, run_id: str, attempt_id: str) -> Path:
        if not ATTEMPT_ID_RE.fullmatch(attempt_id):
            raise ServiceError(ErrorCode.INVALID_INPUT, "analysis attempt_id 格式不合法")
        root = self.run_dir(run_id)
        path = (root / ATTEMPTS_DIR / attempt_id).resolve()
        if root not in path.parents:
            raise ServiceError(ErrorCode.INVALID_INPUT, "analysis attempt_id 越界")
        return path

    def save_analysis(
        self, run_id: str, result: dict[str, Any], warnings: list[str] | None = None,
        *, attempt_id: str | None = None,
    ) -> dict[str, str]:
        path = self.run_dir(run_id, create=True)
        if attempt_id is None and (path / MANIFEST_NAME).is_file():
            manifest = self.read_manifest(run_id)
            if manifest.get("schema_version") == 2:
                # Preserve direct save_analysis callers after a run is upgraded:
                # they must publish a version, not only overwrite stale aliases.
                started = datetime.now().isoformat(timespec="microseconds")
                generated_id = "task-" + new_run_id()
                artifacts = RunStore.save_analysis(
                    self, run_id, result, warnings, attempt_id=generated_id,
                )
                attempt = dict(attempt_id=generated_id, started_at=started,
                               finished_at=datetime.now().isoformat(timespec="microseconds"),
                               status=RunStatus.COMPLETED, stage="分析完成", artifacts=artifacts,
                               counts=dict(manifest.get("counts") or {}), summary=scrub(result.get("summary")),
                               warnings=list(warnings or []), error=None, error_code=None)
                self.update_analysis_attempt(run_id, attempt)
                alias_warnings = self.refresh_analysis_aliases(run_id, generated_id, artifacts)
                if warnings is not None:
                    warnings.extend(alias_warnings)
                return artifacts
        destination = self._attempt_dir(run_id, attempt_id) if attempt_id else path
        stage = Path(tempfile.mkdtemp(dir=str(path), prefix=".analysis-stage-"))
        try:
            payload = dict(result)
            artifacts: dict[str, str] = {}

            staged_image, decode_failed = self._extract_word_cloud(stage, payload)
            if staged_image:
                final_image = destination / ASSETS_DIR / "word_cloud.png"
                payload["word_cloud_image"] = str(final_image)
                artifacts["word_cloud_image"] = str(final_image)
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
                _atomic_write_text(stage / REPORT_MD, scrub(report))
                artifacts["report_markdown"] = str(destination / REPORT_MD)

            _atomic_dump_json(stage / ANALYSIS_JSON, payload, scrub_secrets=True)
            artifacts["analysis_json"] = str(destination / ANALYSIS_JSON)
            if attempt_id:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    raise ServiceError(ErrorCode.INVALID_INPUT, "analysis attempt 已保存，不允许覆盖")
                stage.rename(destination)
            else:
                self._commit_staged_analysis(path, stage)
            return artifacts
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _resolve_analysis_artifacts(self, run_id: str, artifacts: dict[str, Any]) -> dict[str, str]:
        root = self.run_dir(run_id)
        resolved: dict[str, str] = {}
        for key in ANALYSIS_KEYS:
            if key not in artifacts:
                continue
            path = (root / str(artifacts[key])).resolve()
            if root not in path.parents:
                raise ServiceError(ErrorCode.INVALID_INPUT, "analysis artifact 路径越界")
            if not path.is_file():
                raise ServiceError(ErrorCode.NOT_FOUND, "analysis artifact 缺失，不能读取完整版本")
            resolved[key] = str(path)
        return resolved

    def _legacy_analysis(self, run_id: str, manifest: dict[str, Any]) -> dict[str, Any] | None:
        """Copy a pre-v2 report before its canonical names can be replaced."""
        path = self.run_dir(run_id)
        if (manifest.get("schema_version") == 2 or manifest.get("status") != RunStatus.COMPLETED
                or not (path / ANALYSIS_JSON).is_file()):
            return None
        result = json.loads((path / ANALYSIS_JSON).read_text(encoding="utf-8"))
        if (path / REPORT_MD).is_file():
            result["report_markdown"] = (path / REPORT_MD).read_text(encoding="utf-8")
        if (path / ASSETS_DIR / "word_cloud.png").is_file():
            result["word_cloud_image"] = "data:image/png;base64," + base64.b64encode(
                (path / ASSETS_DIR / "word_cloud.png").read_bytes()).decode("ascii")
        attempt_id = "legacy-" + new_run_id()
        # Call the base implementation: this is an import, not a new processor
        # result passed through custom store transformations a second time.
        artifacts = RunStore.save_analysis(self, run_id, result, attempt_id=attempt_id)
        return {"attempt_id": attempt_id, "artifacts": artifacts,
                "counts": dict(manifest.get("counts") or {}), "summary": scrub(result.get("summary")),
                "finished_at": manifest.get("updated_at", ""), "warnings": list(manifest.get("warnings") or [])}

    def update_analysis_attempt(self, run_id: str, attempt: dict[str, Any], **changes: Any) -> bool:
        """Publish one complete version with a single atomic manifest replace."""
        manifest = self.read_manifest(run_id)
        current = manifest.get("current_analysis") or self._legacy_analysis(run_id, manifest)
        attempts = list(manifest.get("analysis_attempts") or [])
        for index, previous in enumerate(attempts):
            if previous["attempt_id"] == attempt["attempt_id"]:
                attempts[index] = attempt
                break
        else:
            attempts.append(attempt)
        if attempt["status"] == RunStatus.COMPLETED and attempt["artifacts"]:
            current = {key: copy.deepcopy(attempt[key]) for key in (
                "attempt_id", "artifacts", "counts", "summary", "finished_at", "warnings")}
        if current:
            artifacts = {key: value for key, value in (manifest.get("artifacts") or {}).items()
                         if key not in ANALYSIS_KEYS}
            artifacts.update(current["artifacts"])
            changes.update(status=RunStatus.COMPLETED, stage="分析完成", counts=current["counts"],
                           artifacts=artifacts, error=None, error_code=None, warnings=current["warnings"])
        self.update_manifest(run_id, **changes, schema_version=2,
                             current_analysis=current, analysis_attempts=attempts)
        return not current or current["attempt_id"] == attempt["attempt_id"]

    def refresh_analysis_aliases(
        self, run_id: str, attempt_id: str, artifacts: dict[str, str],
    ) -> list[str]:
        """Refresh compatibility copies without undoing a published result.

        Record a refresh failure against the same attempt so restart queries
        retain the warning. This only annotates metadata; it never republishes
        a version or retries the failed copy operation.
        """
        try:
            self.sync_analysis_aliases(run_id, artifacts)
            return []
        except (OSError, ServiceError):
            warning = "根目录兼容副本刷新失败；请使用 artifacts 指向的完整分析版本。"
        warnings = [warning]
        try:
            manifest = self.read_manifest(run_id)
            attempts = manifest.get("analysis_attempts") or []
            current = manifest.get("current_analysis") or {}
            records = [record for record in attempts if record.get("attempt_id") == attempt_id]
            if current.get("attempt_id") == attempt_id:
                records.extend([current, manifest])
            elif not current and attempts and attempts[-1].get("attempt_id") == attempt_id:
                records.append(manifest)
            for record in records:
                existing = list(record.get("warnings") or [])
                if warning not in existing:
                    existing.append(warning)
                record["warnings"] = existing
            if records:
                self.write_manifest(run_id, manifest)
        except (OSError, ServiceError) as exc:
            logger.warning("could not persist alias warning for run %s: %s", run_id, scrub(exc))
            warnings.append("兼容副本警告未能写入运行记录。")
        return warnings

    def sync_analysis_aliases(self, run_id: str, artifacts: dict[str, str]) -> None:
        """Best-effort compatibility copies, never the authoritative reader path."""
        path = self.run_dir(run_id)
        stage = Path(tempfile.mkdtemp(dir=str(path), prefix=".analysis-alias-"))
        try:
            names = {"analysis_json": Path(ANALYSIS_JSON), "report_markdown": Path(REPORT_MD),
                     "word_cloud_image": Path(ASSETS_DIR) / "word_cloud.png"}
            for key, source in self._resolve_analysis_artifacts(run_id, artifacts).items():
                target = stage / names[key]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            self._commit_staged_analysis(path, stage)
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    @staticmethod
    def _commit_staged_analysis(run_path: Path, stage: Path) -> None:
        """Archive the old result and install a fully staged replacement.

        Nothing under the canonical names changes until every new artifact has
        been written successfully. If a move still fails during commit, restore
        the old files and remove the partially installed replacement.
        """
        stale = [
            run_path / ANALYSIS_JSON,
            run_path / REPORT_MD,
            run_path / ASSETS_DIR / "word_cloud.png",
        ]
        archive: Path | None = None
        moved_old: list[tuple[Path, Path]] = []
        installed: list[Path] = []
        try:
            if any(item.is_file() for item in stale):
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                archive = run_path / ARCHIVE_DIR / stamp
                archive.mkdir(parents=True, exist_ok=True)
                for item in stale:
                    if item.is_file():
                        relative = Path(ASSETS_DIR) / item.name if item.parent.name == ASSETS_DIR else Path(item.name)
                        target = archive / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        item.replace(target)
                        moved_old.append((target, item))
                        if target.name in {ANALYSIS_JSON, REPORT_MD}:
                            _atomic_write_text(target, scrub(target.read_text(encoding="utf-8")))

            for relative in (Path(REPORT_MD), Path(ASSETS_DIR) / "word_cloud.png", Path(ANALYSIS_JSON)):
                source = stage / relative
                if source.is_file():
                    target = run_path / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source.replace(target)
                    installed.append(target)
        except BaseException:
            for target in reversed(installed):
                target.unlink(missing_ok=True)
            for archived, original in reversed(moved_old):
                original.parent.mkdir(parents=True, exist_ok=True)
                archived.replace(original)
            if archive is not None:
                for directory in (archive / ASSETS_DIR, archive):
                    if directory.is_dir() and not any(directory.iterdir()):
                        directory.rmdir()
            raise

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
            raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        except (IndexError, ValueError):
            payload.pop("word_cloud_image", None)
            return "", True
        try:
            with Image.open(BytesIO(raw)) as image:
                if image.format != "PNG":
                    raise ValueError("word cloud payload is not PNG")
                image.verify()
        except (Image.DecompressionBombError, OSError, SyntaxError, ValueError):
            payload.pop("word_cloud_image", None)
            return "", True
        assets = run_path / ASSETS_DIR
        assets.mkdir(parents=True, exist_ok=True)
        image_path = assets / "word_cloud.png"
        _atomic_write_bytes(image_path, raw)
        payload["word_cloud_image"] = str(image_path)
        return str(image_path), False

    def load_analysis(self, run_id: str) -> dict[str, Any]:
        artifacts = self.artifacts(run_id)
        saved_path = artifacts.get("analysis_json")
        if not saved_path:
            raise ServiceError(ErrorCode.NOT_FOUND, f"run {run_id} 尚无分析结果")
        analysis_path = Path(saved_path)
        if not analysis_path.is_file():
            raise ServiceError(ErrorCode.NOT_FOUND, f"run {run_id} 尚无分析结果")
        try:
            result = json.loads(analysis_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ServiceError(ErrorCode.NOT_FOUND, f"run {run_id} 的分析结果损坏") from exc
        if not isinstance(result, dict):
            raise ServiceError(ErrorCode.NOT_FOUND, f"run {run_id} 的分析结果格式异常")
        if "word_cloud_image" in artifacts:
            result["word_cloud_image"] = artifacts["word_cloud_image"]
        return result

    # -- misc --------------------------------------------------------------
    def artifacts(self, run_id: str, *, manifest: dict[str, Any] | None = None) -> dict[str, str]:
        path = self.run_dir(run_id)
        known = {
            "comments_json": path / COMMENTS_JSON,
            "comments_csv": path / COMMENTS_CSV,
            "analysis_json": path / ANALYSIS_JSON,
            "report_markdown": path / REPORT_MD,
            "word_cloud_image": path / ASSETS_DIR / "word_cloud.png",
        }
        found = {key: str(value) for key, value in known.items() if value.is_file()}
        manifest = manifest if manifest is not None else self.read_manifest(run_id)
        if manifest.get("schema_version") == 2:
            current = manifest.get("current_analysis") or {}
            reference = current.get("artifacts") if current else manifest.get("artifacts")
            found = {key: value for key, value in found.items() if key not in ANALYSIS_KEYS}
            found.update(self._resolve_analysis_artifacts(run_id, reference or {}))
        return found

    def _run_created_at(self, run_id: str) -> datetime:
        try:
            value = str(self.read_manifest(run_id).get("created_at") or "")
            return datetime.fromisoformat(value).replace(tzinfo=None)
        except (ServiceError, TypeError, ValueError):
            try:
                return datetime.strptime(run_id[:15], "%Y%m%d-%H%M%S")
            except ValueError:
                return datetime.min

    def list_runs(self, limit: int = 20) -> list[str]:
        entries = [
            item.name
            for item in self._root.iterdir()
            if item.is_dir() and RUN_ID_RE.match(item.name)
        ]
        return sorted(
            entries,
            key=lambda run_id: (self._run_created_at(run_id), run_id),
            reverse=True,
        )[:limit]

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
        # Keep the requested newest runs, then protect active runs in addition
        # to that quota. An old active run must not evict newer completed
        # history merely because it cannot safely be deleted yet.
        retained = set(candidates[:keep]) | skip
        if keep and len(candidates) >= keep:
            cutoff = self._run_created_at(candidates[keep - 1])
            retained.update(
                run_id
                for run_id in candidates[keep:]
                if self._run_created_at(run_id) == cutoff
            )
        for run_id in candidates:
            if run_id in retained:
                continue
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
