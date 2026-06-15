---
name: test-regression-strategy
description: 面向 SurveyController 仓库的测试分层与回归选择技能。用于判断改动后该补哪类测试、mock 边界放哪、`CI/unit_tests/` 与 `CI/live_tests/` 怎么分层、该跑哪些 `pytest` 目标，以及哪些场景必须跑 `uv run python CI/python_ci.py --full`。适合处理功能改动后的验证策略，不适合替代具体模块修复。
---

# Test Regression Strategy

这个 skill 处理“改完后怎么验”。
重点不是多跑测试，是按改动边界挑对测试，少跑废活，别漏高风险回归。

## must_read

- `CI/python_ci.py`
- `CI/python_checks/common.py`
- `CI/unit_tests/conftest.py`
- 目标模块对应的现有测试文件

## workflow

1. 先给改动分类。
   常见类别：
   - `software/ui/`、`software/ui/controller/`：UI、信号槽、页面同步
   - `software/app/`、`software/io/config/`：配置、路径、迁移、序列化
   - `software/core/engine/`、`software/network/`、`software/providers/`：执行链路、HTTP、代理、并发
   - `wjx/`、`tencent/`、`credamo/`：平台 parser、题型规则、提交参数
   - `software/update/`、`CI/release_tools/`、`Setup/`：更新、打包、发布
2. 先找最近的测试层，不要一上来就全仓库轰炸。
   默认顺序：
   - 目标函数或目标模块的单测
   - 同目录的集成型单测
   - `uv run python CI/python_ci.py`
   - 只有命中高风险条件时才上 `--full`
3. mock 边界按层放。
   - 纯计算、归一化、字段映射：尽量不 mock
   - 文件系统、QSettings、网络、子进程、Qt 桌面服务：用 monkeypatch 或 fake
   - 不要 mock 被测模块自己的核心逻辑，只 mock 外边界
4. unit 和 live 分开。
   - `CI/unit_tests/` 只测本地可重复逻辑
   - `CI/live_tests/` 只放真实问卷、真实网络、真实发布链路回归
   - 普通修复不要顺手把外网访问塞进 unit test
5. 改完后按风险补回归命令。

## when_to_run_full

这些情况必须跑 `uv run python CI/python_ci.py --full`：

- 改了启动链、主窗口装配、页面懒加载、Qt 导入路径
- 改了 `software/app/main.py`、`software/ui/shell/`、`software/ui/pages/`
- 改了配置路径迁移，可能影响启动读配置
- 改了 HTTP 提交主链路、provider 注册、解析入口，担心导入或启动时炸
- 改了更新、打包、版本入口，可能影响主窗口状态区或启动检查

这些情况通常先跑快速检查就够：

- 纯工具函数
- 纯 parser helper
- 纯 schema/codec 归一化
- 纯日志格式化

## test_selection

按改动选测试：

- 配置、路径、迁移：
  - `uv run pytest CI/unit_tests/app/test_config_codec.py`
  - `uv run pytest CI/unit_tests/app/test_config_store.py`
  - `uv run pytest CI/unit_tests/app/test_settings_page_qtbot.py`
- UI 页面和工作台同步：
  - `uv run pytest CI/unit_tests/app/test_workbench_pages_smoke.py`
  - `uv run pytest CI/unit_tests/app/test_ui_layout_contracts.py`
  - 相关 `qtbot` 测试
- 执行引擎、异步链路、HTTP：
  - `uv run pytest CI/unit_tests/engine`
  - `uv run pytest CI/unit_tests/test_http_client.py`
  - `uv run pytest CI/unit_tests/providers/test_http_runtime.py`
- parser、题型规则、平台字段：
  - `uv run pytest CI/unit_tests/questions`
  - `uv run pytest CI/unit_tests/providers`
  - `uv run pytest CI/unit_tests/engine/test_reverse_fill_parser.py`
- 更新、发布、Velopack：
  - `uv run pytest CI/unit_tests/app/test_main_window_update_large.py`
  - `uv run pytest CI/unit_tests/test_velopack_e2e_runner.py`
  - 需要时再看 `CI/live_tests/test_velopack_e2e.py`

## project_conventions

- `CI/python_ci.py` 默认会跑 compile、Ruff、Pyright、unit tests。
- `--full` 额外打开模块导入检查和主窗口 smoke。
- `CI/live_tests/test_live_runtime_regression.py` 依赖真实外部页面，不适合日常修复必跑。
- 覆盖率门槛在 `CI/python_checks/common.py` 里，当前 unit test 会带 `--cov-fail-under=75`。
- 测完如果生成临时文件、覆盖率产物或调试垃圾，要删掉。

## common_commands

```bash
uv run pytest CI/unit_tests/app/test_config_codec.py
uv run pytest CI/unit_tests/app/test_config_store.py
uv run pytest CI/unit_tests/providers
uv run pytest CI/unit_tests/questions
uv run pytest CI/unit_tests/engine
uv run python CI/python_ci.py
uv run python CI/python_ci.py --full
```

## validation_checklist

- 是否先按改动边界分类，再选测试。
- 是否优先跑了最近的单测，而不是一上来全量。
- mock 是否只放在文件系统、网络、QSettings、Qt 外边界。
- unit test 是否没有混入真实外网和真实账号。
- 是否判断了这次改动要不要跑 `--full`。
- 跑不了的检查是否明确说明原因。
