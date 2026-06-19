from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FailureAdvice:
    category: str
    next_step: str
    retryable: bool = True


class DouyinMonitorError(Exception):
    category = "执行失败"
    retryable = True
    next_step = "建议重试；如果重复失败，请导出诊断包。"

    def advice(self) -> FailureAdvice:
        return FailureAdvice(self.category, self.next_step, self.retryable)


class ParserError(DouyinMonitorError):
    category = "解析失败"
    next_step = "重新同步作品或复制作品链接到视频解析页重试。"


class CookieExpiredError(ParserError):
    category = "登录或风控"
    next_step = "更新 Cookie，确认页面可公开访问，然后重试。"


class RiskControlError(ParserError):
    category = "登录或风控"
    next_step = "降低频率，更新 Cookie，必要时稍后重试。"


class DownloadError(DouyinMonitorError):
    category = "下载失败"
    next_step = "检查网络、下载目录权限和磁盘空间后重试。"


class StorageError(DouyinMonitorError):
    category = "文件保存"
    next_step = "检查下载目录是否存在、是否有写入权限，必要时更换保存路径。"


class ConfigError(DouyinMonitorError):
    category = "配置异常"
    next_step = "检查设置项或恢复最近的配置备份。"


def classify_failure(reason: str) -> FailureAdvice:
    text = str(reason or "").strip()
    lower = text.lower()
    if not text:
        return FailureAdvice("未知错误", "建议重试；如果重复失败，请导出诊断包。")
    if any(key in text for key in ("Cookie", "登录", "风控", "验证码", "权限", "403")):
        return FailureAdvice("登录或风控", "更新 Cookie，确认页面可公开访问，然后重试。")
    if any(key in lower for key in ("timeout", "timed out", "readtimeout")) or "超时" in text:
        return FailureAdvice("网络超时", "降低并发或稍后重试；代理不稳定时请先关闭代理测试。")
    if any(key in lower for key in ("connection", "network", "proxy", "dns")) or any(key in text for key in ("网络", "代理", "连接")):
        return FailureAdvice("网络连接", "检查网络和代理地址，确认浏览器能打开作品链接。")
    if any(key in text for key in ("404", "不存在", "删除", "失效")):
        return FailureAdvice("作品失效", "打开原链接确认作品是否仍存在；失效作品可跳过。", retryable=False)
    if any(key in text for key in ("解析", "直链", "未获取", "地址")):
        return FailureAdvice("解析失败", "重新同步作品或复制作品链接到视频解析页重试。")
    if any(key in text for key in ("文件", "权限", "保存", "写入", "磁盘", "空间")):
        return FailureAdvice("文件保存", "检查下载目录是否存在、是否有写入权限，必要时更换保存路径。")
    return FailureAdvice("执行失败", "建议重试；如果重复失败，请导出诊断包。")
