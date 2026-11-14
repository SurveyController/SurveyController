from __future__ import annotations

from surveycore.core.questions.config import QuestionEntry
from surveycore.providers.contracts import SurveyQuestionMeta

from software.application.run_plan import compile_run_plan, question_id
from software.core.config.schema import RuntimeConfig


def test_question_id_prefers_provider_identity_and_has_local_identity() -> None:
    provider_question = SurveyQuestionMeta(
        num=3,
        title="联系方式",
        provider="qq",
        provider_question_id="question-3",
        provider_page_id="page-2",
    )
    local_question = SurveyQuestionMeta(num=4, title="满意度", provider="wjx")

    assert question_id(provider_question) == "qq:page-2:question-3"
    assert question_id(local_question) == question_id(
        SurveyQuestionMeta(num=4, title="满意度", provider="wjx")
    )


def test_run_plan_compiles_detached_config_and_question_ids() -> None:
    config = RuntimeConfig(
        question_entries=[
            QuestionEntry(question_type="single", probabilities=[1], question_num=1)
        ],
        questions_info=[SurveyQuestionMeta(num=1, title="满意度", provider_question_id="q1")],
    )

    plan = compile_run_plan(config)
    first_copy = plan.config
    first_copy.question_entries[0].probabilities[0] = 0

    assert config.question_entries[0].probabilities == [1]
    assert plan.question_ids[0].endswith(":q1")
    assert plan.config.question_entries[0].probabilities == [1]


def test_run_plan_keeps_metadata_identity_when_entries_are_a_subset() -> None:
    config = RuntimeConfig(
        question_entries=[
            QuestionEntry(question_type="single", probabilities=[1], question_num=8)
        ],
        questions_info=[SurveyQuestionMeta(num=2, title="前置题"), SurveyQuestionMeta(num=8, title="目标题")],
    )
    config.questions_info[0].question_id = "question-2"
    config.questions_info[1].question_id = "question-8"

    plan = compile_run_plan(config)

    assert plan.question_ids == ("question-8",)
    assert [question.question_id for question in plan.config.questions_info] == [
        "question-2",
        "question-8",
    ]
