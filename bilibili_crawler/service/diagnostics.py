"""Read-only CLI diagnostics. Never instantiate RunStore or send a chat request."""
from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
from typing import Any

from bilibili_crawler.service.credentials import LLMProfile, resolve_llm_profile, scrub
from bilibili_crawler.service.models import ServiceError
from bilibili_crawler.service.paths import RUNS_DIR_ENV, RUNS_DIR_NAME, candidate_bases


def inspect_runs_directory() -> dict[str, Any]:
    """Estimate permissions without mkdir, migration or a temporary write probe.

    In particular os.access cannot prove Windows ACL writability. Report the
    limitation explicitly; the real RunStore still uses its existing probe.
    """
    override = os.environ.get(RUNS_DIR_ENV, "").strip()
    result: dict[str, Any] = {
        "path": "", "writable_hint": False, "check": "permissions_only",
        "note": "只读权限估计，未创建目录或试写文件；Windows ACL 与实际可写性仍须运行时确认。",
    }
    try:
        candidates = ([Path(override).expanduser()] if override else
                      [base / RUNS_DIR_NAME for base in candidate_bases()])
    except (OSError, ValueError, RuntimeError):
        result["note"] = "无法解析运行目录；请检查 BILIBILI_AGENT_RUNS_DIR 路径。"
        return result
    for candidate in candidates:
        try:
            result["path"] = str(candidate.absolute())
            parent = candidate
            while not parent.exists() and parent.parent != parent:
                parent = parent.parent
            result["writable_hint"] = parent.is_dir() and os.access(parent, os.W_OK)
        except (OSError, ValueError):
            result["path"] = ""
            result["writable_hint"] = False
        if result["writable_hint"]:
            break
    return result


def _check_provider(profile: LLMProfile, timeout: float) -> dict[str, Any]:
    # Opt-in only. No prompts, no paid completion, no raw provider response body,
    # no redirects carrying Authorization, no proxy/netrc ambient credentials.
    import requests

    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(
                profile.credentials.base_url + "/models",
                headers={"Authorization": f"Bearer {profile.credentials.api_key}"},
                timeout=timeout, allow_redirects=False, stream=True,
            ) as response:
                status = response.status_code
    except requests.Timeout:
        return {"ok": False, "error_code": "PROVIDER_TIMEOUT", "error": "连接或等待响应超时。"}
    except requests.RequestException:
        return {"ok": False, "error_code": "PROVIDER_NETWORK", "error": "连接失败；请检查服务地址、网络与 TLS 证书。"}
    except UnicodeError:
        return {"ok": False, "error_code": "CONFIG_INVALID", "error": "请求配置包含无法编码的字符；请检查 Key 和服务地址。"}
    if 200 <= status < 300:
        return {"ok": True, "http_status": status,
                "note": "GET /models 可访问；未验证所选模型或 chat/completions，未发送分析内容。"}
    if status in (401, 403):
        code, message = "PROVIDER_AUTH", "服务拒绝鉴权；请检查 Key 与访问权限。"
    elif 300 <= status < 400:
        code, message = "PROVIDER_REDIRECT", "未跟随重定向；请直接配置最终服务地址。"
    else:
        code, message = "PROVIDER_HTTP", "模型列表检查失败；部分服务不支持 GET /models，这不等于分析接口不可用。"
    return {"ok": False, "http_status": status, "error_code": code, "error": message}


def diagnose(*, check_provider: bool = False, timeout: float = 10.0) -> dict[str, Any]:
    if not 0 < timeout <= 60:
        raise ValueError("timeout must be greater than 0 and at most 60 seconds")
    try:
        version = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        version = None
    payload: dict[str, Any] = {
        "ok": True,
        "mcp": {"installed": version is not None, "version": version,
                "note": "MCP 服务需要 bilibili-crawler[mcp]（源码可用 requirements-agent.txt）；普通 CLI 和本诊断不要求安装 SDK。"},
        "runs": inspect_runs_directory(),
    }
    profile = None
    try:
        profile = resolve_llm_profile()
        payload["profile"] = {"ok": True, **profile.diagnostic_fields()}
    except ServiceError as exc:
        payload["profile"] = {"ok": False, "error_code": exc.code, "error": scrub(str(exc))}
        payload["ok"] = False
    if not payload["runs"]["writable_hint"]:
        payload["ok"] = False
    if check_provider and profile is not None:
        payload["provider"] = _check_provider(profile, timeout)
        payload["ok"] = payload["ok"] and payload["provider"]["ok"]
    else:
        payload["provider"] = {"checked": False}
    # Protect every string boundary, including paths and accidental key echoes
    # in model names. No API key field or suffix is ever returned.
    def safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [safe(item) for item in value]
        if isinstance(value, str):
            rendered = scrub(value)
            # Also mask short keys without rewriting the diagnostic schema.
            if profile is not None:
                rendered = rendered.replace(profile.credentials.api_key, "***")
            return rendered
        return value

    return safe(payload)
