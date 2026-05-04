"""真实问卷链接解析回归测试。"""
from __future__ import annotations
import pytest
import json
from pathlib import Path
from typing import Any, Dict, Tuple
from credamo.provider.parser import parse_credamo_survey
from tencent.provider.parser import parse_qq_survey
from wjx.provider.parser import parse_wjx_survey
WJX_SURVEY_URL = 'https://v.wjx.cn/vm/tgRSrWd.aspx'
QQ_SURVEY_URL = 'https://wj.qq.com/s2/26070328/fa89/'
_ROOT_DIR = Path(__file__).resolve().parents[2]
_CREDAMO_CONFIG_PATH = _ROOT_DIR / 'configs' / 'credamo.json'

def _question_by_num(questions: list[dict], question_num: int) -> dict:
    for item in questions:
        if int(item.get('num') or 0) == int(question_num):
            return item
    raise AssertionError(f'未找到第 {question_num} 题')

def _load_credamo_live_config() -> Dict[str, Any]:
    if not _CREDAMO_CONFIG_PATH.is_file():
        pytest.skip(f'未找到见数真实配置：{_CREDAMO_CONFIG_PATH}')
    data = json.loads(_CREDAMO_CONFIG_PATH.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        pytest.skip(f'见数真实配置格式不对：{_CREDAMO_CONFIG_PATH}')
    url = str(data.get('url') or '').strip()
    if not url:
        pytest.skip(f'见数真实配置缺少 url：{_CREDAMO_CONFIG_PATH}')
    return data

class LiveSurveyParserRegressionTests:
    maxDiff = None

    def _run_with_retry(self, parser, url: str, attempts: int=2) -> Tuple[list[dict], str]:
        last_error: Exception | None = None
        for _ in range(max(1, attempts)):
            try:
                return parser(url)
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise AssertionError('解析器未返回结果')

    def test_wjx_live_parser_regression(self) -> None:
        questions, title = self._run_with_retry(parse_wjx_survey, WJX_SURVEY_URL)
        assert title == 'example'
        assert len(questions) == 11
        q1 = _question_by_num(questions, 1)
        assert q1['type_code'] == '3'
        assert q1['options'] == 2
        assert q1['has_jump']
        assert q1['jump_rules'][0]['jumpto'] == 5
        assert len(q1['option_texts']) == 2
        assert str(q1['option_texts'][0] or '').strip()
        assert q1['option_texts'][1] == '我才是B'
        q2 = _question_by_num(questions, 2)
        assert q2['type_code'] == '11'
        assert q2['options'] == 5
        q3 = _question_by_num(questions, 3)
        assert q3['type_code'] == '5'
        assert q3['options'] == 11
        assert q3['option_texts'][0] == '不可能'
        assert q3['option_texts'][-1] == '极有可能'
        q4 = _question_by_num(questions, 4)
        assert q4['type_code'] == '1'
        assert q4['is_text_like']
        assert q4['text_inputs'] == 1
        q6 = _question_by_num(questions, 6)
        assert q6['type_code'] == '6'
        assert q6['rows'] == 2
        assert q6['row_texts'] == ['外观', '功能']
        q8 = _question_by_num(questions, 8)
        assert q8['type_code'] == '5'
        assert q8['is_rating']
        assert q8['rating_max'] == 5
        assert q8['text_inputs'] == 5
        q9 = _question_by_num(questions, 9)
        assert q9['forced_option_index'] == 0
        assert q9['forced_option_text'] == 'A'
        q11 = _question_by_num(questions, 11)
        assert q11['type_code'] == '9'
        assert q11['is_multi_text']
        assert q11['is_text_like']
        assert q11['text_input_labels'] == ['填空1', '填空2', '填空3']

    def test_qq_live_parser_regression(self) -> None:
        questions, title = self._run_with_retry(parse_qq_survey, QQ_SURVEY_URL)
        assert title == '大学生就业意向调研问卷'
        assert len(questions) == 17
        q1 = _question_by_num(questions, 1)
        assert q1['type_code'] == '3'
        assert q1['provider_type'] == 'radio'
        assert q1['options'] == 3
        assert q1['page'] == 1
        q2 = _question_by_num(questions, 2)
        assert q2['type_code'] == '7'
        assert q2['provider_type'] == 'select'
        assert q2['options'] == 10
        q4 = _question_by_num(questions, 4)
        assert q4['type_code'] == '6'
        assert q4['provider_type'] == 'matrix_star'
        assert q4['options'] == 5
        assert q4['rows'] == 5
        assert q4['row_texts'][0] == '薪资福利'
        q5 = _question_by_num(questions, 5)
        assert q5['type_code'] == '4'
        assert q5['provider_type'] == 'checkbox'
        assert q5['multi_min_limit'] == 1
        assert q5['options'] == 7
        q7 = _question_by_num(questions, 7)
        assert q7['type_code'] == '1'
        assert q7['is_text_like']
        assert q7['provider_type'] == 'text'
        q8 = _question_by_num(questions, 8)
        assert q8['type_code'] == '5'
        assert q8['is_rating']
        assert q8['provider_type'] == 'nps'
        assert q8['options'] == 11
        q9 = _question_by_num(questions, 9)
        assert q9['type_code'] == '6'
        assert q9['provider_type'] == 'matrix_radio'
        assert q9['rows'] == 5
        assert q9['options'] == 4
        q12 = _question_by_num(questions, 12)
        assert q12['page'] == 2
        assert q12['provider_page_id'] == 'p-2-xIOc'
        assert q12['multi_min_limit'] == 1
        q13 = _question_by_num(questions, 13)
        assert q13['provider_type'] == 'textarea'
        assert q13['type_code'] == '1'
        assert q13['is_text_like']
        q16 = _question_by_num(questions, 16)
        assert q16['provider_type'] == 'nps'
        assert q16['options'] == 11
        assert q16['page'] == 2

    def test_credamo_live_parser_regression(self) -> None:
        config = _load_credamo_live_config()
        questions, title = self._run_with_retry(parse_credamo_survey, str(config['url']), attempts=2)
        expected_title = str(config.get('survey_title') or '').strip()
        if expected_title:
            assert title == expected_title
        assert len(questions) >= 4
        expected_questions = config.get('questions_info') or []
        if not isinstance(expected_questions, list) or len(expected_questions) < 4:
            pytest.skip('见数真实配置缺少足够的 questions_info，无法做回归比对')
        stable_fields = ('num', 'type_code', 'provider_type', 'options', 'text_inputs', 'is_text_like', 'is_multi_text', 'required', 'provider_page_id')
        for index, expected in enumerate(expected_questions[:4]):
            actual = questions[index]
            for field_name in stable_fields:
                assert actual.get(field_name) == expected.get(field_name), f'见数第 {index + 1} 个题块字段 {field_name} 不一致'
            assert (actual.get('option_texts') or []) == (expected.get('option_texts') or []), f'见数第 {index + 1} 个题块选项文本不一致'
