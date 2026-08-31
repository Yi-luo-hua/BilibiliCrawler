"""Safe provider failure classification. Never reflect remote error text."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from urllib3.exceptions import ReadTimeoutError

from src.service.models import ErrorCode


class AnalysisError(RuntimeError):
    def __init__(self, message: str, *, code: str = ErrorCode.ANALYSIS_FAILED):
        super().__init__(message)
        self.code = code


class AnalysisCancelled(AnalysisError):
    """Raised when the user cancels an analysis task."""


class ProviderError(AnalysisError):
    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 retry_after: float | None = None, drop_response_format: bool = False):
        super().__init__(message, code=code)
        self.retryable = retryable
        self.retry_after = retry_after
        self.drop_response_format = drop_response_format


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def classify_http_error(response: requests.Response) -> ProviderError:
    status = response.status_code
    # Auth status wins over all attacker-controlled fields in the body.
    if status in {401, 403}:
        return ProviderError(ErrorCode.LLM_AUTH, f"LLM 鉴权或访问权限失败（HTTP {status}），请检查 API Key 与服务权限。")
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = body.get("error", {}) if isinstance(body, dict) else {}
    error = error if isinstance(error, dict) else {}
    codes = {value.lower() for value in (error.get("code"), error.get("type")) if isinstance(value, str)}
    param = str(error.get("param") or "").lower()
    if status == 429:
        quota = bool(codes & {"insufficient_quota", "billing_hard_limit_reached", "quota_exceeded"})
        return ProviderError(ErrorCode.LLM_RATE_LIMIT,
                             "LLM 额度不足，请检查账户额度。" if quota else "LLM 请求受限（HTTP 429），请稍后重试。",
                             retryable=not quota, retry_after=retry_after_seconds(response.headers.get("Retry-After")))
    if status in {400, 404, 422} and (param == "model" or codes & {"model_not_found", "invalid_model", "model_not_supported"}):
        return ProviderError(ErrorCode.LLM_MODEL, "LLM 模型配置不可用，请核对模型名称及访问权限。")
    if status in {400, 422}:
        message = error.get("message")
        message = message.lower() if isinstance(message, str) else ""
        unsupported = bool(codes & {"unsupported_parameter", "unsupported_value", "not_supported"})
        # A precise provider rejection permits one format fallback. An
        # arbitrary 400/404 cannot establish which field caused the failure.
        format_rejected = param in {"", "response_format"} and (
            (param == "response_format" and unsupported) or bool(re.search(
                r'''response_format['"]?\s+(?:is\s+)?(?:not supported|unsupported|not recognized)'''
                r'''|(?:unsupported|unrecognized|unknown)\s+(?:parameter\s*:?\s*)?['"]?response_format\b''',
                message,
            ))
        )
        return ProviderError(ErrorCode.LLM_REQUEST_INVALID, f"LLM 请求配置不被接受（HTTP {status}），请核对服务支持的参数。",
                             drop_response_format=format_rejected)
    if status in {404, 405} or 300 <= status < 400:
        return ProviderError(ErrorCode.LLM_ENDPOINT, f"LLM 端点或路由不可用（HTTP {status}），请核对 base_url 与模型配置。")
    if status in {500, 502, 503, 504}:
        return ProviderError(ErrorCode.LLM_UNAVAILABLE, f"LLM 服务暂时不可用（HTTP {status}），请稍后重试。",
                             retryable=True, retry_after=retry_after_seconds(response.headers.get("Retry-After")))
    if status == 408:
        return ProviderError(ErrorCode.LLM_TIMEOUT, "LLM 请求超时（HTTP 408）；可能已处理，为避免重复计费不自动重放。")
    return ProviderError(ErrorCode.LLM_REQUEST_INVALID, f"LLM 请求失败（HTTP {status}），请检查服务配置。")


def classify_transport_error(error: requests.RequestException) -> ProviderError:
    if isinstance(error, requests.exceptions.SSLError):
        return ProviderError(ErrorCode.LLM_TLS, "LLM TLS 连接失败，请检查证书、系统时间或代理；不要关闭证书验证。")
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return ProviderError(ErrorCode.LLM_TIMEOUT, "LLM 连接超时，请检查网络或稍后重试。", retryable=True)
    if isinstance(error, requests.exceptions.Timeout) or _contains_read_timeout(error):
        return ProviderError(ErrorCode.LLM_TIMEOUT, "LLM 响应超时；可能已处理，为避免重复计费不自动重放。")
    if isinstance(error, (requests.exceptions.InvalidURL, requests.exceptions.InvalidSchema,
                          requests.exceptions.MissingSchema, requests.exceptions.InvalidHeader)):
        return ProviderError(ErrorCode.LLM_REQUEST_INVALID, "LLM 地址或请求头配置无效，请检查配置。")
    return ProviderError(ErrorCode.LLM_NETWORK, "LLM 网络连接失败；可能已发送请求，请检查网络后再决定是否重试。")


def _contains_read_timeout(error: BaseException) -> bool:
    # requests wraps response-body timeouts in ConnectionError. Inspect types,
    # never exception strings (which can contain credentials or remote text).
    pending, seen = [error], set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, ReadTimeoutError):
            return True
        pending.extend(value for value in (item.__cause__, item.__context__, *item.args)
                       if isinstance(value, BaseException))
    return False
