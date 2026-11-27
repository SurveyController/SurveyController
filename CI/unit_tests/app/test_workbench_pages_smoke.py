from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QWidget
from surveycore.core.questions.config import QuestionEntry
from surveycore.providers.contracts import SurveyQuestionMeta

from software.app.config import HTTP_MAX_THREADS
from software.core.config.schema import RuntimeConfig
from software.ui.pages.workbench.dashboard.page import DashboardPage
from software.ui.pages.workbench.presenter import WorkbenchPresenter
from software.ui.pages.workbench.reverse_fill.page import ReverseFillPage
from software.ui.pages.workbench.session import WorkbenchState
from software.ui.pages.workbench.strategy.page import QuestionStrategyPage


class _FakeController(QObject):
    surveyParsed = Signal(list, str)
    surveyParseFailed = Signal(str)
    surveySnapshotChanged = Signal(dict)
    runtimeSnapshotChanged = Signal(dict)
    runtimeUiStateChanged = Signal(dict)
    runStateChanged = Signal(bool)
    randomIpLoadingChanged = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.ai_settings = _FakeAiSettings()
        self.running = False
        self._starting = False
        self.adapter = object()
        self.survey_provider = "wjx"
        self.state = {
            "target": 10,
            "threads": 2,
            "random_ip_enabled": False,
            "proxy_source": "default",
            "answer_duration": (60, 120),
            "answer_datetime_window": ("", ""),
        }
        self.runtime_updates: list[dict] = []
        self.random_ip_toggle_requests: list[bool] = []
        self.parse_calls: list[str] = []
        self.stop_calls = 0
        self.resume_calls = 0

    def get_runtime_ui_state(self):
        return dict(self.state)

    def get_runtime_snapshot(self):
        return {
            "settings": dict(self.state),
            "random_ip": {"loading": False, "loading_message": ""},
            "running": bool(self.running),
            "paused": False,
            "status_text": "等待配置...",
            "progress": {"current": 0, "target": 0},
            "threads": {"rows": [], "num_threads": 0, "per_thread_target": 0},
        }

    def get_survey_snapshot(self):
        return {"survey_provider": self.survey_provider, "question_entries": []}

    def set_runtime_ui_state(self, emit: bool = True, **updates):
        self.state.update(updates)
        self.runtime_updates.append(dict(updates))
        if emit:
            self.runtimeUiStateChanged.emit(dict(self.state))
        return dict(self.state)

    def sync_runtime_ui_state_from_config(self, cfg: RuntimeConfig, *, emit: bool = True):
        self.state.update(
            {
                "target": cfg.target,
                "threads": cfg.threads,
                "random_ip_enabled": cfg.random_ip_enabled,
                "proxy_source": cfg.proxy_source,
                "answer_duration": cfg.answer_duration,
                "answer_datetime_window": cfg.answer_datetime_window,
            }
        )
        if emit:
            self.runtimeUiStateChanged.emit(dict(self.state))
        return dict(self.state)

    def is_initializing(self) -> bool:
        return False

    def request_toggle_random_ip(self, enabled: bool, **_kwargs) -> bool:
        self.random_ip_toggle_requests.append(bool(enabled))
        self.set_runtime_ui_state(random_ip_enabled=bool(enabled))
        return True

    def parse_survey(self, url: str) -> None:
        self.parse_calls.append(url)

    def stop_run(self) -> None:
        self.stop_calls += 1

    def resume_run(self) -> None:
        self.resume_calls += 1

    def refresh_random_ip_counter(self, **_kwargs) -> None:
        return None


class _FakeAiSettings:
    providers = {
        "custom": {
            "label": "OpenAI 兼容",
        },
    }

    def __init__(self) -> None:
        self.settings = {
            "ai_mode": "provider",
            "provider": "custom",
            "api_key": "",
            "base_url": "",
            "api_protocol": "auto",
            "model": "",
            "system_prompt": "默认提示",
        }
        self.writes: list[dict] = []

    def default_system_prompt(self) -> str:
        return "默认提示"

    def get_settings(self) -> dict:
        return dict(self.settings)

    def save_settings(self, **values) -> None:
        self.writes.append(dict(values))
        self.settings.update(values)

    def reset_settings(self) -> None:
        self.settings.clear()

    def readiness_error(self, config=None) -> str:
        return ""

    async def test_connection(self) -> str:
        return "连接成功"


