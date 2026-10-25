from typing import Any, Optional, cast
import logging
from software.logging.log_utils import log_suppressed_exception


from concurrent.futures import Future

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBox,
    EditableComboBox,
    ExpandGroupSettingCard,
    FluentIcon,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    HyperlinkButton,
    LineEdit,
    PasswordLineEdit,
    PlainTextEdit,
    PushSettingCard,
    SettingCard,
    SettingCardGroup,
)

from software.ui.widgets.full_width_infobar import FullWidthInfoBar
from software.ui.workers.ai_test_worker import ai_test_result
from software.application.ports import AiSettingsPort
from software.core.config.schema import RuntimeConfig


class AIPromptSettingCard(ExpandGroupSettingCard):
    def __init__(self, prompt_text: str, default_prompt: str, parent=None):
        super().__init__(
            FluentIcon.EDIT,
            "系统提示词",
            "在此处编辑 AI 填空的系统提示词",
            parent,
        )
        self._default_prompt = (default_prompt or "").strip() or (prompt_text or "").strip()

        self._group_container = QWidget(self)
        layout = QVBoxLayout(self._group_container)
        layout.setContentsMargins(48, 12, 48, 16)
        layout.setSpacing(8)

        self.promptEdit = PlainTextEdit(self._group_container)
        self.promptEdit.setPlaceholderText("留空使用默认提示词...")
        self.promptEdit.setMinimumHeight(180)
        self.promptEdit.setMaximumHeight(230)
        self.promptEdit.setPlainText(prompt_text or self._default_prompt)

        layout.addWidget(self.promptEdit)

        self.addGroupWidget(self._group_container)
        self.setExpand(True)

    def prompt_text(self) -> str:
        return self.promptEdit.toPlainText().strip() or self._default_prompt

    def set_default_prompt(self, default_prompt: str) -> None:
        self._default_prompt = (default_prompt or "").strip() or self._default_prompt

    def set_prompt_text(self, value: str, default_prompt: Optional[str] = None) -> None:
        if default_prompt is not None:
            self.set_default_prompt(default_prompt)
        self.promptEdit.setPlainText((value or "").strip() or self._default_prompt)


