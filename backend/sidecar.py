"""
JSON-line sidecar for the Tauri desktop shell.

Requests arrive on stdin:
{"id":"...","method":"comments.start","params":{...}}

Events and responses are written to stdout as one JSON object per line.
Logging goes to stderr so it never corrupts the protocol stream.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import qrcode

from src.api.bilibili_api import BilibiliAPI
from src.crawler.comment_crawler import CommentCrawler
from src.crawler.dynamic_crawler import DynamicCrawler
from src.exporter.csv_exporter import CSVExporter
from src.processor.analysis_processor import AnalysisCancelled, AnalysisError, LLMAnalysisProcessor
from src.processor.data_processor import DataProcessor
from utils.helpers import ContentType, extract_uid, parse_input

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sidecar")


class Sidecar:
    def __init__(self) -> None:
        self._write_lock = threading.Lock()
        self._task_lock = threading.Lock()
        self._qr_cancel = threading.Event()
        self._analysis_cancel = threading.Event()
        self._active_crawler: CommentCrawler | DynamicCrawler | None = None
        self._active_thread: threading.Thread | None = None
        self._qr_thread: threading.Thread | None = None
        self._api = BilibiliAPI()
        self._logged_in = False
        self._last_comments: list[dict[str, Any]] = []
        self._last_dynamics: list[dict[str, Any]] = []
        self._last_analysis: dict[str, Any] | None = None
        self._last_comment_context: dict[str, str] = {}
        self._responses: "queue.Queue[dict[str, Any]]" = queue.Queue()

    def emit(self, event: str, **payload: Any) -> None:
        self._send({"kind": "event", "event": event, **payload})

    def respond(self, request_id: Any, ok: bool = True, **payload: Any) -> None:
        self._send({"kind": "response", "id": request_id, "ok": ok, **payload})

    def _send(self, payload: dict[str, Any]) -> None:
        with self._write_lock:
            print(json.dumps(payload, ensure_ascii=True, default=str), flush=True)

    def handle(self, request: dict[str, Any]) -> None:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        try:
            if method == "session.status":
                self.respond(
                    request_id,
                    logged_in=self._logged_in,
                    task_running=self._is_task_running(),
                )
            elif method == "comments.start":
                self._start_task(request_id, "comments", params, self._run_comments)
            elif method == "dynamics.start":
                if params.get("uid") is None and not self._logged_in:
                    raise RuntimeError("爬取关注页动态流需要先扫码登录")
                self._start_task(request_id, "dynamics", params, self._run_dynamics)
            elif method == "task.stop":
                active_mode = self._active_thread.name if self._active_thread is not None else "comments"
                is_analysis = active_mode == "analysis"
                self._stop_task()
                self.respond(request_id)
                self.emit("log", message="正在停止分析任务..." if is_analysis else "正在停止爬取任务...")
                self.emit("progress", status="stopping", mode=active_mode, percent=0)
            elif method == "qr.login.start":
                self._start_qr_login(request_id)
            elif method == "qr.login.cancel":
                self._qr_cancel.set()
                self.respond(request_id)
            elif method == "export.csv":
                self._export_csv(request_id, params)
            elif method == "analysis.start":
                self._start_task(request_id, "analysis", params, self._run_analysis)
            elif method == "analysis.latest":
                if not self._last_analysis:
                    raise RuntimeError("暂无分析结果")
                self.respond(request_id, result=self._display_analysis_result(self._last_analysis))
            elif method == "analysis.export":
                self._export_analysis(request_id, params)
            else:
                raise ValueError(f"未知请求方法: {method}")
        except Exception as exc:
            logger.exception("request failed")
            self.respond(request_id, ok=False, error=str(exc))
            self.emit("error", message=str(exc))

    def _is_task_running(self) -> bool:
        return bool(self._active_thread and self._active_thread.is_alive())

    def _start_task(
        self,
        request_id: Any,
        name: str,
        params: dict[str, Any],
        runner: Callable[[dict[str, Any]], None],
    ) -> None:
        with self._task_lock:
            if self._is_task_running():
                raise RuntimeError("已有任务正在运行")
            thread = threading.Thread(target=runner, args=(params,), daemon=True, name=name)
            self._active_thread = thread
            self.respond(request_id)
            self.emit("progress", status="running", mode=name, percent=0)
            task_label = {"comments": "评论", "dynamics": "动态", "analysis": "分析"}.get(name, name)
            self.emit("log", message=f"{task_label}任务已启动")
            thread.start()

    def _stop_task(self) -> None:
        crawler = self._active_crawler
        if crawler:
            crawler.stop()
            return
        active_mode = self._active_thread.name if self._active_thread is not None else ""
        if active_mode == "analysis":
            self._analysis_cancel.set()

    def _make_progress_callback(self, mode: str, max_pages: int) -> Callable[[str], None]:
        def callback(message: str) -> None:
            self.emit("log", message=message)
            match = re.search(r"第\s*(\d+)\s*页", message)
            if not match or max_pages <= 0:
                return
            current_page = max(1, int(match.group(1)))
            percent = min(99, max(1, int(current_page / max_pages * 100)))
            self.emit("progress", status="running", mode=mode, percent=percent)

        return callback

    def _run_comments(self, params: dict[str, Any]) -> None:
        try:
            max_pages = int(params.get("max_pages", 100))
            target_input = str(params.get("input") or "")
            crawler = CommentCrawler(progress_callback=self._make_progress_callback("comments", max_pages))
            crawler.api = self._api
            self._active_crawler = crawler
            comments = crawler.crawl_comments(
                target_input,
                include_replies=bool(params.get("include_replies", True)),
                max_pages=max_pages,
                mode=int(params.get("sort_mode", 3)),
            )
            cleaned = DataProcessor.clean_comments(comments)
            stats = DataProcessor.get_statistics(cleaned)
            self._last_comments = cleaned
            self._last_comment_context = self._comment_context(target_input)
            self.emit("stats", mode="comments", stats=stats)
            self.emit("finished", mode="comments", count=len(cleaned), stats=stats)
        except Exception as exc:
            logger.exception("comments task failed")
            self.emit("error", mode="comments", message=str(exc))
        finally:
            self._active_crawler = None
            self.emit("progress", status="idle", mode="comments", percent=100)

    def _run_dynamics(self, params: dict[str, Any]) -> None:
        try:
            max_pages = int(params.get("max_pages", 20))
            crawler = DynamicCrawler(progress_callback=self._make_progress_callback("dynamics", max_pages))
            crawler.api = self._api
            self._active_crawler = crawler
            uid = params.get("uid")
            if uid is None:
                dynamics = crawler.crawl_following_feed(
                    keyword=params.get("keyword", ""),
                    max_pages=max_pages,
                    start_time=int(params.get("start_ts", 0)),
                    end_time=int(params.get("end_ts", 0)),
                )
            else:
                dynamics = crawler.crawl_dynamics(
                    int(uid),
                    keyword=params.get("keyword", ""),
                    max_pages=max_pages,
                    start_time=int(params.get("start_ts", 0)),
                    end_time=int(params.get("end_ts", 0)),
                )
            self._last_dynamics = dynamics
            stats = {"total": len(dynamics)}
            self.emit("stats", mode="dynamics", stats=stats)
            self.emit("finished", mode="dynamics", count=len(dynamics), stats=stats)
        except Exception as exc:
            logger.exception("dynamics task failed")
            self.emit("error", mode="dynamics", message=str(exc))
        finally:
            self._active_crawler = None
            self.emit("progress", status="idle", mode="dynamics", percent=100)

    def _run_analysis(self, params: dict[str, Any]) -> None:
        try:
            self._active_crawler = None
            self._analysis_cancel.clear()

            def progress(message: str, percent: int) -> None:
                self.emit("analysis.progress", message=message, percent=percent)

            result = LLMAnalysisProcessor.analyze(
                self._last_comments,
                self._last_dynamics,
                params,
                progress=progress,
                cancel_event=self._analysis_cancel,
            )
            if self._analysis_cancel.is_set():
                raise AnalysisCancelled("分析已被取消")
            result["_asset_context"] = self._analysis_asset_context(params)
            self._last_analysis = result
            display_result = self._display_analysis_result(result)
            self.emit(
                "finished",
                mode="analysis",
                count=(result.get("meta") or {}).get("analyzed_records", 0),
                stats=result.get("overview") or {},
                result=display_result,
            )
        except AnalysisCancelled as exc:
            msg = str(exc)
            self.emit("error", mode="analysis", message=msg)
            self.emit("log", message="分析任务已取消")
        except AnalysisError as exc:
            self.emit("error", mode="analysis", message=str(exc))
        except Exception as exc:
            logger.exception("analysis task failed")
            self.emit("error", mode="analysis", message=str(exc))
        finally:
            self._active_crawler = None
            self.emit("progress", status="idle", mode="analysis", percent=100)

    @staticmethod
    def _comment_context(target_input: str) -> dict[str, str]:
        parsed = parse_input(target_input)
        if parsed and parsed.content_type == ContentType.VIDEO:
            context = {"label": "视频评论"}
            if parsed.bvid:
                context["bvid"] = parsed.bvid
            return context
        if parsed and parsed.content_type == ContentType.TEXT_DYNAMIC:
            return {"label": "动态评论"}
        if parsed and parsed.content_type == ContentType.ARTICLE:
            return {"label": "专栏评论"}
        return {"label": "评论"}

    def _analysis_asset_context(self, params: dict[str, Any]) -> dict[str, str]:
        source = str(params.get("source") or "")
        labels: list[str] = []
        bvid = ""
        if source in {"comments", "all"}:
            comment_label = self._last_comment_context.get("label") or "评论"
            labels.append(comment_label)
            bvid = self._last_comment_context.get("bvid") or ""
        if source in {"dynamics", "all"}:
            labels.append("动态")
        if not labels:
            labels.append("分析")
        return {
            "label": "+".join(dict.fromkeys(labels)),
            "bvid": bvid,
            "timestamp": datetime.now().strftime("%Y%m%d-%H%M%S"),
        }

    @classmethod
    def _display_analysis_result(cls, result: dict[str, Any]) -> dict[str, Any]:
        """Return a UI-sized analysis payload; keep full report only in sidecar memory."""
        image_path = cls._image_data_url_file(result, "word_cloud_image")
        image_data_url = cls._image_data_url(result.get("word_cloud_image"))
        payload: dict[str, Any] = {
            "summary": cls._truncate_text(result.get("summary"), 2000),
            "summary_points": cls._text_items(result.get("summary_points"), 7, 260),
            "overview": result.get("overview") or {},
            "sentiment_counts": cls._chart_items(result.get("sentiment_counts"), 8, 80),
            "topic_counts": cls._chart_items(result.get("topic_counts"), 8, 80),
            "word_counts": cls._chart_items(result.get("word_counts"), LLMAnalysisProcessor.WORD_CLOUD_LIMIT, 80),
            "risk_points": cls._text_items(result.get("risk_points"), 8, 240),
            "insights": cls._text_items(result.get("insights"), 8, 240),
            "notable_quotes": cls._text_items(result.get("notable_quotes"), 5, 240),
            "time_series": cls._chart_items(result.get("time_series"), 30, 80),
            "region_counts": cls._chart_items(result.get("region_counts"), 40, 80),
            "overseas_region_counts": cls._chart_items(result.get("overseas_region_counts"), 20, 80),
            "user_level_counts": cls._chart_items(result.get("user_level_counts"), 8, 80),
            "content_type_counts": cls._chart_items(result.get("content_type_counts"), 8, 80),
            "engagement_items": cls._chart_items(result.get("engagement_items"), 10, 120),
            "deep_analysis": cls._deep_analysis(result.get("deep_analysis")),
            "report_markdown": "",
            "meta": result.get("meta") or {},
        }
        if image_data_url:
            payload["word_cloud_image"] = image_data_url
        if image_path:
            payload["word_cloud_image_path"] = image_path
        return payload

    @staticmethod
    def _truncate_text(value: Any, limit: int) -> str:
        text = str(value or "")
        return text if len(text) <= limit else text[: limit - 1] + "…"

    @staticmethod
    def _image_data_url(value: Any) -> str:
        text = str(value or "")
        return text if text.startswith("data:image/png;base64,") else ""

    @classmethod
    def _image_data_url_file(cls, result: dict[str, Any], key: str) -> str:
        cached = str(result.get(f"{key}_path") or "")
        if cached and Path(cached).is_file():
            return cached

        data_url = cls._image_data_url(result.get(key))
        if not data_url:
            return ""
        try:
            raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        except Exception:
            return ""

        digest = hashlib.sha1(raw).hexdigest()[:16]
        target_dir = cls._analysis_asset_dir(result)
        target = target_dir / f"{cls._safe_file_part(key)}-{digest}.png"
        if not target.exists():
            target.write_bytes(raw)
        result[f"{key}_path"] = str(target)
        return str(target)

    @classmethod
    def _analysis_asset_dir(cls, result: dict[str, Any]) -> Path:
        cached = str(result.get("_asset_dir") or "")
        if cached:
            path = Path(cached)
            path.mkdir(parents=True, exist_ok=True)
            return path

        context = result.get("_asset_context") if isinstance(result.get("_asset_context"), dict) else {}
        timestamp = cls._safe_file_part(context.get("timestamp") or datetime.now().strftime("%Y%m%d-%H%M%S"))
        label = cls._safe_file_part(context.get("label") or "分析")
        bvid = cls._safe_file_part(context.get("bvid") or "")
        parts = [timestamp, label]
        if bvid and "视频评论" in str(context.get("label") or ""):
            parts.append(bvid)

        root = cls._analysis_asset_root()
        base_name = "-".join(parts)
        path = root / base_name
        suffix = 2
        while path.exists():
            path = root / f"{base_name}-{suffix}"
            suffix += 1
        path.mkdir(parents=True, exist_ok=True)
        result["_asset_dir"] = str(path)
        return path

    @staticmethod
    def _analysis_asset_root() -> Path:
        # Prefer the project root so users can easily find exported assets.
        candidate = ROOT / "analysis-assets"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            # Quick writability check
            (candidate / ".write-test"). touch()
            (candidate / ".write-test").unlink(missing_ok=True)
            return candidate
        except (OSError, PermissionError):
            pass
        # Fall back to %LOCALAPPDATA% for installed / non-writable layouts.
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "BilibiliCrawler" / "analysis-assets"
        return Path.home() / "AppData" / "Local" / "BilibiliCrawler" / "analysis-assets"

    @staticmethod
    def _safe_file_part(value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", text)
        text = re.sub(r"\s+", "_", text)
        text = text.strip(".-_")
        return text[:80] or "analysis"

    @classmethod
    def _text_items(cls, value: Any, limit: int, text_limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [cls._truncate_text(item, text_limit) for item in value[:limit]]

    @classmethod
    def _chart_items(cls, value: Any, limit: int, text_limit: int) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, Any]] = []
        for item in value[:limit]:
            if not isinstance(item, dict):
                continue
            cleaned: dict[str, Any] = {}
            for key, item_value in item.items():
                cleaned[key] = cls._truncate_text(item_value, text_limit) if isinstance(item_value, str) else item_value
            items.append(cleaned)
        return items

    @classmethod
    def _deep_analysis(cls, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            value = {}
        return {
            "sociology": cls._truncate_text(value.get("sociology"), 800),
            "psychology": cls._truncate_text(value.get("psychology"), 800),
            "philosophy": cls._truncate_text(value.get("philosophy"), 800),
        }

    def _start_qr_login(self, request_id: Any) -> None:
        if self._qr_thread and self._qr_thread.is_alive():
            raise RuntimeError("扫码登录正在进行中")
        self._qr_cancel.clear()
        self._qr_thread = threading.Thread(target=self._run_qr_login, daemon=True)
        self._qr_thread.start()
        self.respond(request_id)

    def _run_qr_login(self) -> None:
        try:
            result = self._api.generate_qrcode()
            if not result:
                raise RuntimeError("获取二维码失败")
            qr_url, qrcode_key = result
            qr = qrcode.QRCode(box_size=8, border=2)
            qr.add_data(qr_url)
            qr.make(fit=True)
            image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
            self.emit("qr", image=data_url, key=qrcode_key)
            self.emit("log", message="二维码已生成，请用哔哩哔哩客户端扫码")

            while not self._qr_cancel.is_set():
                time.sleep(2)
                code, cookies = self._api.poll_qrcode(qrcode_key)
                if code == 0:
                    self._logged_in = True
                    self.emit("login.success", cookies=cookies or {})
                    self.emit("log", message="扫码登录成功")
                    return
                if code == 86090:
                    self.emit("log", message="已扫码，请在手机上确认登录")
                elif code == 86038:
                    self.emit("error", message="二维码已过期")
                    return
                elif code not in (86101,):
                    self.emit("log", message=f"扫码状态: {code}")
        except Exception as exc:
            logger.exception("qr login failed")
            self.emit("error", message=str(exc))

    def _export_csv(self, request_id: Any, params: dict[str, Any]) -> None:
        kind = params.get("kind")
        path = params.get("path")
        if not path:
            raise ValueError("缺少导出路径")
        if kind == "comments":
            ok = CSVExporter.export(self._last_comments, path)
        elif kind == "dynamics":
            ok = CSVExporter.export_dynamics(self._last_dynamics, path)
        else:
            raise ValueError("未知导出类型")
        if not ok:
            raise RuntimeError("导出失败，没有可导出的数据或写入失败")
        self.respond(request_id, path=path)
        self.emit("log", message=f"CSV 已导出: {path}")

    def _export_analysis(self, request_id: Any, params: dict[str, Any]) -> None:
        if not self._last_analysis:
            raise RuntimeError("没有可导出的分析结果")
        path = params.get("path")
        if not path:
            raise ValueError("缺少导出路径")
        export_format = params.get("format") or "markdown"
        target = Path(path)
        if export_format == "json":
            target.write_text(json.dumps(self._last_analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        elif export_format == "markdown":
            chart_assets = self._chart_assets(params.get("chart_assets"))
            asset_dir_name = f"{target.stem}_assets"
            if chart_assets:
                asset_dir = target.with_name(asset_dir_name)
                asset_dir.mkdir(parents=True, exist_ok=True)
                for asset in chart_assets:
                    if asset.get("svg"):
                        (asset_dir / asset["filename"]).write_text(asset["svg"], encoding="utf-8")
                    elif asset.get("data"):
                        (asset_dir / asset["filename"]).write_bytes(asset["data"])
            report = LLMAnalysisProcessor._build_markdown_report(
                self._last_analysis,
                chart_assets=chart_assets,
                asset_dir_name=asset_dir_name if chart_assets else "",
            )
            target.write_text(report, encoding="utf-8")
        else:
            raise ValueError("未知分析导出格式")
        self.respond(request_id, path=str(target))
        self.emit("log", message=f"分析报告已导出: {target}")

    @staticmethod
    def _chart_assets(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        assets: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename") or "")
            svg = str(item.get("svg") or "")
            data_url = str(item.get("data_url") or "")
            file_path = str(item.get("file_path") or "")
            key = str(item.get("key") or "")
            title = str(item.get("title") or "")
            if not filename.endswith(".svg") or not svg.lstrip().startswith("<svg"):
                if not filename.endswith(".png") or not data_url.startswith("data:image/png;base64,"):
                    if not filename.endswith(".png") or not Path(file_path).is_file():
                        continue
                    data = Path(file_path).read_bytes()
                else:
                    try:
                        data = base64.b64decode(data_url.split(",", 1)[1], validate=True)
                    except Exception:
                        continue
                safe_filename = re.sub(r"[^A-Za-z0-9_.-]", "-", filename)
                assets.append({"key": key, "title": title, "filename": safe_filename, "data": data})
            else:
                safe_filename = re.sub(r"[^A-Za-z0-9_.-]", "-", filename)
                assets.append({"key": key, "title": title, "filename": safe_filename, "svg": svg})
        return assets


def _warm_up_wordcloud(sidecar: Sidecar) -> None:
    """Pre-import wordcloud so matplotlib font-cache build happens now, not during analysis."""
    try:
        import sys as _sys
        import time as _time

        _start = _time.time()
        sidecar.emit("log", message="正在初始化渲染引擎...")
        from wordcloud import WordCloud  # noqa: F401
        _elapsed = (_time.time() - _start) * 1000
        sidecar.emit("log", message=f"渲染引擎就绪（{_elapsed:.0f}ms）")
    except Exception as exc:
        sidecar.emit("log", message=f"渲染引擎初始化失败（Python: {sys.executable}）：{exc}")
        print(f"[sidecar] warm-up failed (Python: {sys.executable}): {exc}", file=_sys.stderr)


def main() -> None:
    sidecar = Sidecar()
    sidecar.emit("ready")
    # Log the actual Python executable so we can diagnose import issues.
    sidecar.emit("log", message=f"Python: {sys.executable}")

    # Pre-initialize wordcloud / matplotlib font cache at startup
    # to avoid a 30–120 s hang later when the user runs analysis.
    _warm_up_wordcloud(sidecar)

    for raw_line in sys.stdin.buffer:
        line = raw_line.decode("utf-8-sig", errors="replace")
        line = line.replace("\x00", "").strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            sidecar.emit("error", message=f"请求 JSON 无效: {exc}")
            continue
        sidecar.handle(request)


if __name__ == "__main__":
    main()
