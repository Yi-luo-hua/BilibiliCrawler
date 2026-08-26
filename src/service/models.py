"""
Value types and tunables for the headless agent service.

Deliberately stdlib-only: the service layer must import cleanly with just
requirements.txt installed, so the thin CLI works without the MCP SDK. The
pydantic response model lives in backend/mcp_server.py instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class RunStatus:
    """Run lifecycle states.

    queued -> crawling -> analyzing -> exporting -> completed
                       +-> cancelling -> cancelled
                       +-> failed
    """

    QUEUED = "queued"
    CRAWLING = "crawling"
    ANALYZING = "analyzing"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"

    TERMINAL = frozenset({COMPLETED, CANCELLED, FAILED})


class ErrorCode:
    BUSY = "BUSY"
    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    NO_CREDENTIALS = "NO_CREDENTIALS"
    CRAWL_FAILED = "CRAWL_FAILED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    CANCELLED = "CANCELLED"


class TaskKind:
    CRAWL = "crawl"
    ANALYZE = "analyze"
    CRAWL_AND_ANALYZE = "crawl_and_analyze"


# --- Abuse controls -------------------------------------------------------
# The desktop app defaults to 100 pages behind a human clicking a button. An
# MCP tool can be invoked by any agent in a loop, so the headless defaults are
# far lower and the ceiling cannot be raised through tool arguments.
MAX_PAGES_DEFAULT = 5
MAX_PAGES_CEILING = 50
SAMPLE_SIZE_DEFAULT = 300
WAIT_SECONDS_DEFAULT = 90
WAIT_SECONDS_CEILING = 600

# --- Analysis defaults ----------------------------------------------------
# NOTE: LLMAnalysisProcessor._normalize_chart_keys ends in `return selected or
# allowed_keys`, so passing an empty list silently re-enables EVERY chart
# including word_cloud. This list must stay explicit and non-empty. Word cloud
# is excluded on purpose: an agent cannot use a PNG, and rendering it pulls in
# matplotlib font-cache work that costs tens of seconds on a cold start.
AGENT_CHART_KEYS = [
    "sentiment_distribution",
    "topic_ranking",
    "time_trend",
    "level_distribution",
    "region_map",
    "deep_analysis",
]

# --- Untrusted-content handling -------------------------------------------
# Everything derived from Bilibili comments is attacker-controlled text that
# ends up inside the calling agent's context. Mark it, and keep it short.
UNTRUSTED_OPEN = "<untrusted-data>"
UNTRUSTED_CLOSE = "</untrusted-data>"
SUMMARY_CHAR_LIMIT = 2000


def clamp_int(value: Any, default: int, low: int, high: int) -> int:
    """Coerce value to an int inside [low, high], falling back to default."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


@dataclass(frozen=True)
class CallerPolicy:
    """Static limits that belong to a caller, not to a single request.

    Deliberately holds no credentials. An API key is scoped to one analysis
    call, so it travels as an argument and is never stored on a long-lived
    object that could reach a repr, a log line or a manifest.

    The defaults are the agent's: conservative page limits, and a chart set that
    excludes the word cloud because an agent cannot use a PNG. The desktop needs
    the opposite on both counts, which is what DESKTOP_POLICY expresses.
    """

    max_pages_default: int = MAX_PAGES_DEFAULT
    # None means "no ceiling": the caller's own number is honoured.
    max_pages_ceiling: int | None = MAX_PAGES_CEILING
    # None means "do not force a set"; the processor applies its own default.
    default_chart_keys: tuple[str, ...] | None = tuple(AGENT_CHART_KEYS)

    def __post_init__(self) -> None:
        # A misconfigured policy would otherwise hand the crawler a page count
        # of zero or a negative one, which no downstream code checks for.
        if self.max_pages_default < 1:
            raise ValueError(f"max_pages_default must be >= 1, got {self.max_pages_default}")
        if self.max_pages_ceiling is not None:
            if self.max_pages_ceiling < 1:
                raise ValueError(f"max_pages_ceiling must be >= 1, got {self.max_pages_ceiling}")
            if self.max_pages_ceiling < self.max_pages_default:
                raise ValueError(
                    "max_pages_ceiling must not be below max_pages_default: "
                    f"{self.max_pages_ceiling} < {self.max_pages_default}"
                )
        if self.default_chart_keys is not None and not self.default_chart_keys:
            # _normalize_chart_keys reads an empty list as "give me everything",
            # so an empty default would silently re-enable the word cloud.
            raise ValueError("default_chart_keys must be None or non-empty")

    def resolve_max_pages(self, value: Any) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return self.max_pages_default
        number = max(1, number)
        if self.max_pages_ceiling is not None:
            number = min(number, self.max_pages_ceiling)
        return number

    def resolve_chart_keys(self, requested: Any = None) -> list[str] | None:
        """Pick the chart set for one analysis.

        A non-empty request wins; otherwise the policy default applies.
        Returning None tells the caller to omit chart_keys entirely -- passing
        an empty list instead would make _normalize_chart_keys fall back to the
        full set, word cloud included.
        """
        if isinstance(requested, (list, tuple)) and requested:
            return [str(item) for item in requested]
        if self.default_chart_keys is None:
            return None
        return list(self.default_chart_keys)


# What every MCP tool and the CLI run under.
AGENT_POLICY = CallerPolicy()

# What backend/sidecar.py will pass once the migration wires it up: the desktop
# default of 100 pages, no ceiling, and whatever chart set the UI ticked.
DESKTOP_POLICY = CallerPolicy(
    max_pages_default=100,
    max_pages_ceiling=None,
    default_chart_keys=None,
)


@dataclass
class TaskSnapshot:
    """Immutable view of a task's state, safe to hand to any adapter."""

    task_id: str
    run_id: str
    kind: str
    status: str
    stage: str = ""
    percent: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    summary: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None

    @property
    def done(self) -> bool:
        return self.status in RunStatus.TERMINAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "kind": self.kind,
            "status": self.status,
            "stage": self.stage,
            "percent": self.percent,
            "counts": dict(self.counts),
            "summary": self.summary,
            "artifacts": dict(self.artifacts),
            "warnings": list(self.warnings),
            "error": self.error,
            "error_code": self.error_code,
            "done": self.done,
        }


class ServiceError(RuntimeError):
    """Business error with a machine-readable code and a human message."""

    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(message)
        self.code = code
        self.context = context


def mark_untrusted(text: Any, limit: int = SUMMARY_CHAR_LIMIT) -> str:
    """Wrap attacker-controlled text so the calling agent treats it as data.

    Comment text is written by strangers, and an LLM summary derived from it can
    carry injected instructions just as easily as the raw comments can. Anything
    that crosses into a calling agent's context goes through here.
    """
    body = str(text or "").strip()
    if not body:
        return ""
    if len(body) > limit:
        body = body[:limit].rstrip() + "…（已截断）"
    return f"{UNTRUSTED_OPEN}\n{body}\n{UNTRUSTED_CLOSE}"
