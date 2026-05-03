from __future__ import annotations

import os
import tempfile
import unittest

from openpyxl import Workbook

from software.app.config import DEFAULT_FILL_TEXT
from software.core.questions.schema import QuestionEntry
from software.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
    REVERSE_FILL_STATUS_BLOCKED,
    REVERSE_FILL_STATUS_FALLBACK,
    REVERSE_FILL_STATUS_REVERSE,
)
from software.core.reverse_fill.validation import build_enabled_reverse_fill_spec, build_reverse_fill_spec
from software.io.config import RuntimeConfig
from software.io.spreadsheets import load_wjx_excel_export


def _write_workbook(rows: list[list[object]]) -> str:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(list(row))
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    handle.close()
    workbook.save(handle.name)
    workbook.close()
    return handle.name


class WjxReverseFillTests(unittest.TestCase):
    def tearDown(self) -> None:
        for path in getattr(self, "_temp_paths", []):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def _track(self, path: str) -> str:
        if not hasattr(self, "_temp_paths"):
            self._temp_paths = []
        self._temp_paths.append(path)
        return path

    def test_detects_three_wjx_export_formats(self) -> None:
        sequence_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、单选题", "2、(选项1)", "2、(选项2)"],
                    [1, 2, 1, 2],
                ]
            )
        )
        score_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、满意度"],
                    [1, 4],
                ]
            )
        )
        text_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、满意度"],
                    [1, "4"],
                ]
            )
        )

        self.assertEqual(load_wjx_excel_export(sequence_path).detected_format, REVERSE_FILL_FORMAT_WJX_SEQUENCE)
        self.assertEqual(load_wjx_excel_export(score_path).detected_format, REVERSE_FILL_FORMAT_WJX_SCORE)
        self.assertEqual(load_wjx_excel_export(text_path).detected_format, REVERSE_FILL_FORMAT_WJX_TEXT)

    def test_build_reverse_fill_spec_parses_supported_v1_answers(self) -> None:
        workbook_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、单选题", "2、姓名", "3、字段A", "3、字段B", "4、外观", "4、功能"],
                    [1, 2, "张三", "甲", "乙", 1, 2],
                ]
            )
        )
        questions_info = [
            {"num": 1, "title": "单选题", "type_code": "3", "option_texts": ["选项1", "选项2", "选项3"]},
            {"num": 2, "title": "姓名", "type_code": "1"},
            {"num": 3, "title": "多项填空", "type_code": "1", "is_multi_text": True, "text_input_labels": ["字段A", "字段B"]},
            {"num": 4, "title": "矩阵题", "type_code": "6", "row_texts": ["外观", "功能"], "option_texts": ["差", "中", "好"]},
        ]

        spec = build_reverse_fill_spec(
            source_path=workbook_path,
            survey_provider="wjx",
            questions_info=questions_info,
            question_entries=[],
            selected_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE,
            start_row=1,
            target_num=1,
        )

        self.assertEqual(spec.selected_format, REVERSE_FILL_FORMAT_WJX_SEQUENCE)
        self.assertEqual(spec.blocking_issue_count, 0)
        self.assertEqual([plan.status for plan in spec.question_plans], [REVERSE_FILL_STATUS_REVERSE] * 4)
        self.assertEqual(spec.samples[0].answers[1].choice_index, 1)
        self.assertEqual(spec.samples[0].answers[2].text_value, "张三")
        self.assertEqual(spec.samples[0].answers[3].text_values, ["甲", "乙"])
        self.assertEqual(spec.samples[0].answers[4].matrix_choice_indexes, [0, 1])

    def test_build_reverse_fill_spec_blocks_unsupported_composite_value(self) -> None:
        workbook_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、单选题"],
                    [1, "其他〖无〗"],
                ]
            )
        )
        questions_info = [
            {"num": 1, "title": "单选题", "type_code": "3", "option_texts": ["选项1", "选项2"]},
        ]

        spec = build_reverse_fill_spec(
            source_path=workbook_path,
            survey_provider="wjx",
            questions_info=questions_info,
            question_entries=[],
            selected_format=REVERSE_FILL_FORMAT_WJX_TEXT,
            start_row=1,
            target_num=1,
        )

        self.assertEqual(spec.blocking_issue_count, 1)
        self.assertEqual(spec.question_plans[0].status, REVERSE_FILL_STATUS_BLOCKED)
        self.assertEqual(spec.issues[0].category, "unsupported_value")

    def test_build_reverse_fill_spec_uses_available_samples_as_target_when_not_provided(self) -> None:
        workbook_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、单选题"],
                    [1, 1],
                    [2, 2],
                    [3, 1],
                ]
            )
        )

        spec = build_reverse_fill_spec(
            source_path=workbook_path,
            survey_provider="wjx",
            questions_info=[
                {"num": 1, "title": "单选题", "type_code": "3", "option_texts": ["选项1", "选项2"]},
            ],
            question_entries=[],
            selected_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE,
            start_row=2,
            target_num=0,
        )

        self.assertEqual(spec.available_samples, 2)
        self.assertEqual(spec.target_num, 2)

    def test_build_reverse_fill_spec_blocks_when_start_row_has_no_remaining_samples(self) -> None:
        workbook_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、单选题"],
                    [1, 1],
                ]
            )
        )

        spec = build_reverse_fill_spec(
            source_path=workbook_path,
            survey_provider="wjx",
            questions_info=[
                {"num": 1, "title": "单选题", "type_code": "3", "option_texts": ["选项1", "选项2"]},
            ],
            question_entries=[],
            selected_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE,
            start_row=2,
            target_num=0,
        )

        self.assertEqual(spec.blocking_issue_count, 1)
        self.assertEqual(spec.issues[0].category, "sample_empty")

    def test_build_reverse_fill_spec_marks_custom_fallback_as_resolved(self) -> None:
        workbook_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、姓名", "1、姓名补列"],
                    [1, "张三", "李四"],
                ]
            )
        )

        spec = build_reverse_fill_spec(
            source_path=workbook_path,
            survey_provider="wjx",
            questions_info=[
                {"num": 1, "title": "姓名", "type_code": "1"},
            ],
            question_entries=[
                QuestionEntry(
                    question_type="text",
                    probabilities=[1.0],
                    texts=["手动配置值"],
                    question_num=1,
                    question_title="姓名",
                )
            ],
            selected_format=REVERSE_FILL_FORMAT_WJX_TEXT,
            start_row=1,
            target_num=0,
        )

        self.assertEqual(spec.question_plans[0].status, "fallback_config")
        self.assertTrue(spec.question_plans[0].fallback_ready)
        self.assertTrue(spec.question_plans[0].fallback_resolved)

    def test_build_reverse_fill_spec_keeps_default_fallback_unresolved(self) -> None:
        workbook_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、姓名", "1、姓名补列"],
                    [1, "张三", "李四"],
                ]
            )
        )

        spec = build_reverse_fill_spec(
            source_path=workbook_path,
            survey_provider="wjx",
            questions_info=[
                {"num": 1, "title": "姓名", "type_code": "1"},
            ],
            question_entries=[
                QuestionEntry(
                    question_type="text",
                    probabilities=[1.0],
                    texts=[DEFAULT_FILL_TEXT],
                    question_num=1,
                    question_title="姓名",
                )
            ],
            selected_format=REVERSE_FILL_FORMAT_WJX_TEXT,
            start_row=1,
            target_num=0,
        )

        self.assertEqual(spec.question_plans[0].status, "fallback_config")
        self.assertTrue(spec.question_plans[0].fallback_ready)
        self.assertFalse(spec.question_plans[0].fallback_resolved)

    def test_build_reverse_fill_spec_marks_order_as_auto_handled_unsupported(self) -> None:
        workbook_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、排序题"],
                    [1, "1→2→3"],
                ]
            )
        )

        spec = build_reverse_fill_spec(
            source_path=workbook_path,
            survey_provider="wjx",
            questions_info=[
                {"num": 1, "title": "排序题", "type_code": "11", "option_texts": ["A", "B", "C"]},
            ],
            question_entries=[],
            selected_format=REVERSE_FILL_FORMAT_WJX_TEXT,
            start_row=1,
            target_num=0,
        )

        self.assertEqual(spec.blocking_issue_count, 0)
        self.assertEqual(spec.question_plans[0].status, REVERSE_FILL_STATUS_BLOCKED)
        self.assertEqual(spec.issues[0].category, "auto_handled")
        self.assertEqual(spec.issues[0].severity, "warn")
        self.assertIn("自动按常规逻辑处理", spec.issues[0].suggestion)

    def test_build_enabled_reverse_fill_spec_raises_human_readable_blocking_message(self) -> None:
        workbook_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、单选题"],
                    [1, "其他〖无〗"],
                ]
            )
        )

        config = RuntimeConfig(
            survey_provider="wjx",
            reverse_fill_source_path=workbook_path,
            reverse_fill_format=REVERSE_FILL_FORMAT_WJX_TEXT,
            reverse_fill_start_row=1,
        )

        with self.assertRaisesRegex(ValueError, "反填配置校验失败") as context:
            build_enabled_reverse_fill_spec(
                config,
                questions_info=[
                    {"num": 1, "title": "单选题", "type_code": "3", "option_texts": ["选项1", "选项2"]},
                ],
                question_entries=[],
            )

        self.assertIn("第 1 题", str(context.exception))
        self.assertIn("无法匹配选项", str(context.exception))

    def test_build_enabled_reverse_fill_spec_allows_warn_only_fallback_plan(self) -> None:
        workbook_path = self._track(
            _write_workbook(
                [
                    ["序号", "1、所在地区"],
                    [1, "上海"],
                ]
            )
        )

        spec = build_enabled_reverse_fill_spec(
            RuntimeConfig(
                survey_provider="wjx",
                reverse_fill_source_path=workbook_path,
                reverse_fill_format=REVERSE_FILL_FORMAT_WJX_TEXT,
                reverse_fill_start_row=1,
            ),
            questions_info=[
                {"num": 1, "title": "所在地区", "type_code": "1", "is_location": True},
            ],
            question_entries=[
                QuestionEntry(
                    question_type="text",
                    probabilities=[1.0],
                    texts=["上海"],
                    question_num=1,
                    question_title="所在地区",
                    is_location=True,
                )
            ],
        )

        self.assertEqual(spec.blocking_issue_count, 0)
        self.assertEqual(spec.question_plans[0].status, REVERSE_FILL_STATUS_FALLBACK)
        self.assertTrue(spec.question_plans[0].fallback_ready)


if __name__ == "__main__":
    unittest.main()
