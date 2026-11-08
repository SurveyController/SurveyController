---
name: structure-refactor
description: 面向 SurveyController 仓库的目录结构重构与模块拆分技能。用于整理 software/、wjx/、tencent/、credamo/、CI/unit_tests/ 等真实目录，处理文件移动、命名调整、导入修复、测试路径更新、资源路径修复、CI 检查联动。适合在需要小步重构、保持行为不变、清理屎山边界时使用，不适合纯样式改名或无关大洗牌。
---

# structure-refactor

## name

`structure-refactor`

## description

这个 skill 处理项目级结构重构。
重点是模块拆分、文件移动、命名整理、导入修复、测试同步。
目标是让 `software/`、平台适配目录、测试目录和资源目录的职责更清楚。

## when_to_use

出现这些情况时用：

- 某个文件职责失控，已经把 UI、网络、解析、状态逻辑搅成一锅粥。
- 需要把代码从 `software/ui/`、`software/core/`、`software/network/`、`software/providers/`、`wjx/provider/` 之类目录重新归位。
- 需要移动或拆分文件，同时修复 import、测试引用、资源路径、CI 检查路径。
- 新增或删除顶层目录，必须同步检查 `AGENTS.md` 和 `CONTRIBUTING.md`。

这些情况别乱用：

- 只是顺手把文件名改得更“好看”。
- 没有行为问题，却想大面积重排目录。
- 想把平台特定逻辑塞回通用层。

## instructions

1. 先读真实入口和边界。
   必读：`SurveyController.py`、`software/app/main.py`、`software/providers/registry.py`、相关模块和对应测试。
2. 先画出这次改动涉及的目录。
   常见边界：
   - `software/ui/` 放界面和控制器。
   - `software/core/` 放执行引擎、任务、题目模型。
   - `software/network/` 放 HTTP、代理、会话。
   - `software/providers/` 放平台公共层和适配注册。
   - `wjx/provider/`、`tencent/provider/`、`credamo/provider/` 放平台专属解析和提交链路。
   - `CI/unit_tests/`、`CI/live_tests/` 放测试。
3. 结构调整遵守“小步、可回滚、行为不变”。
   一次只解决一个边界问题。先移动，再修导入，再补测试。
4. 移动文件后立刻修这些东西：
   - Python import 路径
   - `__init__.py` 暴露
   - Qt 懒加载导入路径
   - 资源文件路径
   - `CI/python_ci.py`、`CI/python_checks/`、测试文件中的路径引用
5. 优先保留现有公开接口。
   如果必须改接口，先找调用方和测试，不准只改一头。
6. 不要为了“统一风格”把平台目录和通用目录混起来。
   `wjx/`、`tencent/`、`credamo/` 的逻辑必须继续隔离。
7. 涉及用户数据路径时，不准把可写数据挪到安装目录。
   路径规则看 `software/app/runtime_paths.py` 和 `software/app/user_paths.py`。
8. 改完就跑最小相关测试。
   如果改动碰到入口、路径、UI、执行链路，再补更大范围检查。

## project_conventions

- 仓库没有 `src/`，主体代码在 `software/`、`wjx/`、`tencent/`、`credamo/`。
- 仓库没有顶层 `tests/`，测试在 `CI/unit_tests/` 和 `CI/live_tests/`。
- `requirements.txt` 当前不存在，依赖以 `pyproject.toml` 和 `uv.lock` 为准。
- GUI 代码优先留在 `software/ui/`，不要把业务实现塞进页面文件。
- 平台解析和 HTTP 提交逻辑优先留在各自 `*/provider/`。
- 纯 HTTP 链路已经固化，`software/providers/registry.py` 明确禁用浏览器填答兜底。别把这坨屎又搬回来。
- 改顶层目录时，同步更新 `AGENTS.md` 和 `CONTRIBUTING.md`。

## common_commands

```bash
uv run python CI/python_ci.py
uv run pytest CI/unit_tests
uv run pytest CI/unit_tests/engine
uv run pytest CI/unit_tests/app
uv run pytest CI/unit_tests/questions
uv run python CI/python_ci.py --full
rg "from software|import software|from wjx|from tencent|from credamo"
rg --files software CI wjx tencent credamo
```

## validation_checklist

- 是否先读了入口、被移动模块、调用方、相关测试。
- 是否只做本次问题需要的结构调整，没有无关大重排。
- 文件移动后 import、测试路径、资源路径、CI 路径是否已修完。
- `software/`、平台目录、测试目录的职责边界是否更清楚。
- 相关测试和检查是否已运行；没跑要说明原因。
- 如果改了顶层目录，`AGENTS.md` 和 `CONTRIBUTING.md` 是否同步更新。
