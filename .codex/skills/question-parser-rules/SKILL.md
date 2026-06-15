---
name: question-parser-rules
description: 面向 SurveyController 仓库的题型解析、字段映射与 parser 规则技能。用于修改 `wjx/provider/`、`tencent/provider/`、`credamo/provider/`、`software/core/questions/`、`software/providers/` 中的题目结构解析、元数据字段、题型识别、逻辑规则标记、答案模型映射和最小兼容适配。适合处理 parser 规则和题目结构演进，不适合处理 HTTP 提交调度或纯接口逆向分析。
---

# Question Parser Rules

这个 skill 处理“题目怎么被识别、落成什么字段、后面怎么用”。
重点是 parser 输出结构稳定，平台隔离清楚，别把题型判断和执行链路搅成屎。

## must_read

- `software/providers/contracts.py`
- `software/core/questions/config.py`
- `software/core/questions/schema.py`
- `software/core/questions/validation.py`
- 目标平台的 `parser.py`
- 目标平台的 `answering_builders.py` 或相关 helper
- 对应测试文件

## workflow

1. 先定范围。
   - 入口页/接口字段变了
   - 题型识别错了
   - option、row、text_inputs、逻辑规则字段错了
   - parser 输出对了，但后续答案构造跟不上
2. 先抓事实，再改规则。
   - HTML 片段
   - JSON payload
   - 现有 parser 输出
   - 失败日志
3. 找落点。
   - 平台专属解析：各自 `*/provider/parser.py`
   - 平台专属 helper：平台目录下的辅助模块
   - 通用题目字段和约束：`software/core/questions/`
   - 通用问卷元数据契约：`software/providers/contracts.py`
4. 最小改动适配。
   - 先补具体题型规则
   - 再看要不要抽公共 helper
   - 没必要别顺手重写整个 parser
5. 如果 parser 输出字段变了，顺手检查消费方。
   - UI 问题编辑器
   - provider answering builders
   - runtime preparation

## field_rules

改 parser 时重点盯这些字段：

- `type_code`
- `option_texts`
- `rows`、`row_texts`
- `text_inputs`、`text_input_labels`
- `fillable_options`
- `attached_option_selects`
- `is_location`
- `is_rating`
- `multi_min_limit`、`multi_max_limit`
- `has_jump`、`jump_rules`
- `has_display_condition`、`display_conditions`
- `has_dependent_display_logic`、`controls_display_targets`
- `logic_parse_status`
- `provider`、`provider_question_id`、`provider_page_id`、`provider_type`

这些字段不是随便加着玩的。
一旦语义变了，UI、执行链路、反填和答案构造都可能跟着炸。

## boundaries

1. 平台差异留在各自目录。
   - `wjx/provider/`
   - `tencent/provider/`
   - `credamo/provider/`
2. 通用层不要出现平台私货字段判断。
3. 题型解析和 HTTP 调度分开。
   提交并发、超时、重试去 `async-http-pipeline`。
4. 接口事实提取和签名字段归类优先走 `survey-platform-reverse-analysis`。
   这个 skill 只负责把题目结构落成项目内部可消费的数据。

## common_commands

```bash
uv run pytest CI/unit_tests/providers
uv run pytest CI/unit_tests/questions
uv run pytest CI/unit_tests/providers/test_http_runtime.py
uv run pytest CI/unit_tests/engine/test_provider_common.py
uv run pytest CI/unit_tests/engine/test_reverse_fill_parser.py
uv run python CI/python_ci.py
rg "type_code|logic_parse_status|provider_question_id|option_texts|row_texts|fillable_options" wjx tencent credamo software/core software/providers
```

## validation_checklist

- 是否先拿到了 HTML、接口 payload 或失败日志，而不是瞎猜。
- 规则改动是否落在对应平台目录，没有把平台脏活抹进通用层。
- parser 输出字段语义是否和现有契约一致。
- 改了字段后，消费方是否一起看过。
- 是否优先补了 provider 和 questions 测试。
- 如果只是某个平台新增小规则，是否避免了无关重构。
