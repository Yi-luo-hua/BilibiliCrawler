"""
AgentService: the single business entry point for headless (non-desktop) use.

Adapters on top of this are thin. backend/mcp_server.py translates tool calls
into these methods, backend/agent.py does the same for the CLI. Neither holds
business logic, and neither is imported by the desktop sidecar.

The service owns orchestration, the run state machine, cancellation and
persistence. It deliberately contains no presentation logic: no base64 data
URLs, no truncation for display, no JSONL events. Those belong to whichever
adapter is talking to a particular front end.
"""
from __future__ import annotations

import copy
import dataclasses
import inspect
import logging
import queue
import threading
import traceback
from datetime import datetime
from typing import Any, Callable

from src.api.bilibili_api import BilibiliAPI
from src.crawler.comment_crawler import CommentCrawler
from src.processor.analysis_processor import AnalysisCancelled, AnalysisError, LLMAnalysisProcessor
from src.processor.data_processor import DataProcessor
from src.service.credentials import LLMCredentials, resolve_llm_credentials, scrub
from src.service.models import (
    SAMPLE_SIZE_DEFAULT,
    CallerPolicy,
    ErrorCode,
    EventKind,
    RunStatus,
    ServiceError,
    TaskEvent,
    TaskKind,
    TaskOutcome,
    TaskSnapshot,
    clamp_int as _clamp,
)
from src.service.run_store import RunStore, new_run_id

logger = logging.getLogger(__name__)

ProgressEvent = tuple[int, str]

# Artifacts produced by (and owned by) the analysis half: a re-analysis
# replaces them wholesale instead of merging, so a stale word cloud cannot
# survive a re-analysis that produced none.
_ANALYSIS_ARTIFACT_KEYS = ("analysis_json", "report_markdown", "word_cloud_image")


