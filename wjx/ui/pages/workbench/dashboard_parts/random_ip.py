"""DashboardPage 随机 IP 与卡密相关方法。"""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QDialog
from qfluentwidgets import FluentIcon

from wjx.network.proxy import (
    _format_status_payload,
    _validate_card,
    get_ipzan_minute_by_answer_seconds,
    get_quota_cost_by_minute,
    get_random_ip_counter_snapshot_local,
    get_status,
    on_random_ip_toggle,
    refresh_ip_counter_display,
)
from wjx.ui.dialogs.card_unlock import CardUnlockDialog
from wjx.ui.dialogs.contact import ContactDialog
from wjx.utils.app.config import get_bool_from_qsettings
from wjx.utils.logging.log_utils import log_suppressed_exception
from wjx.utils.system.registry_manager import RegistryManager

if TYPE_CHECKING:
    from qfluentwidgets import BodyLabel, CheckBox, LineEdit, PushButton
    from wjx.ui.controller import RunController
    from wjx.ui.pages.workbench.runtime import RuntimePage
    from wjx.ui.widgets.full_width_infobar import FullWidthInfoBar


class DashboardRandomIPMixin:
    """随机 IP、额度提示、卡密与调试重置逻辑。"""

    if TYPE_CHECKING:
        # 以下属性由 DashboardPage 主类提供，此处仅用于 Pylance 类型检查
        url_edit: LineEdit
        card_btn: PushButton
        random_ip_hint: BodyLabel
        random_ip_cb: CheckBox
        controller: RunController
        runtime_page: RuntimePage
        _ip_low_infobar: Optional[FullWidthInfoBar]
        _ip_cost_infobar: Optional[FullWidthInfoBar]
        _ip_low_infobar_dismissed: bool
        _ip_low_threshold: int
        _api_balance_cache: Optional[float]
        _ip_balance_fetch_lock: threading.Lock
        _ip_balance_fetching: bool
        _last_ip_balance_fetch_ts: float
        _ip_balance_fetch_interval_sec: float
        _debug_reset_in_progress: bool
        _debug_reset_started_at: float
        _debugResetFinished: Any  # PySide6.QtCore.Signal，Mixin 中无法精确声明描述符类型
        _ipBalanceChecked: Any   # 同上

        def _toast(self, text: str, level: str = "info", duration: int = 2000, show_progress: bool = False) -> Any: ...
        def window(self) -> Any: ...  # 继承自 QWidget，此处仅供类型检查

    def _on_url_text_changed(self, text: str):
        """监听问卷链接输入框文本变化，检测 reset 命令（仅调试模式下可用）"""
        if text.strip().lower() != "reset":
            return

        settings = QSettings("FuckWjx", "Settings")
        debug_mode = get_bool_from_qsettings(settings.value("debug_mode"), False)
        if not debug_mode:
            return

        if self._debug_reset_in_progress:
            self.url_edit.clear()
            return

        self._debug_reset_in_progress = True
        self._debug_reset_started_at = time.monotonic()
        self.url_edit.clear()
        self._toast("正在重置随机IP额度...", "info", duration=-1, show_progress=True)

        thread = threading.Thread(
            target=self._run_debug_reset_worker,
            daemon=True,
            name="DebugResetWorker",
        )
        thread.start()

    def _run_debug_reset_worker(self) -> None:
        """后台执行 debug reset，避免阻塞 GUI。"""
        from wjx.network.proxy import _get_default_quota_with_cache

        payload: Dict[str, Any] = {"ok": False, "quota": None, "error": ""}
        try:
            default_quota = _get_default_quota_with_cache()
            if default_quota is None:
                payload["error"] = "default_quota_unavailable"
                return

            RegistryManager.write_submit_count(0)
            RegistryManager.write_quota_limit(default_quota)
            RegistryManager.set_card_verified(False)
            RegistryManager.set_extra_quota_verified(False)
            RegistryManager.set_confetti_played(False)
            payload["ok"] = True
            payload["quota"] = int(default_quota)
        except Exception as exc:
            payload["error"] = str(exc)
            log_suppressed_exception("dashboard._run_debug_reset_worker", exc, level=logging.WARNING)
        finally:
            self._debugResetFinished.emit(payload)

    def _on_debug_reset_finished(self, payload: Any) -> None:
        data = payload if isinstance(payload, dict) else {}
        min_loading_ms = 300
        elapsed_ms = int(max(0.0, time.monotonic() - float(getattr(self, "_debug_reset_started_at", 0.0))) * 1000)
        delay_ms = max(0, min_loading_ms - elapsed_ms)
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, lambda d=data: self._apply_debug_reset_result(d))
            return
        self._apply_debug_reset_result(data)

    def _apply_debug_reset_result(self, data: Dict[str, Any]) -> None:
        self._debug_reset_in_progress = False
        success = bool(data.get("ok"))
        quota = data.get("quota")

        if not success:
            logging.warning("调试重置：默认额度API不可用，保持 --/-- 状态")
            refresh_ip_counter_display(self.controller.adapter)
            self._toast("默认额度API不可用，随机IP额度保持未初始化（--/--）", "warning", duration=3000)
            return

        refresh_ip_counter_display(self.controller.adapter)
        self._toast(f"已重置随机IP额度为 0/{quota}", "success", duration=2500)

    def _set_runtime_ip_switch(self, enabled: bool) -> None:
        """设置运行时页面的随机IP开关，并同步展开区域的启用状态（绕过信号阻塞）。"""
        try:
            self.runtime_page.random_ip_switch.blockSignals(True)
            self.runtime_page.random_ip_switch.setChecked(enabled)
            self.runtime_page.random_ip_switch.blockSignals(False)
            self.runtime_page.random_ip_card._sync_ip_enabled(enabled)
        except Exception as exc:
            log_suppressed_exception("_set_runtime_ip_switch", exc, level=logging.WARNING)

    def update_random_ip_counter(self, count: int, limit: int, custom_api: bool):
        # 三态按钮：未验证 → 已验证(可申请更多) → 二次验证(禁用)
        is_verified = RegistryManager.is_card_verified()
        is_extra = RegistryManager.is_extra_quota_verified()
        has_used_random_ip = int(count or 0) > 0
        if is_verified and is_extra:
            self.card_btn.setEnabled(False)
            self.card_btn.setText("已解锁")
            self.card_btn.setIcon(FluentIcon.FINGERPRINT)
        elif is_verified:
            self.card_btn.setEnabled(has_used_random_ip)
            self.card_btn.setText("申请更多额度")
            self.card_btn.setIcon(FluentIcon.SHOPPING_CART)
        else:
            self.card_btn.setEnabled(has_used_random_ip)
            self.card_btn.setText("解锁大额IP")
            self.card_btn.setIcon(FluentIcon.FINGERPRINT)
        if (not has_used_random_ip) and (not (is_verified and is_extra)):
            self.card_btn.setToolTip("请先使用随机IP提交至少1次后再申请")
        else:
            self.card_btn.setToolTip("")

        if custom_api:
            self.random_ip_hint.setText("自定义接口")
            self.random_ip_hint.setStyleSheet("color:#ff8c00;")
            self._update_ip_low_infobar(count, limit, custom_api)
            self._update_ip_cost_infobar(custom_api)
            return
        if limit <= 0:
            self.random_ip_hint.setText("--/--")
            self.random_ip_hint.setStyleSheet("color:#6b6b6b;")
            self._update_ip_low_infobar(count, limit, custom_api)
            self._update_ip_cost_infobar(custom_api)
            if self.random_ip_cb.isChecked():
                self.random_ip_cb.blockSignals(True)
                self.random_ip_cb.setChecked(False)
                self.random_ip_cb.blockSignals(False)
            return
        self.random_ip_hint.setText(f"{count}/{limit}")
        # 额度耗尽时变红
        if count >= limit:
            self.random_ip_hint.setStyleSheet("color:red;")
        else:
            self.random_ip_hint.setStyleSheet("color:#6b6b6b;")
        self._update_ip_low_infobar(count, limit, custom_api)
        self._update_ip_cost_infobar(custom_api)
        # 达到上限时自动关闭随机IP开关
        if count >= limit and self.random_ip_cb.isChecked():
            self.random_ip_cb.blockSignals(True)
            self.random_ip_cb.setChecked(False)
            self.random_ip_cb.blockSignals(False)
            self._set_runtime_ip_switch(False)

    @staticmethod
    def _format_duration_text(seconds: int) -> str:
        total = max(0, int(seconds))
        mins = total // 60
        secs = total % 60
        return f"{mins}分{secs}秒"

    def _refresh_ip_cost_infobar(self) -> None:
        """根据当前配置刷新随机IP成本提示条。"""
        try:
            _, _, custom_api = get_random_ip_counter_snapshot_local()
        except Exception:
            custom_api = False
        self._update_ip_cost_infobar(bool(custom_api))

    def _update_ip_cost_infobar(self, custom_api: bool) -> None:
        if not self._ip_cost_infobar:
            return
        if custom_api:
            self._ip_cost_infobar.hide()
            return

        try:
            timed_enabled = bool(self.runtime_page.timed_switch.isChecked())
        except Exception:
            timed_enabled = False
        if timed_enabled:
            self._ip_cost_infobar.hide()
            return

        try:
            answer_seconds = int(self.runtime_page.answer_card.getValue())
        except Exception:
            answer_seconds = 0

        minute = int(get_ipzan_minute_by_answer_seconds(answer_seconds))
        if minute <= 1:
            self._ip_cost_infobar.hide()
            return

        quota_cost = int(get_quota_cost_by_minute(minute))
        content = (
            f"当前作答时长约 {self._format_duration_text(answer_seconds)}，成本较高，"
            f"将按 {quota_cost} 倍消耗速率扣减随机IP额度。"
        )
        try:
            # InfoBar 初始化时 title/content 都是空，会把对应 QLabel 设为隐藏。
            # 这里动态更新文本时，必须同步恢复标签可见性。
            self._ip_cost_infobar.title = content
            self._ip_cost_infobar.content = ""
            if hasattr(self._ip_cost_infobar, "titleLabel"):
                self._ip_cost_infobar.titleLabel.setVisible(True)
            if hasattr(self._ip_cost_infobar, "contentLabel"):
                self._ip_cost_infobar.contentLabel.setVisible(False)
            if hasattr(self._ip_cost_infobar, "_adjustText"):
                self._ip_cost_infobar._adjustText()
            self._ip_cost_infobar.show()
        except Exception as exc:
            log_suppressed_exception("_update_ip_cost_infobar", exc, level=logging.WARNING)

    def _on_random_ip_toggled(self, state: int):
        enabled = state != 0
        # 先同步检查限制，防止快速点击绕过
        if enabled:
            count, limit, custom_api = get_random_ip_counter_snapshot_local()
            if (not custom_api) and limit <= 0:
                self._toast("随机IP额度不可用（本地未初始化且默认额度API不可用）", "warning")
                self.random_ip_cb.blockSignals(True)
                self.random_ip_cb.setChecked(False)
                self.random_ip_cb.blockSignals(False)
                self._set_runtime_ip_switch(False)
                refresh_ip_counter_display(self.controller.adapter)
                return
            if (not custom_api) and count >= limit:
                self._toast(f"随机IP已达{limit}份限制，请验证卡密后再启用。", "warning")
                self.random_ip_cb.blockSignals(True)
                self.random_ip_cb.setChecked(False)
                self.random_ip_cb.blockSignals(False)
                self._set_runtime_ip_switch(False)
                return
        try:
            self.controller.adapter.random_ip_enabled_var.set(bool(enabled))
            on_random_ip_toggle(self.controller.adapter)
            enabled = bool(self.controller.adapter.random_ip_enabled_var.get())
        except Exception:
            enabled = bool(enabled)
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(enabled)
        self.random_ip_cb.blockSignals(False)
        self._set_runtime_ip_switch(enabled)
        refresh_ip_counter_display(self.controller.adapter)

    def _ask_card_code(self) -> Optional[str]:
        """向主窗口请求卡密输入，兜底弹出输入框。"""
        win = self.window()
        if hasattr(win, "_ask_card_code"):
            try:
                return win._ask_card_code()  # type: ignore[union-attr]
            except Exception as exc:
                log_suppressed_exception("_ask_card_code: main window passthrough", exc, level=logging.WARNING)
        dialog = CardUnlockDialog(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            contact_handler=lambda: self._open_contact_dialog(default_type="卡密获取"),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_card_code()
        return None

    def _open_contact_dialog(self, default_type: str = "报错反馈"):
        """打开联系对话框"""
        win = self.window()
        if hasattr(win, "_open_contact_dialog"):
            try:
                return win._open_contact_dialog(default_type)  # type: ignore[union-attr]
            except Exception as exc:
                log_suppressed_exception("_open_contact_dialog passthrough", exc, level=logging.WARNING)
        dlg = ContactDialog(self, default_type=default_type, status_fetcher=get_status, status_formatter=_format_status_payload)
        dlg.exec()

    def _on_card_code_clicked(self):
        """用户主动输入卡密解锁大额随机IP。"""
        if RegistryManager.read_submit_count() <= 0:
            self._toast("请先使用随机IP提交至少1次后再申请额度。", "warning", duration=2500)
            return
        was_already_verified = RegistryManager.is_card_verified()
        dialog = CardUnlockDialog(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            contact_handler=lambda: self._open_contact_dialog(default_type="卡密获取"),
            card_validator=_validate_card,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        # 验证成功后处理解锁逻辑：在原有额度基础上增加卡密提供的额度
        if dialog.get_validation_result():
            quota = dialog.get_validation_quota()
            if quota is None:
                self._toast("卡密验证返回缺少额度信息，拒绝解锁，请联系开发者。", "error")
                return
            quota_to_add = max(1, int(quota))
            current_limit = int(RegistryManager.read_quota_limit(0) or 0)
            new_limit = current_limit + quota_to_add
            RegistryManager.write_quota_limit(new_limit)
            RegistryManager.set_card_verified(True)
            if was_already_verified:
                RegistryManager.set_extra_quota_verified(True)
            refresh_ip_counter_display(self.controller.adapter)
            self.random_ip_cb.setChecked(True)
            self._set_runtime_ip_switch(True)

    def _on_ip_low_infobar_closed(self):
        self._ip_low_infobar_dismissed = True
        if self._ip_low_infobar:
            self._ip_low_infobar.hide()

    def _update_ip_low_infobar(self, count: int, limit: int, custom_api: bool):
        """更新IP余额不足提示条，基于API余额换算的剩余IP数判断"""
        if not self._ip_low_infobar:
            return
        if custom_api:
            self._ip_low_infobar.hide()
            self._ip_low_infobar_dismissed = False
            return

        # 先用缓存快速更新，避免每次刷新都走网络
        if self._api_balance_cache is not None:
            cached_remaining = int(max(0.0, float(self._api_balance_cache)) / 0.0035)
            self._on_ip_balance_checked(cached_remaining)

        now = time.monotonic()
        with self._ip_balance_fetch_lock:
            if self._ip_balance_fetching or (now - self._last_ip_balance_fetch_ts) < self._ip_balance_fetch_interval_sec:
                return
            self._ip_balance_fetching = True
            self._last_ip_balance_fetch_ts = now

        # 异步获取 API 余额并判断
        def _fetch_and_check():
            try:
                import wjx.network.http_client as http_client

                response = http_client.get(
                    "https://service.ipzan.com/userProduct-get",
                    params={"no": "20260112572376490874", "userId": "72FH7U4E0IG"},
                    timeout=5,
                )
                data = response.json()
                if data.get("code") in (0, 200) and data.get("status") in (200, "200", None):
                    balance = data.get("data", {}).get("balance", 0)
                    remaining_ip = int(float(balance) / 0.0035)
                    self._api_balance_cache = float(balance)
                    self._ipBalanceChecked.emit(remaining_ip)
            except Exception as exc:
                timeout_error_names = {"ReadTimeout", "ConnectTimeout", "PoolTimeout", "TimeoutException"}
                level = logging.DEBUG if exc.__class__.__name__ in timeout_error_names else logging.WARNING
                log_suppressed_exception("_fetch_and_check: API balance fetch failed", exc, level=level)
            finally:
                with self._ip_balance_fetch_lock:
                    self._ip_balance_fetching = False

        threading.Thread(target=_fetch_and_check, daemon=True, name="IPBalanceCheck").start()

    def _on_ip_balance_checked(self, remaining_ip: int):
        """处理IP余额检查结果（在主线程中执行）"""
        if not self._ip_low_infobar:
            return
        if remaining_ip < self._ip_low_threshold:
            if not self._ip_low_infobar_dismissed:
                self._ip_low_infobar.show()
        else:
            self._ip_low_infobar.hide()
            self._ip_low_infobar_dismissed = False
