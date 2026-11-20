from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QObject
from surveycore.core.questions.config import QuestionEntry
from surveycore.providers.contracts import SurveyQuestionMeta

from software.core.config.schema import RuntimeConfig
from software.ui.pages.workbench.presenter import WorkbenchPresenter
from software.ui.pages.workbench.session import WorkbenchState


class _FakeController:
    def __init__(self) -> None:
        self.config = RuntimeConfig(
            url="https://www.wjx.cn/vm/demo.aspx",
            survey_provider="wjx",
        )
        self.survey_provider = "wjx"
        self.question_entries: list[QuestionEntry] = []
        self.synced_configs: list[RuntimeConfig] = []
        self.counter_refreshes = 0

    def sync_runtime_ui_state_from_config(self, cfg: RuntimeConfig) -> None:
        self.synced_configs.append(cfg)

    def refresh_random_ip_counter(self) -> None:
        self.counter_refreshes += 1

    def get_survey_snapshot(self) -> dict:
        return {
            "question_entries": list(self.question_entries),
            "survey_provider": self.survey_provider,
        }


class _FakeDashboard:
    def __init__(self) -> None:
        self.url_edit = _FakeLineEdit()
        self.applied: list[RuntimeConfig] = []
        self.meta: tuple[str, int] | None = None
        self._survey_title = ""
        self._open_wizard_after_parse = False
        self.wizard_calls: list[tuple[list[QuestionEntry], list, str | None]] = []
        self.wizard_result = True
        self.toasts: list[tuple[str, str]] = []
        self.parse_success_calls: list[tuple[list, str]] = []
        self.parse_failed_calls: list[str] = []
        self.run_states: list[bool] = []
        self.loading_events: list[tuple[bool, str]] = []
        self.status_updates: list[tuple[str, int, int]] = []
        self.thread_payloads: list[dict] = []
        self.pause_states: list[tuple[bool, str]] = []
        self.runtime_snapshots: list[dict] = []
        self.execution_steps = 0

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self.applied.append(cfg)

    def update_question_meta(self, title: str, count: int) -> None:
        self.meta = (title, count)
        self._survey_title = title

    def build_base_config(self) -> RuntimeConfig:
        return RuntimeConfig(url=self.url_edit.text(), target=3, threads=2)

    def run_question_wizard(
        self,
        entries: list[QuestionEntry],
        info: list,
        survey_title: str | None = None,
    ) -> bool:
        self.wizard_calls.append((entries, info, survey_title))
        return self.wizard_result

    def _toast(self, text: str, level: str = "info", *_args, **_kwargs) -> None:
        self.toasts.append((text, level))

    def _on_survey_parsed(self, info: list, title: str) -> None:
        self.parse_success_calls.append((list(info or []), title))

    def _on_survey_parse_failed(self, error_msg: str) -> None:
        self.parse_failed_calls.append(str(error_msg or ""))

    def present_parse_succeeded(self, info: list, title: str) -> None:
        self._on_survey_parsed(info, title)

    def present_parse_failed(self, error_msg: str) -> None:
        self._on_survey_parse_failed(error_msg)

    def apply_runtime_snapshot(self, snapshot: dict) -> None:
        self.runtime_snapshots.append(dict(snapshot or {}))

    def open_execution_step(self) -> None:
        self.execution_steps += 1

    def on_run_state_changed(self, running: bool) -> None:
        self.run_states.append(bool(running))

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self.loading_events.append((bool(loading), str(message or "")))

    def update_status(self, text: str, current: int, target: int) -> None:
        self.status_updates.append((str(text or ""), int(current), int(target)))

    def update_thread_progress(self, payload: dict) -> None:
        self.thread_payloads.append(dict(payload or {}))

    def on_pause_state_changed(self, paused: bool, reason: str = "") -> None:
        self.pause_states.append((bool(paused), str(reason or "")))


class _FakeReverseFillPage:
    def __init__(self) -> None:
        self.url_edit = _FakeLineEdit()
        self.applied: list[RuntimeConfig] = []
        self.contexts: list[dict] = []
        self.preview_refreshes = 0
        self.run_states: list[bool] = []
        self.loading_events: list[tuple[bool, str]] = []
        self.status_updates: list[tuple[str, int, int]] = []
        self.pause_states: list[tuple[bool, str]] = []
        self.parse_success_calls: list[tuple[list, str]] = []
        self.parse_failed_calls: list[str] = []

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self.applied.append(cfg)

    def set_question_context(
        self,
        questions_info,
        question_entries,
        *,
        survey_title: str,
        survey_provider: str,
    ) -> None:
        self.contexts.append(
            {
                "questions_info": list(questions_info or []),
                "question_entries": list(question_entries or []),
                "survey_title": survey_title,
                "survey_provider": survey_provider,
            }
        )

    def _refresh_preview(self) -> None:
        self.preview_refreshes += 1

    def on_run_state_changed(self, running: bool) -> None:
        self.run_states.append(bool(running))

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self.loading_events.append((bool(loading), str(message or "")))

    def update_status(self, text: str, current: int, target: int) -> None:
        self.status_updates.append((str(text or ""), int(current), int(target)))

    def on_pause_state_changed(self, paused: bool, reason: str = "") -> None:
        self.pause_states.append((bool(paused), str(reason or "")))

    def _on_survey_parsed(self, info: list, title: str) -> None:
        self.parse_success_calls.append((list(info or []), str(title or "")))

    def _on_survey_parse_failed(self, error_msg: str) -> None:
        self.parse_failed_calls.append(str(error_msg or ""))

    def present_parse_succeeded(self, info: list, title: str) -> None:
        self._on_survey_parsed(info, title)

    def present_parse_failed(self, error_msg: str) -> None:
        self._on_survey_parse_failed(error_msg)


