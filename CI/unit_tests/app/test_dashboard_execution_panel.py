from __future__ import annotations

from software.ui.pages.workbench.dashboard.execution_panel import DashboardExecutionPanel


def test_execution_panel_displays_submission_and_session_progress(qtbot) -> None:
    panel = DashboardExecutionPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.on_run_state_changed(True)
    panel.apply_runtime_snapshot(
        {
            "running": True,
            "paused": False,
            "phase_code": "running",
            "status_text": "已提交 1/4 份 | 提交连续失败 0 次",
            "progress": {"current": 1, "target": 4, "consecutive_failures": 0},
            "threads": {
                "num_threads": 4,
                "per_thread_target": 1,
                "rows": [
                    {
                        "thread_name": "Slot-1",
                        "status_text": "构造答案",
                        "success_count": 1,
                        "fail_count": 0,
                        "step_current": 2,
                        "step_total": 4,
                        "running": True,
                        "progress_kind": "waiting",
                    },
                    {
                        "thread_name": "Slot-2",
                        "status_text": "正在提交",
                        "success_count": 0,
                        "fail_count": 0,
                        "step_current": 0,
                        "step_total": 0,
                        "running": True,
                        "progress_kind": "submitting",
                    },
                    {
                        "thread_name": "Slot-3",
                        "status_text": "失败重试",
                        "success_count": 0,
                        "fail_count": 1,
                        "step_current": 0,
                        "step_total": 0,
                        "running": True,
                        "progress_kind": "unknown",
                    },
                    {
                        "thread_name": "Slot-4",
                        "status_text": "网络请求失败",
                        "success_count": 0,
                        "fail_count": 1,
                        "step_current": 0,
                        "step_total": 0,
                        "running": False,
                        "progress_kind": "failed",
                    },
                ],
            },
        }
    )
    assert panel.summary_label.text() == "1 / 4 份"
    assert panel.overall_status_label.text() == "执行中"

    assert {row["name"].text(): row["status"].text() for row in panel._session_rows.values()} == {
        "会话 1": "构造答案",
        "会话 2": "正在提交",
        "会话 3": "失败重试",
        "会话 4": "网络请求失败",
    }
    assert panel._session_rows["Slot-1"]["pct"].text() == "50%"


def test_execution_panel_dispatches_pause_resume_and_stop_controls(qtbot) -> None:
    panel = DashboardExecutionPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.reset_for_new_run(10)
    assert panel.overall_status_label.text() == "正在初始化"

    panel.on_run_state_changed(True)
    assert panel.back_btn.isEnabled() is False
    assert panel.pause_resume_btn.isHidden() is False
    assert panel.stop_btn.isHidden() is False
    assert panel.restart_btn.isHidden() is True
    with qtbot.waitSignal(panel.pauseRequested):
        panel.pause_resume_btn.click()

    panel.apply_runtime_snapshot(
        {
            "running": True,
            "paused": True,
            "phase_code": "paused",
            "pause_reason": "用户手动暂停",
            "status_text": "已暂停 2/10 份 | 提交连续失败 0 次 | 用户手动暂停",
            "progress": {"current": 2, "target": 10, "consecutive_failures": 0},
            "threads": {"rows": []},
        }
    )
    panel.on_pause_state_changed(True, "用户手动暂停")
    assert panel.overall_status_label.text() == "已暂停"
    assert panel.pause_resume_btn.text() == "继续执行"
    with qtbot.waitSignal(panel.resumeRequested):
        panel.pause_resume_btn.click()
    with qtbot.waitSignal(panel.stopRequested):
        panel.stop_btn.click()

    panel.on_run_state_changed(False)
    assert panel.back_btn.isEnabled() is True
    assert panel.pause_resume_btn.isHidden() is True
    assert panel.stop_btn.isHidden() is True
    assert panel.restart_btn.isHidden() is False
