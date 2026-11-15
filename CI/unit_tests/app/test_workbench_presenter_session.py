from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import QObject
from surveycore.core.questions.config import QuestionEntry
from surveycore.providers.contracts import SurveyQuestionMeta

import software.ui.pages.workbench.presenter as presenter_module
import software.ui.pages.workbench.session as session_module
from software.core.config.schema import RuntimeConfig
from software.ui.controller.run_controller import RunController
from software.ui.pages.workbench.presenter import WorkbenchPresenter
from software.ui.pages.workbench.session import WorkbenchRunCoordinator, WorkbenchState


class _LineEdit(QObject):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._text = text

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text


def _presenter() -> WorkbenchPresenter:
    controller = SimpleNamespace(
        config=RuntimeConfig(url="https://www.wjx.cn/vm/demo.aspx", survey_provider="wjx"),
        question_entries=[QuestionEntry("single", [1, 1], question_num=1)],
        load_saved_config=MagicMock(),
        refresh_random_ip_counter=MagicMock(),
    )
    controller.get_survey_snapshot = lambda: {"question_entries": controller.question_entries}
    controller.replace_question_entries = MagicMock(
        side_effect=lambda entries, **_kwargs: setattr(
            controller, "question_entries", list(entries or [])
        )
    )
    p = WorkbenchPresenter.__new__(WorkbenchPresenter)
    p.controller = controller
    p.host = SimpleNamespace(
        toasts=[], _toast=lambda text, level="info": p.host.toasts.append((text, level))
    )
    p.state = WorkbenchState()
    p.strategy_page = SimpleNamespace(
        set_questions_info=MagicMock(),
        set_entries=MagicMock(),
        set_rules=MagicMock(),
        set_dimension_groups=MagicMock(),
    )
    p.dashboard = SimpleNamespace(
        url_edit=_LineEdit(),
        _survey_title="旧标题",
        _open_wizard_after_parse=False,
        apply_config=MagicMock(),
        update_question_meta=MagicMock(),
        run_question_wizard=MagicMock(return_value=True),
        open_inline_question_wizard=MagicMock(),
        _on_survey_parsed=MagicMock(),
        _on_survey_parse_failed=MagicMock(),
        present_parse_succeeded=MagicMock(),
        present_parse_failed=MagicMock(),
        apply_runtime_snapshot=MagicMock(),
        on_run_state_changed=MagicMock(),
        on_pause_state_changed=MagicMock(),
        open_execution_step=MagicMock(),
        _toast=MagicMock(),
    )
    p.dashboard.open_inline_question_wizard.side_effect = lambda *_args, on_finished, **_kwargs: (
        on_finished(False)
    )
    p.reverse_fill_page = SimpleNamespace(
        url_edit=_LineEdit(),
        apply_config=MagicMock(),
        set_question_context=MagicMock(),
        _refresh_preview=MagicMock(),
        present_parse_succeeded=MagicMock(),
        present_parse_failed=MagicMock(),
    )
    p.state.configChanged.connect(p._render_draft_config)
    return p


def test_workbench_state_sets_and_appends_entries() -> None:
    state = WorkbenchState()
    seen: list[frozenset[str]] = []
    state.configChanged.connect(lambda _config, changed: seen.append(changed))

    info = [SurveyQuestionMeta(num=1, title="标题", type_code="3", option_texts=["A"])]
    entry = QuestionEntry("single", [1, 1], question_num=1)
    state.set_questions(info, [entry])

    assert state.questions_info[0].title == "标题"
    assert state.entries[0].question_title == "标题"
    assert entry.question_title is None
    assert state.has_question_entries() is True
    assert "question_entries" in seen[-1]
    assert state.get_entries() == state.entries

    state.append_entry(QuestionEntry("text", None, question_title="手动"))
    assert len(state.entries) == 2


def test_controller_saves_the_supplied_ui_draft_without_overwriting_it() -> None:
    saved = MagicMock(return_value="draft.json")
    controller = SimpleNamespace(_command_service=SimpleNamespace(save_config=saved))
    draft = RuntimeConfig(
        url="https://www.wjx.cn/vm/draft.aspx",
        target=8,
        threads=3,
        question_entries=[QuestionEntry("single", [2, 3], question_num=1)],
    )

    result = RunController.save_current_config(
        controller, "draft.json", config=draft, include_secrets=True
    )

    assert result == "draft.json"
    config = saved.call_args.args[0]
    assert config.url == draft.url
    assert config.target == 8
    assert config.threads == 3
    assert config.question_entries == draft.question_entries
    assert config is not draft
    saved.assert_called_once_with(config, "draft.json", include_secrets=True)


