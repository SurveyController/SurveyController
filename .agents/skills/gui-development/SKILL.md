---
name: gui-development
description: 面向 SurveyController 桌面端的 GUI 开发与界面修复技能。用于修改 software/ui/ 下的 PySide6 + QFluentWidgets 页面、弹窗、导航、配置编辑、运行状态展示和日志界面，处理信号槽、线程协作、对象生命周期、布局、主题和窗口缩放问题。适合做桌面界面开发、交互修复和配置同步，不适合把耗时逻辑直接塞进主线程。
---

# gui-development

## name

`gui-development`

## description

这个 skill 处理桌面 GUI。
重点是页面、弹窗、交互逻辑、配置编辑、日志展示和运行状态反馈。
技术栈是 PySide6 加 QFluentWidgets。

## when_to_use

出现这些情况时用：

- 要改 `software/ui/` 下的页面、对话框、导航、卡片、表格、日志面板。
- 配置项在 UI 里显示错、保存错、同步错。
- 运行状态、错误提示、日志展示不清楚。
- 主线程卡死、信号槽没接好、对象生命周期出问题。

这些情况别乱搞：

- 把网络、解析、平台逻辑直接塞进页面类。
- 在主线程里跑 HTTP、磁盘大 IO、长循环。

## instructions

1. 先读入口和页面装配点。
   必读：
   - `software/app/main.py`
   - `software/ui/shell/main_window.py`
   - `software/ui/shell/main_window_parts/lazy_pages.py`
   - 相关页面模块
2. 优先复用现有 PySide6 / QFluentWidgets 组件。
   不要自己造一套风格。
3. 耗时任务别堵主线程。
   需要走线程、异步桥接、任务队列或现有控制层。
4. UI 改动时至少检查这些东西：
   - 信号槽连接
   - 对象生命周期
   - 布局是否挤炸
   - 深色模式
   - DPI 缩放
   - 异常提示是否能看懂
5. 涉及配置编辑时，先找真实读写路径。
   重点看：
   - `software/app/settings_store.py`
   - `software/app/user_paths.py`
   - 相关 `software/io/` 和页面同步模块
6. 涉及运行状态时，优先检查：
   - `software/ui/controller/`
   - `software/ui/pages/workbench/runtime_panel/`
   - `software/ui/pages/workbench/log_panel/`
   - `software/ui/pages/workbench/dashboard/`
7. 不要吞异常。
   用户至少要看到清楚的错误反馈，日志里也要能追。
8. 修改后做基本 smoke test。
   至少确保应用能启动，并能进入相关页面。

## project_conventions

- GUI 主目录是真实存在的 `software/ui/`。
- 设置页、更多页、工作台页都通过主窗口懒加载组织，别乱改路由键。
- 资源路径别写死安装目录。只读资源看 `software/app/runtime_paths.py`，用户可写配置看 `software/app/user_paths.py`。
- 改 UI 优先用 QFluentWidgets 原生组件。
- 不要把内部解释、迁移提示、开发说明直接写进图形界面。
- 如果用了 Playwright MCP，本项目约束是用系统 Edge；但当前仓库规则同时禁止引入浏览器自动化依赖，普通 GUI 改动优先用 Qt smoke test。

## common_commands

```bash
uv run python SurveyController.py
uv run pytest CI/unit_tests/app
uv run pytest CI/unit_tests/app/test_runtime_panel_cards_qtbot.py
uv run pytest CI/unit_tests/app/test_question_wizard_dialog_qtbot.py
uv run pytest CI/unit_tests/app/test_quota_redeem_dialog.py
uv run python CI/python_ci.py
uv run python CI/python_ci.py --full
rg "QFluent|Signal|slot|qtbot|Page|Dialog" software/ui CI/unit_tests/app
```

## validation_checklist

- 是否先读了主窗口、目标页面、相关控制器和配置读写代码。
- 是否复用了现有 PySide6 / QFluentWidgets 组件。
- 是否没有把耗时任务放到主线程。
- 信号槽、对象生命周期、布局、深色模式、缩放是否检查过。
- 配置项显示和实际配置读写是否一致。
- 日志、任务状态、错误反馈是否清楚，没有吞异常。
- 是否做了基本 GUI smoke test；没跑要说明原因。
