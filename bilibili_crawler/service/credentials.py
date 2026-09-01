"""
LLM credential resolution for headless runs.

The desktop app already stores the user's key via the Rust command
``write_llm_api_key`` at ``<user_data_dir>/config/credentials.json``
(desktop/src-tauri/src/main.rs). Reading that file back means a user who
configured the GUI does not have to copy a plaintext key into their MCP host
config, which is typically world-readable and frequently pasted into issues.

Resolution order per field:
  1. Nonempty BILIBILI_LLM_API_KEY / BILIBILI_LLM_BASE_URL / BILIBILI_LLM_MODEL
  2. One credentials.json + adjacent ui.json profile, explicitly selected by
     BILIBILI_AGENT_CREDENTIALS or auto-discovered in this order:
       <repo>/.install-test/user-data/config/credentials.json   (debug layout)
       %LOCALAPPDATA%/BilibiliCrawler/user-data/config/...      (currentUser install)
       %PROGRAMFILES%[ (x86)]/BilibiliCrawler/user-data/...     (perMachine install)
  3. Compatible OpenAI endpoint/model defaults.

A selected malformed profile fails closed; explicit paths never fall through
to another installation. Fully specified environment settings skip file reads.

An installed build keeps user data next to the executable
(<install dir>/user-data), which a source checkout cannot derive, so discovery
probes the installer's default targets instead. A non-default install location
still needs BILIBILI_AGENT_CREDENTIALS or the environment variables.

The key is never logged, never written to a manifest, and never included in an
error message; text echoed back by a provider is scrubbed via scrub().
"""
from __future__ import annotations

import json
import logging
import os
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bilibili_crawler.service.models import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL, ErrorCode, ServiceError
from bilibili_crawler.service.paths import ROOT, SOURCE_CHECKOUT, user_config_dir

ENV_API_KEY = "BILIBILI_LLM_API_KEY"
ENV_BASE_URL = "BILIBILI_LLM_BASE_URL"
ENV_MODEL = "BILIBILI_LLM_MODEL"
ENV_CREDENTIALS_FILE = "BILIBILI_AGENT_CREDENTIALS"

_DEV_CREDENTIALS = ROOT / ".install-test" / "user-data" / "config" / "credentials.json"


# Every key we have ever held, so error text echoed back by a provider can be
# scrubbed before it reaches a manifest, a log line or a tool result. An upstream
# 401 body that quotes the key back at us is the realistic leak path.
_KNOWN_SECRETS: set[str] = set()
REDACTED = "***"


def register_secret(value: str) -> None:
    text = str(value or "").strip()
    # Short values would scrub harmless substrings out of unrelated messages.
    if len(text) >= 8:
        _KNOWN_SECRETS.add(text)


def scrub(text: Any) -> str:
    """Replace any known credential occurring in text."""
    register_env_secrets()
    rendered = str(text or "")
    for secret in _KNOWN_SECRETS:
        if secret in rendered:
            rendered = rendered.replace(secret, REDACTED)
    return rendered


def register_env_secrets() -> None:
    """Register keys visible in the environment.

    Registration must not depend on credentials having been resolved: a crawl
    task never calls the resolver, yet its logs and errors still need scrubbing.
    """
    register_secret(os.environ.get(ENV_API_KEY, ""))


