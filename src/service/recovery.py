"""Recovery guidance shared by the CLI and MCP adapters."""
from src.service.models import ErrorCode, RunStatus, TaskSnapshot


def analysis_recovery_hint(snapshot: TaskSnapshot, *, cli: bool = False) -> str:
    if (snapshot.status != RunStatus.FAILED or not snapshot.run_id
            or "comments_json" not in snapshot.artifacts
            or not (snapshot.error_code == ErrorCode.ANALYSIS_FAILED
                    or str(snapshot.error_code).startswith("LLM_"))):
        return ""
    guidance = {
        ErrorCode.LLM_AUTH: "请修正 API Key 或服务权限，可先运行 doctor 检查配置。",
        ErrorCode.LLM_MODEL: "请修正模型名称或模型访问权限。",
        ErrorCode.LLM_ENDPOINT: "请核对 base_url 的 API 路由与模型配置。",
        ErrorCode.LLM_REQUEST_INVALID: "请核对服务支持的请求参数与配置。",
        ErrorCode.LLM_TLS: "请修复证书、系统时间或代理设置，不要关闭证书验证。",
        ErrorCode.LLM_RATE_LIMIT: "请检查额度或等待限流解除。",
        ErrorCode.LLM_UNAVAILABLE: "请等待服务恢复。",
        ErrorCode.LLM_TIMEOUT: "请检查网络与服务状态；请求可能已消费额度，确认后再重试。",
        ErrorCode.LLM_NETWORK: "请检查网络；请求可能已发送，确认后再重试。",
        ErrorCode.LLM_RESPONSE_INVALID: "请检查模型输出能力或调整配置。",
    }.get(snapshot.error_code, "请检查分析错误说明。")
    command = (f"python -m backend.agent analyze-run {snapshot.run_id}" if cli else
               f'analyze_run(run_id="{snapshot.run_id}")')
    return f"评论已保留，无需重新爬取。{guidance}之后使用 {command} 复用原 run 分析。"