class _FakeStrategyPage:
    def __init__(self) -> None:
        self.questions_info: list = []
        self.entries_calls: list[tuple[list, list]] = []
        self.rules: list = []
        self.dimension_groups: list = []

    def set_questions_info(self, info) -> None:
        self.questions_info = list(info or [])

    def set_entries(self, entries, info) -> None:
        self.entries_calls.append((list(entries or []), list(info or [])))

    def set_rules(self, rules) -> None:
        self.rules = list(rules or [])

    def set_dimension_groups(self, groups) -> None:
        self.dimension_groups = list(groups or [])


class _FakeHost:
    def __init__(self) -> None:
        self.toasts: list[tuple[str, str]] = []

    def _toast(self, text: str, level: str = "info", *_args, **_kwargs) -> None:
        self.toasts.append((text, level))

    def switchTo(self, _page) -> None:
        return None


class _FakeLineEdit(QObject):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._text = text

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = str(text or "")


def _presenter_with_fakes() -> WorkbenchPresenter:
    presenter = object.__new__(WorkbenchPresenter)
    dynamic = cast(Any, presenter)
    dynamic.controller = _FakeController()
    dynamic.host = _FakeHost()
    dynamic._last_running_state = None
    dynamic._last_pause_state = None
    presenter.state = WorkbenchState()
    dynamic.dashboard = _FakeDashboard()
    dynamic.reverse_fill_page = _FakeReverseFillPage()
    dynamic.strategy_page = _FakeStrategyPage()
    presenter.state.configChanged.connect(presenter._render_draft_config)
    return presenter


def _question_entry(num: int = 1) -> QuestionEntry:
    return QuestionEntry(
        question_type="single",
        probabilities=[1.0],
        question_num=num,
        question_title=f"Q{num}",
    )


def _question_meta(num: int = 1) -> SurveyQuestionMeta:
    return SurveyQuestionMeta(num=num, title=f"Q{num}", type_code="3", options=1)


def test_workbench_presenter_applies_config_to_workbench_pages() -> None:
    presenter = _presenter_with_fakes()
    dashboard = cast(_FakeDashboard, presenter.dashboard)
    reverse_fill_page = cast(_FakeReverseFillPage, presenter.reverse_fill_page)
    strategy_page = cast(_FakeStrategyPage, presenter.strategy_page)
    entry = _question_entry()
    meta = _question_meta()
    cfg = RuntimeConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        target=5,
        threads=2,
        survey_title="Demo",
        question_entries=[entry],
        questions_info=[meta],
        answer_rules=[{"kind": "demo"}],
        dimension_groups=["A"],
    )

    presenter.apply_config(cfg)

    assert presenter.state.get_entries() == [entry]
    current = presenter.state.snapshot()
    assert current.url == cfg.url
    assert current.target == cfg.target
    assert current.questions_info == [meta]
    assert current.answer_rules == [{"kind": "demo"}]
    assert current.dimension_groups == ["A"]
    assert dashboard.applied == [cfg]
    assert reverse_fill_page.applied == [cfg]
    assert strategy_page.rules == [{"kind": "demo"}]


def test_workbench_presenter_survey_parsed_updates_state_and_context() -> None:
    presenter = _presenter_with_fakes()
    dashboard = cast(_FakeDashboard, presenter.dashboard)
    reverse_fill_page = cast(_FakeReverseFillPage, presenter.reverse_fill_page)
    strategy_page = cast(_FakeStrategyPage, presenter.strategy_page)
    entry = _question_entry()
    meta = _question_meta()
    cast(_FakeController, presenter.controller).question_entries = [entry]

    presenter.on_survey_snapshot_changed(
        {
            "phase": "ready",
            "url": "https://www.wjx.cn/vm/demo.aspx",
            "survey_title": "Parsed",
            "survey_provider": "wjx",
            "questions_info": [meta],
            "question_entries": [entry],
        }
    )

    assert presenter.state.get_entries() == [entry]
    assert [(item.num, item.title) for item in dashboard.parse_success_calls[-1][0]] == [(1, "Q1")]
    assert dashboard.parse_success_calls[-1][1] == "Parsed"
    assert [(item.num, item.title) for item in reverse_fill_page.parse_success_calls[-1][0]] == [
        (1, "Q1")
    ]
    assert reverse_fill_page.parse_success_calls[-1][1] == "Parsed"
    assert [(item.num, item.title) for item in strategy_page.questions_info] == [(1, "Q1")]
    assert strategy_page.dimension_groups == []
    assert dashboard.meta == ("Parsed", 1)
    assert reverse_fill_page.contexts[-1]["question_entries"] == [entry]