class _Task:
    """Mutable task state. All mutation goes through the instance lock."""

    def __init__(
        self,
        task_id: str,
        run_id: str,
        kind: str,
        events: Callable[[TaskEvent], None] | None = None,
    ) -> None:
        self.task_id = task_id
        self.run_id = run_id
        self.kind = kind
        self._events = events
        self.status = RunStatus.QUEUED
        self.stage = ""
        self.percent = 0
        self.counts: dict[str, int] = {}
        self.summary = ""
        self.artifacts: dict[str, str] = {}
        # What the crawler learned about the target (title/owner/pubdate),
        # persisted into the manifest next to the comments it describes.
        self.target: dict = {}
        self.warnings: list[str] = []
        self.error: str | None = None
        self.error_code: str | None = None

        # Which body is running, so a generic failure gets the right code.
        # Status alone is ambiguous: both crawl and analyze pass through
        # EXPORTING.
        self.phase = TaskKind.CRAWL
        # Set once the task has committed to a terminal status, so a late
        # stop() cannot move it back to a non-terminal one.
        self.terminal = False
        # True only while crawler.stop() is on the stack, to break the
        # stop -> log -> progress -> stop cycle.
        self._stopping = False

        self.cancel_event = threading.Event()
        self.done_event = threading.Event()
        self.progress: "queue.Queue[ProgressEvent]" = queue.Queue()
        self.thread: threading.Thread | None = None
        self.crawler: CommentCrawler | None = None
        self._lock = threading.Lock()

    def update(self, **changes: Any) -> None:
        with self._lock:
            # A pending cancel must not be rolled back by a phase transition
            # racing it (e.g. update(EXPORTING) landing just after
            # request_cancel set CANCELLING); the user would see "writing
            # files" instead of "stopping" until settle. Terminal states are
            # committed by settle()/mark_failed() directly, not via update().
            if self.status == RunStatus.CANCELLING and not self.terminal:
                changes = {
                    key: value
                    for key, value in changes.items()
                    if key not in {"status", "stage", "percent"}
                }
            for key, value in changes.items():
                setattr(self, key, value)

    def attach_crawler(self, crawler: CommentCrawler | None) -> None:
        with self._lock:
            self.crawler = crawler

    def stop_crawler(self) -> None:
        """Signal the crawler, guarding against re-entry.

        CommentCrawler.stop() writes a progress log, which re-enters the
        service's progress callback, which asks to stop again -- straight into
        a RecursionError. The guard is scoped to the call, not permanent:
        crawl_comments() clears its own stop flag on entry, so later progress
        lines must be able to re-assert the stop.
        """
        with self._lock:
            crawler = self.crawler
            if crawler is None or self._stopping:
                return
            self._stopping = True
        try:
            crawler.stop()
        finally:
            with self._lock:
                self._stopping = False

    def request_cancel(self) -> bool:
        """Ask the task to stop. Returns False if it already reached a terminal state.

        The cancel flag is raised before taking the lock, so a settle running
        concurrently either sees it (and finishes as cancelled) or has already
        marked itself terminal (and this call declines to move the status back
        to `cancelling`). Without that guard a stop landing just after settle
        left the task stuck on a non-terminal status forever.
        """
        self.cancel_event.set()
        with self._lock:
            if self.terminal:
                return False
            self.status = RunStatus.CANCELLING
            self.stage = "正在停止任务"
        self.stop_crawler()
        return True

    def settle(self, completed_stage: str, cancelled_stage: str, changes: dict[str, Any]) -> None:
        """Atomically choose the terminal status and record results."""
        with self._lock:
            if self.cancel_event.is_set():
                self.status = RunStatus.CANCELLED
                self.stage = cancelled_stage
                self.error_code = ErrorCode.CANCELLED
            else:
                self.status = RunStatus.COMPLETED
                self.stage = completed_stage
            for key, value in changes.items():
                setattr(self, key, value)
            self.percent = 100
            self.terminal = True

    def mark_failed(self, code: str, message: str) -> None:
        with self._lock:
            self.status = RunStatus.FAILED
            self.error = message
            self.error_code = code
            self.percent = 100
            self.terminal = True

    def add_warning(self, message: str) -> None:
        with self._lock:
            self.warnings = [*self.warnings, message]

    def snapshot(self) -> TaskSnapshot:
        with self._lock:
            return TaskSnapshot(
                task_id=self.task_id,
                run_id=self.run_id,
                kind=self.kind,
                status=self.status,
                stage=self.stage,
                percent=self.percent,
                counts=dict(self.counts),
                summary=self.summary,
                artifacts=dict(self.artifacts),
                warnings=list(self.warnings),
                error=self.error,
                error_code=self.error_code,
            )

    def emit(self, percent: int, message: str) -> None:
        self.update(percent=percent, stage=message)
        self.progress.put((percent, message))

    def notify(self, kind: str, message: str = "", percent: int | None = None) -> None:
        """Push one typed event to the adapter listener, if there is one.

        Called without the instance lock on purpose: a listener writes a frame
        and may take locks of its own, and one that reads the snapshot back
        would deadlock against a lock held across this call.
        """
        listener = self._events
        if listener is None:
            return
        try:
            listener(
                TaskEvent(
                    kind=kind,
                    task_id=self.task_id,
                    run_id=self.run_id,
                    message=message,
                    percent=percent,
                )
            )
        except Exception:  # noqa: BLE001 - a broken listener must not kill the task
            logger.error(
                "listener failed for task %s: %s", self.task_id, scrub(traceback.format_exc())
            )

    @property
    def alive(self) -> bool:
        return not self.done_event.is_set()