class SecretScrubbingFilter(logging.Filter):
    """Scrub credentials from every log record, whoever emitted it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never break logging
            return True
        scrubbed = scrub(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        if record.exc_info:
            # Rendering it here means the traceback text is scrubbed too.
            record.exc_text = scrub("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        return True


def install_log_scrubbing(logger: logging.Logger | None = None) -> None:
    target = logger if logger is not None else logging.getLogger()
    if not any(isinstance(f, SecretScrubbingFilter) for f in target.filters):
        target.addFilter(SecretScrubbingFilter())
    for handler in target.handlers:
        if not any(isinstance(f, SecretScrubbingFilter) for f in handler.filters):
            handler.addFilter(SecretScrubbingFilter())


@dataclass(frozen=True)
class LLMCredentials:
    """An API key plus endpoint settings. Never render this with str()/repr()."""

    api_key: str
    base_url: str = ""
    model: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        # Registering here (rather than only in resolve_llm_credentials) means
        # every path that builds credentials, tests included, is covered.
        register_secret(self.api_key)

    def __repr__(self) -> str:
        def safe(value: str) -> str:
            # Mask before repr escapes quotes or backslashes in a credential.
            return scrub(value).replace(self.api_key, REDACTED) if self.api_key else scrub(value)

        return f"LLMCredentials(api_key='***', base_url={safe(self.base_url)!r}, model={safe(self.model)!r}, source={safe(self.source)!r})"

    __str__ = __repr__

    @classmethod
    def from_config(cls, config: Any, source: str = "request") -> "LLMCredentials":
        """Build credentials from an RPC-shaped llm_config mapping.

        The desktop sends {api_key, base_url, model} inside its analysis
        request. Giving callers this instead of letting them pass the raw dict
        keeps the service's own signature typed.
        """
        if isinstance(config, cls):
            return config
        if not isinstance(config, dict):
            raise TypeError(f"llm_config must be a mapping, got {type(config).__name__}")
        return cls(
            api_key=str(config.get("api_key") or "").strip(),
            base_url=str(config.get("base_url") or "").strip(),
            model=str(config.get("model") or "").strip(),
            source=source,
        )

    def to_llm_config(self) -> dict[str, str]:
        """Build the dict LLMAnalysisProcessor.analyze expects under 'llm_config'.

        Empty base_url/model are passed through so the processor applies its own
        DEFAULT_BASE_URL / DEFAULT_MODEL, matching desktop behaviour.
        """
        return {"api_key": self.api_key, "base_url": self.base_url, "model": self.model}


def _config_error(location: str, detail: str) -> ServiceError:
    # Only fixed labels, never paths, raw values or JSON/OS exception strings.
    return ServiceError(ErrorCode.CONFIG_INVALID, f"LLM 配置错误（{location}）：{detail}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _read_profile_file(path: Path, label: str, *, required: bool = False) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        if required:
            raise _config_error(label, "文件不存在；请检查 BILIBILI_AGENT_CREDENTIALS。") from None
        return {}
    except (OSError, UnicodeDecodeError, ValueError):
        raise _config_error(label, "无法读取 UTF-8 文件；请检查文件权限与编码。") from None
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        raise _config_error(label, "JSON 损坏或存在重复字段；请修正配置。") from None
    if not isinstance(payload, dict):
        raise _config_error(label, "顶层必须是 JSON 对象。")
    return payload


def _profile_string(payload: dict[str, Any], field: str, label: str) -> str:
    value = payload.get(field, "")
    if not isinstance(value, str):
        raise _config_error(label, f"{field} 必须是字符串。")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _config_error(label, f"{field} 不得包含控制字符。")
    return value.strip()


def _validate_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                 and parsed.username is None and parsed.password is None
                 and not parsed.query and not parsed.fragment
                 and not any(char.isspace() for char in value))
        # Accessing port validates malformed and out-of-range ports.
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise _config_error("base_url", "请使用完整 HTTP(S) 地址，不要在地址中放用户名、密码、查询参数或片段。")
    return value.rstrip("/")


@dataclass(frozen=True)
class LLMProfile:
    """Resolved credentials and non-secret provenance; never persisted."""

    credentials: LLMCredentials
    field_sources: dict[str, str]

    def diagnostic_fields(self) -> dict[str, Any]:
        key = self.credentials.api_key

        def safe(value: str) -> str:
            return scrub(value).replace(key, REDACTED) if key else scrub(value)

        return {
            "credential_source": self.field_sources["api_key"],
            "base_url": safe(self.credentials.base_url),
            "model": safe(self.credentials.model),
            "field_sources": dict(self.field_sources),
        }


# tauri.conf.json sets productName "BilibiliCrawler" and installMode
# "currentUser". The NSIS template bundled with Tauri 2.11.2 installs a
# currentUser build to $LOCALAPPDATA\\${PRODUCTNAME} and a perMachine build to
# $PROGRAMFILES64\\${PRODUCTNAME} -- no "Programs" segment and no manufacturer
# folder. main.rs then keeps user data at <install dir>/user-data.
PRODUCT_NAME = "BilibiliCrawler"
_USER_DATA_RELATIVE = Path("user-data") / "config" / "credentials.json"


def _installed_credential_paths() -> list[Path]:
    """Best-effort discovery of an installed desktop build's user-data.

    The Rust side derives this from the executable's own location, which a
    source checkout cannot know, so these are the installer's default targets.
    """
    roots = [
        os.environ.get("LOCALAPPDATA"),      # currentUser (the configured default)
        os.environ.get("PROGRAMFILES"),      # perMachine, 64-bit
        os.environ.get("PROGRAMFILES(X86)"),  # perMachine, 32-bit
    ]
    return [
        Path(root) / PRODUCT_NAME / _USER_DATA_RELATIVE
        for root in roots
        if root
    ]


def credential_file_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.environ.get(ENV_CREDENTIALS_FILE, "").strip()
    if explicit:
        # An explicitly selected profile must never fall through to a different
        # installation (and potentially send its key to the wrong provider).
        try:
            return [Path(explicit).expanduser()]
        except (ValueError, RuntimeError):
            raise _config_error("BILIBILI_AGENT_CREDENTIALS", "无法解析路径；请使用有效的文件绝对路径。") from None
    if SOURCE_CHECKOUT:
        candidates.append(_DEV_CREDENTIALS)
        candidates.extend(_installed_credential_paths())
        candidates.append(user_config_dir() / "credentials.json")
    else:
        candidates.append(user_config_dir() / "credentials.json")
        candidates.extend(_installed_credential_paths())
    return candidates


def resolve_llm_profile() -> LLMProfile:
    """Resolve env > one credentials/ui pair > compatible OpenAI defaults.

    Empty environment fields do not override a profile. Fully explicit env
    configuration does not consult files. Invalid selected files fail closed.
    """
    variables = {"api_key": ENV_API_KEY, "base_url": ENV_BASE_URL, "model": ENV_MODEL}
    values = {
        field: (_profile_string(os.environ, variable, "环境变量")
                if os.environ.get(variable, "").strip() else "")
        for field, variable in variables.items()
    }
    sources = {field: "env" for field, value in values.items() if value}
    register_secret(values["api_key"])
    explicit = bool(os.environ.get(ENV_CREDENTIALS_FILE, "").strip())

    if not all(values.values()):
        for candidate in credential_file_candidates():
            label = "显式 credentials.json" if explicit else "自动发现 credentials.json"
            payload = _read_profile_file(candidate, label, required=explicit)
            # Register even an overridden key before any public diagnostics.
            file_key = payload.get("api_key", "")
            if isinstance(file_key, str):
                register_secret(file_key)
            if not values["api_key"]:
                file_key = _profile_string(payload, "api_key", label)
            ui_path = candidate.with_name("ui.json")
            if not explicit and not file_key and not (
                values["api_key"] and (payload or ui_path.is_file())
            ):
                continue
            if not values["api_key"] and file_key:
                values["api_key"] = file_key
                sources["api_key"] = "explicit_file" if explicit else "discovered_file"
            ui = (_read_profile_file(ui_path, "相邻 ui.json")
                  if not values["base_url"] or not values["model"] else {})
            for field in ("base_url", "model"):
                if values[field]:
                    continue
                stored = _profile_string(payload, field, label)
                desktop = _profile_string(ui, f"llm_{field}", "相邻 ui.json")
                if field == "base_url":
                    stored, desktop = stored.rstrip("/"), desktop.rstrip("/")
                if stored and desktop and stored != desktop:
                    raise _config_error(field, f"credentials.json 与 ui.json 冲突；请统一配置或设置 {variables[field]}。")
                values[field] = desktop or stored
                if values[field]:
                    sources[field] = "ui_file" if desktop else "credentials_file"
            break  # Never mix endpoint/model from another installation.

    if not values["api_key"]:
        raise ServiceError(
            ErrorCode.NO_CREDENTIALS,
            "缺少 LLM API Key。请设置 BILIBILI_LLM_API_KEY，或检查 "
            "BILIBILI_AGENT_CREDENTIALS 指向的 credentials.json"
            "（安装版位于 <安装目录>/user-data/config/credentials.json）。",
        )
    try:
        values["api_key"].encode("latin-1")
    except UnicodeEncodeError:
        raise _config_error("api_key", "无法编码为 HTTP 请求头；请检查是否误填中文说明或损坏字符。") from None
    for field, default in (("base_url", DEFAULT_LLM_BASE_URL), ("model", DEFAULT_LLM_MODEL)):
        if not values[field]:
            values[field] = default
            sources[field] = "default"
    values["base_url"] = _validate_base_url(values["base_url"])
    credentials = LLMCredentials(**values, source="env" if sources["api_key"] == "env" else "file:credentials.json")
    return LLMProfile(credentials, sources)


def resolve_llm_credentials() -> LLMCredentials:
    """Shared resolver for CLI/MCP; desktop request credentials remain explicit."""
    return resolve_llm_profile().credentials


def has_llm_credentials() -> bool:
    try:
        resolve_llm_credentials()
    except ServiceError:
        return False
    return True


# Register at import so scrubbing works even for tasks that never resolve
# credentials, such as a crawl-only run.
register_env_secrets()
