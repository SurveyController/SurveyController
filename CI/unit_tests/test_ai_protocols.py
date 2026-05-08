from __future__ import annotations
from software.integrations.ai.client import (
    AI_MODE_FREE,
    AI_MODE_PROVIDER,
    AI_PROVIDERS,
    FREE_QUESTION_TYPE_FILL,
    generate_answer,
    get_ai_settings,
    save_ai_settings,
)
from software.integrations.ai.settings import reset_ai_settings
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
        original_chat = client_module.call_chat_completions
        original_responses = client_module.call_responses_api
        save_ai_settings(api_protocol='auto')
        calls: list[str] = []

        def _fake_chat(*_args, **_kwargs):
            calls.append('chat')
            raise RuntimeError('404 not found')

        def _fake_responses(*_args, **_kwargs):
            calls.append('responses')
            return '回退成功'
        client_module.call_chat_completions = _fake_chat
        client_module.call_responses_api = _fake_responses
        try:
            answer = generate_answer('测试问题', question_type=FREE_QUESTION_TYPE_FILL, blank_count=1)
        finally:
            client_module.call_chat_completions = original_chat
            client_module.call_responses_api = original_responses
        assert answer == '回退成功'
        assert calls == ['chat', 'responses']

    def test_generate_answer_uses_mimo_token_plan_openai_endpoint(self) -> None:
        import software.integrations.ai.client as client_module
        original_chat = client_module.call_chat_completions
        save_ai_settings(
            ai_mode=AI_MODE_PROVIDER,
            provider='mimo',
            api_key='test-key',
            model='',
            system_prompt='测试提示词',
        )
        captured: dict[str, str] = {}

        def _fake_chat(url, api_key, model, question, system_prompt, **kwargs):
            captured.update(
                url=url,
                api_key=api_key,
                model=model,
                question=question,
                system_prompt=system_prompt,
                include_sampling_params=kwargs.get('include_sampling_params'),
                provider_key=kwargs.get('provider_key'),
                timeout=kwargs.get('timeout'),
                max_concurrent_requests=kwargs.get('max_concurrent_requests'),
                max_request_attempts=kwargs.get('max_request_attempts'),
            )
            return '连接成功'

        client_module.call_chat_completions = _fake_chat
        try:
            answer = generate_answer('测试问题', question_type=FREE_QUESTION_TYPE_FILL, blank_count=1)
        finally:
            client_module.call_chat_completions = original_chat

        assert answer == '连接成功'
        assert captured['url'] == 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions'
        assert captured['api_key'] == 'test-key'
        assert captured['model'] == AI_PROVIDERS['mimo']['default_model']
        assert captured['question'] == '测试问题'
        assert captured['include_sampling_params'] is False
        assert captured['provider_key'] == 'mimo'
        assert captured['timeout'] == 45
        assert captured['max_concurrent_requests'] == 2
        assert captured['max_request_attempts'] == 1

    def test_reset_ai_settings_keeps_free_ai_as_default(self) -> None:
        save_ai_settings(ai_mode=AI_MODE_PROVIDER, provider='mimo', api_key='test-key')
        reset_ai_settings()

        settings = get_ai_settings()
        assert settings['ai_mode'] == AI_MODE_FREE
        assert settings['provider'] == 'deepseek'
