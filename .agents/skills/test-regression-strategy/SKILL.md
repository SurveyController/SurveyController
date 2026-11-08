---
name: test-regression-strategy
description: 面向 SurveyController 仓库的测试分层与回归选择技能。用于判断改动后该补哪类测试、mock 边界放哪、`CI/unit_tests/` 与 `CI/live_tests/` 怎么分层，以及哪些 CI job 应覆盖改动。适合处理功能改动后的验证策略，不适合替代具体模块修复。
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
   - 先由远端 CI 执行快速检查
   - 高风险改动还须由完整检查 job 覆盖
3. mock 边界按层放。
   - 纯计算、归一化、字段映射：尽量不 mock
   - 文件系统、QSettings、网络、子进程、Qt 桌面服务：用 monkeypatch 或 fake
   - 不要 mock 被测模块自己的核心逻辑，只 mock 外边界
4. unit 和 live 分开。
   - `CI/unit_tests/` 只测本地可重复逻辑
   - `CI/live_tests/` 只放真实问卷、真实网络、真实发布链路回归
   - 普通修复不要顺手把外网访问塞进 unit test
5. 改完后按风险补回归，并确认远端 CI 覆盖目标测试。
   仅当远端 CI 失败时，才按仓库规则在本地针对失败项做最小复现。

## when_to_run_full

这些情况必须由远端完整检查 job 验证：

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

按改动选远端 CI 中应覆盖的测试：

- 配置、路径、序列化：`CI/unit_tests/app/` 的 codec、store、设置页用例。
- UI 页面和工作台同步：相关 Qt 单测与离屏 smoke job。
- 执行引擎、异步链路、HTTP：`CI/unit_tests/engine/`、HTTP client 与 Provider HTTP runtime 用例。
- parser、题型规则、平台字段：`CI/unit_tests/questions/`、`CI/unit_tests/providers/` 与反填解析用例。
- 版本检查、发布：更新与元数据的离线用例；独立包构建不进入默认 CI。

## project_conventions

- 快速检查覆盖 compile、Ruff lint/format、ty 和 unit tests。
- 完整检查额外覆盖模块导入和主窗口离屏 smoke。
- `CI/live_tests/test_live_runtime_regression.py` 依赖真实外部页面，不适合日常修复必跑。
- 覆盖率门槛在 `CI/python_checks/common.py` 里：全仓 80%，core/application/network 85%，Provider 80%，UI 65%，并分别检查行与分支覆盖率。
- CI 或最小本地复现生成的临时文件、覆盖率产物按仓库规则清理。

## common_commands

先由远端 CI 验证代码改动；仅当远端 CI 失败时，才按仓库规则在本地做最小复现。

```bash
rg -n "ai_api_key|QSettings|config_directory|load_config|save_config" software CI
```

## validation_checklist

- 是否先按改动边界分类，再选测试。
- 是否先由远端 CI 验证，只有失败后才做最小本地复现。
- mock 是否只放在文件系统、网络、QSettings、Qt 外边界。
- unit test 是否没有混入真实外网和真实账号。
- 是否判断了这次改动需要哪些远端 CI job。
- 跑不了的检查是否明确说明原因。
