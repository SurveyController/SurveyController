from __future__ import annotations

import logging
import os
import sys
from concurrent.futures import Future
from types import SimpleNamespace
from typing import List, cast

from PySide6.QtCore import QEvent, QPoint, QTimer, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QDialog, QStackedWidget, QWidget
from qfluentwidgets import (
    FluentWindow,
    Flyout,
    FlyoutAnimationType,
    Theme,
    qconfig,
    setTheme,
    setThemeColor,
)
from shiboken6 import isValid

from software.app.app_info import APP_VERSION
from software.app.bootstrap import create_application_dependencies
from software.app.config import (
    APP_ICON_RELATIVE_PATH,
    app_settings,
    get_bool_from_qsettings,
)
from software.app.runtime_paths import get_resource_path
from software.logging.action_logger import log_action
from software.logging.log_utils import register_popup_handler
from software.ui.controller.run_controller import RunController
from software.ui.dialogs.quota_redeem import QuotaRedeemDialog
from software.ui.pages.workbench.presenter import WorkbenchPresenter
from software.ui.shell.boot import create_boot_splash, finish_boot_splash
from software.ui.shell.main_window_parts.dialogs import MainWindowDialogsMixin
from software.ui.shell.main_window_parts.lazy_pages import (
    MainWindowLazyPagesMixin,
)
from software.ui.shell.main_window_parts.lifecycle import (
    MainWindowLifecycleMixin,
)
from software.ui.shell.main_window_parts.update import MainWindowUpdateMixin
from software.ui.shell.startup_tutorial import (
    STARTUP_TUTORIAL_HINT_SEEN_SETTING_KEY,
    TUTORIAL_DOC_URL,
    StartupTutorialFlyoutView,
)


class _ImportCheckWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"SurveyController v{APP_VERSION}")
        self.navigationInterface = object()
        self.stackedWidget = QStackedWidget(self)
        self.workbench = SimpleNamespace()
        self.controller = SimpleNamespace(
            request_shutdown_for_close=lambda timeout_seconds=5.0: None
        )
        for index in range(4):
            page = QWidget(self)
            page.setObjectName(f"import_check_page_{index}")
            self.stackedWidget.addWidget(page)


def _should_use_import_check_window() -> bool:
    if sys.platform != "win32":
        return False
    return str(os.environ.get(MainWindow._IMPORT_CHECK_ENV, "") or "").strip() == "1"


