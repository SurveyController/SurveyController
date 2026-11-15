from __future__ import annotations

from software.ui.pages.workbench.dashboard.execution_panel import DashboardExecutionPanel


def test_execution_panel_renders_four_progress_bar_states(qtbot) -> None:
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
    qtbot.wait(180)

    assert panel.overall_progress_ring.value() == 25
    assert panel.overall_progress_ring.isHidden() is False
    assert panel.overall_indeterminate_ring.isHidden() is True
    assert panel.summary_label.text() == "1 / 4 份"
    assert panel.overall_status_label.text() == "执行中"
    assert panel.overall_fail_label.text() == "连续失败 0 次"
    assert panel.sessions_count_label.text() == "4 个"

    row_percent = panel._session_rows["Slot-1"]
    assert row_percent["name"].text() == "会话 1"
    assert row_percent["step_bar"].isHidden() is False
    assert row_percent["step_busy_bar"].isHidden() is True
    assert row_percent["step_bar"].value() == 50
    assert row_percent["step_bar"].isPaused() is False
    assert row_percent["step_bar"].isError() is False
    assert row_percent["pct"].text() == "50%"

    row_loading = panel._session_rows["Slot-2"]
    assert row_loading["step_bar"].isHidden() is True
    assert row_loading["step_busy_bar"].isHidden() is False
    assert row_loading["pct"].text() == "..."

    row_yellow = panel._session_rows["Slot-3"]
    assert row_yellow["step_bar"].isHidden() is False
    assert row_yellow["step_busy_bar"].isHidden() is True
    assert row_yellow["step_bar"].isPaused() is True
    assert row_yellow["step_bar"].isError() is False

    row_red = panel._session_rows["Slot-4"]
    assert row_red["step_bar"].isHidden() is False
    assert row_red["step_busy_bar"].isHidden() is True
    assert row_red["step_bar"].isError() is True

    for row in panel._session_rows.values():
        assert "·" not in row["name"].text()
        assert "·" not in row["status"].text()
        assert "·" not in row["counter"].text()
        assert "·" not in row["pct"].text()


def test_execution_panel_overall_states_and_controls(qtbot) -> None:
    panel = DashboardExecutionPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.reset_for_new_run(10)
    assert panel.overall_progress_ring.isHidden() is True
    assert panel.overall_indeterminate_ring.isHidden() is False

    panel.on_run_state_changed(True)
    assert panel.back_btn.isEnabled() is False
    assert panel.pause_resume_btn.isHidden() is False
    assert panel.stop_btn.isHidden() is False
    assert panel.restart_btn.isHidden() is True

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
    assert panel.overall_progress_ring.isPaused() is True
    assert panel.overall_status_label.text() == "已暂停：用户手动暂停"
    assert panel.pause_resume_btn.text() == "继续执行"

    panel.on_run_state_changed(False)
    assert panel.back_btn.isEnabled() is True
    assert panel.pause_resume_btn.isHidden() is True
    assert panel.stop_btn.isHidden() is True
    assert panel.restart_btn.isHidden() is False
