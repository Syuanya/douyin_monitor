from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParserFailureAssessment:
    category: str
    retryable: bool
    user_action_required: bool
    detail: str


_RISK_CONTROL_MARKERS = (
    "captcha",
    "verify",
    "验证",
    "风控",
    "risk",
    "security",
    "访问频繁",
    "too many requests",
    "rate limit",
    "429",
    "响应内容为空",
    "空响应",
    "empty response",
    "http 200 空响应",
)

_AUTH_MARKERS = (
    "cookie",
    "login",
    "登录",
    "unauthorized",
    "forbidden",
    "403",
)

_NOT_FOUND_MARKERS = (
    "404",
    "not found",
    "不存在",
    "删除",
    "private",
    "私密",
)

_NETWORK_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "network",
    "dns",
    "proxy",
    "ssl",
    "tls",
    "连接",
    "超时",
)


def classify_parser_failure(error: object) -> ParserFailureAssessment:
    """Classify parser failures into stable categories for UI/retry decisions."""

    text = str(error or "").strip()
    lowered = text.lower()
    if not lowered:
        return ParserFailureAssessment(
            category="unknown",
            retryable=False,
            user_action_required=True,
            detail="未返回明确错误信息，需要查看诊断日志。",
        )

    if _contains_any(lowered, _RISK_CONTROL_MARKERS):
        return ParserFailureAssessment(
            category="risk_control",
            retryable=False,
            user_action_required=True,
            detail="平台触发验证、限流或风控，程序不应自动绕过；请降低频率并在浏览器确认账号状态。",
        )
    if _contains_any(lowered, _AUTH_MARKERS):
        return ParserFailureAssessment(
            category="auth_required",
            retryable=False,
            user_action_required=True,
            detail="Cookie/登录状态不可用或权限不足，请更新 Cookie 后重试。",
        )
    if _contains_any(lowered, _NOT_FOUND_MARKERS):
        return ParserFailureAssessment(
            category="not_found_or_private",
            retryable=False,
            user_action_required=False,
            detail="作品不存在、已删除或不可公开访问。",
        )
    if _contains_any(lowered, _NETWORK_MARKERS):
        return ParserFailureAssessment(
            category="network",
            retryable=True,
            user_action_required=False,
            detail="网络、代理或 TLS 连接异常，可稍后重试。",
        )
    return ParserFailureAssessment(
        category="parser_error",
        retryable=True,
        user_action_required=False,
        detail="解析器返回未分类错误，可重试；若持续失败请导出诊断报告。",
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)
