---
name: gui-development
description: 面向 SurveyController 桌面端的 GUI 开发与界面修复技能。用于修改 software/ui/ 下的 PySide6 + QFluentWidgets 页面、弹窗、导航、配置编辑、运行状态展示和日志界面，处理信号槽、线程协作、对象生命周期、布局、主题和窗口缩放问题。适合做桌面界面开发、交互修复和配置同步，不适合把耗时逻辑直接塞进主线程。
---

# gui-development

## name

`gui-development`

## description

这个 skill 处理桌面 GUI。
重点是页面、弹窗、交互逻辑、配置编辑、日志展示、运行状态反馈以及符合 Fluent Design 的界面架构。
技术栈是 PySide6 加 QFluentWidgets。

## when_to_use

出现这些情况时用：

- 要改 `software/ui/` 下的页面、对话框、导航、卡片、表格、日志面板或执行状态视图。
- 配置项在 UI 里显示错、保存错、同步错。
- 运行状态、错误提示、日志展示不清楚，或界面层级杂乱、缺乏主次。
- 主线程卡死、信号槽没接好、对象生命周期出问题。

这些情况别乱搞：

- 把网络、解析、平台逻辑直接塞进页面类。
- 在主线程里跑 HTTP、磁盘大 IO、长循环。
- 把所有内容无脑套进 `CardWidget` 堆砌盒子。

## design_philosophy

### 1. 去容器化与 Mica 透明画布优先

- 优先让界面直接呼吸在窗口 Mica / 透明背景上，不要把所有区域都套进 `CardWidget` 或多层嵌套边框。
- 容器需要透明时统一设置：
  - `setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)`
  - `setAutoFillBackground(False)`
  - `ScrollArea.enableTransparentBackground()` 并将 `viewport()` 设为透明。
- 仅在明确需要配置项分组或折叠详情时使用 `SettingCardGroup`、`SettingCard`、`ExpandGroupSettingCard`；平级内容之间优先使用 `HorizontalSeparator`、`VerticalSeparator` 与留白间距拉开层次。

### 2. 明确主次与视觉焦点

- 每个页面必须有唯一主视觉焦点，辅以次级信息区，避免多个同尺寸、同权重的平铺容器抢占视线。
- 严格使用 QFluentWidgets 语义字号组件建立层级，同时自动兼容深色/浅色主题：
  - `LargeTitleLabel`：核心数字或主指标（如 `11 / 30 份`）
  - `TitleLabel` / `SubtitleLabel`：页面主标题
  - `StrongBodyLabel`：关键状态、分组标题、百分比与会话名称
  - `BodyLabel`：常规状态与计数文本
- 禁止硬编码 `#6b6b6b` 等浅色模式专属颜色，主题色与文字对比度交由 QFluentWidgets 原生组件托管。

### 3. 克制文案与纯净界面

- 禁止在界面中添加解释性小字、迁移提示、内部实现说明或开发备注。
- 禁止在 GUI 文案中使用 `·` 进行拼接（遵循仓库规则）。
- 同一数据不要在相邻区域重复展示（例如主指标已展示 `11 / 30 份`，状态文本中不再重复拼接相同计数）。

### 4. 原生组件四态与动画规范

- 进度展示统一复用原生 `ProgressRing`、`IndeterminateProgressRing`、`ProgressBar`、`IndeterminateProgressBar`，并完整覆盖四种视觉状态：
  1. **百分比态**：正常强调色，`ProgressBar` 配合 `QPropertyAnimation` 平滑过渡数值。
  2. **加载中态**：使用 `IndeterminateProgressRing` / `IndeterminateProgressBar`；显示时调用 `start()`，隐藏或销毁前必须调用 `stop()`。
  3. **警告/暂停态（黄色）**：用于全局暂停、重试、代理切换、智能验证、冷却、未知状态。由于 `ProgressBar.setError(False)` 会同时清除暂停标记，切换黄色态必须先调用 `resume()` 再调用 `setPaused(True)`。
  4. **异常/失败态（红色）**：用于明确失败或连接异常，调用 `setError(True)`。