def test_workbench_run_coordinator_blocks_restarts_and_builds_config(monkeypatch) -> None:
    state = WorkbenchState()
    dashboard = SimpleNamespace(
        _completion_notified=False,
        _last_progress=0,
        _pending_restart=False,
        _toast=MagicMock(),
        _sync_start_button_state=MagicMock(),
        progress_bar=SimpleNamespace(setValue=MagicMock()),
        progress_pct=SimpleNamespace(setText=MagicMock()),
        status_label=SimpleNamespace(setText=MagicMock()),
        _on_resume_clicked=MagicMock(),
    )
    controller = SimpleNamespace(
        running=True,
        stop_run=MagicMock(),
        start_run=MagicMock(),
        set_runtime_ui_state=MagicMock(),
    )
    coordinator = WorkbenchRunCoordinator(controller=controller, state=state, dashboard=dashboard)
    state.update_settings(target=2, threads=1)

    assert coordinator.start() is False
    controller.stop_run.assert_not_called()

    dashboard._completion_notified = True
    assert coordinator.start() is False
    controller.stop_run.assert_called_once()
    assert dashboard._pending_restart is True

    controller.running = False
    dashboard._completion_notified = False
    monkeypatch.setattr(session_module, "log_action", lambda *_args, **_kwargs: None)
    assert coordinator.start() is False
    dashboard._toast.assert_called_with(
        "未配置任何题目，无法开始执行（请先在'题目配置'页添加/配置题目）",
        "warning",
    )

    state.set_entries([QuestionEntry("single", [1, 1])], [])
    state.update_settings(reverse_fill_source_path="data.xlsx", reverse_fill_threads=3)
    dashboard._last_progress = 100
    coordinator.set_reverse_fill_target(5)
    reverse_page = SimpleNamespace(
        progress_bar=SimpleNamespace(setValue=MagicMock()),
        progress_pct=SimpleNamespace(setText=MagicMock()),
        status_label=SimpleNamespace(setText=MagicMock()),
        _on_resume_clicked=MagicMock(),
    )
    session_module.set_completion_notified(reverse_page, True)
    session_module.set_last_progress(reverse_page, 100)
    coordinator.bind_reverse_fill_page(reverse_page)
    assert coordinator.start(enable_reverse_fill=True) is True
    cfg = controller.start_run.call_args.args[0]
    assert cfg.target == 5
    assert cfg.reverse_fill_enabled is True
    assert reverse_page.progress_bar.setValue.called

    state.update_settings(target=9)
    assert coordinator.build_config().target == 9

    dashboard.resume_run_from_ui = MagicMock()
    coordinator.resume()
    reverse_page._on_resume_clicked.assert_called_once()


def test_workbench_run_coordinator_checks_ai_only_before_start(monkeypatch) -> None:
    state = WorkbenchState()
    state.set_entries([QuestionEntry("text", None, ai_enabled=True)], [])
    dashboard = SimpleNamespace(
        _completion_notified=False,
        _last_progress=0,
        _pending_restart=False,
        _toast=MagicMock(),
        build_base_config=MagicMock(return_value=RuntimeConfig(target=1, threads=1)),
    )
    controller = SimpleNamespace(running=False, start_run=MagicMock())
    coordinator = WorkbenchRunCoordinator(controller=controller, state=state, dashboard=dashboard)

    monkeypatch.setattr(session_module, "get_ai_readiness_error", lambda: "缺少 API Key")

    assert coordinator.start() is False
    controller.start_run.assert_not_called()
    dashboard._toast.assert_called_once_with("请先补全 AI 配置：缺少 API Key", "warning")


