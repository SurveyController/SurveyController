from __future__ import annotations

import logging
from unittest.mock import patch

from software.logging.action_logger import log_action


def test_log_action_suppresses_low_value_info_clicks() -> None:
    with patch("software.logging.action_logger.logging.log") as mock_log:
        log_action("NAV", "switch_page", "settings", "main")

    mock_log.assert_not_called()


def test_log_action_keeps_important_info_events() -> None:
    with patch("software.logging.action_logger.logging.log") as mock_log:
        log_action(
            "RUN",
            "start_run",
            "start_btn",
            "dashboard",
            result="submitted",
            payload={"threads": 3},
        )

    mock_log.assert_called_once()
    message = mock_log.call_args.args[1]
    assert "event=start_run" in message
    assert "threads=3" in message


def test_log_action_keeps_warning_events_even_when_not_whitelisted() -> None:
    with patch("software.logging.action_logger.logging.log") as mock_log:
        log_action(
            "UI",
            "open_config_list",
            "config_btn",
            "dashboard",
            level=logging.WARNING,
        )

    mock_log.assert_called_once()