- `ProgressBar` 与 `ProgressRing` 在 `value == 0` 时不会绘制进度填充；处于黄色或红色状态且当前进度为 `0` 时，应将显示值兜底设为可见数值（如 `100`），确保状态色清晰可见。

### 5. 空间导航与响应式布局

- 多步骤流程使用 `HorizontalSlideStackedWidget`（见 `software/ui/pages/workbench/dashboard/ui_builder.py`），通过 `isBack=False/True` 区分前进与回退动画方向，左上角统一使用 `TransparentToolButton(FluentIcon.RETURN)` 返回上一步。
- 内容区使用 `ScrollArea`（`setWidgetResizable(True)` + `ScrollBarAlwaysOff`）包裹居中弹性容器（两侧 `addStretch(1)`，中间 `setMaximumWidth(760~860)` + `Expanding` 水平策略），保证宽屏不过度拉宽、窄窗不挤压裁切。
- 并列监控条目（如并发会话）优先采用自适应网格（单条目单列、多条目双列），避免大面积空白。

## exemplar_implementations

1. **概览主页第一步（极简聚焦入口）**：`software/ui/pages/workbench/dashboard/ui_builder.py`（`home_view`）
   - 亮点：完全去卡片化。右上角放置轻量 `CommandBar` 工具栏（`配置列表`、`载入配置`、`保存配置`）；主体通过上下左右 `addStretch(1)` 居中并限制最大宽度 `760px`，仅保留 `50px` 高的 `LineEdit`（支持拖拽与 `PasteOnlyMenu`）与两个操作按钮（`PushButton` 上传二维码 + `PrimaryPushButton` 自动配置问卷），无多余边框与说明文字。
2. **概览主页第四步（主次分层 + 无卡片执行监控）**：`software/ui/pages/workbench/dashboard/execution_panel.py`（`DashboardExecutionPanel`）
   - 亮点：去容器化与主次分明的典型范例。顶部极简返回栏；Hero 主视觉区直接置于透明画布上，左侧 `108x108` `ProgressRing` / `IndeterminateProgressRing` 与右侧 `LargeTitleLabel` 主进度 + `VerticalSeparator` 分隔的状态与失败计数构成核心焦点；中间用一条 `HorizontalSeparator` 过渡到次级“并发会话”区；会话区不使用 `CardWidget`，通过 `QGridLayout`（单会话单列、多会话双列）排布各并发会话的 `ProgressBar` / `IndeterminateProgressBar`，完整实现百分比、加载中、黄色、红色四态；底部右对齐操作栏统一承载 `暂停/继续`、`停止`、`重新开始`。
3. **概览主页第三步（结构化配置表单）**：`software/ui/pages/workbench/dashboard/run_setup_panel.py`（`DashboardRunSetupPanel`）
   - 亮点：当页面承担密集参数编辑时，使用 `SettingCardGroup` + `SettingCard` / `ExpandGroupSettingCard` / `SliderSettingCard` / `SwitchButton` 组织表单，保持 `860px` 居中弹性容器与透明 `ScrollArea`，底部固定主操作按钮（`PrimaryPushButton("开始执行")`）。

## instructions

1. 先读入口、工作台装配点和目标页面。
   必读：
   - `software/app/main.py`
   - `software/ui/shell/main_window.py`
   - `software/ui/shell/main_window_parts/lazy_pages.py`
   - `software/ui/pages/workbench/presenter.py`
   - `software/ui/pages/workbench/session.py`
   - 相关页面模块
2. 优先复用现有 PySide6 / QFluentWidgets 组件与上述优秀实现范式，不要自己造一套风格，也不要滥用外框卡片。
3. 耗时任务别堵主线程，需要走线程、异步桥接、任务队列或现有控制层。
4. UI 改动时至少检查这些东西：
   - 信号槽连接与去重
   - 对象生命周期（隐藏/移除时停止动画并安全 `deleteLater`）
   - 主次层级与布局是否挤压或大面积留空
   - 深色模式与浅色模式
   - DPI 缩放与窄窗口适配
   - 异常提示是否清晰可懂
