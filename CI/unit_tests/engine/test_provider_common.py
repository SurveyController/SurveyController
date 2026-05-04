from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import patch
from software.core.engine.provider_common import _build_grouped_runtime_items, build_psychometric_plan_for_run, ensure_joint_psychometric_answer_plan, provider_run_context
from software.core.questions.config import GLOBAL_RELIABILITY_DIMENSION
from software.core.task import ExecutionConfig

class _FakeBlueprintItem:

    def __init__(self, value: object) -> None:
        self.value = value

    def to_runtime_item(self) -> object:
        return self.value

class ProviderCommonTests:

    def test_build_grouped_runtime_items_filters_blank_dimension(self) -> None:
        config = ExecutionConfig()
        with patch('software.core.engine.provider_common.build_psychometric_blueprint', return_value={'A': [_FakeBlueprintItem({'num': 1})], '': [_FakeBlueprintItem({'num': 2})]}):
            grouped = _build_grouped_runtime_items(config)
        assert grouped == {'A': [{'num': 1}]}

    def test_build_psychometric_plan_for_run_returns_none_when_blueprint_is_empty(self) -> None:
        with patch('software.core.engine.provider_common._build_grouped_runtime_items', return_value={}):
            plan = build_psychometric_plan_for_run(ExecutionConfig())
        assert plan is None

    def test_build_psychometric_plan_for_run_falls_back_to_default_target_alpha_when_normalizer_errors(self) -> None:
        config = ExecutionConfig()
        with patch('software.core.engine.provider_common._build_grouped_runtime_items', return_value={'A': [{'num': 1}]}), patch('software.core.engine.provider_common.normalize_target_alpha', side_effect=[RuntimeError('boom'), 0.91]), patch('software.core.engine.provider_common.build_dimension_psychometric_plan', return_value='plan') as build_mock:
            plan = build_psychometric_plan_for_run(config)
        assert plan == 'plan'
        build_mock.assert_called_once_with(grouped_items={'A': [{'num': 1}]}, target_alpha=0.91)

    def test_ensure_joint_psychometric_answer_plan_reuses_cached_value(self) -> None:
        config = ExecutionConfig()
        config.joint_psychometric_answer_plan = 'cached'
        with patch('software.core.engine.provider_common.build_joint_psychometric_answer_plan') as build_mock:
            plan = ensure_joint_psychometric_answer_plan(config)
        assert plan == 'cached'
        build_mock.assert_not_called()

    def test_ensure_joint_psychometric_answer_plan_builds_and_caches_value(self) -> None:
        config = ExecutionConfig()
        with patch('software.core.engine.provider_common.build_joint_psychometric_answer_plan', return_value='joint-plan') as build_mock:
            plan = ensure_joint_psychometric_answer_plan(config)
        assert plan == 'joint-plan'
        assert config.joint_psychometric_answer_plan == 'joint-plan'
        build_mock.assert_called_once_with(config)

    def test_provider_run_context_uses_explicit_plan_and_resets_persona(self) -> None:
        config = ExecutionConfig(answer_rules=[{'num': 1}], questions_metadata={1: {'title': 'Q1'}})
        with patch('software.core.engine.provider_common.generate_persona', return_value={'name': 'p'}), patch('software.core.engine.provider_common.set_current_persona') as set_persona_mock, patch('software.core.engine.provider_common._reset_answer_context') as reset_context_mock, patch('software.core.engine.provider_common.reset_tendency') as reset_tendency_mock, patch('software.core.engine.provider_common.reset_consistency_context') as reset_consistency_mock, patch('software.core.engine.provider_common.reset_persona') as reset_persona_mock:
            with provider_run_context(config, psycho_plan='manual-plan') as resolved:
                assert resolved == 'manual-plan'
        set_persona_mock.assert_called_once_with({'name': 'p'})
        reset_context_mock.assert_called_once()
        reset_tendency_mock.assert_called_once()
        reset_consistency_mock.assert_called_once_with(config.answer_rules, [{'title': 'Q1'}])
        reset_persona_mock.assert_called_once()

    def test_provider_run_context_combines_joint_sample_plan_with_fallback(self) -> None:
        config = ExecutionConfig(psycho_target_alpha=0.93)
        state = SimpleNamespace(peek_reserved_joint_sample=lambda thread_name: 1)
        joint_plan = SimpleNamespace(build_sample_plan=lambda sample_index: SimpleNamespace(diagnostics_by_dimension={}, choices={1: 2}, plans={'A': object()}, items=[1, 2]))
        combined_result = object()
        with patch('software.core.engine.provider_common.generate_persona', return_value={}), patch('software.core.engine.provider_common.set_current_persona'), patch('software.core.engine.provider_common._reset_answer_context'), patch('software.core.engine.provider_common.reset_tendency'), patch('software.core.engine.provider_common.reset_consistency_context'), patch('software.core.engine.provider_common.build_psychometric_plan_for_run', return_value='fallback-plan'), patch('software.core.engine.provider_common.ensure_joint_psychometric_answer_plan', return_value=joint_plan), patch('software.core.engine.provider_common.CombinedPsychometricPlan', return_value=combined_result) as combined_mock, patch('software.core.engine.provider_common.reset_persona'):
            with provider_run_context(config, state=state, thread_name='Worker-2') as resolved:
                assert resolved is combined_result
        combined_mock.assert_called_once()
        assert combined_mock.call_args.kwargs['fallback'] == 'fallback-plan'
        assert combined_mock.call_args.kwargs['primary'].choices == {1: 2}

    def test_provider_run_context_logs_global_dimension_summary_for_fallback_plan(self) -> None:
        config = ExecutionConfig(psycho_target_alpha=0.95)
        fallback_plan = SimpleNamespace(plans={GLOBAL_RELIABILITY_DIMENSION: object()}, items=[1, 2, 3])
        with patch('software.core.engine.provider_common.generate_persona', return_value={}), patch('software.core.engine.provider_common.set_current_persona'), patch('software.core.engine.provider_common._reset_answer_context'), patch('software.core.engine.provider_common.reset_tendency'), patch('software.core.engine.provider_common.reset_consistency_context'), patch('software.core.engine.provider_common.build_psychometric_plan_for_run', return_value=fallback_plan), patch('software.core.engine.provider_common.ensure_joint_psychometric_answer_plan', return_value=None), patch('software.core.engine.provider_common.logging.info') as info_mock, patch('software.core.engine.provider_common.reset_persona'):
            with provider_run_context(config) as resolved:
                assert resolved is fallback_plan
        info_call = info_mock.call_args_list[-1]
        assert '全局未分组问卷' in info_call.args[-1]