def _patch_page_dependencies(monkeypatch) -> None:
    import software.ui.pages.workbench.runtime_panel.random_ip_card as random_ip_card
    import software.ui.pages.workbench.shared.clipboard as clipboard_module

    monkeypatch.setattr(
        random_ip_card,
        "load_area_codes",
        lambda supported_only=True: [
            {"code": "110000", "name": "北京", "cities": [{"code": "110100", "name": "北京"}]}
        ],
    )
    monkeypatch.setattr(
        random_ip_card, "load_supported_area_codes", lambda: ({"110000", "110100"}, False)
    )
    monkeypatch.setattr(
        random_ip_card, "load_benefit_supported_areas", lambda force_refresh=False: []
    )
    proxy_settings = SimpleNamespace(
        source="default",
        custom_api_url="",
        default_area_code="",
        benefit_area_code="",
    )
    monkeypatch.setattr(random_ip_card, "get_proxy_settings", lambda: proxy_settings)
    monkeypatch.setattr(random_ip_card, "apply_proxy_area_code", lambda _code: None)
    monkeypatch.setattr(random_ip_card, "apply_custom_proxy_api", lambda _url: None)
    monkeypatch.setattr(random_ip_card, "test_custom_proxy_api", lambda _url: (True, "", []))

    monkeypatch.setattr(
        clipboard_module.SurveyClipboardMixin, "_on_clipboard_changed", lambda self: None
    )


