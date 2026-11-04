from __future__ import annotations

import threading

import pytest
from openpyxl import Workbook

from software.core.config.schema import RuntimeConfig
from software.core.reverse_fill.validation import (
    ReverseFillValidationCancelled,
    build_enabled_reverse_fill_spec,
    build_reverse_fill_spec,
)
from surveycore.core.reverse_fill.schema import REVERSE_FILL_FORMAT_WJX_SEQUENCE


def _write_workbook(path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["序号", "1、单选题"])
    sheet.append([1, 1])
    sheet.append([2, 2])
    workbook.save(path)
    workbook.close()


def _build_spec(source_path, **kwargs):
    return build_reverse_fill_spec(
        source_path=str(source_path),
        survey_provider="wjx",
        questions_info=[
            {
                "num": 1,
                "title": "单选题",
                "type_code": "3",
                "option_texts": ["选项1", "选项2"],
            }
        ],
        question_entries=[],
        selected_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE,
        target_num=2,
        **kwargs,
    )


def test_reverse_fill_validation_reports_read_and_validation_progress(tmp_path) -> None:
    source_path = tmp_path / "samples.xlsx"
    _write_workbook(source_path)
    progress: list[tuple[str, int, int]] = []

    _build_spec(
        source_path,
        progress_callback=lambda stage, current, total: progress.append((stage, current, total)),
    )

    assert progress[0] == ("reading", 0, 0)
    assert ("preparing", 2, 2) in progress
    assert ("questions", 1, 1) in progress
    assert ("samples", 2, 2) in progress
    assert progress[-1] == ("complete", 1, 1)


def test_reverse_fill_validation_honors_cancellation_between_sample_rows(tmp_path) -> None:
    source_path = tmp_path / "samples.xlsx"
    _write_workbook(source_path)
    cancel_event = threading.Event()

    def request_cancel(stage: str, _current: int, _total: int) -> None:
        if stage == "samples":
            cancel_event.set()

    with pytest.raises(ReverseFillValidationCancelled):
        _build_spec(
            source_path,
            progress_callback=request_cancel,
            cancellation_check=cancel_event.is_set,
        )


def test_enabled_reverse_fill_validation_accepts_cancellation_check(tmp_path) -> None:
    source_path = tmp_path / "samples.xlsx"
    _write_workbook(source_path)
    cancel_event = threading.Event()

    def request_cancel(stage: str, _current: int, _total: int) -> None:
        if stage == "samples":
            cancel_event.set()

    config = RuntimeConfig(
        survey_provider="wjx",
        reverse_fill_enabled=True,
        reverse_fill_source_path=str(source_path),
        reverse_fill_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE,
        target=2,
    )
    with pytest.raises(ReverseFillValidationCancelled):
        build_enabled_reverse_fill_spec(
            config,
            questions_info=[
                {
                    "num": 1,
                    "title": "单选题",
                    "type_code": "3",
                    "option_texts": ["选项1", "选项2"],
                }
            ],
            question_entries=[],
            progress_callback=request_cancel,
            cancellation_check=cancel_event.is_set,
        )
