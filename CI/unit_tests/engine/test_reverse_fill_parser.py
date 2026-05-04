from __future__ import annotations
import pytest
from software.core.reverse_fill.parser import parse_choice_answer, parse_matrix_answer, parse_multi_text_answer, resolve_ordered_columns, supports_reverse_fill_runtime
from software.core.reverse_fill.schema import REVERSE_FILL_FORMAT_WJX_SCORE, REVERSE_FILL_FORMAT_WJX_TEXT, ReverseFillColumn, ReverseFillRawRow

class ReverseFillParserTests:

    def test_resolve_ordered_columns_reorders_by_suffix_label(self) -> None:
        columns = [ReverseFillColumn(column_index=4, header='1、矩阵题-功能', question_num=1, suffix='功能'), ReverseFillColumn(column_index=3, header='1、矩阵题-外观', question_num=1, suffix='外观')]
        ordered = resolve_ordered_columns(columns, ['外观', '功能'])
        assert [column.column_index for column in ordered] == [3, 4]

    def test_supports_reverse_fill_runtime_rejects_location_and_fillable_options(self) -> None:
        assert not supports_reverse_fill_runtime('text', {'is_location': True})
        assert not supports_reverse_fill_runtime('single', {'fillable_options': ['其他']})
        assert not supports_reverse_fill_runtime('dropdown', {'attached_option_selects': [{'index': 0}]})
        assert supports_reverse_fill_runtime('text', {'is_location': False})

    def test_parse_choice_answer_accepts_numeric_score_text(self) -> None:
        answer = parse_choice_answer(question_num=1, question_type='score', raw_value='2', export_format=REVERSE_FILL_FORMAT_WJX_SCORE, option_texts=['差', '中', '好'])
        assert answer is not None
        assert answer.choice_index == 1

    def test_parse_choice_answer_rejects_composite_value(self) -> None:
        with pytest.raises(ValueError, match='复合值'):
            parse_choice_answer(question_num=1, question_type='single', raw_value='其他〖请填写〗', export_format=REVERSE_FILL_FORMAT_WJX_TEXT, option_texts=['选项1', '选项2'])

    def test_parse_multi_text_answer_returns_none_when_all_values_blank(self) -> None:
        answer = parse_multi_text_answer(question_num=3, ordered_columns=[ReverseFillColumn(column_index=2, header='3、字段A', question_num=3, suffix='字段A'), ReverseFillColumn(column_index=3, header='3、字段B', question_num=3, suffix='字段B')], raw_row=ReverseFillRawRow(data_row_number=1, worksheet_row_number=2, values_by_column={2: '', 3: None}))
        assert answer is None

    def test_parse_matrix_answer_rejects_partial_blank_rows(self) -> None:
        with pytest.raises(ValueError, match='部分行为空'):
            parse_matrix_answer(question_num=4, ordered_columns=[ReverseFillColumn(column_index=5, header='4、外观', question_num=4, suffix='外观'), ReverseFillColumn(column_index=6, header='4、功能', question_num=4, suffix='功能')], raw_row=ReverseFillRawRow(data_row_number=1, worksheet_row_number=2, values_by_column={5: 1, 6: ''}), export_format=REVERSE_FILL_FORMAT_WJX_SCORE, option_texts=['差', '中', '好'])