def test_presenter_apply_load_build_and_url_sync(monkeypatch) -> None:
    p = _presenter()
    cfg = RuntimeConfig(
        url="https://wjx.cn/vm/demo.aspx",
        survey_title="标题",
        question_entries=[QuestionEntry("single", [1, 1], question_num=1)],
        questions_info=[SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A"])],
        answer_rules=[{"id": "r"}],
        dimension_groups=["体验"],
    )

    p.apply_config(cfg)

    assert p.state.snapshot().url == cfg.url
    assert p.state.snapshot().answer_rules == [{"id": "r"}]
    assert p.dashboard.apply_config.call_args.args[0].url == cfg.url
    assert p.reverse_fill_page.apply_config.call_args.args[0].url == cfg.url
    assert p.strategy_page.set_rules.call_args.args[0] == [{"id": "r"}]
    assert p.dashboard.update_question_meta.call_args.args == ("标题", 1)
    assert p.reverse_fill_page.set_question_context.called

    p.controller.load_saved_config.return_value = cfg
    assert p.load_saved_config(strict=True) is cfg
    p.controller.load_saved_config.assert_called_with(strict=True)
    p.controller.refresh_random_ip_counter.assert_called()

    assert p.load_config_from_path("x.json") is cfg
    p.controller.load_saved_config.assert_called_with("x.json", strict=True)

    built = p.build_current_config()
    assert built.url == "https://wjx.cn/vm/demo.aspx"
    assert built.reverse_fill_source_path == ""

    snapshot = p.build_current_config_snapshot()
    assert p.controller.config != snapshot
    assert snapshot.question_entries

    p.state.set_url(" next ")
    assert p.dashboard.url_edit.text() == "next"
    assert p.reverse_fill_page.url_edit.text() == "next"
    p.reverse_fill_page._refresh_preview.assert_called()


def test_presenter_parse_success_failed_and_reverse_fill_wizard(monkeypatch) -> None:
    p = _presenter()
    monkeypatch.setattr(presenter_module.QTimer, "singleShot", lambda _delay, callback: callback())
    monkeypatch.setattr(presenter_module, "log_action", lambda *_args, **_kwargs: None)
    p.controller.config.url = "https://wjx.cn/vm/demo.aspx"
    p.controller.question_entries = [QuestionEntry("single", [1, 1], question_num=1)]
    info = [SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A"])]

    p.dashboard._open_wizard_after_parse = True
    p.on_survey_snapshot_changed(
        {
            "phase": "ready",
            "url": p.controller.config.url,
            "survey_title": "解析标题",
            "survey_provider": "wjx",
            "questions_info": info,
            "question_entries": p.controller.question_entries,
        }
    )
    parsed_call = p.dashboard.present_parse_succeeded.call_args
    assert parsed_call is not None
    assert parsed_call.args[1] == "解析标题"
    assert [(item.num, item.title) for item in parsed_call.args[0]] == [(1, "Q1")]
    p.dashboard.open_inline_question_wizard.assert_called()
    assert p.dashboard._open_wizard_after_parse is False
    assert p.controller.question_entries[0].question_num == 1

    p.dashboard.run_question_wizard.reset_mock()
    p.on_survey_snapshot_changed(
        {
            "phase": "ready",
            "url": p.controller.config.url,
            "survey_title": "",
            "survey_provider": "wjx",
            "questions_info": info,
            "question_entries": p.controller.question_entries,
        }
    )
    assert p.strategy_page.set_entries.called
    p.dashboard.update_question_meta.assert_called_with("问卷", 1)

    p.dashboard._open_wizard_after_parse = True
    p.on_survey_parse_failed("问卷已暂停")
    p.dashboard.present_parse_failed.assert_called_with("问卷已暂停")
    assert p.dashboard._open_wizard_after_parse is False
    assert p.state.get_entries() == []
    assert p.strategy_page.set_questions_info.call_args.args[0] == []

    p.state.set_questions(info, p.controller.question_entries)
    p.open_reverse_fill_wizard([])
    assert p.host.toasts[-1] == ("当前没有需要处理的异常题目。", "warning")

    p.state.set_questions([], [])
    p.open_reverse_fill_wizard([1])
    assert p.host.toasts[-1] == ("当前还没有解析出题目，无法打开配置向导。", "warning")

    p.state.set_questions(info, p.controller.question_entries)
    p.open_reverse_fill_wizard([1])
    p.dashboard.run_question_wizard.assert_called()

    p.open_parse_wizard_after_parse(info, "标题", issue_question_nums=[99])
    assert p.host.toasts[-1] == ("异常题目配置数据不完整，暂时无法打开配置向导。", "warning")

    p.dashboard.run_question_wizard.return_value = False
    p.open_parse_wizard_after_parse(info, "标题")
    assert p.host.toasts[-1] == ("已取消自动配置，保留原有题目设置", "warning")

    p.dashboard.open_inline_question_wizard.side_effect = RuntimeError("boom")
    p.open_parse_wizard_after_parse(info, "标题")
    p.dashboard._toast.assert_called_with(
        "自动配置向导打开失败，已保留原有题目设置；详细原因已写入日志",
        "error",
        duration=4200,
    )


def test_presenter_clears_old_questions_while_parsing_snapshot() -> None:
    p = _presenter()
    info = [SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A"])]
    p.state.set_questions(info, p.controller.question_entries)

    p.on_survey_snapshot_changed(
        {
            "phase": "parsing",
            "url": "https://wj.qq.com/s2/123/hash/",
            "survey_title": "",
            "questions_info": [],
            "question_entries": [],
            "parse_error": "",
        }
    )

    assert p.state.get_entries() == []
    assert p.strategy_page.set_questions_info.call_args.args[0] == []
