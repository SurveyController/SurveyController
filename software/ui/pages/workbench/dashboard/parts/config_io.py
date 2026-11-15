from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtWidgets import QFileDialog, QWidget

from software.app.user_paths import get_user_config_directory
from software.io.config.store import build_default_config_filename
from software.logging.action_logger import log_action


class DashboardConfigIOMixin:
    if TYPE_CHECKING:
        controller: Any
        config_drawer: Any
        workbench_state: Any
        strategy_page: Any
        _survey_title: str

        def _toast(
            self,
            text: str,
            level: str = "info",
            duration: int = 2000,
            show_progress: bool = False,
        ) -> Any: ...
        def apply_config(self, cfg: Any) -> None: ...
        def update_question_meta(self, title: str, count: int) -> None: ...
        def window(self) -> Any: ...

        open_run_setup_step: Any

    @staticmethod
    def _format_load_config_error(exc: Exception) -> str:
        text = str(exc or "").strip()
        if "该配置文件损坏，请输入问卷链接/二维码重新配置" in text:
            return "该配置文件损坏，请输入问卷链接/二维码重新配置"
        if "配置文件为空" in text:
            return "配置加载失败：文件为空"
        if "JSON" in text and "顶层必须是对象" in text:
            return "配置加载失败：文件格式错误"
        if "读取配置失败" in text:
            return "配置加载失败：文件损坏"
        return f"载入失败：{text}" if text else "载入失败"

    def _on_show_config_list(self):
        try:
            self.config_drawer.open_drawer()
            log_action(
                "UI",
                "open_config_list",
                "config_list_btn",
                "dashboard",
                result="opened",
            )
        except Exception as exc:
            log_action(
                "UI",
                "open_config_list",
                "config_list_btn",
                "dashboard",
                result="failed",
                level=logging.ERROR,
                detail=exc,
            )
            self._toast(f"无法打开配置列表：{exc}", "error")

    def _on_load_config(self):
        configs_dir = get_user_config_directory()
        if not os.path.exists(configs_dir):
            os.makedirs(configs_dir, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            cast(QWidget, self),
            "载入配置",
            configs_dir,
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            log_action(
                "CONFIG",
                "load_config",
                "load_cfg_btn",
                "dashboard",
                result="cancelled",
            )
            return
        self._load_config_from_path(path)

    def _load_config_from_path(self, path: str):
        if not path:
            log_action(
                "CONFIG",
                "load_config",
                "load_cfg_btn",
                "dashboard",
                result="cancelled",
            )
            return
        if not os.path.exists(path):
            log_action(
                "CONFIG",
                "load_config",
                "load_cfg_btn",
                "dashboard",
                result="failed",
                level=logging.WARNING,
                payload={
                    "reason": "missing_file",
                    "file": os.path.basename(path),
                },
            )
            self._toast("文件不存在，可能已被删除", "warning")
            return
        try:
            self.window().workbench.load_config_from_path(path)
        except Exception as exc:
            logging.error("[CONFIG] load_saved_config failed: %s", exc, exc_info=True)
            log_action(
                "CONFIG",
                "load_config",
                "load_cfg_btn",
                "dashboard",
                result="failed",
                level=logging.ERROR,
                payload={"file": os.path.basename(path)},
                detail=exc,
            )
            logging.error("手动载入配置失败: %s", exc, exc_info=True)
            self._toast(self._format_load_config_error(exc), "error")
            return

        log_action(
            "CONFIG",
            "load_config",
            "load_cfg_btn",
            "dashboard",
            result="success",
            payload={"file": os.path.basename(path)},
        )
        self._toast("已载入配置", "success")
        if self.workbench_state.has_question_entries():
            cfg = self.workbench_state.snapshot()
            self.open_run_setup_step(cfg.survey_title, len(cfg.question_entries))

    def _on_save_config(self):
        cfg = self.window().workbench.build_current_config_snapshot()
        configs_dir = get_user_config_directory()
        os.makedirs(configs_dir, exist_ok=True)
        default_name = build_default_config_filename(self._survey_title)
        default_path = os.path.join(configs_dir, default_name)
        path, _ = QFileDialog.getSaveFileName(
            cast(QWidget, self),
            "保存配置",
            default_path,
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            log_action(
                "CONFIG",
                "save_config",
                "save_cfg_btn",
                "dashboard",
                result="cancelled",
            )
            return
        try:
            self.controller.save_current_config(
                path,
                config=cfg,
                include_secrets=True,
            )
            log_action(
                "CONFIG",
                "save_config",
                "save_cfg_btn",
                "dashboard",
                result="success",
                payload={"file": os.path.basename(path)},
            )
            self._toast("配置已保存", "success")
        except Exception as exc:
            log_action(
                "CONFIG",
                "save_config",
                "save_cfg_btn",
                "dashboard",
                result="failed",
                level=logging.ERROR,
                payload={"file": os.path.basename(path)},
                detail=exc,
            )
            self._toast(f"保存失败：{exc}", "error")
