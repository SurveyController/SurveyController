from __future__ import annotations

from typing import Any

from software.application.interactions import InteractionKind, InteractionRequest
from software.application.models import RuntimeSnapshot, SurveySnapshot


_PROXY_NOTICES = {
    "proxy_auth_error": ("随机IP账号状态异常", ""),
    "proxy_sync_failed": ("随机IP同步失败", ""),
    "trial_claimed": ("试用已领取", ""),
    "trial_failed": ("领取试用失败", ""),
    "quota_required": ("需要补充额度", "请先兑换随机IP额度后再使用。"),
    "proxy_unavailable": ("随机IP暂不可用", ""),
    "quota_exhausted": ("提示", "随机IP已用额度已达到上限，请先补充额度后再启用。"),
}
_LOADING_STAGES = {
    "processing": "正在处理...",
    "claiming_trial": "正在领取试用...",
    "syncing_quota": "正在同步服务端额度...",
}
_PARSE_ERRORS = {
    "url_required": "请填写问卷链接",
    "url_unsupported": "仅支持问卷星、腾讯问卷与 Credamo 见数链接",
    "parse_failed": "解析失败，请稍后重试",
    "dispatch_failed": "解析失败，请稍后重试",
}


def runtime_status(snapshot: RuntimeSnapshot) -> str:
    if (snapshot.get("initialization") or {}).get("active"):
        return "正在初始化"
    if snapshot.get("phase") == "idle":
        return "等待配置..."
    progress = snapshot.get("progress") or {}
    current = int(progress.get("current") or 0)
    target = int(progress.get("target") or 0)
    failures = int(progress.get("consecutive_failures") or 0)
    quota_failures = int(progress.get("device_quota_fail_count") or 0)
    terminal = snapshot.get("terminal_stop") or {}
    if terminal.get("category") in {"run_preparation_failed", "engine_start_failed", "engine_failed", "dispatch_failed"}:
        return str(terminal.get("message") or "后台运行内核异常退出，请查看日志")
    if not snapshot.get("running") and terminal.get("category") == "user_stopped" and target == 0:
        return "已停止"
    prefix = "已提交"
    if snapshot.get("stopping"):
        prefix = "正在停止"
    elif snapshot.get("paused"):
        prefix = "已暂停"
    elif not snapshot.get("running") and terminal.get("category") == "user_stopped":
        prefix = "已停止"
    status = f"{prefix} {current}/{target} 份 | 提交连续失败 {failures} 次"
    if quota_failures > 0:
        status += f" | 设备限制拦截 {quota_failures} 次"
    if snapshot.get("paused"):
        status += f" | {snapshot.get('pause_reason') or '已暂停'}"
    return status


def runtime_view(snapshot: RuntimeSnapshot) -> dict[str, Any]:
    view: dict[str, Any] = dict(snapshot)
    view["status_text"] = runtime_status(snapshot)
    initialization: dict[str, Any] = dict(snapshot.get("initialization") or {})
    initialization["text"] = "正在初始化" if initialization.get("active") else ""
    initialization["logs"] = ["正在初始化"] if initialization.get("active") else []
    view["initialization"] = initialization
    proxy: dict[str, Any] = dict(snapshot.get("random_ip") or {})
    stage = str(proxy.pop("loading_stage", "") or "")
    proxy["loading_message"] = _LOADING_STAGES.get(stage, stage)
    view["random_ip"] = proxy
    terminal: dict[str, Any] = dict(snapshot.get("terminal_stop") or {})
    if terminal.get("category") == "user_stopped" and not terminal.get("message"):
        terminal["message"] = "用户手动停止任务"
    view["terminal_stop"] = terminal
    return view


def survey_view(snapshot: SurveySnapshot) -> dict[str, Any]:
    view: dict[str, Any] = dict(snapshot)
    if snapshot.get("phase") == "error":
        view["parse_error"] = str(snapshot.get("parse_error") or _PARSE_ERRORS.get(
            str(snapshot.get("error_code") or "parse_failed"), _PARSE_ERRORS["parse_failed"],
        ))
    return view


def interaction_view(request: InteractionRequest) -> dict[str, Any]:
    event: dict[str, Any] = {"request_id": request.request_id}
    if request.kind == InteractionKind.QUOTA:
        return {**event, "type": "open_quota_request_form"}
    title, default = _PROXY_NOTICES.get(request.code, ("提示", ""))
    detail = request.detail
    if request.code == "trial_failed" and detail:
        detail = f"领取试用失败：{detail}"
    return {**event, "type": "dialog_message", "title": title,
            "message": detail or default, "level": request.level}
