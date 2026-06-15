# Provider 与纯 HTTP 提交流程

## 总原则
当前主线明确只走纯 HTTP 问卷提交流程，不新增 Playwright、Selenium 或浏览器自动化依赖。

证据：
- [AGENTS.md](/abs/path/D:/Projects/SurveyController/AGENTS.md:1)
- [CONTRIBUTING.md](/abs/path/D:/Projects/SurveyController/CONTRIBUTING.md:1)
- [software/providers/registry.py](/abs/path/D:/Projects/SurveyController/software/providers/registry.py:1)

`registry.py` 里三个 `_browser_runtime_removed()` 直接抛错，这不是提示语，是硬边界。

## 统一合同
跨平台公共合同和归一化在：
- [software/providers/contracts.py](/abs/path/D:/Projects/SurveyController/software/providers/contracts.py:1)
- [software/providers/common.py](/abs/path/D:/Projects/SurveyController/software/providers/common.py:1)
- [software/providers/registry.py](/abs/path/D:/Projects/SurveyController/software/providers/registry.py:1)

规则：
- 新平台字段先在平台私有解析器里归一，再落到 `SurveyQuestionMeta` / `SurveyDefinition`。
- 公共层只接受归一化后的结构，不要把某平台原始 payload 泄露到 UI 或 engine。
- provider identity 相关字段，如 `provider_question_id`、`provider_page_id`、`provider_type`，改动时要保持三平台合同一致。

对应契约测试：
- [CI/unit_tests/providers/test_contracts.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/providers/test_contracts.py:1)

## 平台实现怎么放
- 问卷星：`wjx/provider/`
- 腾讯问卷：`tencent/provider/`
- 见数：`credamo/provider/`

每个平台通常拆成：
- `parser.py` 或 html parser 相关模块
- `answering_builders.py`
- `http_runtime.py`

公共运行时会通过 `fill_survey_http()` 调到这些实现。

## 运行前准备和运行时状态
启动前校验集中在 [software/ui/controller/run_controller_parts/runtime_preparation.py](/abs/path/D:/Projects/SurveyController/software/ui/controller/run_controller_parts/runtime_preparation.py:1)。

这里会：
- 校验题目配置
- 构造 `ExecutionConfig`
- 处理反填配置
- 校验见数作答时间窗
- 启动前复查问卷星问卷状态

规则：
- 运行前能确定的问题，在 preparation 阶段拦住，不要把明显配置错误拖到提交时才炸。
- provider 运行时错误要尽量带题号、题目标题、平台信息，别只抛 `boom`。

## 代理与 HTTP 约束
代理相关逻辑统一进 `software/network/proxy/`。不要在 provider 内私自发明另一套代理池。

随机 IP 相关落点：
- `software/network/proxy/api/`
- `software/network/proxy/areas/`
- `software/network/proxy/policy/`
- `software/network/proxy/pool/`
- `software/network/proxy/session/`

## 测试要求
provider / HTTP 相关改动，优先补这些层：
- [CI/unit_tests/providers/test_http_runtime.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/providers/test_http_runtime.py:1)
- [CI/unit_tests/providers/test_wjx_parser.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/providers/test_wjx_parser.py:1)
- [CI/unit_tests/providers/test_tencent_parser.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/providers/test_tencent_parser.py:1)
- [CI/unit_tests/providers/test_credamo_parser.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/providers/test_credamo_parser.py:1)

## 反模式
- 在 UI 层直接拼平台提交参数。
- 恢复浏览器提交兜底，哪怕只是“临时过渡”。
- 让一个平台的原始题目结构污染公共合同。
- 代理逻辑散落到 provider 私有文件里，最后谁也管不住。
