from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from qfluentwidgets import FluentIcon

if TYPE_CHECKING:
    from qfluentwidgets.common.icon import FluentIconBase

from software.app.config import (
    SUBMISSION_REPORT_TELEMETRY_SETTING_KEY,
    TASK_RESULT_SYSTEM_NOTIFICATION_SETTING_KEY,
)


@dataclass(frozen=True)
class SwitchCardDefinition:
    attr_name: str
    icon: "FluentIconBase"
    title: str
    content: str
    setting_key: str
    default: bool
    event: str
    target: str
    handler_name: str


BEHAVIOR_SWITCHES = (
    SwitchCardDefinition(
        attr_name="ask_save_card",
        icon=FluentIcon.SAVE,
        title="关闭前询问是否保存",
        content="关闭窗口时提示是否保存当前配置",
        setting_key="ask_save_on_close",
        default=True,
        event="toggle_ask_save_on_close",
        target="ask_save_switch",
        handler_name="_on_ask_save_on_close_toggled",
    ),
    SwitchCardDefinition(
        attr_name="task_result_notification_card",
        icon=FluentIcon.INFO,
        title="后台任务完成/失败时通知",
        content="当程序不在前台时，任务完成或失败会弹出系统通知",
        setting_key=TASK_RESULT_SYSTEM_NOTIFICATION_SETTING_KEY,
        default=True,
        event="toggle_task_result_windows_notification",
        target="task_result_notification_switch",
        handler_name="_on_task_result_notification_toggled",
    ),
    SwitchCardDefinition(
        attr_name="submission_report_telemetry_card",
        icon=FluentIcon.SEND,
        title="提交结果遥测",
        content="启用随机 IP 时，提交成功或失败结果会同步上报服务端做统计，便于排查问题",
        setting_key=SUBMISSION_REPORT_TELEMETRY_SETTING_KEY,
        default=True,
        event="toggle_submission_report_telemetry",
        target="submission_report_telemetry_switch",
        handler_name="_on_submission_report_telemetry_toggled",
    ),
)

UPDATE_SWITCHES = (
    SwitchCardDefinition(
        attr_name="auto_update_card",
        icon=FluentIcon.UPDATE,
        title="在应用程序启动时检查更新",
        content="新版本将更加稳定并拥有更多功能（建议启用此选项）",
        setting_key="auto_check_update",
        default=True,
        event="toggle_auto_update",
        target="auto_update_switch",
        handler_name="_on_auto_update_toggled",
    ),
)
