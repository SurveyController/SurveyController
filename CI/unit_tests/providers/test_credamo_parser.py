from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import patch
from credamo.provider import parser
from software.core.questions.default_builder import build_default_question_entries
from software.core.questions.normalization import configure_probabilities
from software.core.questions.schema import QuestionEntry

class CredamoParserTests:

    class _FakeButton:

        def __init__(self, text: str, visible: bool) -> None:
            self.text = text
            self.visible = visible

        def is_visible(self, timeout: int=0) -> bool:
            return self.visible

        def text_content(self, timeout: int=0) -> str:
            return self.text

        def get_attribute(self, _name: str) -> str:
            return ''

    class _FakeLocator:

        def __init__(self, items: list['CredamoParserTests._FakeButton']) -> None:
            self.items = items

        def count(self) -> int:
            return len(self.items)

        def nth(self, index: int) -> 'CredamoParserTests._FakeButton':
            return self.items[index]

    class _FakePage:

        def __init__(self, buttons: list['CredamoParserTests._FakeButton']) -> None:
            self.buttons = buttons

        def locator(self, _selector: str) -> 'CredamoParserTests._FakeLocator':
            return CredamoParserTests._FakeLocator(self.buttons)

    class _RetryPage:

        def __init__(self, url: str='https://www.credamo.com/answer.html#/s/demo/') -> None:
            self.url = url
            self.goto_calls: list[tuple[str, str, int]] = []
            self.reload_calls = 0
            self.wait_calls = 0

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            self.goto_calls.append((url, wait_until, timeout))

        def reload(self, wait_until: str, timeout: int) -> None:
            self.reload_calls += 1

        def wait_for_load_state(self, _state: str, timeout: int) -> None:
            self.wait_calls += 1

    def test_infer_type_code_uses_page_block_kind(self) -> None:
        assert parser._infer_type_code({'question_kind': 'dropdown'}) == '7'
        assert parser._infer_type_code({'question_kind': 'scale'}) == '5'
        assert parser._infer_type_code({'question_kind': 'order'}) == '11'
        assert parser._infer_type_code({'question_kind': 'multiple'}) == '4'

    def test_detect_navigation_action_ignores_hidden_submit_button(self) -> None:
        page = self._FakePage([self._FakeButton('提交', False), self._FakeButton('下一页', True)])
        assert parser._detect_navigation_action(page) == 'next'

    def test_retry_initial_question_load_refreshes_when_stuck_on_loading_shell(self) -> None:
        page = self._RetryPage()
        expected_roots = [object()]
        with patch('credamo.provider.parser._wait_for_question_roots', side_effect=[[], expected_roots]), patch('credamo.provider.parser._page_loading_snapshot', return_value=('答卷', '载入中...')):
            roots = parser._retry_initial_question_load_if_needed(page)
        assert roots == expected_roots
        assert page.goto_calls == [(page.url, 'domcontentloaded', 45000)]
        assert page.wait_calls == 1
        assert page.reload_calls == 0

    def test_retry_initial_question_load_skips_refresh_when_not_loading_shell(self) -> None:
        page = self._RetryPage()
        with patch('credamo.provider.parser._wait_for_question_roots', return_value=[]), patch('credamo.provider.parser._page_loading_snapshot', return_value=('AI 技能成长平台功能需求调研问卷', '页面正文')):
            roots = parser._retry_initial_question_load_if_needed(page)
        assert roots == []
        assert page.goto_calls == []
        assert page.wait_calls == 0

    def test_normalize_question_keeps_credamo_specific_type(self) -> None:
        question = parser._normalize_question({'question_num': 'Q3', 'title': 'Q3', 'question_kind': 'dropdown', 'provider_type': 'dropdown', 'option_texts': ['选项 1', '选项 2', '选项 3'], 'text_inputs': 0, 'page': 2, 'question_id': 'question-2'}, fallback_num=3)
        assert question['num'] == 3
        assert question['type_code'] == '7'
        assert question['provider_type'] == 'dropdown'
        assert question['provider_page_id'] == '2'
        assert question['options'] == 3

    def test_normalize_question_detects_matrix_scale(self) -> None:
        question = parser._normalize_question({'question_num': 'Q11', 'title': 'Q11', 'question_kind': 'matrix', 'provider_type': 'matrix', 'option_texts': ['选项 1', '选项 2', '选项 3', '选项 4', '选项 5'], 'row_texts': ['陈述 1', '陈述 2', '陈述 3', '陈述 4', '陈述 5', '陈述 6', '陈述 7'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-5'}, fallback_num=11)
        assert question['num'] == 11
        assert question['type_code'] == '6'
        assert question['provider_type'] == 'matrix'
        assert question['options'] == 5
        assert question['rows'] == 7
        assert question['row_texts'][0] == '陈述 1'

    def test_normalize_question_prefers_matrix_column_texts_over_placeholder_options(self) -> None:
        question = parser._normalize_question({'question_num': 'Q8', 'title': 'Q8 生成基于专业与目标的大学四年成长路径', 'question_kind': 'matrix', 'provider_type': 'matrix', 'option_texts': ['选项 1', '选项 2', '选项 3', '选项 4', '选项 5'], 'matrix_column_texts': ['非常满意', '比较满意', '满意', '比较不满意', '非常不满意'], 'row_texts': ['如果提供此服务，您觉得', '如果不提供此服务，您觉得'], 'text_inputs': 0, 'page': 2, 'question_id': 'question-3'}, fallback_num=8)
        assert question['option_texts'] == ['非常满意', '比较满意', '满意', '比较不满意', '非常不满意']
        assert question['options'] == 5
        assert question['rows'] == 2

    def test_extract_questions_from_current_page_reads_matrix_header_container_texts(self) -> None:

        class _EvalPage:

            def evaluate(self, script: str):
                self.script = script
                return [{'question_id': 'question-3', 'question_num': 'Q8', 'title': 'Q8 生成基于专业与目标的大学四年成长路径', 'title_full_text': 'Q8 生成基于专业与目标的大学四年成长路径', 'title_text': '生成基于专业与目标的大学四年成长路径', 'tip_text': '', 'body_text': 'Q8 生成基于专业与目标的大学四年成长路径 非常满意 比较满意 满意 比较不满意 非常不满意 如果提供此服务，您觉得 如果不提供此服务，您觉得', 'option_texts': ['选项 1', '选项 2', '选项 3', '选项 4', '选项 5'], 'matrix_column_texts': ['非常满意', '比较满意', '满意', '比较不满意', '非常不满意'], 'row_texts': ['如果提供此服务，您觉得', '如果不提供此服务，您觉得'], 'input_types': ['radio'], 'text_inputs': 0, 'required': True, 'provider_type': 'matrix', 'question_kind': 'matrix'}]
        questions = parser._extract_questions_from_current_page(_EvalPage(), page_number=1)
        assert len(questions) == 1
        assert questions[0]['option_texts'] == ['非常满意', '比较满意', '满意', '比较不满意', '非常不满意']

    def test_normalize_question_detects_force_select_instruction(self) -> None:
        question = parser._normalize_question({'question_num': 'Q7', 'title': 'Q7 本题检测是否认真作答，请选 非常不满意', 'title_text': '本题检测是否认真作答，请选 非常不满意', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['非常不满意', '不满意', '满意', '非常满意'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-7'}, fallback_num=7)
        assert question['num'] == 7
        assert question['forced_option_index'] == 0
        assert question['forced_option_text'] == '非常不满意'

    def test_normalize_question_detects_arithmetic_trap_answer(self) -> None:
        question = parser._normalize_question({'question_num': 'Q8', 'title': 'Q8 请问100+100等于多少', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['300', '200', '500', '600'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-8'}, fallback_num=8)
        assert question['forced_option_index'] == 1
        assert question['forced_option_text'] == '200'

    def test_normalize_question_detects_forced_text_answer(self) -> None:
        question = parser._normalize_question({'question_num': 'Q10', 'title': 'Q10 本题检测是否认真作答，请输入：“你好”（仅输入引号内文字）', 'question_kind': 'text', 'provider_type': 'text', 'option_texts': [], 'text_inputs': 1, 'page': 1, 'question_id': 'question-10'}, fallback_num=10)
        assert question['forced_texts'] == ['你好']

    def test_normalize_question_detects_title_max_multi_select_limit(self) -> None:
        question = parser._normalize_question({'question_num': 'Q17', 'title': 'Q17 正餐替代时，你最看重的3个属性？ [至多选3项]', 'title_text': '正餐替代时，你最看重的3个属性？', 'tip_text': '[至多选3项]', 'question_kind': 'multiple', 'provider_type': 'multiple', 'option_texts': ['分量足', '方便', '便宜', '口味好', '可宿舍煮'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-17'}, fallback_num=17)
        assert question['multi_min_limit'] is None
        assert question['multi_max_limit'] == 3

    def test_normalize_question_detects_title_min_multi_select_limit(self) -> None:
        question = parser._normalize_question({'question_num': 'Q30', 'title': 'Q30 哪种周边会让你更想集体购买？ [至少选2项]', 'title_text': '哪种周边会让你更想集体购买？', 'tip_text': '[至少选2项]', 'question_kind': 'multiple', 'provider_type': 'multiple', 'option_texts': ['宿舍小煮锅', '超大分享碗', '非遗文创', '趣味贴纸'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-30'}, fallback_num=30)
        assert question['multi_min_limit'] == 2
        assert question['multi_max_limit'] is None

    def test_normalize_question_detects_range_multi_select_limit(self) -> None:
        question = parser._normalize_question({'question_num': 'Q32', 'title': 'Q32 请选择2-4项你最常用的功能', 'question_kind': 'multiple', 'provider_type': 'multiple', 'option_texts': ['功能A', '功能B', '功能C', '功能D', '功能E'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-32'}, fallback_num=32)
        assert question['multi_min_limit'] == 2
        assert question['multi_max_limit'] == 4

    def test_normalize_question_detects_chinese_multi_select_limit(self) -> None:
        question = parser._normalize_question({'question_num': 'Q33', 'title': 'Q33 以下渠道最少选两项', 'question_kind': 'multiple', 'provider_type': 'multiple', 'option_texts': ['渠道A', '渠道B', '渠道C', '渠道D'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-33'}, fallback_num=33)
        assert question['multi_min_limit'] == 2

    def test_normalize_question_ignores_multi_select_limit_for_single_choice(self) -> None:
        question = parser._normalize_question({'question_num': 'Q31', 'title': 'Q31 单选题示例 [至多选2项]', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['愿意', '不愿意', '无所谓'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-31'}, fallback_num=31)
        assert question['multi_min_limit'] is None
        assert question['multi_max_limit'] is None

    def test_normalize_question_does_not_treat_plain_select_prompt_as_forced_choice(self) -> None:
        question = parser._normalize_question({'question_num': 'Q2', 'title': 'Q2 请选择你的年龄段', 'title_text': '请选择你的年龄段', 'body_text': '请选择你的年龄段 1. 15-25岁 2. 26-35岁 3. 36-45岁 4. 46-55岁 5. 56-65岁 6. 65岁以上', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['15-25岁', '26-35岁', '36-45岁', '46-55岁', '56-65岁', '65岁以上'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-2'}, fallback_num=2)
        assert question['forced_option_index'] is None
        assert question['forced_option_text'] is None

    def test_normalize_question_does_not_match_option_from_body_text_only(self) -> None:
        question = parser._normalize_question({'question_num': 'Q5', 'title': 'Q5 请选择你的职业类型', 'title_text': '请选择你的职业类型', 'body_text': '请选择你的职业类型 1. 学生 2. 国有企业 3. 事业单位 4. 公务员 5. 民营企业/个体工商户 6. 外资企业 7. 退休人员', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['学生', '国有企业', '事业单位', '公务员', '民营企业/个体工商户', '外资企业', '退休人员'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-5'}, fallback_num=5)
        assert question['forced_option_index'] is None
        assert question['forced_option_text'] is None

    def test_normalize_question_prefers_full_title_text_and_strips_type_tag(self) -> None:
        question = parser._normalize_question({'question_num': 'Q7', 'title': '本题检测是否认真作答', 'title_full_text': 'Q7 [单选题] 本题检测是否认真作答，请选 非常不满意', 'title_text': '本题检测是否认真作答', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['非常不满意', '不满意', '满意', '非常满意'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-7'}, fallback_num=7)
        assert question['num'] == 7
        assert question['title'] == '本题检测是否认真作答，请选 非常不满意'
        assert question['forced_option_index'] == 0
        assert question['forced_option_text'] == '非常不满意'

    def test_default_builder_locks_credamo_force_select_question(self) -> None:
        entries = build_default_question_entries([{'num': 7, 'title': '本题检测是否认真作答，请选 非常不满意', 'type_code': '3', 'options': 4, 'option_texts': ['非常不满意', '不满意', '满意', '非常满意'], 'provider': 'credamo', 'provider_question_id': 'question-7', 'provider_page_id': '1', 'forced_option_index': 0, 'forced_option_text': '非常不满意'}], survey_url='https://www.credamo.com/answer.html#/s/demo')
        assert len(entries) == 1
        assert entries[0].question_num == 7
        assert entries[0].question_type == 'single'
        assert entries[0].distribution_mode == 'custom'
        assert entries[0].probabilities == [1.0, 0.0, 0.0, 0.0]
        assert entries[0].custom_weights == [1.0, 0.0, 0.0, 0.0]

    def test_default_builder_locks_credamo_forced_text_question(self) -> None:
        entries = build_default_question_entries([{'num': 10, 'title': '本题检测是否认真作答，请输入：你好', 'type_code': '1', 'options': 1, 'provider': 'credamo', 'provider_question_id': 'question-10', 'provider_page_id': '1', 'forced_texts': ['你好'], 'is_text_like': True, 'text_inputs': 1}], survey_url='https://www.credamo.com/answer.html#/s/demo')
        assert len(entries) == 1
        assert entries[0].question_num == 10
        assert entries[0].question_type == 'text'
        assert entries[0].texts == ['你好']

    def test_collect_current_page_until_stable_keeps_revealed_questions(self) -> None:
        q8 = {'provider_question_id': 'question-8', 'num': 8, 'title': 'Q8'}
        q9 = {'provider_question_id': 'question-9', 'num': 9, 'title': 'Q9'}
        page = object()

        def fake_prime(_page, questions, primed_keys=None):
            primed = primed_keys if primed_keys is not None else set()
            count = 0
            for question in questions:
                key = parser._question_dedupe_key(question)
                if key in primed:
                    continue
                primed.add(key)
                count += 1
            return count
        with patch('credamo.provider.parser._extract_questions_from_current_page', side_effect=[[q8], [q8, q9]]), patch('credamo.provider.parser._prime_page_for_next', side_effect=fake_prime), patch('credamo.provider.parser._wait_for_dynamic_questions', side_effect=[[q8, q9], [q8, q9]]):
            current, discovered = parser._collect_current_page_until_stable(page, page_number=1)
        assert [question['num'] for question in current] == [8, 9]
        assert [question['num'] for question in discovered] == [8, 9]

    def test_question_dedupe_key_does_not_trust_reused_credamo_dom_id(self) -> None:
        q8 = {'provider_page_id': '2', 'provider_question_id': 'question-0', 'num': 8, 'title': '请问100+100等于多少'}
        q10 = {'provider_page_id': '4', 'provider_question_id': 'question-0', 'num': 10, 'title': '本题检测是否认真作答，请输入：你好'}
        assert parser._question_dedupe_key(q8) != parser._question_dedupe_key(q10)

    def test_prime_question_uses_forced_scale_answer(self) -> None:
        page = object()
        root = object()
        question = {'provider_type': 'scale', 'options': 7, 'forced_option_index': 0}
        with patch('credamo.provider.runtime._answer_scale', return_value=True) as scale_mock:
            parser._prime_question_for_next(page, root, question)
        scale_mock.assert_called_once_with(page, root, [100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_prime_question_answers_matrix_for_dynamic_reveal(self) -> None:
        page = object()
        root = object()
        question = {'provider_type': 'matrix', 'options': 5}
        with patch('credamo.provider.runtime._answer_matrix', return_value=True) as matrix_mock:
            parser._prime_question_for_next(page, root, question)
        matrix_mock.assert_called_once_with(page, root, [100.0, 0.0, 0.0, 0.0, 0.0])

    def test_order_entry_is_exposed_to_runtime_mapping(self) -> None:
        entry = QuestionEntry(question_type='order', probabilities=-1, option_count=4, question_num=6, question_title='排序题', survey_provider='credamo')
        ctx = SimpleNamespace()
        configure_probabilities([entry], ctx)
        assert ctx.question_config_index_map[6] == ('order', -1)