def test_workbench_presenter_parse_failed_notifies_reverse_fill_page() -> None:
    presenter = _presenter_with_fakes()
    dashboard = cast(_FakeDashboard, presenter.dashboard)
    reverse_fill_page = cast(_FakeReverseFillPage, presenter.reverse_fill_page)

    presenter.on_survey_parse_failed("问卷已暂停")

    assert dashboard.parse_failed_calls[-1] == "问卷已暂停"
    assert reverse_fill_page.parse_failed_calls[-1] == "问卷已暂停"


def test_workbench_presenter_renders_url_from_state_without_looping() -> None:
    presenter = _presenter_with_fakes()
    dashboard = cast(_FakeDashboard, presenter.dashboard)
    reverse_fill_page = cast(_FakeReverseFillPage, presenter.reverse_fill_page)
    presenter.state.set_url(" https://reverse.example ")

    assert presenter.state.snapshot().url == "https://reverse.example"
    assert dashboard.url_edit.text() == "https://reverse.example"
    assert reverse_fill_page.url_edit.text() == "https://reverse.example"


def test_workbench_state_preserves_url_while_editing() -> None:
    presenter = _presenter_with_fakes()

    presenter.state.set_url("www.wjx.cn/vm/demo.aspx")

    assert presenter.state.snapshot().url == "www.wjx.cn/vm/demo.aspx"


def test_workbench_presenter_forwards_random_ip_loading_state() -> None:
    presenter = _presenter_with_fakes()
    dashboard = cast(_FakeDashboard, presenter.dashboard)
    reverse_fill_page = cast(_FakeReverseFillPage, presenter.reverse_fill_page)

    presenter.on_runtime_snapshot_changed(
        {
            "running": False,
            "paused": False,
            "status_text": "等待配置...",
            "progress": {"current": 0, "target": 0},
            "threads": {"rows": [], "num_threads": 0, "per_thread_target": 0},
            "random_ip": {"loading": True, "loading_message": "正在处理..."},
        }
    )

    assert dashboard.runtime_snapshots[-1]["random_ip"]["loading"] is True
    assert reverse_fill_page.loading_events[-1] == (True, "正在处理...")


def test_workbench_presenter_skips_duplicate_run_and_pause_notifications() -> None:
    presenter = _presenter_with_fakes()
    dashboard = cast(_FakeDashboard, presenter.dashboard)
    reverse_fill_page = cast(_FakeReverseFillPage, presenter.reverse_fill_page)
    running_snapshot = {
        "running": True,
        "paused": False,
        "status_text": "运行中",
        "progress": {"current": 1, "target": 4},
        "threads": {"rows": [], "num_threads": 0, "per_thread_target": 0},
        "random_ip": {"loading": False, "loading_message": ""},
    }

    presenter.on_runtime_snapshot_changed(running_snapshot)
    presenter.on_runtime_snapshot_changed(dict(running_snapshot))

    assert dashboard.run_states == [True]
    assert reverse_fill_page.run_states == [True]
    assert dashboard.pause_states == [(False, "")]
    assert reverse_fill_page.pause_states == [(False, "")]


def test_workbench_presenter_switches_to_dashboard_execution_step_on_run_start() -> None:
    presenter = _presenter_with_fakes()
    switched: list[Any] = []
    opened_execution_steps: list[bool] = []
    presenter.host.switchTo = lambda target: switched.append(target)
    presenter.dashboard.open_execution_step = lambda: opened_execution_steps.append(True)

    presenter.on_runtime_snapshot_changed(
        {
            "running": True,
            "paused": False,
            "status_text": "已提交 0/4 份 | 提交连续失败 0 次",
            "progress": {"current": 0, "target": 4},
            "threads": {"rows": [], "num_threads": 2, "per_thread_target": 2},
            "random_ip": {"loading": False, "loading_message": ""},
        }
    )

    assert opened_execution_steps == [True]
    assert switched == [presenter.dashboard]


def test_workbench_presenter_builds_config_snapshot_from_single_draft() -> None:
    presenter = _presenter_with_fakes()
    controller = cast(_FakeController, presenter.controller)
    entry = _question_entry()
    meta = _question_meta()
    presenter.state.set_entries([entry], [meta])
    presenter.state.set_url("https://www.wjx.cn/vm/demo.aspx")
    presenter.state.update_settings(target=3, threads=2)

    cfg = presenter.build_current_config_snapshot()

    assert cfg.url == "https://www.wjx.cn/vm/demo.aspx"
    assert cfg.target == 3
    assert cfg.threads == 2
    assert cfg.question_entries == [entry]
    assert [(item.num, item.title) for item in cfg.questions_info] == [(1, "Q1")]
    assert cfg.reverse_fill_source_path == ""
    assert controller.config != cfg
