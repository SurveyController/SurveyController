---
name: log-config-debugging
description: 面向 SurveyController 的日志、配置与报错排查技能。用于根据用户提供的日志、截图、配置文件、调用栈、运行环境和最近改动定位根因，修复 software/app/、software/io/、software/logging/、software/network/、software/ui/ 以及平台适配层中的配置兼容、路径、编码、权限、依赖版本和平台差异问题。适合处理真实报错和配置脱节，不适合只改表面提示词。
---

# log-config-debugging

## name

`log-config-debugging`

## description

这个 skill 处理日志、配置和报错排查。
重点是先找根因，再修代码，再验证。
不是只给报错糊个补丁。

## when_to_use

出现这些情况时用：

- 用户给了日志、截图、配置文件、报错堆栈，要定位问题。
- 配置兼容性出毛病，旧配置升级后炸了。
- 路径、编码、权限、依赖版本、平台差异导致运行异常。
- UI 显示和实际配置脱节，日志里看不清根因。

这些情况别偷懒：

- 只改提示文案，不修根因。
- 在日志里打印敏感配置、token、cookie、代理密钥。

## instructions

1. 先收集现场。
   必看：
   - 错误信息
   - 调用栈
   - 用户配置文件
   - 运行环境
   - 最近改动
2. 先定根因，再决定改哪层。
   常见落点：
   - `software/app/` 路径、设置、迁移
   - `software/logging/` 日志初始化和格式
   - `software/io/` 配置读写、导入导出
   - `software/network/` HTTP、代理、会话
   - `software/ui/` 配置同步和错误反馈
3. 涉及配置时，保持兼容。
   优先考虑迁移、默认值、缺省字段补齐。
   相关路径先看 `software/app/user_paths.py`。
4. 修复时重点排查：
   - 路径拼错
   - 编码不一致
   - 文件权限
   - 依赖版本
   - Windows 与其他平台差异
5. 日志只记录必要信息。
   敏感字段要脱敏。
6. 改完后给出可复现步骤和验证命令。
   如果用户还要自查，再补最少量排查命令。

## project_conventions

- 用户可写配置和日志目录不在仓库根目录，真实入口看 `software/app/user_paths.py`。
- `configs/` 在当前工作区可直接读取做真实提交回归，但不要把敏感数据写回仓库。
- 日志工具主要在 `software/logging/log_utils.py`、`software/logging/action_logger.py`。
- 配置和路径问题优先修根因，不要只在 UI 上盖个提示。
- 普通单测不要访问真实外部服务，live 回归放 `CI/live_tests/`。

## common_commands

```bash
uv run python CI/python_ci.py
uv run pytest CI/unit_tests/app
uv run pytest CI/unit_tests/test_log_utils.py
uv run pytest CI/unit_tests/test_log_utils_concurrency.py
uv run pytest CI/unit_tests/test_submission_report.py
uv run pytest CI/unit_tests/test_system_helpers.py
rg "config|settings|log|path|encoding|json|traceback|exception" software CI/unit_tests
```

## validation_checklist

- 是否先看了错误信息、调用栈、配置文件、环境和最近改动。
- 是否找到根因，而不是只改表面报错。
- 对旧配置是否保持兼容；需要迁移时是否补了迁移或默认值。
- 路径、编码、权限、依赖版本、平台差异是否排查过。
- 日志里是否没有泄露敏感信息。
- 是否整理了复现步骤、修复点、验证命令和用户可执行的排查命令。
