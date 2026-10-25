from __future__ import annotations

from software.core.task import ExecutionConfig
from surveycore.providers.answering import AnswerAction
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.credamo.provider import answering_builders as credamo_builders
from credamo.provider import http_runtime as credamo_http


def test_credamo_signature_headers_match_frontend_algorithm() -> None:
    token = "token"
    union_id = "UNION12345"
    nonce = "NONCE1234567890"
    timestamp = "1710000000000"
    headers = credamo_http._build_signature_headers(
        answer_token=token,
        union_id=union_id,
        nonce=nonce,
        timestamp_ms=timestamp,
    )

    inner = credamo_http._sha1_upper(f"{token}{nonce}{timestamp}{union_id}P96D0A7D0M8C3R2D0M1")
    expected = credamo_http._sha1_upper(
        f"{token}{nonce}{timestamp}{inner}{union_id}P96D0A7D0M8C3R2D0M1"
    )

    assert headers["signature"] == expected
    assert headers["unionId"] == "UNION12345"
    assert headers["nonce"] == "NONCE1234567890"


def test_credamo_question_answer_payload_covers_current_types() -> None:
    raw_by_num = {
        1: {
            "qstId": "101",
            "questionType": 2,
            "selector": 1,
            "choices": [{"choiceId": "11"}, {"choiceId": "12"}],
        },
        2: {
            "qstId": "102",
            "questionType": 2,
            "selector": 2,
            "choices": [{"choiceId": "21"}, {"choiceId": "22"}],
        },
        3: {
            "qstId": "103",
            "questionType": 2,
            "selector": 3,
            "choices": [{"choiceId": "31"}, {"choiceId": "32"}],
        },
        4: {
            "qstId": "104",
            "questionType": 11,
            "choices": [{"choiceId": "41"}, {"choiceId": "42"}],
        },
        5: {"qstId": "105", "questionType": 6, "choices": [{"choiceId": "51"}, {"choiceId": "52"}]},
        6: {
            "qstId": "106",
            "questionType": 4,
            "choices": [{"choiceId": "61"}, {"choiceId": "62"}],
            "answers": [{"answerId": "71"}, {"answerId": "72"}],
        },
        7: {"qstId": "107", "questionType": 1},
    }
    actions = [
        AnswerAction(question_num=1, kind="single", selected_indices=(1,)),
        AnswerAction(question_num=2, kind="multiple", selected_indices=(0, 1)),
        AnswerAction(question_num=3, kind="select", selected_indices=(0,)),
        AnswerAction(question_num=4, kind="scale", selected_indices=(1,)),
        AnswerAction(question_num=5, kind="order", selected_indices=(1, 0)),
        AnswerAction(question_num=6, kind="matrix", matrix_indices=(0, 1)),
        AnswerAction(question_num=7, kind="text", text_values=("你好",)),
    ]

    items = credamo_http._answer_payload_items(raw_by_num, actions, answer_duration_seconds=70)

    assert items[0]["answerQstChoice"] == {"choiceId": 12, "choiceContent": ""}
    assert items[1]["answerQstChoiceList"] == [
        {"choiceId": 21, "choiceContent": ""},
        {"choiceId": 22, "choiceContent": ""},
    ]
    assert items[2]["answerQstChoice"] == {"choiceId": 31, "choiceContent": ""}
    assert items[3]["answerQstChoice"] == {"choiceId": 42, "choiceContent": ""}
    assert items[4]["answerChoiceContent"] == [
        {"choiceId": 52, "choiceContent": 1},
        {"choiceId": 51, "choiceContent": 2},
    ]
    assert items[5]["answerQstChoiceList"] == [
        {"choiceId": 61, "choiceAnswerList": [{"answerId": 71}]},
        {"choiceId": 62, "choiceAnswerList": [{"answerId": 72}]},
    ]
    assert items[6]["answerContent"] == "你好"
    assert all(item["answerTime"] == 10000 for item in items)


def test_credamo_choice_payload_includes_option_fill_text() -> None:
    raw_by_num = {
        1: {
            "qstId": "101",
            "questionType": 2,
            "selector": 1,
            "choices": [{"choiceId": "11"}, {"choiceId": "12"}],
        },
        2: {
            "qstId": "102",
            "questionType": 2,
            "selector": 2,
            "choices": [{"choiceId": "21"}, {"choiceId": "22"}],
        },
    }
    actions = [
        AnswerAction(
            question_num=1, kind="single", selected_indices=(1,), option_fill_texts=((1, "补充"),)
        ),
        AnswerAction(
            question_num=2,
            kind="multiple",
            selected_indices=(0, 1),
            option_fill_texts=((1, "其他"),),
        ),
    ]

    items = credamo_http._answer_payload_items(raw_by_num, actions, answer_duration_seconds=20)

    assert items[0]["answerQstChoice"] == {"choiceId": 12, "choiceContent": "补充"}
    assert items[1]["answerQstChoiceList"] == [
        {"choiceId": 21, "choiceContent": ""},
        {"choiceId": 22, "choiceContent": "其他"},
    ]