5. 涉及配置编辑时，先找真实读写路径：
   - `software/app/settings_store.py`
   - `software/app/user_paths.py`
   - 相关 `software/io/` 和页面同步模块
6. 涉及运行状态时，优先检查：
   - `software/ui/controller/`
   - `software/ui/pages/workbench/dashboard/`
   - `software/ui/pages/workbench/session.py`
   - `software/ui/pages/workbench/runtime_panel/`
   - `software/ui/pages/workbench/log_panel/`
   - `software/ui/pages/workbench/reverse_fill/`
7. 主页相关改动要区分页面装配和导航懒加载：
   - 工作台由 `WorkbenchPresenter` 在主窗口启动时装配。
   - `DashboardPage` 内部的 `home_view`（第一步）、内嵌题目向导（第二步）、`DashboardRunSetupPanel`（第三步）和 `DashboardExecutionPanel`（第四步）负责主页四步流程，通过 `HorizontalSlideStackedWidget` 切换。
   - `RuntimePage` 是共享运行配置承载对象，当前隐藏侧边栏入口；不要把它当成独立导航页重新接回去。
   - 日志、社区、关于、捐赠和设置页仍通过 `MainWindowLazyPagesMixin` 按需加载。
8. 不要吞异常，用户至少要看到清楚的错误反馈，日志里也要能追。
9. 修改后做基本 smoke test，确保应用能启动并能进入相关页面。

## project_conventions

- GUI 主目录是真实存在的 `software/ui/`。
- 工作台由 `WorkbenchPresenter` 直接装配；设置、更多、社区和日志等辅助页通过主窗口懒加载。侧边栏路由键仍由 `software/ui/shell/main_window_parts/lazy_pages.py` 集中维护。
- 资源路径别写死安装目录。只读资源看 `software/app/runtime_paths.py`，用户可写配置看 `software/app/user_paths.py`。
- 改 UI 优先用 QFluentWidgets 原生组件。
- 不要把内部解释、迁移提示、开发说明或带 `·` 的说明性文字直接写进图形界面。
- 如果用了 Playwright MCP，本项目约束是用系统 Edge；但当前仓库规则同时禁止引入浏览器自动化依赖，普通 GUI 改动优先用 Qt smoke test。

## common_commands

```bash
uv run python SurveyController.py
uv run python -m pytest CI/unit_tests/app
uv run python -m pytest CI/unit_tests/app/test_dashboard_execution_panel.py
uv run python -m pytest CI/unit_tests/app/test_runtime_panel_cards_qtbot.py
uv run python -m pytest CI/unit_tests/app/test_question_wizard_dialog_qtbot.py
uv run python -m pytest CI/unit_tests/app/test_workbench_pages_smoke.py CI/unit_tests/app/test_workbench_presenter.py CI/unit_tests/app/test_workbench_session.py
uv run python -m pytest CI/unit_tests/app/test_dashboard_parts.py CI/unit_tests/app/test_dashboard_entries_run_actions.py
uv run python -m pytest CI/unit_tests/app/test_quota_redeem_dialog.py
uv run python -m CI.python_checks.window_smoke_check
uv run python CI/python_ci.py
uv run python CI/python_ci.py --full
rg "QFluent|Signal|slot|qtbot|Page|Dialog" software/ui CI/unit_tests/app
```

## validation_checklist

- 是否先读了主窗口、目标页面、相关控制器和配置读写代码。
- 是否遵循去容器化、主次分明、无冗余说明文字与无 `·` 的设计原则。
- 是否复用了现有 PySide6 / QFluentWidgets 原生组件并正确处理了深色模式与动画生命周期。
- 是否没有把耗时任务放到主线程。
- 信号槽、对象生命周期、布局、窄窗口与 DPI 缩放是否检查过。
- 配置项显示和实际配置读写是否一致。
- 日志、任务状态、错误反馈是否清楚，没有吞异常。
- 是否做了基本 GUI smoke test；没跑要说明原因。
