from __future__ import annotations

import pytest

from surveycore.providers.answering import AnswerAction
from tencent.provider import http_runtime as qq_http


def test_qq_question_answer_builders_cover_choice_text_and_matrix() -> None:
    choice = qq_http._question_answer(
        {
            "id": "q1",
            "type": "radio",
            "options": [{"id": "o1", "text": "A"}, {"id": "o2", "text": "B"}],
        },
        AnswerAction(question_id="q1", kind="choice", selected_indices=(1,)),
    )
    text = qq_http._question_answer(
        {"id": "q2", "type": "text"},
        AnswerAction(question_id="q2", kind="text", text_values=("hello",)),
    )
    matrix = qq_http._question_answer(
        {
            "id": "q-16-6ef8",
            "type": "matrix_radio",
            "options": [{"id": "o-101-1d22", "text": "A"}, {"id": "o-102-98ff", "text": "B"}],
            "sub_titles": [{"id": "g-101-f3a5", "text": "R1"}],
        },
        AnswerAction(question_id="q-16-6ef8", kind="matrix", matrix_indices=(0,)),
    )

    assert choice["options"][1]["checked"] == 1
    assert text["text"] == "hello"
    assert matrix == [
        {"id": "q-16-6ef8_g-101-f3a5_o-101-1d22", "type": "matrix_radio", "answer": "on"}
    ]


def test_qq_score_answer_uses_scalar_answer_field_for_nps() -> None:
    score = qq_http._question_answer(
        {
            "id": "q-15-a899",
            "type": "nps",
            "star_begin_num": 0,
            "star_num": 11,
        },
        AnswerAction(
            question_num=8,
            question_id="q-15-a899",
            kind="choice",
            selected_indices=(3,),
            scalar_value=3,
            record_type="score",
        ),
    )

    assert score == {
        "id": "q-15-a899-3",
        "type": "nps",
        "answer": "3",
    }


def test_qq_score_answer_rejects_missing_score_choice() -> None:
    with pytest.raises(RuntimeError, match="没有生成评分答案"):
        qq_http._question_answer(
            {
                "id": "q8",
                "type": "star",
                "star_begin_num": 1,
                "star_num": 5,
            },
            AnswerAction(
                question_num=8, question_id="q8", kind="choice", scalar_value=9, record_type="score"
            ),
        )


def test_qq_matrix_star_answer_builds_star_options_without_raw_options() -> None:
    matrix = qq_http._question_answer(
        {
            "id": "q-13-7d39",
            "type": "matrix_star",
            "star_begin_num": 1,
            "star_num": 5,
            "sub_titles": [{"id": "g-101-ae7c", "text": "薪资福利"}],
        },
        AnswerAction(
            question_num=4,
            question_id="q-13-7d39",
            kind="matrix",
            matrix_indices=(2,),
            record_type="matrix",
        ),
    )

    assert matrix == [{"id": "q-13-7d39-g-101-ae7c-3", "type": "matrix_star", "answer": "on"}]


def test_qq_matrix_radio_answer_uses_question_row_id_and_option_id() -> None:
    matrix = qq_http._question_answer(
        {
            "id": "q-16-6ef8",
            "type": "matrix_radio",
            "options": [{"id": "o-101-1d22", "text": "较弱"}, {"id": "o-102-98ff", "text": "一般"}],
            "sub_titles": [
                {"id": "g-101-f3a5", "text": "专业实践能力"},
                {"id": "g-102-fefa", "text": "外语能力"},
            ],
        },
        AnswerAction(
            question_num=16,
            question_id="q-16-6ef8",
            kind="matrix",
            matrix_indices=(1, 0),
            record_type="matrix",
        ),
    )

    assert matrix == [
        {"id": "q-16-6ef8_g-101-f3a5_o-102-98ff", "type": "matrix_radio", "answer": "on"},
        {"id": "q-16-6ef8_g-102-fefa_o-101-1d22", "type": "matrix_radio", "answer": "on"},
    ]


def test_qq_matrix_radio_answer_rejects_missing_option_id() -> None:
    with pytest.raises(RuntimeError, match="缺少矩阵列 id"):
        qq_http._question_answer(
            {
                "id": "q16",
                "type": "matrix_radio",
                "options": [{"text": "较弱"}, {"text": "一般"}],
                "sub_titles": [{"id": "g-101-f3a5", "text": "专业实践能力"}],
            },
            AnswerAction(
                question_num=16,
                question_id="q-16-6ef8",
                kind="matrix",
                matrix_indices=(1,),
                record_type="matrix",
            ),
        )


def test_qq_matrix_answer_rejects_empty_business_answer() -> None:
    with pytest.raises(RuntimeError, match="没有可提交的矩阵列"):
        qq_http._question_answer(
            {"id": "q4", "type": "matrix_radio", "sub_titles": [{"id": "g1", "text": "薪资福利"}]},
            AnswerAction(
                question_num=4,
                question_id="q4",
                kind="matrix",
                matrix_indices=(0,),
                record_type="matrix",
            ),
        )


def test_qq_choice_payload_includes_option_fill_blanks() -> None:
    action = AnswerAction(
        question_num=1,
        question_id="q1",
        kind="choice",
        selected_indices=(1,),
        option_fill_texts=((1, "补充信息"),),
    )

    answer = qq_http._question_answer(
        {
            "id": "q1",
            "type": "radio",
            "options": [
                {"id": "o1", "text": "A"},
                {"id": "o2", "text": "其他 {fillblank-1}"},
            ],
        },
        action,
    )

    assert answer["blanks"] == [{"id": "fillblank-1", "text": "补充信息"}]
    assert answer["options"][1]["checked"] == 1
