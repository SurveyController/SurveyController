---
name: survey-platform-reverse-analysis
description: 面向 SurveyController 的问卷平台链路分析与适配技能。用于梳理问卷星、腾讯问卷、Credamo 见数等平台的入口页、初始化接口、题目结构、提交接口、校验字段、签名字段和页面解析流程，结合用户提供的页面、日志、HAR、请求响应、配置文件做合规调试与适配。只用于事实提取、参数归类、接口整理和适配器隔离，不用于绕过验证码、风控、付费限制或平台安全机制。
---

# survey-platform-reverse-analysis

## name

`survey-platform-reverse-analysis`

## description

这个 skill 处理问卷平台链路分析。
重点是请求流程、参数来源、签名字段、页面解析和适配器整理。
只做合规调试和平台适配。

## when_to_use

出现这些情况时用：

- 用户给了问卷页面、抓包、HAR、请求响应、日志、配置文件，要分析平台提交流程。
- 要确认哪些参数是固定值、动态值、环境值、用户输入值。
- 要把某个平台的解析、提交、校验逻辑落到 `wjx/provider/`、`tencent/provider/` 或 `credamo/provider/`。
- 要排查某平台最近接口变动，导致解析失败或提交失败。

这些情况别碰：

- 绕过验证码、风控、频控、付费墙。
- 要求把真实 cookie、token、账号密码写进代码、日志或测试。

## instructions

1. 先收事实。
   优先看用户提供的：
   - 页面源码
   - 请求响应
   - HAR
   - 运行日志
   - 配置文件样本
2. 按平台流程拆：
   - 入口页
   - 初始化接口
   - 题目结构来源
   - 提交接口
   - 校验接口
3. 对每个参数分类：
   - 固定值
   - 动态值
   - 环境值
   - 用户输入值
4. 写结论时分三类：
   - 已确认
   - 推测
   - 待验证
5. 落代码时把平台逻辑关进对应目录：
   - `wjx/provider/`
   - `tencent/provider/`
   - `credamo/provider/`
   通用层只留 `software/providers/` 的公共接口和注册逻辑。
6. 先读已有实现，别瞎猜：
   - `software/providers/registry.py`
   - `wjx/provider/parser.py`
   - `wjx/provider/http_runtime.py`
   - `tencent/provider/parser.py`
   - `tencent/provider/http_runtime.py`
   - `credamo/provider/parser.py`
   - `credamo/provider/http_runtime.py`
7. 如果接口字段变化，先做最小适配。
   不要顺手重写整个 parser。
8. 日志脱敏。
   cookie、token、手机号、账号、代理密钥都别落盘。

## project_conventions

- 项目支持的平台是真实存在的 `wjx/`、`tencent/`、`credamo/`。
- README 已写明三条主要 HTTP 链路，可拿来对照，但以真实代码和抓包为准。
- 平台适配器隔离很重要。别把 `jqsign`、`answer_session_id`、`signature` 这类平台字段塞进 `software/network/http/`。
- live 测试在 `CI/live_tests/`。普通单测不要碰真实问卷和真实账号。
- 不确定的接口行为，标成“待验证”，不要装懂。

## common_commands

```bash
uv run pytest CI/unit_tests/questions
uv run pytest CI/unit_tests/engine/test_provider_common.py
uv run pytest CI/unit_tests/engine/test_reverse_fill_parser.py
uv run python CI/python_ci.py
rg "parse_|http_runtime|submit|signature|sign|token|cookie|header" wjx tencent credamo software/providers
rg "WJX|QQ|CREDAMO|provider" software/providers software/core
```

## validation_checklist

- 是否先基于页面、日志、HAR、请求响应提取事实。
- 平台流程是否拆清楚了：入口、初始化、题目、提交、校验。
- 参数是否区分了固定值、动态值、环境值、用户输入值。
- 结论是否明确标注“已确认 / 推测 / 待验证”。
- 平台逻辑是否仍隔离在各自 provider 目录。
- 日志和代码里是否没有写入敏感信息。
- 是否避免了绕过验证码、风控、付费限制这类脏活。