class AgentService:
    def __init__(
        self,
        store: RunStore | None = None,
        api: Any = None,
        crawler_factory: Callable[[Callable[[str], None]], Any] | None = None,
        analysis_processor: Any = LLMAnalysisProcessor,
        data_processor: Any = DataProcessor,
        credentials_resolver: Callable[[], LLMCredentials] = resolve_llm_credentials,
        policy: CallerPolicy | None = None,
        events: Callable[[TaskEvent], None] | None = None,
        retain_outcome: bool = False,
    ) -> None:
        self._store = store or RunStore()
        self._api = api if api is not None else BilibiliAPI()
        self._crawler_factory = crawler_factory or (
            lambda progress: CommentCrawler(progress_callback=progress, api=self._api)
        )
        self._analysis_processor = analysis_processor
        self._data_processor = data_processor
        self._resolve_credentials = credentials_resolver
        # Static caller behavior and limits only. Credentials are never stored
        # here; they arrive per analysis call and leave with it.
        self._policy = policy or CallerPolicy()
        # The adapter-only channel. Both halves default to off, so the MCP and
        # CLI paths allocate nothing extra and behave exactly as before.
        self._events = events
        self._retain_outcome = bool(retain_outcome)
        self._outcome: TaskOutcome | None = None

        self._lock = threading.Lock()
        self._active: _Task | None = None
        self._tasks: dict[str, _Task] = {}

    @property
    def store(self) -> RunStore:
        return self._store

    @property
    def policy(self) -> CallerPolicy:
        return self._policy

    @property
    def active_run_id(self) -> str:
        """The run the currently executing task writes to, "" when idle.

        Consumers that delete run directories (e.g. prune) must hold this one
        back: the worker would otherwise re-create the directory mid-delete
        and leave a manifest-less zombie on disk.
        """
        with self._lock:
            return self._active.run_id if self._active is not None else ""

    # -- task lifecycle ----------------------------------------------------
    def _begin(self, kind: str, run_id: str) -> _Task:
        with self._lock:
            active = self._active
            if active is not None and active.alive:
                raise ServiceError(
                    ErrorCode.BUSY,
                    f"已有任务正在运行（task_id={active.task_id}），本进程同时只允许一个任务。"
                    "请等待其完成或先调用 stop_task。",
                    task_id=active.task_id,
                    run_id=active.run_id,
                )
            task = _Task(
                task_id=f"task-{new_run_id()}",
                run_id=run_id,
                kind=kind,
                events=self._events,
            )
            self._active = task
            self._tasks[task.task_id] = task
            # Only the newest task's outcome is kept. _tasks itself never
            # shrinks, so hanging comment lists off it would turn a small leak
            # into one that grows with every run.
            self._outcome = None
            return task

    def _create_run_or_release(self, task: _Task, kind: str, params: dict[str, Any]) -> None:
        """Create the run directory, freeing the task slot if that fails."""
        try:
            self._store.create_run(task.run_id, kind, params)
        except BaseException:
            with self._lock:
                if self._active is task:
                    self._active = None
            self._tasks.pop(task.task_id, None)
            task.done_event.set()
            raise

    def _spawn(self, task: _Task, target: Callable[[_Task], None]) -> TaskSnapshot:
        def runner() -> None:
            try:
                target(task)
            except ServiceError as exc:
                self._fail(task, exc.code, str(exc))
            except Exception as exc:  # noqa: BLE001 - surfaced through the snapshot
                # logger.exception would emit the raw message and traceback,
                # which can contain a key echoed back by the provider.
                logger.error(
                    "task %s failed: %s", task.task_id, scrub(traceback.format_exc())
                )
                fallback = (
                    ErrorCode.ANALYSIS_FAILED
                    if task.phase == TaskKind.ANALYZE
                    else ErrorCode.CRAWL_FAILED
                )
                self._fail(task, fallback, str(exc))
            finally:
                with self._lock:
                    if self._active is task:
                        self._active = None
                # Signals both worker completion and readiness for the next
                # task, so publish it only after releasing the active slot.
                task.done_event.set()

        thread = threading.Thread(target=runner, name=task.kind, daemon=True)
        task.thread = thread
        thread.start()
        return task.snapshot()

    def _fail(self, task: _Task, code: str, message: str) -> None:
        # Providers echo the key back in 401 bodies, and this text lands in the
        # manifest and in tool results, so it is scrubbed at the single choke
        # point where task errors are recorded.
        task.mark_failed(code, scrub(message))
        self._persist(task)

    def _settle(
        self,
        task: _Task,
        completed_stage: str,
        cancelled_stage: str = "任务已取消",
        **changes: Any,
    ) -> None:
        """Record results, choosing the terminal status by cancellation state.

        Cancellation can land while data is being written. Checking only before
        the export would let the completion update overwrite `cancelling`, so a
        stopped task must be resolved here, after the writes.
        """
        task.settle(completed_stage, cancelled_stage, changes)
        self._persist(task)

    def _persist(self, task: _Task) -> None:
        try:
            existing = self._store.read_manifest(task.run_id)
            # Merge rather than replace: an analyze task starts with empty
            # counts/artifacts, and overwriting would erase the crawl's record
            # of how many comments exist and where the CSV went.
            counts = {**(existing.get("counts") or {}), **task.counts}
            artifacts = {**(existing.get("artifacts") or {}), **task.artifacts}
            if task.phase == TaskKind.ANALYZE and task.terminal:
                # The analysis owns these keys; a re-analysis replaces them.
                # Merge-only would keep announcing an archived word cloud
                # after a re-analysis that produced none.
                for key in _ANALYSIS_ARTIFACT_KEYS:
                    if key not in task.artifacts:
                        artifacts.pop(key, None)
            target = {**(existing.get("target") or {}), **task.target}
            self._store.update_manifest(
                task.run_id,
                status=task.status,
                stage=task.stage,
                counts=counts,
                artifacts=artifacts,
                target=target,
                warnings=task.warnings,
                error=task.error,
                error_code=task.error_code,
            )
        except ServiceError:
            logger.warning("could not persist manifest for run %s", task.run_id)
        except OSError as exc:
            # A settle()'d terminal status must not be rewritten to FAILED by
            # a transient write failure (antivirus/indexer holding the file,
            # disk full). The data files are already on disk; only this
            # manifest refresh is lost.
            logger.warning("could not persist manifest for run %s: %s", task.run_id, exc)

    # -- public API --------------------------------------------------------
    def start_crawl(
        self,
        url: str,
        max_pages: int | None = None,
        include_replies: bool = True,
        sort_mode: int = 3,
    ) -> TaskSnapshot:
        params = self._crawl_params(url, max_pages, include_replies, sort_mode)
        # Claim the slot before touching the disk: creating the run first would
        # leave an orphan directory stuck at `queued` every time a concurrent
        # call is rejected as BUSY.
        task = self._begin(TaskKind.CRAWL, new_run_id())
        self._create_run_or_release(task, TaskKind.CRAWL, params)
        return self._spawn(task, lambda t: self._do_crawl(t, params))

    def start_analyze(
        self,
        run_id: str,
        sample_size: int = SAMPLE_SIZE_DEFAULT,
        strategy: str = "sample",
        chart_keys: list[str] | None = None,
        batch_size: int | None = None,
        credentials: LLMCredentials | None = None,
    ) -> TaskSnapshot:
        # Validate the run and its data before claiming the single task slot,
        # so a bad run_id cannot make the service look busy.
        self._store.run_dir(run_id)
        self._store.load_comments(run_id)
        params = self._analysis_params(sample_size, strategy, chart_keys, batch_size, credentials)
        task = self._begin(TaskKind.ANALYZE, run_id)
        # Carry the crawl's counts and artifacts forward so the snapshot for a
        # re-analysis still reports how many comments the run holds.
        try:
            existing = self._store.read_manifest(run_id)
            task.update(
                counts={str(k): int(v) for k, v in (existing.get("counts") or {}).items()},
                artifacts=dict(self._store.artifacts(run_id)),
            )
        except ServiceError:
            logger.warning("could not seed task from manifest for run %s", run_id)
        return self._spawn(task, lambda t: self._do_analyze(t, params))

    def start_crawl_and_analyze(
        self,
        url: str,
        max_pages: int | None = None,
        include_replies: bool = True,
        sort_mode: int = 3,
        sample_size: int = SAMPLE_SIZE_DEFAULT,
        strategy: str = "sample",
        chart_keys: list[str] | None = None,
        batch_size: int | None = None,
        credentials: LLMCredentials | None = None,
    ) -> TaskSnapshot:
        crawl_params = self._crawl_params(url, max_pages, include_replies, sort_mode)
        analysis_params = self._analysis_params(sample_size, strategy, chart_keys, batch_size, credentials)
        task = self._begin(TaskKind.CRAWL_AND_ANALYZE, new_run_id())
        self._create_run_or_release(
            task, TaskKind.CRAWL_AND_ANALYZE, {**crawl_params, **_public(analysis_params)}
        )

        def target(t: _Task) -> None:
            self._do_crawl(t, crawl_params)
            if t.status == RunStatus.CANCELLED or t.error:
                return
            self._do_analyze(t, analysis_params)

        return self._spawn(task, target)

    def get_status(self, task_id: str | None = None, run_id: str | None = None) -> TaskSnapshot:
        if task_id:
            task = self._tasks.get(task_id)
            if task is None:
                raise ServiceError(ErrorCode.NOT_FOUND, f"找不到 task_id: {task_id}")
            return task.snapshot()
        if run_id:
            for task in reversed(list(self._tasks.values())):
                if task.run_id == run_id:
                    return task.snapshot()
            return self._snapshot_from_manifest(run_id)
        with self._lock:
            active = self._active
        if active is not None:
            return active.snapshot()
        raise ServiceError(ErrorCode.INVALID_INPUT, "当前没有活动任务，请提供 task_id 或 run_id。")

    def stop(self, task_id: str) -> TaskSnapshot:
        task = self._tasks.get(task_id)
        if task is None:
            raise ServiceError(ErrorCode.NOT_FOUND, f"找不到 task_id: {task_id}")
        if not task.alive:
            return task.snapshot()
        task.request_cancel()
        return task.snapshot()

    def wait(self, task_id: str, timeout: float) -> TaskSnapshot:
        task = self._tasks.get(task_id)
        if task is None:
            raise ServiceError(ErrorCode.NOT_FOUND, f"找不到 task_id: {task_id}")
        task.done_event.wait(timeout=max(0.0, timeout))
        return task.snapshot()

    def wait_until_finished(self, task_id: str, timeout: float) -> bool:
        """Wait until the worker has exited and the service can start another task."""
        task = self._tasks.get(task_id)
        if task is None:
            raise ServiceError(ErrorCode.NOT_FOUND, f"找不到 task_id: {task_id}")
        return task.done_event.wait(timeout=max(0.0, timeout))

    def take_outcome(self, task_id: str) -> TaskOutcome | None:
        """Hand the adapter the heavy results of a finished task, once.

        Ownership transfers: the service drops its reference, so a caller that
        annotates the result dict is not quietly editing the service's copy too.

        Refused while the task is still running. A crawl-and-analyse task
        records its two halves at different moments, so an early call would hand
        over one incomplete outcome and leave the other half behind to be taken
        as a second one -- the same task consumed twice, neither time whole.
        This is also not a back door to terminal state: that is read from
        TaskSnapshot, and there is still only one way to learn a task ended.

        Returns None when the task is unknown or still running, when it is not
        the most recent one, when the service was built without retain_outcome,
        or when the outcome was already taken.
        """
        task = self._tasks.get(task_id)
        if task is None or not task.snapshot().done:
            return None
        with self._lock:
            outcome = self._outcome
            if outcome is None or outcome.task_id != task_id:
                return None
            self._outcome = None
            return outcome

    def _record_outcome(self, task: _Task, **fields: Any) -> None:
        """Fold one stage's results into the current task's outcome.

        Callers pass the live objects; the copying happens here, behind the
        retain_outcome check, so a caller who never asked for the channel pays
        nothing at all -- not even a container copy.

        The copy is deep. A shallow one leaves every nested list and dict shared
        with whoever the value came from, and RunStore.save_analysis is right
        next in line to edit exactly those. Deep-copying a crawl's worth of
        comments costs single-digit milliseconds against a JSON and CSV write.

        The slot always belongs to this task: _begin clears it, and it cannot
        begin a second task until the first one's thread has finished recording.
        """
        if not self._retain_outcome:
            return
        # Copied outside the lock: it is the expensive part, and nothing else
        # touches the slot while this task is the active one.
        copied = {key: copy.deepcopy(value) for key, value in fields.items()}
        with self._lock:
            current = self._outcome or TaskOutcome(task_id=task.task_id, run_id=task.run_id)
            self._outcome = dataclasses.replace(current, **copied)

    def drain_progress(self, task_id: str) -> list[ProgressEvent]:
        task = self._tasks.get(task_id)
        if task is None:
            return []
        events: list[ProgressEvent] = []
        while True:
            try:
                events.append(task.progress.get_nowait())
            except queue.Empty:
                break
        return events

    # -- work bodies -------------------------------------------------------
    def _do_crawl(self, task: _Task, params: dict[str, Any]) -> None:
        task.update(phase=TaskKind.CRAWL, status=RunStatus.CRAWLING, stage="正在爬取评论")
        self._persist(task)

        max_pages = int(params["max_pages"])

        # A cancel that arrived before the crawl started must not fire off
        # requests anyway. Desktop callers still need the same explicit empty
        # outcome they receive when cancellation lands after crawler creation.
        if task.cancel_event.is_set():
            changes = self._crawl_results(task, []) if self._policy.empty_crawl_is_success else {}
            self._settle(task, "评论爬取完成", **changes)
            return

        def progress(message: str) -> None:
            # CommentCrawler.crawl_comments clears its own _stop_flag on entry,
            # so a stop() issued before that point is silently discarded.
            # Re-asserting from inside the crawl is what actually makes an early
            # cancel take effect; the crawler logs before its first page request,
            # so this lands before any network call. stop_crawler() is
            # re-entrancy guarded because stop() itself logs through here.
            if task.cancel_event.is_set():
                task.stop_crawler()
            text = str(message)
            # Must never print: stdout belongs to the MCP JSON-RPC stream.
            task.emit(min(70, task.percent + 2), text)
            # Verbatim, and after the emit so a listener reading the snapshot
            # back sees the state this line already produced.
            task.notify(EventKind.LOG, text)

        crawler = self._crawler_factory(progress)
        task.attach_crawler(crawler)

        # Re-check after the crawler exists. Building it is not instantaneous,
        # and crawl_comments() resolves the target -- a BV/dynamic metadata
        # request -- before its first stop check, so a cancel that arrived in
        # the meantime can only be honoured by not calling it at all.
        if task.cancel_event.is_set():
            changes = self._crawl_results(task, []) if self._policy.empty_crawl_is_success else {}
            self._settle(task, "评论爬取完成", **changes)
            return

        comments = crawler.crawl_comments(
            str(params["url"]),
            include_replies=bool(params["include_replies"]),
            max_pages=max_pages,
            mode=int(params["sort_mode"]),
        )
        # Captured while the crawler still exists: the title/owner it learned
        # resolving the target belongs in the manifest next to the comments.
        target_info = getattr(crawler, "target_info", None)
        if isinstance(target_info, dict) and target_info:
            task.update(target=dict(target_info))
        task.attach_crawler(None)

        cleaned = self._data_processor.clean_comments(comments)

        if task.cancel_event.is_set():
            # A stopped crawler still returns the pages it managed to fetch.
            # Persisting them is what makes "partial data is kept" true.
            self._settle(task, "评论爬取完成", **self._crawl_results(task, cleaned))
            return

        if not cleaned and not self._policy.empty_crawl_is_success:
            raise ServiceError(
                ErrorCode.CRAWL_FAILED,
                "没有爬到任何评论，请检查链接是否为公开可访问的视频/动态/专栏。",
            )

        task.update(status=RunStatus.EXPORTING, stage="正在写入评论文件")
        changes = self._crawl_results(task, cleaned)

        if task.kind == TaskKind.CRAWL or task.cancel_event.is_set():
            # For a stop landing during the export, settle() picks `cancelled`
            # and we do not roll on into analysis.
            self._settle(task, "评论爬取完成", **changes)
        else:
            task.update(status=RunStatus.ANALYZING, stage="评论爬取完成", **changes)
            self._persist(task)

    def _crawl_results(self, task: _Task, cleaned: list[dict[str, Any]]) -> dict[str, Any]:
        """Persist the crawled comments and build the resulting state changes."""
        if not cleaned and not self._policy.empty_crawl_is_success:
            # The data processor is deliberately not called here. It never was
            # on this path, and it is an injection point: one that rejects an
            # empty list would turn a crawl stopped before its first page from
            # `cancelled` into `failed`.
            return {"percent": 70}
        # Snapshotted before the store is handed the same list. save_comments
        # does not edit it today, but the analysis half records early for
        # exactly this reason and there is no case for the crawl half being the
        # weaker of the two.
        self._record_outcome(task, comments=cleaned)
        artifacts = self._store.save_comments(task.run_id, cleaned)
        if cleaned and "comments_csv" not in artifacts:
            # The CSV is a convenience export; losing it must not look like
            # success. An empty list is "no data", not "export failed" -- the
            # desktop policy treats an empty crawl as success, and warning
            # here would record a failure that never happened.
            task.add_warning("CSV 导出失败，评论数据仍完整保存在 comments.json 中。")
        stats = self._data_processor.get_statistics(cleaned)
        # counts keeps three integers; the rest of this dict is what the desktop
        # renders. Recomputing it from reloaded JSON would give the same numbers
        # only for as long as nothing drifts, and no way to notice when it does.
        self._record_outcome(task, stats=stats)
        changes: dict[str, Any] = {
            "counts": {
                **task.counts,
                "comments": len(cleaned),
                "main_comments": int(stats.get("main_comments", 0)),
                "replies": int(stats.get("replies", 0)),
            },
            "artifacts": {**task.artifacts, **artifacts},
            "percent": 70,
        }
        if task.target:
            changes["target"] = dict(task.target)
        return changes

    def _do_analyze(self, task: _Task, params: dict[str, Any]) -> None:
        task.update(phase=TaskKind.ANALYZE, status=RunStatus.ANALYZING, stage="正在分析评论")
        self._persist(task)

        comments = self._store.load_comments(task.run_id)

        def progress(message: str, percent: int) -> None:
            text = str(message)
            task.emit(70 + int(percent * 0.25), text)
            # The unremapped number. 70 + p*0.25 cannot be inverted once a
            # combined run has folded the crawl into the same scale, and the
            # desktop's analysis.progress is a 0-100 contract.
            task.notify(EventKind.ANALYSIS_PROGRESS, text, percent=int(percent))

        try:
            result = self._analysis_processor.analyze(
                comments,
                [],
                params,
                progress=progress,
                cancel_event=task.cancel_event,
            )
        except AnalysisCancelled:
            self._settle(task, "分析完成", cancelled_stage="分析已取消")
            return
        except AnalysisError as exc:
            raise ServiceError(ErrorCode.ANALYSIS_FAILED, str(exc)) from exc

        # A cancel landing here must not discard an already-complete result:
        # the full LLM cost has been paid, and the crawl half keeps partial
        # data on the same race ("partial data is kept"). Persisting first and
        # letting settle() pick `cancelled` afterwards matches that contract.

        # Recorded before the store sees it. save_analysis lifts
        # report_markdown into its own file and rewrites word_cloud_image from a
        # base64 data URL into a path; it happens to work on a shallow copy of
        # its own today, but the desktop needs the originals whether or not it
        # keeps doing that. _record_outcome takes the deep copy.
        self._record_outcome(task, analysis=result)

        task.update(status=RunStatus.EXPORTING, stage="正在导出分析结果", percent=95)
        # The on-disk report gets run context the processor cannot know: the
        # source URL from the crawl's manifest, this run's id, and the word
        # cloud that save_analysis is about to write next to the report. Built
        # on a shallow copy so the already-recorded outcome keeps the
        # processor's original report (the desktop re-renders its own with
        # chart assets anyway). Processors without a _build_markdown_report
        # (custom/test doubles) keep their own report verbatim.
        payload = dict(result)
        build_report = getattr(self._analysis_processor, "_build_markdown_report", None)
        if callable(build_report):
            word_cloud = str(result.get("word_cloud_image") or "")
            chart_assets = (
                [{"key": "word_cloud", "filename": "word_cloud.png"}]
                if word_cloud.startswith("data:image/")
                else []
            )
            source_url, target = self._report_context(task.run_id)
            report_context = {
                "chart_assets": chart_assets,
                "asset_dir_name": "assets" if chart_assets else "",
                "source_url": source_url,
                "source_title": str(target.get("title") or ""),
                "source_owner": str(target.get("owner") or ""),
                "source_pubdate": _format_pubdate(target.get("pubdate")),
                "run_id": task.run_id,
                "records": comments,
            }
            try:
                parameters = inspect.signature(build_report).parameters
            except (TypeError, ValueError):
                report_args = [result]
                report_kwargs = report_context
            else:
                report_args = [result]
                consumed_result = False
                positional_context: set[str] = set()
                for parameter in parameters.values():
                    if parameter.kind in {
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    } and not consumed_result:
                        consumed_result = True
                        continue
                    if (
                        parameter.kind is inspect.Parameter.POSITIONAL_ONLY
                        and parameter.name in report_context
                    ):
                        report_args.append(report_context[parameter.name])
                        positional_context.add(parameter.name)
                accepts_kwargs = any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters.values()
                )
                report_kwargs = (
                    {
                        key: value
                        for key, value in report_context.items()
                        if key not in positional_context
                    }
                    if accepts_kwargs
                    else {
                        key: value
                        for key, value in report_context.items()
                        if key in parameters
                        and parameters[key].kind
                        in {
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            inspect.Parameter.KEYWORD_ONLY,
                        }
                    }
                )
            payload["report_markdown"] = build_report(*report_args, **report_kwargs)
        store_warnings: list[str] = []
        artifacts = self._store.save_analysis(task.run_id, payload, warnings=store_warnings)
        for message in store_warnings:
            task.add_warning(message)
        meta = result.get("meta") or {}
        # The seeded artifacts may carry a previous analysis's keys (this run
        # was re-analysed); the store archived those files, so they must not
        # survive into the final set alongside the fresh ones.
        final_artifacts = {
            key: value for key, value in task.artifacts.items() if key not in _ANALYSIS_ARTIFACT_KEYS
        }
        final_artifacts.update(artifacts)
        self._settle(
            task,
            "分析完成",
            cancelled_stage="分析已取消",
            percent=100,
            # The public snapshot reaches CLI/MCP directly. Disk scrubbing
            # alone does not protect a successful provider echo in its summary.
            summary=scrub(result.get("summary")),
            counts={
                **task.counts,
                "analyzed": int(meta.get("analyzed_records", 0) or 0),
                "total_records": int(meta.get("total_records", 0) or 0),
            },
            artifacts=final_artifacts,
        )

    # -- helpers -----------------------------------------------------------
    def _report_context(self, run_id: str) -> tuple[str, dict[str, Any]]:
        """The crawl's source URL and target metadata, for the report header.

        Best effort: the manifest is known to exist here (load_comments
        already succeeded), but a corrupted one must not turn the export into
        a failure.
        """
        try:
            manifest = self._store.read_manifest(run_id)
        except ServiceError:
            return "", {}
        url = str((manifest.get("params") or {}).get("url") or "")
        target = manifest.get("target") or {}
        return url, target if isinstance(target, dict) else {}

    def _crawl_params(self, url: str, max_pages: Any, include_replies: Any, sort_mode: Any) -> dict[str, Any]:
        target = str(url or "").strip()
        if not target:
            raise ServiceError(ErrorCode.INVALID_INPUT, "url 不能为空")
        return {
            "url": target,
            # The ceiling comes from the caller's policy and is applied here,
            # not in the adapter, so no tool argument or CLI flag can raise it.
            "max_pages": self._policy.resolve_max_pages(max_pages),
            "include_replies": bool(include_replies),
            # Only 3 (by time) and 2 (by popularity) are meaningful to the
            # upstream API; anything else would be forwarded verbatim.
            "sort_mode": int(sort_mode) if sort_mode in (2, 3, "2", "3") else 3,
        }

    def _analysis_params(
        self,
        sample_size: Any,
        strategy: Any,
        chart_keys: Any = None,
        batch_size: Any = None,
        credentials: LLMCredentials | None = None,
    ) -> dict[str, Any]:
        """Build one analysis request.

        Everything credential-shaped is resolved here and handed straight to the
        processor, so no caller has to keep a key alive between requests.
        """
        chosen = str(strategy or "sample").strip()
        if chosen not in {"sample", "all"}:
            chosen = "sample"
        if credentials is None:
            resolved = _require_credentials(self._resolve_credentials(), "credentials_resolver 的返回值")
        else:
            resolved = _require_credentials(credentials, "credentials 参数")
        params: dict[str, Any] = {
            "source": "comments",
            "strategy": chosen,
            "sample_size": _clamp(sample_size, SAMPLE_SIZE_DEFAULT, 20, 2000),
            "llm_config": resolved.to_llm_config(),
        }
        # Omitted rather than sent empty: _normalize_chart_keys falls back to the
        # full set (word cloud included) when handed an empty list, so an agent
        # must always send an explicit non-empty list while the desktop wants the
        # processor's own default when the UI ticked nothing.
        selected = self._policy.resolve_chart_keys(chart_keys)
        if selected is not None:
            params["chart_keys"] = selected
        if batch_size is not None:
            params["batch_size"] = _clamp(batch_size, 80, 20, 200)
        return params

    def _snapshot_from_manifest(self, run_id: str) -> TaskSnapshot:
        """Rebuild state for a run this process did not start.

        This is the restart-recovery path: the MCP host may respawn the server
        between a crawl and its analysis.
        """
        manifest = self._store.read_manifest(run_id)
        status = str(manifest.get("status") or RunStatus.COMPLETED)
        stage = str(manifest.get("stage") or "")
        error = manifest.get("error")
        error_code = manifest.get("error_code")

        if status not in RunStatus.TERMINAL:
            # No task is running for this run in this process, so a non-terminal
            # status means the previous process died mid-run. Reporting it as
            # still-running would send the caller into an endless poll loop.
            status = RunStatus.FAILED
            stage = "任务在上一个进程中被中断"
            error = error or f"run {run_id} 的上一次执行未正常结束，已爬取的数据仍可用。"
            error_code = error_code or ErrorCode.CRAWL_FAILED

        return TaskSnapshot(
            task_id="",
            run_id=run_id,
            kind=str(manifest.get("kind") or ""),
            status=status,
            stage=stage,
            percent=100,
            counts={str(k): int(v) for k, v in (manifest.get("counts") or {}).items()},
            summary="",
            artifacts=self._store.artifacts(run_id),
            warnings=list(manifest.get("warnings") or []),
            error=error,
            error_code=error_code,
        )


def _require_credentials(value: Any, origin: str) -> LLMCredentials:
    """Check anything credential-shaped at the boundary it arrives through.

    Both the explicit argument and whatever credentials_resolver returns end up
    calling to_llm_config(); validating only the former left a caller supplying
    a resolver to trip over a bare AttributeError instead.
    """
    if isinstance(value, LLMCredentials):
        return value
    raise ServiceError(
        ErrorCode.INVALID_INPUT,
        f"{origin} 必须是 LLMCredentials，收到 {type(value).__name__}；"
        "如果手上是 llm_config 字典，请先用 LLMCredentials.from_config() 转换。",
    )


def _public(params: dict[str, Any]) -> dict[str, Any]:
    """Strip the credential blob before params go anywhere near a manifest."""
    return {key: value for key, value in params.items() if key != "llm_config"}


def _format_pubdate(value: Any) -> str:
    """A Unix timestamp from target metadata as YYYY-MM-DD, "" if unusable."""
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d")
