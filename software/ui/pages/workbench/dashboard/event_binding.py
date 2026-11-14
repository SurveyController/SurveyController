from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QApplication

from software.logging.action_logger import bind_logged_action


def bind_dashboard_events(page: Any) -> None:
    bind_logged_action(
        page.parse_btn.clicked,
        page._on_parse_clicked,
        scope="UI",
        event="parse_survey",
        target="parse_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    bind_logged_action(
        page.config_list_action.triggered,
        page._on_show_config_list,
        scope="UI",
        event="open_config_list",
        target="config_list_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    bind_logged_action(
        page.load_cfg_action.triggered,
        page._on_load_config,
        scope="CONFIG",
        event="load_config",
        target="load_cfg_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    bind_logged_action(
        page.save_cfg_action.triggered,
        page._on_save_config,
        scope="CONFIG",
        event="save_config",
        target="save_cfg_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    bind_logged_action(
        page.qr_btn.clicked,
        page._on_qr_clicked,
        scope="UI",
        event="parse_qr_image",
        target="qr_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    QApplication.clipboard().dataChanged.connect(page._on_clipboard_changed)
