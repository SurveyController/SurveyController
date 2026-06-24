import { describe, expect, it } from 'vitest'
import { emptyShellState } from './shellFixture'
import {
  applyConfigToShell,
  normalizeRuntimeConfig,
  questionTypeLabel,
  updateAppSettingsField,
  updateRuntimeConfigField,
} from './stateMapper'
import type { AppSettings, RuntimeConfig } from '../types'

const settings: AppSettings = {
  configDirectory: 'D:/configs',
  themeMode: 'system',
  showNavigationText: true,
  micaEnabled: true,
  topmost: false,
  notifications: true,
  autosaveLogCount: 5,
}

describe('stateMapper', () => {
  it('maps runtime config into dashboard and runtime groups', () => {
    const config: RuntimeConfig = {
      url: 'https://wj.qq.com/s2/123/hash/',
      survey_title: '腾讯测试',
      survey_provider: 'qq',
      target: 8,
      threads: 3,
      random_ip_enabled: true,
      proxy_source: 'custom',
      custom_proxy_api: 'https://proxy.example/api',
      reverse_fill_enabled: true,
      questions_info: [
        {
          num: 1,
          title: '单选',
          description: '',
          type_code: '3',
          options: 2,
          rows: 0,
          row_texts: [],
          option_texts: ['A', 'B'],
          provider: 'qq',
          provider_type: 'single',
          is_description: false,
          is_text_like: false,
          text_inputs: 0,
        },
      ],
      question_entries: [{ question_type: 'single', probabilities: [1, 1], question_num: 1, distribution_mode: 'random', dimension: '服务' }],
      answer_rules: [{
        condition_question_num: 1,
        condition_mode: 'selected',
        condition_option_indices: [0],
        target_question_num: 1,
        action_mode: 'must_select',
        target_option_indices: [1],
      }],
    }

    const shell = applyConfigToShell(emptyShellState, settings, config, null)

    expect(shell.dashboard.surveyTitle).toBe('腾讯测试')
    expect(shell.dashboard.platformLabel).toBe('腾讯问卷')
    expect(shell.dashboard.targetCount).toBe(8)
    expect(shell.dashboard.questionRows).toEqual([{ index: 1, type: '单选题', dimension: '服务', strategy: 'random' }])
    expect(shell.dimensionGroups).toEqual(['服务'])
    expect(shell.strategyRules[0]).toEqual({
      condition: '第 1 题 选中 1',
      action: '必须选择',
      target: '第 1 题 2',
    })
    expect(shell.runtimeGroups.some((group) => group.fields.some((field) => field.id === 'custom-proxy-api'))).toBe(true)
    expect(shell.runtimeGroups.some((group) => group.fields.some((field) => field.id === 'reverse-fill-enabled'))).toBe(true)
    expect(shell.runtimeGroups.some((group) => group.fields.some((field) => field.id === 'ai-api-key'))).toBe(true)
    expect(shell.runtimeGroups.some((group) => group.fields.some((field) => field.id === 'ai-api-protocol'))).toBe(true)
  })

  it('normalizes missing runtime values', () => {
    const config = normalizeRuntimeConfig({ url: 'https://www.wjx.cn/vm/demo.aspx', target: -1, threads: 0 })

    expect(config.survey_provider).toBe('wjx')
    expect(config.target).toBe(1)
    expect(config.threads).toBe(1)
    expect(config.reverse_fill_threads).toBe(1)
  })

  it('updates runtime fields from editable controls', () => {
    let config = normalizeRuntimeConfig({ url: '', target: 1, threads: 1 })

    config = updateRuntimeConfigField(config, 'target', '12')
    config = updateRuntimeConfigField(config, 'threads', '4')
    config = updateRuntimeConfigField(config, 'random-ip', true)
    config = updateRuntimeConfigField(config, 'proxy-source', '自定义')
    config = updateRuntimeConfigField(config, 'custom-proxy-api', 'https://proxy.example/api')
    config = updateRuntimeConfigField(config, 'interval', '2-5')
    config = updateRuntimeConfigField(config, 'answer-duration', '45-90')
    config = updateRuntimeConfigField(config, 'ai-api-key', 'sk-test')
    config = updateRuntimeConfigField(config, 'ai-api-protocol', 'responses')
    config = updateRuntimeConfigField(config, 'reliability-mode', false)
    config = updateRuntimeConfigField(config, 'psycho-target-alpha', '0.9')

    expect(config.target).toBe(12)
    expect(config.threads).toBe(4)
    expect(config.random_ip_enabled).toBe(true)
    expect(config.proxy_source).toBe('custom')
    expect(config.custom_proxy_api).toBe('https://proxy.example/api')
    expect(config.submit_interval).toEqual([2, 5])
    expect(config.answer_duration).toEqual([45, 90])
    expect(config.ai_api_key).toBe('sk-test')
    expect(config.ai_api_protocol).toBe('responses')
    expect(config.reliability_mode_enabled).toBe(false)
    expect(config.psycho_target_alpha).toBe(0.9)
  })

  it('updates persisted app settings fields', () => {
    const next = updateAppSettingsField(settings, 'autosave', '10')

    expect(next.autosaveLogCount).toBe(10)
    expect(updateAppSettingsField(next, 'nav-text', false).showNavigationText).toBe(false)
  })

  it('labels provider question types', () => {
    expect(questionTypeLabel({ provider_type: 'matrix', type_code: '', num: 1 } as any)).toBe('矩阵题')
    expect(questionTypeLabel({ provider_type: '', type_code: '7', num: 1 } as any)).toBe('下拉题')
  })
})
