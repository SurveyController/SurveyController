from __future__ import annotations

from software.core.questions.default_builder import build_default_question_entries
from software.core.questions.schema import QuestionEntry, _TEXT_RANDOM_MOBILE, _TEXT_RANDOM_NONE
from software.providers.contracts import SurveyQuestionMeta


class DefaultBuilderRuntimeTests:
    def test_build_default_question_entries_creates_defaults_for_common_types(self) -> None:
        questions = [
            SurveyQuestionMeta(num=1, title="单选", type_code="3", options=4, option_texts=["A", "B"], forced_option_index=2, forced_option_text="C"),
            SurveyQuestionMeta(num=2, title="多选", type_code="4", options=3),
            SurveyQuestionMeta(num=3, title="矩阵", type_code="6", options=5, rows=2),
            SurveyQuestionMeta(num=4, title="评分", type_code="5", is_rating=True, rating_max=7),
            SurveyQuestionMeta(num=5, title="滑块", type_code="5", is_slider_matrix=True, slider_min=10, slider_max=20),
            SurveyQuestionMeta(num=6, title="填空", type_code="1", text_inputs=1, forced_texts=["指定文本"]),
            SurveyQuestionMeta(num=7, title="说明", type_code="0", is_description=True),
            SurveyQuestionMeta(num=8, title="不支持", type_code="99", unsupported=True),
        ]

        entries = build_default_question_entries(questions, survey_url="https://www.wjx.cn/vm/demo.aspx")

        assert [entry.question_num for entry in entries] == [1, 2, 3, 4, 5, 6]
        assert entries[0].question_type == "single"
        assert entries[0].probabilities == [0.0, 0.0, 1.0, 0.0]
        assert entries[0].distribution_mode == "custom"
        assert entries[1].question_type == "multiple"
        assert entries[1].probabilities == [50.0, 50.0, 50.0]
        assert entries[2].question_type == "matrix"
        assert entries[2].rows == 2
        assert entries[3].question_type == "score"
        assert entries[3].option_count == 7
        assert entries[4].question_type == "matrix"
        assert entries[4].probabilities == -1
        assert entries[5].question_type == "text"
        assert entries[5].texts == ["指定文本"]

    def test_build_default_question_entries_infers_multi_text_mobile_blank(self) -> None:
        questions = [
            SurveyQuestionMeta(
                num=11,
                title="多项填空",
                type_code="9",
                text_inputs=3,
                is_text_like=True,
                is_multi_text=True,
                text_input_labels=["项目评价", "请输入手机号", "备注"],
            )
        ]

        entries = build_default_question_entries(questions, survey_url="https://www.wjx.cn/vm/demo.aspx")

        assert entries[0].question_type == "multi_text"
        assert entries[0].multi_text_blank_modes == [_TEXT_RANDOM_NONE, _TEXT_RANDOM_MOBILE, _TEXT_RANDOM_NONE]

    def test_build_default_question_entries_reuses_existing_by_provider_num_and_title(self) -> None:
        existing_by_provider = QuestionEntry(
            "single",
            [0, 1],
            option_count=2,
            question_num=99,
            question_title="旧标题",
            survey_provider="wjx",
            provider_question_id="provider-1",
            distribution_mode="custom",
            custom_weights=[0, 1],
            option_fill_texts=["", "其他"],
            fillable_option_indices=[1],
            attached_option_selects=[{"option_index": 1, "weights": [1, 0]}],
        )
        existing_by_num = QuestionEntry(
            "multiple",
            [10, 90],
            option_count=2,
            question_num=2,
            question_title="多选题",
            distribution_mode="custom",
            custom_weights=[10, 90],
        )
        existing_by_title = QuestionEntry(
            "text",
            [1],
            texts=["旧答案"],
            question_num=88,
            question_title="标题匹配",
            ai_enabled=True,
        )
        questions = [
            SurveyQuestionMeta(
                num=1,
                title="新标题",
                type_code="3",
                options=2,
                provider_question_id="provider-1",
                fillable_options=[1],
                attached_option_selects=[{"option_index": 1, "option_text": "其他", "select_options": ["北京", "上海"]}],
                has_attached_option_select=True,
            ),
            SurveyQuestionMeta(num=2, title="多选题", type_code="4", options=2),
            SurveyQuestionMeta(num=3, title="标题匹配", type_code="1", text_inputs=1),
        ]

        entries = build_default_question_entries(
            questions,
            existing_entries=[existing_by_provider, existing_by_num, existing_by_title],
        )

        assert entries[0].probabilities == [0, 1]
        assert entries[0].custom_weights == [0, 1]
        assert entries[0].option_fill_texts == ["", "其他"]
        assert entries[0].fillable_option_indices == [1]
        assert entries[0].attached_option_selects == [
            {"option_index": 1, "option_text": "其他", "select_options": ["北京", "上海"], "weights": [1.0, 0.0]}
        ]
        assert entries[1].probabilities == [10, 90]
        assert entries[1].distribution_mode == "custom"
        assert entries[2].texts == ["旧答案"]
        assert entries[2].ai_enabled is True

    def test_build_default_question_entries_does_not_reuse_mismatched_title_or_type(self) -> None:
        existing = QuestionEntry(
            "single",
            [0, 1],
            option_count=2,
            question_num=1,
            question_title="旧标题",
            distribution_mode="custom",
            custom_weights=[0, 1],
        )
        questions = [SurveyQuestionMeta(num=1, title="新标题", type_code="3", options=2)]

        entries = build_default_question_entries(questions, existing_entries=[existing])

        assert entries[0].probabilities == -1
        assert entries[0].distribution_mode == "random"