def test_dashboard_run_setup_builds_and_syncs_config_without_network(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    state = WorkbenchState()
    strategy_page = QuestionStrategyPage()
    page = DashboardPage(controller, state, strategy_page)
    qtbot.addWidget(strategy_page)
    qtbot.addWidget(page)

    cfg = RuntimeConfig(target=7, threads=99, random_ip_enabled=True)
    page.apply_config(cfg)

    assert page.run_setup_panel.target_spin.value() == 7
    assert page.run_setup_panel.thread_card.slider.slider.maximum() == HTTP_MAX_THREADS
    assert page.run_setup_panel.thread_card.slider.value() == HTTP_MAX_THREADS
    assert cfg.target == 7
    assert cfg.threads == 99
    assert cfg.answer_datetime_window == ("", "")
    assert page.run_setup_panel.ai_section.ai_provider_combo.count() == 1
    assert page.run_setup_panel.ai_section.ai_provider_combo.currentData() == "custom"


@pytest.mark.parametrize("provider,model", [("custom", "test-model"), ("deepseek", "legacy-model")])
def test_dashboard_ai_preserves_saved_model_when_loading_legacy_config(
    monkeypatch, qtbot, provider, model
) -> None:
    _patch_page_dependencies(monkeypatch)
    saved = {
        "ai_mode": "free",
        "provider": provider,
        "api_key": "test-key",
        "base_url": "https://example.test/v1",
        "model": model,
        "system_prompt": "用户提示词",
    }
    controller = _FakeController()
    controller.ai_settings.settings = dict(saved)
    state = WorkbenchState()
    strategy_page = QuestionStrategyPage()
    page = DashboardPage(controller, state, strategy_page)
    qtbot.addWidget(page)
    qtbot.addWidget(strategy_page)
    assert page.run_setup_panel.ai_section._get_current_model_value() == model
    assert controller.ai_settings.writes == []

    cfg = RuntimeConfig(ai_mode="free")
    page.apply_config(cfg)
    assert cfg.ai_mode == "provider"
    assert cfg.ai_provider == "custom"
    assert cfg.ai_model == model
    assert cfg.ai_api_key == "test-key"
    assert cfg.ai_system_prompt == "用户提示词"


def test_strategy_page_builds_rules_and_dimension_sections(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    page = QuestionStrategyPage()
    qtbot.addWidget(page)

    info = [
        SurveyQuestionMeta(num=1, title="性别", type_code="3", option_texts=["男", "女"]),
        SurveyQuestionMeta(num=2, title="满意度", type_code="3", option_texts=["高", "低"]),
    ]
    page.set_questions_info(info)
    page.set_rules(
        [
            {
                "condition_question_num": 1,
                "condition_option_indices": [0],
                "target_question_num": 2,
                "target_option_indices": [1],
                "condition_mode": "selected",
                "action_mode": "must_select",
            }
        ]
    )
    page.set_entries([QuestionEntry("single", [1, 1], question_num=1, dimension="体验")], info)
    page.set_dimension_groups(["体验", "未分组", "体验"])
    page._on_segment_changed("dimensions")

    assert page.rule_panel.table.rowCount() == 1
    assert page.rule_panel.table.item(0, 0).text().startswith("第1题")
    assert page.get_dimension_groups() == ["体验"]
    assert page.stack.currentWidget() is page.dimension_panel


def test_reverse_fill_page_builds_and_updates_config(monkeypatch, qtbot, tmp_path) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    page = ReverseFillPage(controller)
    qtbot.addWidget(page)
    xlsx = tmp_path / "data.xlsx"
    xlsx.write_text("placeholder", encoding="utf-8")

    page.url_edit.setText("https://www.wjx.cn/vm/demo.aspx")
    page.parse_btn.click()
    page._parsed_url = page.url_edit.text()
    page.set_question_context(
        [SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"])],
        [QuestionEntry("single", [1, 1], question_num=1)],
        survey_provider="wjx",
    )
    page.file_edit.setText(str(xlsx))
    page._last_spec = SimpleNamespace(target_num=3)

    changes: list[dict] = []
    page.configurationChanged.connect(changes.append)
    page._apply_excel_source_path(str(xlsx))
    page._on_reverse_fill_threads_changed(3)
    page.on_run_state_changed(True)
    page.update_status("正在初始化", 0, 3)
    page.update_status("运行中", 2, 3)
    page.on_run_state_changed(False)

    assert page.parse_btn.text() == "解析"
    assert controller.parse_calls == ["https://www.wjx.cn/vm/demo.aspx"]
    assert changes[0] == {
        "reverse_fill_source_path": str(xlsx),
        "reverse_fill_enabled": True,
    }
    assert changes[-1] == {"reverse_fill_threads": 3}
    assert page.stop_btn.isEnabled() is False


def test_dashboard_page_builds_first_step_with_mica_transparency(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    strategy_page = QuestionStrategyPage()
    state = WorkbenchState()
    state.set_entries(
        [QuestionEntry("single", [1, 1], question_num=1, question_title="Q1")],
        [SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"])],
    )
    page = DashboardPage(controller, state, strategy_page)
    qtbot.addWidget(strategy_page)
    qtbot.addWidget(page)

    page.show()
    QApplication.processEvents()
    assert page.qr_btn.isVisible()
    assert page.url_edit.isVisible()
    assert page.parse_btn.isVisible()
    assert [action.text() for action in page.config_command_bar.actions()] == [
        "配置列表",
        "载入配置",
        "保存配置",
    ]
    assert "background: transparent" in page.link_card.styleSheet()
    assert page.testAttribute(Qt.WidgetAttribute.WA_StyledBackground) is False


def test_workbench_config_projects_random_ip_state_to_all_pages(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    host = QWidget()
    qtbot.addWidget(host)
    presenter = WorkbenchPresenter(controller=controller, host=host)

    presenter.apply_config(RuntimeConfig(random_ip_enabled=True))

    assert presenter.dashboard.run_setup_panel.random_ip_switch.isChecked()
    assert presenter.reverse_fill_page.random_ip_cb.isChecked()
    assert controller.random_ip_toggle_requests == []

    controller.state["random_ip_enabled"] = False
    controller.runtimeSnapshotChanged.emit(controller.get_runtime_snapshot())
    qtbot.waitUntil(
        lambda: (
            not presenter.dashboard.run_setup_panel.random_ip_switch.isChecked()
            and not presenter.reverse_fill_page.random_ip_cb.isChecked()
        )
    )
    assert presenter.state.snapshot().random_ip_enabled is False


@pytest.mark.parametrize("enable_succeeded", [True, False])
def test_random_ip_switch_waits_for_balance(monkeypatch, qtbot, enable_succeeded) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    host = QWidget()
    qtbot.addWidget(host)
    presenter = WorkbenchPresenter(controller=controller, host=host)
    panel = presenter.dashboard.run_setup_panel
    card = panel.random_ip_card
    reverse_page = presenter.reverse_fill_page
    read_snapshot = controller.get_runtime_snapshot
    quota_state = {"loading": False, "loading_message": ""}

    def snapshot():
        return {**read_snapshot(), "random_ip": dict(quota_state)}

    def request_toggle(enabled):
        controller.random_ip_toggle_requests.append(enabled)
        quota_state.update(loading=True, loading_message="正在连接随机 IP 账户")
        controller.runtimeSnapshotChanged.emit(snapshot())
        return True

    monkeypatch.setattr(controller, "get_runtime_snapshot", snapshot)
    monkeypatch.setattr(controller, "request_toggle_random_ip", request_toggle)

    card.switchButton.setChecked(True)

    assert not card.switchButton.isEnabled()
    assert not card.loadingRing.isHidden()
    assert card.loadingRing.property("surveycontroller_active")
    qtbot.waitUntil(lambda: not reverse_page.random_ip_cb.isEnabled())

    quota_state["loading_message"] = "正在同步服务端额度"
    controller.runtimeSnapshotChanged.emit(snapshot())
    QApplication.processEvents()
    assert not card.switchButton.isEnabled()

    controller.state["random_ip_enabled"] = enable_succeeded
    quota_state.update(loading=False, loading_message="")
    controller.runtimeSnapshotChanged.emit(snapshot())
    qtbot.waitUntil(lambda: card.switchButton.isEnabled() and reverse_page.random_ip_cb.isEnabled())

    assert card.loadingRing.isHidden()
    assert not card.loadingRing.property("surveycontroller_active")
    assert card.switchButton.isChecked() is enable_succeeded
    assert reverse_page.random_ip_cb.isChecked() is enable_succeeded
    assert controller.random_ip_toggle_requests == [True]


def test_workbench_user_edits_reach_saved_and_run_config(monkeypatch, qtbot, tmp_path) -> None:
    _patch_page_dependencies(monkeypatch)
    controller = _FakeController()
    host = QWidget()
    qtbot.addWidget(host)
    presenter = WorkbenchPresenter(controller=controller, host=host)
    panel = presenter.dashboard.run_setup_panel

    presenter.dashboard.url_edit.setText("https://www.wjx.cn/vm/draft.aspx")
    panel.target_spin.setValue(8)
    panel.thread_card.slider.setValue(3)
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"placeholder")
    source_path = str(source)
    presenter.reverse_fill_page._apply_excel_source_path(source_path)
    presenter.reverse_fill_page.reverse_fill_threads_spin.setValue(2)
    panel.ai_section.ai_model_edit.setText("draft-model")
    panel.ai_section.ai_model_edit.editingFinished.emit()

    saved = presenter.build_current_config_snapshot()
    run = presenter.run_coordinator.build_config()
    for config in (saved, run):
        assert config.url == "https://www.wjx.cn/vm/draft.aspx"
        assert config.target == 8
        assert config.threads == 3
        assert config.reverse_fill_source_path == source_path
        assert config.reverse_fill_threads == 2
        assert config.ai_model == "draft-model"
    assert presenter.reverse_fill_page.url_edit.text() == saved.url


def test_workbench_dimension_edit_commits_and_refreshes_reverse_fill(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    host = QWidget()
    qtbot.addWidget(host)
    presenter = WorkbenchPresenter(controller=_FakeController(), host=host)
    presenter.apply_config(
        RuntimeConfig(
            question_entries=[QuestionEntry("single", [1, 1], question_num=1, dimension="A")],
            questions_info=[SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2)],
            dimension_groups=["A", "B"],
        )
    )
    changes = []
    presenter.state.configChanged.connect(lambda _config, changed: changes.append(changed))

    presenter.strategy_page.dimension_panel._apply_entries_to_dimension([0], "B")

    assert presenter.state.snapshot().question_entries[0].dimension == "B"
    assert presenter.reverse_fill_page._question_entries[0].dimension == "B"
    assert any("question_entries" in changed for changed in changes)


def test_workbench_question_wizard_edits_current_draft(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    host = QWidget()
    qtbot.addWidget(host)
    presenter = WorkbenchPresenter(controller=_FakeController(), host=host)
    presenter.apply_config(
        RuntimeConfig(
            question_entries=[QuestionEntry("single", [1, 1], question_num=1, dimension="B")],
            questions_info=[SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2)],
            dimension_groups=["B"],
        )
    )

    def edit(entries, _info, _title):
        assert entries[0].dimension == "B"
        entries[0].custom_weights = [9.0, 1.0]
        return True

    monkeypatch.setattr(presenter.dashboard, "run_question_wizard", edit)
    presenter.open_reverse_fill_wizard([1])

    config = presenter.state.snapshot()
    assert config.question_entries[0].custom_weights == [9.0, 1.0]
    assert config.question_entries[0].dimension == "B"
    assert config.dimension_groups == ["B"]


def test_workbench_ready_snapshot_preserves_loaded_dimensions(monkeypatch, qtbot) -> None:
    _patch_page_dependencies(monkeypatch)
    host = QWidget()
    qtbot.addWidget(host)
    presenter = WorkbenchPresenter(controller=_FakeController(), host=host)
    config = RuntimeConfig(
        question_entries=[QuestionEntry("single", [1, 1], question_num=1, dimension="B")],
        questions_info=[SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2)],
        dimension_groups=["A", "B"],
    )
    presenter.apply_config(config)

    presenter.on_survey_snapshot_changed(
        {
            "phase": "ready",
            "url": config.url,
            "survey_title": config.survey_title,
            "questions_info": config.questions_info,
            "question_entries": config.question_entries,
        }
    )

    assert presenter.state.snapshot().dimension_groups == ["A", "B"]
