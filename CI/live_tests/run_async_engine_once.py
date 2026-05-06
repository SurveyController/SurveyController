#!/usr/bin/env python
"""Run one real survey submission through AsyncRuntimeEngine."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from software.core.engine.async_engine import AsyncEngineClient
from software.core.task import ExecutionState
from software.io.config import load_config
from software.ui.controller.run_controller_parts.runtime_preparation import prepare_execution_artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = load_config(args.config, strict=True)
    config.target = 1
    config.threads = 1
    config.submit_interval = (0, 0)
    config.answer_duration = (0, 0)
    config.random_ip_enabled = False
    config.random_ua_enabled = False
    config.fail_stop_enabled = True
    if args.headed:
        config.headless_mode = False
    else:
        config.headless_mode = True

    prepared = prepare_execution_artifacts(config, fallback_survey_title=config.survey_title)
    execution_config = prepared.execution_config_template
    execution_config.target_num = 1
    execution_config.num_threads = 1
    execution_config.submit_interval_range_seconds = (0, 0)
    execution_config.answer_duration_range_seconds = (0, 0)
    execution_config.random_proxy_ip_enabled = False
    execution_config.random_user_agent_enabled = False
    execution_config.headless_mode = bool(config.headless_mode)
    state = ExecutionState(config=execution_config)
    state.initialize_reverse_fill_runtime()

    client = AsyncEngineClient()
    try:
        future = client.start_run(execution_config, state, gui_instance=None)
        future.result(timeout=max(1.0, float(args.timeout or 1.0)))
    finally:
        client.shutdown(timeout=15.0)

    print(
        f"provider={execution_config.survey_provider} cur_num={state.cur_num} "
        f"cur_fail={state.cur_fail} terminal={state.get_terminal_stop_snapshot()}"
    )
    return 0 if int(state.cur_num or 0) >= 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
