from __future__ import annotations
import asyncio

from software.integrations.ai.client import AI_MODE_PROVIDER, FREE_QUESTION_TYPE_FILL, save_ai_settings
from software.integrations.ai.protocols import _extract_chat_completion_text, _extract_responses_text, _resolve_custom_endpoint

class AIProtocolTests:

    def setup_method(self, _method) -> None:
        save_ai_settings(ai_mode=AI_MODE_PROVIDER, provider='custom', api_key='test-key', base_url='https://example.com/v1', api_protocol='responses', model='demo-model', system_prompt='测试提示词')

    def test_resolve_custom_endpoint_appends_protocol_suffix(self) -> None:
        protocol, url, explicit = _resolve_custom_endpoint('https://example.com/v1', 'responses')
        assert protocol == 'responses'
        assert url == 'https://example.com/v1/responses'
        assert not explicit

    def test_extract_chat_completion_text_prefers_message_content(self) -> None:
        text = _extract_chat_completion_text({'choices': [{'message': {'content': [{'type': 'text', 'text': '第一句'}, {'type': 'output_text', 'text': '第二句'}]}}]})
        assert text == '第一句\n第二句'

    def test_extract_responses_text_reads_output_content(self) -> None:
        text = _extract_responses_text({'output': [{'content': [{'type': 'output_text', 'text': '连接成功'}]}]})
        assert text == '连接成功'

    def test_generate_answer_tries_chat_then_falls_back_to_responses_in_auto_mode(self) -> None:
        import software.integrations.ai.client as client_module
        original_chat = client_module.acall_chat_completions
        original_responses = client_module.acall_responses_api
        save_ai_settings(api_protocol='auto')
        calls: list[str] = []

        async def _fake_chat(*_args, **_kwargs):
            calls.append('chat')
            raise RuntimeError('404 not found')

        async def _fake_responses(*_args, **_kwargs):
            calls.append('responses')
            return '回退成功'
        client_module.acall_chat_completions = _fake_chat
        client_module.acall_responses_api = _fake_responses
        try:
            answer = asyncio.run(
                client_module.agenerate_answer(
                    '测试问题',
                    question_type=FREE_QUESTION_TYPE_FILL,
                    blank_count=1,
                )
            )
        finally:
            client_module.acall_chat_completions = original_chat
            client_module.acall_responses_api = original_responses
        assert answer == '回退成功'
        assert calls == ['chat', 'responses']