class RuntimeAISection(QObject):
    aiTestFinished = Signal(bool, str)
    _PROVIDER_DOCS = {
        "deepseek": "https://api-docs.deepseek.com/zh-cn/",
        "custom": "https://platform.openai.com/docs/api-reference/introduction",
    }

    def __init__(
        self,
        parent_view: QWidget,
        owner: QWidget,
        *,
        ai_settings: AiSettingsPort,
    ):
        super().__init__(parent_view)
        self._owner = owner
        self._ai_settings = ai_settings
        self.group = SettingCardGroup("AI 填空助手", parent_view)
        self._ai_loading = True
        self._ai_test_future: Future[Any] | None = None
        self._current_infobar: Optional[InfoBar] = None
        ai_config = self._ai_settings.get_settings()
        self._ai_system_prompt = (
            str(ai_config.get("system_prompt") or "").strip()
            or self._ai_settings.default_system_prompt()
        )
        self._build_ui(ai_config)
        self._bind_events()
        self.aiTestFinished.connect(self._on_ai_test_finished)
        self._update_ai_visibility()
        self._ai_loading = False

    def _build_ui(self, ai_config):
        self.ai_privacy_bar = FullWidthInfoBar(
            InfoBarIcon.INFORMATION,
            "AI 配置保存在本地；调用时向所选服务发送题目、提示词和 API Key。",
            "",
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            duration=-1,
            position=InfoBarPosition.NONE,
            parent=self.group,
        )
        self.ai_privacy_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ai_privacy_bar.setMinimumWidth(0)
        self.ai_privacy_bar.setMaximumWidth(16777215)
        self.ai_privacy_bar.contentLabel.setVisible(False)
        self.ai_privacy_bar_spacer = QWidget(self.ai_privacy_bar)
        self.ai_privacy_bar_spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.ai_privacy_tutorial_link = HyperlinkButton(
            FluentIcon.LINK,
            "https://surveydoc.hungrym0.com/api-key-configuration.html#api-key-%E9%85%8D%E7%BD%AE",
            "使用教程",
            self.ai_privacy_bar,
        )
        self.ai_privacy_bar.addWidget(self.ai_privacy_bar_spacer, 1)
        self.ai_privacy_bar.addWidget(self.ai_privacy_tutorial_link)
        self.group.addSettingCard(self.ai_privacy_bar)

        self.ai_provider_card = SettingCard(
            FluentIcon.CLOUD,
            "AI 服务提供商",
            "选择 AI 服务，自定义模式支持任意 OpenAI 兼容接口",
            self.group,
        )
        self.ai_provider_combo = ComboBox(self.ai_provider_card)
        self.ai_provider_combo.setMinimumWidth(200)
        for key, provider in self._ai_settings.providers.items():
            self.ai_provider_combo.addItem(provider.get("label", key), userData=key)
        saved_provider = ai_config.get("provider") or "deepseek"
        if saved_provider not in self._ai_settings.providers:
            saved_provider = "deepseek"
        idx = self.ai_provider_combo.findData(saved_provider)
        if idx >= 0:
            self.ai_provider_combo.setCurrentIndex(idx)
        self.ai_provider_link = HyperlinkButton(
            FluentIcon.LINK, "", "API文档", self.ai_provider_card
        )
        self._update_ai_doc_link(saved_provider)
        self.ai_provider_card.hBoxLayout.addWidget(
            self.ai_provider_link, 0, Qt.AlignmentFlag.AlignRight
        )
        self.ai_provider_card.hBoxLayout.addSpacing(8)
        self.ai_provider_card.hBoxLayout.addWidget(
            self.ai_provider_combo, 0, Qt.AlignmentFlag.AlignRight
        )
        self.ai_provider_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_provider_card)

        self.ai_baseurl_card = SettingCard(
            FluentIcon.LINK,
            "Base URL",
            "自定义模式下可填根地址或完整端点，程序会自动识别协议（如 https://api.example.com/v1）",
            self.group,
        )
        self.ai_baseurl_edit = LineEdit(self.ai_baseurl_card)
        self.ai_baseurl_edit.setMinimumWidth(280)
        self.ai_baseurl_edit.setPlaceholderText("https://api.example.com/v1 或完整端点")
        self.ai_baseurl_edit.setText(ai_config.get("base_url") or "")
        self.ai_baseurl_card.hBoxLayout.addWidget(
            self.ai_baseurl_edit, 0, Qt.AlignmentFlag.AlignRight
        )
        self.ai_baseurl_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_baseurl_card)

        self.ai_apikey_card = SettingCard(
            FluentIcon.FINGERPRINT,
            "API Key",
            "输入对应服务的 API 密钥，获取方法请查阅服务商API文档",
            self.group,
        )
        self.ai_apikey_edit = PasswordLineEdit(self.ai_apikey_card)
        self.ai_apikey_edit.setMinimumWidth(280)
        self.ai_apikey_edit.setPlaceholderText("sk-...")
        self.ai_apikey_edit.setText(ai_config.get("api_key") or "")
        self.ai_apikey_card.hBoxLayout.addWidget(
            self.ai_apikey_edit, 0, Qt.AlignmentFlag.AlignRight
        )
        self.ai_apikey_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_apikey_card)

        self.ai_model_card = SettingCard(
            FluentIcon.DEVELOPER_TOOLS,
            "模型 ID",
            "请查阅所选服务商的API文档后再填写准确的模型id号，切勿随意填写",
            self.group,
        )

        self.ai_model_combo = EditableComboBox(self.ai_model_card)
        self.ai_model_combo.setMinimumWidth(280)
        self.ai_model_combo.setPlaceholderText("输入或选择模型名称")
        current_model = ai_config.get("model") or ""
        if current_model:
            self.ai_model_combo.setText(current_model)

        self.ai_model_edit = LineEdit(self.ai_model_card)
        self.ai_model_edit.setMinimumWidth(280)
        self.ai_model_edit.setPlaceholderText("输入模型名称")
        if current_model:
            self.ai_model_edit.setText(current_model)
        self.ai_model_card.hBoxLayout.addWidget(self.ai_model_combo, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_model_card.hBoxLayout.addWidget(self.ai_model_edit, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_model_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_model_card)

        self.ai_test_card = PushSettingCard(
            text="测试",
            icon=FluentIcon.SEND,
            title="测试 AI 连接",
            content="验证 API 配置是否正确",
            parent=self.group,
        )
        self.group.addSettingCard(self.ai_test_card)
        self.ai_test_spinner = IndeterminateProgressRing(self.ai_test_card)
        self.ai_test_spinner.setFixedSize(20, 20)
        self.ai_test_spinner.setStrokeWidth(2)
        self.ai_test_spinner.hide()
        insert_index = self.ai_test_card.hBoxLayout.indexOf(self.ai_test_card.button)
        if insert_index >= 0:
            self.ai_test_card.hBoxLayout.insertWidget(
                insert_index,
                self.ai_test_spinner,
                0,
                Qt.AlignmentFlag.AlignRight,
            )
            self.ai_test_card.hBoxLayout.insertSpacing(insert_index + 1, 6)

        self.ai_prompt_card = AIPromptSettingCard(
            self._ai_system_prompt,
            self._ai_settings.default_system_prompt(),
            self.group,
        )
        self.group.addSettingCard(self.ai_prompt_card)

    def bind_to_layout(self, layout):
        layout.addWidget(self.group)

    def _bind_events(self):
        self.ai_provider_combo.currentIndexChanged.connect(self._on_ai_provider_changed)
        self.ai_apikey_edit.editingFinished.connect(self._on_ai_apikey_changed)
        self.ai_baseurl_edit.editingFinished.connect(self._on_ai_baseurl_changed)
        self.ai_model_combo.currentTextChanged.connect(self._on_ai_model_changed)
        self.ai_model_edit.editingFinished.connect(self._on_ai_model_edit_changed)
        self.ai_test_card.clicked.connect(self._on_ai_test_clicked)
        self.ai_prompt_card.promptEdit.textChanged.connect(self._on_ai_prompt_changed)

    def update_config(self, cfg: RuntimeConfig):
        cfg.ai_mode = "provider"
        idx = self.ai_provider_combo.currentIndex()
        cfg.ai_provider = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "deepseek"
        cfg.ai_api_key = self.ai_apikey_edit.text().strip()
        cfg.ai_base_url = self.ai_baseurl_edit.text().strip()
        cfg.ai_api_protocol = "auto"
        cfg.ai_model = self._get_current_model_value()
        cfg.ai_system_prompt = self._ai_system_prompt or self._ai_settings.default_system_prompt()

    def apply_config(self, cfg: RuntimeConfig):
        self._apply_ai_config(cfg)

    def _set_ai_controls_blocked(self, blocked: bool):
        try:
            self.ai_provider_combo.blockSignals(blocked)
        except Exception as exc:
            log_suppressed_exception(
                "_set_ai_controls_blocked: combo blockSignals",
                exc,
                level=logging.WARNING,
            )

    def _set_ai_test_loading(self, loading: bool):
        self.ai_test_spinner.setVisible(loading)
        self.ai_test_card.button.setEnabled(not loading)

    def _show_ai_infobar(self, message: str, success: bool = True, duration: int = 2000):

        if self._current_infobar is not None:
            try:
                self._current_infobar.close()
            except (RuntimeError, AttributeError):
                pass
            self._current_infobar = None

        infobar_func = InfoBar.success if success else InfoBar.error
        self._current_infobar = infobar_func(
            "",
            message,
            parent=self._owner.window(),
            position=InfoBarPosition.TOP,
            duration=duration,
        )

    def _update_ai_visibility(self):

        idx = self.ai_provider_combo.currentIndex()
        provider_key = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "deepseek"
        is_custom = provider_key == "custom"
        self.ai_baseurl_card.setVisible(is_custom)

        provider_config = self._ai_settings.providers.get(provider_key, {})
        recommended_models = provider_config.get("recommended_models", [])
        default_model = provider_config.get("default_model", "")

        self.ai_model_combo.setVisible(not is_custom)
        self.ai_model_edit.setVisible(is_custom)

        if is_custom:
            if not self._ai_loading:
                self.ai_model_edit.setText("")
                self._ai_settings.save_settings(model="")
        else:
            current_model = self.ai_model_combo.currentText().strip()
            self.ai_model_combo.clear()
            if recommended_models:
                self.ai_model_combo.addItems(recommended_models)

            self.ai_model_combo.setPlaceholderText(default_model or "输入模型名称")

            if self._ai_loading:
                self.ai_model_combo.setText(current_model or default_model)
            else:
                self.ai_model_combo.setText(default_model)
                self._ai_settings.save_settings(model=default_model)

        self._update_ai_doc_link(provider_key)

    def _apply_ai_config(self, cfg: RuntimeConfig):
        ai_config_present = getattr(cfg, "_ai_config_present", False)
        if not ai_config_present:
            ai_config = self._ai_settings.get_settings()
            cfg.ai_provider = str(ai_config.get("provider") or "deepseek")
            cfg.ai_api_key = str(ai_config.get("api_key") or "")
            cfg.ai_base_url = str(ai_config.get("base_url") or "")
            cfg.ai_api_protocol = str(ai_config.get("api_protocol") or "auto")
            cfg.ai_model = str(ai_config.get("model") or "")
            cfg.ai_system_prompt = (
                str(ai_config.get("system_prompt") or "").strip()
                or self._ai_settings.default_system_prompt()
            )
        if not getattr(cfg, "ai_provider", ""):
            cfg.ai_provider = "deepseek"
        if cfg.ai_provider not in self._ai_settings.providers:
            cfg.ai_provider = "deepseek"
        cfg.ai_mode = "provider"
        if not getattr(cfg, "ai_api_protocol", ""):
            cfg.ai_api_protocol = "auto"
        if not getattr(cfg, "ai_system_prompt", ""):
            cfg.ai_system_prompt = self._ai_settings.default_system_prompt()

        if ai_config_present:
            self._ai_settings.update_session(
                {
                    "provider": cfg.ai_provider,
                    "api_key": cfg.ai_api_key,
                    "base_url": cfg.ai_base_url,
                    "api_protocol": cfg.ai_api_protocol,
                    "model": cfg.ai_model,
                    "system_prompt": cfg.ai_system_prompt,
                }
            )

        self._ai_loading = True
        self._set_ai_controls_blocked(True)
        idx = self.ai_provider_combo.findData(cfg.ai_provider)
        if idx >= 0:
            self.ai_provider_combo.setCurrentIndex(idx)
        else:
            self.ai_provider_combo.setCurrentIndex(0)
        self.ai_apikey_edit.setText(cfg.ai_api_key or "")
        self.ai_baseurl_edit.setText(cfg.ai_base_url or "")
        current_model = (cfg.ai_model or "").strip()
        self.ai_model_combo.setText(current_model)
        self.ai_model_edit.setText(current_model)
        default_prompt = self._ai_settings.default_system_prompt()
        self._ai_system_prompt = cfg.ai_system_prompt or default_prompt
        self.ai_prompt_card.set_prompt_text(self._ai_system_prompt, default_prompt=default_prompt)
        self._update_ai_visibility()
        self._set_ai_controls_blocked(False)
        self._ai_loading = False

    def _on_ai_provider_changed(self):

        if self._ai_loading:
            return
        idx = self.ai_provider_combo.currentIndex()
        provider_key = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "deepseek"
        self._ai_settings.save_settings(provider=provider_key)
        self._update_ai_visibility()

    def _update_ai_doc_link(self, provider_key: str):
        url = self._PROVIDER_DOCS.get(provider_key, "")
        self.ai_provider_link.setVisible(provider_key != "custom")
        if url:
            self.ai_provider_link.setEnabled(True)
            self.ai_provider_link.setText("API文档")
            self.ai_provider_link.setUrl(url)
        else:
            self.ai_provider_link.setEnabled(False)
            self.ai_provider_link.setText("暂无文档")
            self.ai_provider_link.setUrl("")

    def _on_ai_apikey_changed(self):

        if self._ai_loading:
            return
        self._ai_settings.save_settings(api_key=self.ai_apikey_edit.text())

    def _on_ai_baseurl_changed(self):

        if self._ai_loading:
            return
        self._ai_settings.save_settings(base_url=self.ai_baseurl_edit.text())

    def _on_ai_model_changed(self, text: str):

        if self._ai_loading:
            return
        self._ai_settings.save_settings(model=text.strip())

    def _on_ai_model_edit_changed(self):

        if self._ai_loading:
            return
        self._ai_settings.save_settings(model=self.ai_model_edit.text().strip())

    def _get_current_model_value(self) -> str:

        idx = self.ai_provider_combo.currentIndex()
        if idx >= 0 and self.ai_provider_combo.itemData(idx) == "custom":
            return self.ai_model_edit.text().strip()
        return self.ai_model_combo.currentText().strip()

    def _on_ai_prompt_changed(self):

        if self._ai_loading:
            return
        self._ai_system_prompt = self.ai_prompt_card.prompt_text()
        self._ai_settings.save_settings(system_prompt=self._ai_system_prompt)

    def _on_ai_test_clicked(self):

        if self._ai_loading:
            return
        if self._ai_test_future is not None and not self._ai_test_future.done():
            return
        self._ai_settings.save_settings(
            api_key=self.ai_apikey_edit.text(),
            base_url=self.ai_baseurl_edit.text(),
            api_protocol="auto",
            model=self._get_current_model_value(),
            system_prompt=self._ai_system_prompt,
        )
        self._set_ai_test_loading(True)
        try:
            runtime_engine = cast(Any, self._owner).controller._async_engine_client
            future = runtime_engine.submit_ui_task(
                "ai_test_connection",
                self._ai_settings.test_connection,
            )
        except Exception as exc:
            self._on_ai_test_finished(*ai_test_result(error=exc))
            return
        self._ai_test_future = future
        future.add_done_callback(self._on_ai_test_future_done)

    def _on_ai_test_future_done(self, future: Future[Any]) -> None:
        try:
            result = future.result()
        except Exception as exc:
            outcome = ai_test_result(error=exc)
        else:
            outcome = ai_test_result(result=str(result or ""))
        try:
            self.aiTestFinished.emit(*outcome)
        except RuntimeError:
            logging.debug("AI 测试结果到达时设置页已关闭")

    def _on_ai_test_finished(self, success: bool, message: str):
        self._ai_test_future = None
        self._set_ai_test_loading(False)
        if success:
            self._show_ai_infobar(message, success=True, duration=3000)
        else:
            logging.error("AI 连接测试失败: %s", message)
            self._show_ai_infobar(message, success=False, duration=5000)
