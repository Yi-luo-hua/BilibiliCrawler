"""
JSON-line sidecar for the Tauri desktop shell.

Requests arrive on stdin:
{"id":"...","method":"comments.start","params":{...}}

Events and responses are written to stdout as one JSON object per line.
Logging goes to stderr so it never corrupts the protocol stream.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import queue
import re
import sys
import threading
import time
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
from src.processor.data_processor import DataProcessor
from utils.helpers import extract_uid, parse_input

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
        self._active_crawler: CommentCrawler | DynamicCrawler | None = None
        self._active_thread: threading.Thread | None = None
        self._qr_thread: threading.Thread | None = None
        self._api = BilibiliAPI()
        self._logged_in = False
        self._last_comments: list[dict[str, Any]] = []
        self._last_dynamics: list[dict[str, Any]] = []
        self._responses: "queue.Queue[dict[str, Any]]" = queue.Queue()

    def emit(self, event: str, **payload: Any) -> None:
        self._send({"kind": "event", "event": event, **payload})

    def respond(self, request_id: Any, ok: bool = True, **payload: Any) -> None:
        self._send({"kind": "response", "id": request_id, "ok": ok, **payload})

    def _send(self, payload: dict[str, Any]) -> None:
        with self._write_lock:
            print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)

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
                self._stop_task()
                self.respond(request_id)
                self.emit("log", message="正在停止爬取任务...")
            elif method == "qr.login.start":
                self._start_qr_login(request_id)
            elif method == "qr.login.cancel":
                self._qr_cancel.set()
                self.respond(request_id)
            elif method == "export.csv":
                self._export_csv(request_id, params)
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
            thread.start()
        self.respond(request_id)
        self.emit("progress", status="running", mode=name, percent=0)
        task_label = "评论" if name == "comments" else "动态"
        self.emit("log", message=f"{task_label}任务已启动")

    def _stop_task(self) -> None:
        crawler = self._active_crawler
        if crawler:
            crawler.stop()

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
            crawler = CommentCrawler(progress_callback=self._make_progress_callback("comments", max_pages))
            self._active_crawler = crawler
            comments = crawler.crawl_comments(
                params.get("input", ""),
                include_replies=bool(params.get("include_replies", True)),
                max_pages=max_pages,
                mode=int(params.get("sort_mode", 3)),
            )
            cleaned = DataProcessor.clean_comments(comments)
            stats = DataProcessor.get_statistics(cleaned)
            self._last_comments = cleaned
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


def main() -> None:
    sidecar = Sidecar()
    sidecar.emit("ready")
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
