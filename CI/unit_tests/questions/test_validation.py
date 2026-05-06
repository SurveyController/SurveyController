from __future__ import annotations
from software.core.questions.schema import QuestionEntry
from software.core.questions.validation import validate_question_config

class QuestionValidationTests:

    def test_validate_question_config_rejects_empty_entries(self) -> None:
        assert validate_question_config([]) == '未配置任何题目'

    def test_validate_question_config_blocks_unsupported_questions(self) -> None:
        result = validate_question_config([QuestionEntry(question_type='single', probabilities=[100.0], question_num=1)], [{'num': 9, 'title': '上传文件', 'unsupported': True, 'provider_type': 'upload', 'unsupported_reason': '当前平台还没做'}])
        assert result is not None
        assert result is not None
        assert '暂不支持的题型' in result
        assert '第 9 题' in result
        assert 'upload' in result

    def test_multiple_validation_allows_more_positive_candidates_than_max_limit(self) -> None:
        entry = QuestionEntry(question_type='multiple', probabilities=[50.0, 50.0, 50.0, 50.0], option_count=4, question_num=4)
        result = validate_question_config([entry], [{'num': 4, 'multi_min_limit': None, 'multi_max_limit': 3}])
        assert result is None

    def test_multiple_validation_still_blocks_when_positive_candidates_below_min_limit(self) -> None:
        entry = QuestionEntry(question_type='multiple', probabilities=[100.0, 0.0, 0.0, 0.0], option_count=4, question_num=6)
        result = validate_question_config([entry], [{'num': 6, 'multi_min_limit': 2, 'multi_max_limit': 3}])
        assert result is not None
        assert result is not None
        assert '最少选择 2 项' in result

    def test_single_question_uses_custom_weights_and_rejects_all_zero(self) -> None:
        entry = QuestionEntry(question_type='single', probabilities=[100.0, 0.0], custom_weights=[0.0, 0.0], distribution_mode='custom', option_count=2, question_num=3)
        result = validate_question_config([entry])
        assert result is not None
        assert result is not None
        assert '第 3 题（single）配置无效' in result

    def test_matrix_question_rejects_zero_weight_row(self) -> None:
        entry = QuestionEntry(question_type='matrix', probabilities=[[100.0, 0.0], [0.0, 0.0]], option_count=2, rows=2, question_num=5)
        result = validate_question_config([entry])
        assert result is not None
        assert result is not None
        assert '第 2 行所有选项配比都小于等于 0' in result

    def test_attached_option_select_rejects_zero_weight_group(self) -> None:
        entry = QuestionEntry(question_type='single', probabilities=[100.0, 0.0], option_count=2, question_num=7, attached_option_selects=[{'option_text': '其他', 'weights': [0.0, 0.0, 0.0]}])
        result = validate_question_config([entry])
        assert result is not None
        assert result is not None
        assert '嵌入式下拉' in result
        assert '其他' in result

    def test_text_validation_blocks_answer_shorter_than_min_length_hint(self) -> None:
        entry = QuestionEntry(question_type='text', probabilities=[1.0], texts=['无'], question_num=4)
        result = validate_question_config([entry], [{'num': 4, 'title': '请简述个人发展目标（最少30字）'}])
        assert result is not None
        assert '最少 30 字' in result
        assert '启用 AI 作答' in result

    def test_text_validation_allows_ai_for_min_length_hint(self) -> None:
        entry = QuestionEntry(question_type='text', probabilities=[1.0], texts=['无'], question_num=4, ai_enabled=True)
        result = validate_question_config([entry], [{'num': 4, 'title': '请简述个人发展目标（最少30字）'}])
        assert result is None

    def test_text_validation_blocks_random_mode_for_min_length_hint(self) -> None:
        entry = QuestionEntry(question_type='text', probabilities=[1.0], texts=['无'], question_num=4, text_random_mode='name')
        result = validate_question_config([entry], [{'num': 4, 'title': '请简述个人发展目标（至少30字）'}])
        assert result is not None
        assert '随机姓名' in result

    def test_text_validation_reads_min_length_from_description(self) -> None:
        entry = QuestionEntry(question_type='text', probabilities=[1.0], texts=['短答案'], question_num=8)
        result = validate_question_config([entry], [{'num': 8, 'title': '开放题', 'description': '答案需10字以上'}])
        assert result is not None
        assert '最少 10 字' in result

    def test_validation_uses_display_num_in_error_message(self) -> None:
        entry = QuestionEntry(question_type='text', probabilities=[1.0], texts=['无'], question_num=23)
        result = validate_question_config([entry], [{'num': 23, 'display_num': 22, 'title': '简要评价（最少30字）'}])
        assert result is not None
        assert '第 22 题' in result
        assert '第 23 题' not in result