class MainWindow(
    MainWindowDialogsMixin,
    MainWindowLifecycleMixin,
    MainWindowLazyPagesMixin,
    MainWindowUpdateMixin,
    FluentWindow,
):
    _IMPORT_CHECK_ENV = "WJX_IMPORT_CHECK"

    def eventFilter(self, obj, e):
        return super().eventFilter(obj, e)

    def __init__(self, parent=None):
        self._boot_splash = None
        self._import_check_mode = (
            str(os.environ.get(self._IMPORT_CHECK_ENV, "") or "").strip() == "1"
        )
        super().__init__(parent)
        theme_path = get_resource_path(os.path.join("software", "ui", "theme.json"))
        if os.path.exists(theme_path):
            qconfig.load(theme_path)
        self._theme_sync_pending = False
        self._apply_theme_mode(qconfig.get(qconfig.themeMode))
        setThemeColor("#2563EB")
        qconfig.themeChanged.connect(self._on_theme_changed)
        self._skip_save_on_close = False
        self._async_dialog_refs = []
        self._quota_redeem_dialog = None
        self._quota_redeem_dialog_active = False
        self._quota_redeem_waiters: list[Future[bool]] = []
        self._startup_update_check_timer = None
        self._startup_update_check_completed = False
        self._startup_update_notification_timer = None
        self._startup_update_pending_info = None
        self._startup_post_init_done = False
        self._startup_tutorial_hint_timer = None
        self._startup_tutorial_flyout = None
        self._startup_tutorial_view = None
        self._startup_tutorial_hint_showing = False
        self._random_ip_quota_auto_sync_interval_ms = 90000
        self._random_ip_quota_auto_sync_timer = QTimer(self)
        self._random_ip_quota_auto_sync_timer.setInterval(
            self._random_ip_quota_auto_sync_interval_ms
        )
        self._random_ip_quota_auto_sync_timer.timeout.connect(self._sync_random_ip_quota_silently)

        self._base_window_title = f"SurveyController v{APP_VERSION}"
        self.setWindowTitle(self._base_window_title)
        icon_path = get_resource_path(os.path.join("assets", "icon.png"))
        if not os.path.exists(icon_path):
            icon_path = get_resource_path(APP_ICON_RELATIVE_PATH)
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(900, 640)
        self._apply_default_window_size()
        self._enable_window_material_effect()

        if not self._import_check_mode:
            self._boot_splash = create_boot_splash(self)

        self.controller = RunController(
            self,
            dependencies=create_application_dependencies(),
        )
        self.workbench = WorkbenchPresenter(controller=self.controller, host=self)
        self.workbench_state = self.workbench.state
        self.strategy_page = self.workbench.strategy_page
        self.dashboard = self.workbench.dashboard
        self.run_coordinator = self.workbench.run_coordinator
        self.reverse_fill_page = self.workbench.reverse_fill_page

        self._log_page = None
        self._community_page = None
        self._about_page = None
        self._donate_page = None
        self._settings_page = None
        self._last_logged_page = ""

        self._init_navigation()
        self.navigationInterface.setExpandWidth(193)
        self.navigationInterface.expand(useAni=False)
        self.stackedWidget.currentChanged.connect(self._on_stack_widget_changed)

        self._bind_controller_signals()
        self._refresh_title_random_ip_user_id()
        self.workbench.sync_reverse_fill_context()
        self._register_popups()
        self._center_on_screen()

        if not self._import_check_mode:
            finish_boot_splash(1500)
            QTimer.singleShot(0, self._run_post_init_tasks)

        self._latest_badge = None
        self._outdated_badge = None
        self._preview_badge = None
        self._unknown_badge = None
        self._update_checking_spinner = None

    def _apply_theme_mode(self, theme_mode: Theme):

        try:
            setTheme(theme_mode, save=False, lazy=False)
        except Exception:
            logging.info("应用主题模式失败", exc_info=True)

    def _enable_window_material_effect(self):

        if not sys.platform.startswith("win"):
            return
        if not hasattr(self, "setMicaEffectEnabled"):
            return
        try:
            self.setMicaEffectEnabled(True)
        except Exception:
            logging.info("启用窗口材质效果失败", exc_info=True)

    def _apply_default_window_size(self):

        fallback_width, fallback_height = 1100, 780
        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if not screen:
                self.resize(fallback_width, fallback_height)
                return

            available = screen.availableGeometry()
            target_width = int(available.width() * 0.78)
            target_height = int(available.height() * 0.88)

            target_width = max(900, min(target_width, 1120))
            target_height = max(640, min(target_height, 860))

            self.resize(
                min(target_width, available.width()),
                min(target_height, available.height()),
            )
        except Exception:
            logging.info("设置默认窗口尺寸失败", exc_info=True)
            self.resize(fallback_width, fallback_height)

    def _on_theme_changed(self, _theme: Theme):

        self._enable_window_material_effect()
        try:
            drawer = getattr(getattr(self, "dashboard", None), "config_drawer", None)
            if drawer and hasattr(drawer, "_apply_theme"):
                drawer._apply_theme()
        except Exception:
            logging.info("主题变更后刷新组件失败", exc_info=True)

    def changeEvent(self, e):

        super().changeEvent(e)
        watched_events = {
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.PaletteChange,
        }
        if hasattr(QEvent.Type, "ThemeChange"):
            watched_events.add(QEvent.Type.ThemeChange)
        if e.type() in watched_events:
            self._schedule_auto_theme_sync()

    def _schedule_auto_theme_sync(self):
        if self._theme_sync_pending:
            return
        self._theme_sync_pending = True
        QTimer.singleShot(0, self._sync_auto_theme_if_needed)

    def _sync_auto_theme_if_needed(self):
        self._theme_sync_pending = False
        try:
            theme_mode = qconfig.get(qconfig.themeMode)
        except Exception:
            theme_mode = Theme.AUTO
        if theme_mode != Theme.AUTO:
            return

        from qfluentwidgets.common.style_sheet import updateStyleSheet

        old_theme = qconfig.theme
        qconfig.theme = Theme.AUTO
        if qconfig.theme != old_theme:
            updateStyleSheet()
            qconfig.themeChangedFinished.emit()
            qconfig._cfg.themeChanged.emit(Theme.AUTO)

    def resizeEvent(self, e):

        super().resizeEvent(e)
        if self._boot_splash:
            self._boot_splash.update_layout(self.width(), self.height())

    def closeEvent(self, e):

        if getattr(self, "_close_request_confirmed", False):
            self._finalize_confirmed_close()
            e.accept()
            return
        e.ignore()
        self._schedule_deferred_close_confirmation()

    def _start_random_ip_quota_auto_sync(self) -> None:
        try:
            self._random_ip_quota_auto_sync_timer.start()
        except Exception:
            logging.info("启动随机IP额度自动同步失败", exc_info=True)

    def _sync_random_ip_quota_silently(self) -> None:
        try:
            if self.controller.is_initializing() or bool(
                getattr(self.controller, "running", False)
            ):
                return
            self.controller.sync_random_ip_counter_from_server(
                silent=True,
                min_interval_seconds=45.0,
            )
        except Exception:
            logging.info("静默同步随机IP额度失败", exc_info=True)

    def _on_stack_widget_changed(self, _index: int):
        current_widget = self.stackedWidget.currentWidget()
        current_name = current_widget.objectName() if current_widget else ""
        if current_name and current_name != self._last_logged_page:
            log_action(
                "NAV",
                "switch_page",
                current_name,
                "main_window",
                result="opened",
            )
            self._last_logged_page = current_name

    def _notify_ai_unstable(self) -> None:
        self._toast("AI 填空连续失败，请稍后再试", "warning", duration=3500)

    def _notify_submission_verification(self, message: str) -> None:
        self._toast(
            str(message or "提交触发智能验证，请启用随机 IP 后再试"), "warning", duration=4500
        )

    def _center_on_screen(self):

        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if not screen:
                return
            available = screen.availableGeometry()
            frame = self.frameGeometry()
            frame.moveCenter(available.center())
            self.move(frame.topLeft())
        except Exception:
            logging.info("窗口居中失败", exc_info=True)

    def _run_post_init_tasks(self) -> None:
        if self._startup_post_init_done or self._import_check_mode:
            return
        self._startup_post_init_done = True
        self._load_saved_config()
        self._start_random_ip_quota_auto_sync()
        self._check_preview_version()
        self._check_update_on_startup()
        self._schedule_startup_tutorial_hint(1800)

    def _has_seen_startup_tutorial_hint(self) -> bool:
        settings = app_settings()
        return get_bool_from_qsettings(
            settings.value(STARTUP_TUTORIAL_HINT_SEEN_SETTING_KEY),
            False,
        )

    def _mark_startup_tutorial_hint_seen(self) -> None:
        settings = app_settings()
        settings.setValue(STARTUP_TUTORIAL_HINT_SEEN_SETTING_KEY, True)

    def _schedule_startup_tutorial_hint(self, delay_ms: int) -> None:
        if (
            self._import_check_mode
            or self._has_seen_startup_tutorial_hint()
            or self._startup_tutorial_hint_showing
        ):
            return
        if self._startup_tutorial_hint_timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._show_startup_tutorial_hint)
            self._startup_tutorial_hint_timer = timer
        self._startup_tutorial_hint_timer.start(max(int(delay_ms), 0))

    def _can_show_startup_tutorial_hint(self) -> bool:
        if (
            self._import_check_mode
            or self._has_seen_startup_tutorial_hint()
            or self._startup_tutorial_hint_showing
            or self._startup_tutorial_flyout is not None
        ):
            return False
        try:
            if not self.isVisible() or self.isMinimized():
                return False
        except Exception:
            return False
        if self._is_boot_splash_visible():
            return False
        return True

    def _startup_tutorial_hint_global_pos(self, hint_width: int, hint_height: int) -> QPoint:
        margin = 28
        local_pos = QPoint(
            max(margin, self.width() - int(hint_width) - margin),
            max(margin, self.height() - int(hint_height) - margin),
        )
        pos = self.mapToGlobal(local_pos)
        try:
            screen = (
                self.screen() or QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
            )
            if screen is None:
                return pos
            available = screen.availableGeometry()
            x = min(
                max(pos.x(), available.left() + margin),
                available.right() - int(hint_width) - margin + 1,
            )
            y = min(
                max(pos.y(), available.top() + margin),
                available.bottom() - int(hint_height) - margin + 1,
            )
            return QPoint(x, y)
        except Exception:
            logging.info("计算启动教程提示位置失败", exc_info=True)
            return pos

    def _show_startup_tutorial_hint(self) -> None:
        if not self._can_show_startup_tutorial_hint():
            if not self._import_check_mode and not self._has_seen_startup_tutorial_hint():
                self._schedule_startup_tutorial_hint(800)
            return

        try:
            view = StartupTutorialFlyoutView(self)
            view.openRequested.connect(self._open_startup_tutorial_from_hint)
            view.dismissed.connect(self._dismiss_startup_tutorial_hint)

            flyout = Flyout(view, self, isDeleteOnClose=True)
            flyout.closed.connect(self._on_startup_tutorial_hint_closed)
            self._startup_tutorial_view = view
            self._startup_tutorial_flyout = flyout
            self._startup_tutorial_hint_showing = True

            flyout.show()
            size = flyout.sizeHint()
            pos = self._startup_tutorial_hint_global_pos(size.width(), size.height())
            flyout.exec(pos, FlyoutAnimationType.SLIDE_LEFT)
        except Exception:
            self._startup_tutorial_hint_showing = False
            self._clear_startup_tutorial_refs()
            logging.info("显示启动教程提示失败", exc_info=True)

    def _dismiss_startup_tutorial_hint(self) -> None:
        self._mark_startup_tutorial_hint_seen()
        flyout = getattr(self, "_startup_tutorial_flyout", None)
        if flyout is not None:
            flyout.close()

    def _open_startup_tutorial_from_hint(self) -> None:
        self._mark_startup_tutorial_hint_seen()
        try:
            import webbrowser

            webbrowser.open(TUTORIAL_DOC_URL)
        finally:
            flyout = getattr(self, "_startup_tutorial_flyout", None)
            if flyout is not None:
                flyout.close()

    def _clear_startup_tutorial_refs(self) -> None:
        self._startup_tutorial_flyout = None
        self._startup_tutorial_view = None

    def _on_startup_tutorial_hint_closed(self) -> None:
        self._mark_startup_tutorial_hint_seen()
        self._startup_tutorial_hint_showing = False
        self._clear_startup_tutorial_refs()

    def _bind_controller_signals(self):
        self.controller.controllerEvent.connect(self._on_controller_event)
        self.controller.on_ip_counter = self._on_random_ip_counter_update

    def _register_popups(self):
        def handler(kind: str, title: str, message: str):
            if kind == "confirm":
                self.request_confirm_dialog(title, message)
                return False
            self._toast(message, "error" if kind == "error" else kind, 3000)
            return kind != "error"

        register_popup_handler(handler)

    def _on_run_failed(self, msg: str) -> None:
        text = str(msg or "")
        self._toast(text, "error")
        if not self.isActiveWindow():
            self.show_task_result_system_notification("任务失败", text)

    @Slot(dict)
    def _on_controller_event(self, event: dict) -> None:
        event_type = str((event or {}).get("type") or "").strip()
        if event_type == "run_failed":
            self._on_run_failed(str((event or {}).get("message") or ""))
            return
        if event_type in {"dialog_message", "open_quota_request_form"}:
            request_id = str(event.get("request_id") or "")
            if event_type == "dialog_message":
                result = self.show_message_dialog(
                    str(event.get("title") or ""),
                    str(event.get("message") or ""),
                    level=str(event.get("level") or "info"),
                )
            else:
                result = self._open_quota_redeem_dialog_async()
            if request_id:
                result.add_done_callback(
                    lambda future, request_id=request_id: self.controller.respond_to_interaction(
                        request_id,
                        bool(future.result()),
                    )
                )
            return
        if event_type == "ai_unstable":
            self._notify_ai_unstable()
            return
        if event_type == "submission_verification_required":
            self._notify_submission_verification(str((event or {}).get("message") or ""))
            return
        if event_type == "run_finished":
            self.reverse_fill_page.on_run_finished()

    def _open_quota_redeem_dialog_async(self) -> Future[bool]:
        result: Future[bool] = Future()
        dialog = getattr(self, "_quota_redeem_dialog", None)
        if dialog is not None and isValid(dialog):
            dialog.raise_()
            dialog.activateWindow()
            self._quota_redeem_waiters.append(result)
            return result

        dialog = QuotaRedeemDialog(self, submit_async_task=self.controller.submit_ui_task)
        self._quota_redeem_dialog = dialog
        self._quota_redeem_dialog_active = True
        self._quota_redeem_waiters.append(result)
        dialog.finished.connect(self._on_quota_redeem_interaction_finished)
        dialog.destroyed.connect(self._on_quota_redeem_interaction_destroyed)
        self._open_async_dialog(dialog, result)
        return result

    def _open_quota_redeem_dialog(self) -> Future[bool]:
        return self._open_quota_redeem_dialog_async()

    def _on_quota_redeem_interaction_finished(self, code: int) -> None:
        accepted = code == QDialog.DialogCode.Accepted
        if accepted:
            self.controller.refresh_random_ip_counter()
        for waiter in self._quota_redeem_waiters:
            if not waiter.done():
                waiter.set_result(accepted)
        self._quota_redeem_waiters.clear()
        self._quota_redeem_dialog = None
        self._quota_redeem_dialog_active = False

    def _on_quota_redeem_interaction_destroyed(self, *_args) -> None:
        for waiter in self._quota_redeem_waiters:
            if not waiter.done():
                waiter.set_result(False)
        self._quota_redeem_waiters.clear()
        self._quota_redeem_dialog = None
        self._quota_redeem_dialog_active = False

    def _open_reverse_fill_wizard(self, issue_question_nums: List[int]) -> None:
        self.workbench.open_reverse_fill_wizard(issue_question_nums)

    def _open_parse_wizard_after_parse(
        self,
        info: List[dict],
        parsed_title: str,
        *,
        issue_question_nums: List[int] | None = None,
    ) -> None:
        self.workbench.open_parse_wizard_after_parse(
            info,
            parsed_title,
            issue_question_nums=issue_question_nums,
        )


def create_window() -> MainWindow:

    if _should_use_import_check_window():
        return cast(MainWindow, _ImportCheckWindow())
    return MainWindow()