def test_credamo_builder_includes_static_option_fill_text() -> None:
    config = ExecutionConfig(survey_provider="credamo")
    config.single_prob = [[0.0, 1.0]]
    config.single_option_fill_texts = [[None, "__RANDOM_NAME__"]]
    question = SurveyQuestionMeta(
        num=1,
        title="请选择",
        provider="credamo",
        options=2,
        fillable_options=[1],
    )

    action = credamo_builders.build_answer_action(
        root_index=0,
        question_num=1,
        entry_type="single",
        config_index=0,
        config=config,
        question_meta=question,
    )

    assert action is not None
    assert action.selected_indices == (1,)
    assert action.option_fill_texts
    assert action.option_fill_texts[0][0] == 1


def test_credamo_builder_does_not_randomize_empty_multiple_probabilities() -> None:
    config = ExecutionConfig(survey_provider="credamo")
    config.multiple_prob = [[]]
    question = SurveyQuestionMeta(num=1, title="多选题", provider="credamo", options=3)

    action = credamo_builders.build_answer_action(
        root_index=0,
        question_num=1,
        entry_type="multiple",
        config_index=0,
        config=config,
        question_meta=question,
    )

    assert action is None


def test_credamo_builder_does_not_randomize_all_zero_multiple_probabilities() -> None:
    config = ExecutionConfig(survey_provider="credamo")
    config.multiple_prob = [[0.0, 0.0, 0.0]]
    question = SurveyQuestionMeta(num=1, title="多选题", provider="credamo", options=3)

    action = credamo_builders.build_answer_action(
        root_index=0,
        question_num=1,
        entry_type="multiple",
        config_index=0,
        config=config,
        question_meta=question,
    )

    assert action is None


def test_credamo_forced_choice_prefers_text_when_api_choice_order_changes() -> None:
    config = ExecutionConfig(survey_provider="credamo")
    config.questions_metadata = {
        8: SurveyQuestionMeta(
            num=8,
            title="请选择 200",
            provider="credamo",
            options=4,
            forced_option_index=1,
            forced_option_text="200",
        ),
    }
    raw_by_num = {
        8: {
            "qstId": "108",
            "questionType": 2,
            "selector": 1,
            "choices": [
                {"choiceId": "6787", "display": "300"},
                {"choiceId": "6788", "display": "500"},
                {"choiceId": "6789", "display": "200"},
                {"choiceId": "6790", "display": "600"},
            ],
        },
    }
    actions = [AnswerAction(question_num=8, kind="single", selected_indices=(1,))]

    items = credamo_http._answer_payload_items(
        raw_by_num, actions, config=config, answer_duration_seconds=9
    )

    assert items[0]["answerQstChoice"] == {"choiceId": 6789, "choiceContent": ""}


def test_credamo_builder_supports_dropdown_and_order_for_http(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="credamo")
    config.droplist_prob = [[0.0, 1.0, 0.0]]
    dropdown_question = SurveyQuestionMeta(num=1, title="Q1", provider="credamo", options=3)
    order_question = SurveyQuestionMeta(num=2, title="Q2", provider="credamo", options=3)

    monkeypatch.setattr(credamo_builders, "weighted_index", lambda _probs: 1)
    monkeypatch.setattr(credamo_builders.random, "shuffle", lambda items: items.reverse())

    dropdown_action = credamo_builders.build_answer_action(
        root_index=0,
        question_num=1,
        entry_type="dropdown",
        config_index=0,
        config=config,
        question_meta=dropdown_question,
    )
    order_action = credamo_builders.build_answer_action(
        root_index=1,
        question_num=2,
        entry_type="order",
        config_index=0,
        config=config,
        question_meta=order_question,
    )

    assert dropdown_action is not None
    assert dropdown_action.kind == "select"
    assert dropdown_action.record_type == "dropdown"
    assert dropdown_action.selected_indices == (1,)
    assert order_action is not None
    assert order_action.kind == "order"
    assert order_action.selected_indices == (2, 1, 0)
