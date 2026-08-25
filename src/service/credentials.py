"""
LLM credential resolution for headless runs.

The desktop app already stores the user's key via the Rust command
``write_llm_api_key`` at ``<user_data_dir>/config/credentials.json``
(desktop/src-tauri/src/main.rs). Reading that file back means a user who
configured the GUI does not have to copy a plaintext key into their MCP host
config, which is typically world-readable and frequently pasted into issues.

Resolution order:
  1. BILIBILI_LLM_API_KEY / BILIBILI_LLM_BASE_URL / BILIBILI_LLM_MODEL
  2. BILIBILI_AGENT_CREDENTIALS -> explicit path to a credentials.json
  3. auto-discovery, in order:
       <repo>/.install-test/user-data/config/credentials.json   (debug layout)
       %LOCALAPPDATA%/BilibiliCrawler/user-data/config/...      (currentUser install)
       %PROGRAMFILES%[ (x86)]/BilibiliCrawler/user-data/...     (perMachine install)

An installed build keeps user data next to the executable
(<install dir>/user-data), which a source checkout cannot derive, so step 3
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

from src.service.models import ErrorCode, ServiceError
from src.service.paths import ROOT

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
        return f"LLMCredentials(api_key='***', base_url={self.base_url!r}, model={self.model!r}, source={self.source!r})"

    __str__ = __repr__

    def to_llm_config(self) -> dict[str, str]:
        """Build the dict LLMAnalysisProcessor.analyze expects under 'llm_config'.

        Empty base_url/model are passed through so the processor applies its own
        DEFAULT_BASE_URL / DEFAULT_MODEL, matching desktop behaviour.
        """
        return {"api_key": self.api_key, "base_url": self.base_url, "model": self.model}


def _read_credentials_file(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("api_key") or "").strip()


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
        candidates.append(Path(explicit).expanduser())
    candidates.append(_DEV_CREDENTIALS)
    candidates.extend(_installed_credential_paths())
    return candidates


def resolve_llm_credentials() -> LLMCredentials:
    """Return usable LLM credentials or raise ServiceError(NO_CREDENTIALS)."""
    base_url = os.environ.get(ENV_BASE_URL, "").strip()
    model = os.environ.get(ENV_MODEL, "").strip()

    api_key = os.environ.get(ENV_API_KEY, "").strip()
    if api_key:
        return LLMCredentials(api_key=api_key, base_url=base_url, model=model, source="env")

    for candidate in credential_file_candidates():
        api_key = _read_credentials_file(candidate)
        if api_key:
            return LLMCredentials(
                api_key=api_key,
                base_url=base_url,
                model=model,
                source=f"file:{candidate.name}",
            )

    raise ServiceError(
        ErrorCode.NO_CREDENTIALS,
        "缺少 LLM API Key。请设置环境变量 BILIBILI_LLM_API_KEY，"
        f"或用 {ENV_CREDENTIALS_FILE} 指向桌面端的 credentials.json"
        "（安装版位于 <安装目录>/user-data/config/credentials.json）。",
    )


def has_llm_credentials() -> bool:
    try:
        resolve_llm_credentials()
    except ServiceError:
        return False
    return True


# Register at import so scrubbing works even for tasks that never resolve
# credentials, such as a crawl-only run.
register_env_secrets()
