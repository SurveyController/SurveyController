---
name: playwright-pipeline
description: 面向 SurveyController 仓库 v3 分支的 Playwright 作答执行层技能。仅在修改或排查 Playwright 作答链路、异步浏览器 owner/context 池、BrowserDriver 封装、页面加载、运行时答题、翻页、提交、取消、超时、资源释放和并发调度时使用。只能用于 v3 分支；只允许系统自带 Microsoft Edge，不允许安装或引入 Chromium；要求全量异步，不使用 Playwright sync_api。
---

# playwright-pipeline

## scope

这个 skill 处理 v3 的 Playwright 作答执行层。
重点是浏览器生命周期、上下文池、页面加载、题目交互、翻页、提交、停止、异常和资源释放。

先确认当前分支：

```bash
git branch --show-current
```

不是 `v3` 时不要直接改 Playwright 作答链路。
除非用户明确要求把 v3 方案迁到当前分支。

## must_read

改动前先读相关文件。
不要凭记忆猜。

- `software/network/browser/startup.py`
- `software/network/browser/options.py`
- `software/network/browser/runtime_async.py`
- `software/network/browser/async_owner_pool.py`
- `software/network/browser/pool_config.py`
- `software/core/engine/async_engine.py`
- `software/core/engine/async_runtime_loop.py`
- `software/core/engine/page_loader.py`
- `software/core/engine/submission_service.py`
- 目标平台的运行时文件：`wjx/provider/runtime*.py`、`wjx/provider/answering*.py`、`wjx/provider/navigation.py`、`wjx/provider/submission*.py`
- 目标平台的运行时文件：`tencent/provider/runtime*.py`、`tencent/provider/answering*.py`、`tencent/provider/navigation.py`、`tencent/provider/submission*.py`
- 目标平台的运行时文件：`credamo/provider/runtime*.py`、`credamo/provider/submission.py`

## hard_rules

1. 只能用系统 Microsoft Edge。
   Playwright 要走 `chromium.launch(channel="msedge")`。
   项目现有入口是 `software/network/browser/options.py::_build_launch_args()`。
2. 不准执行或建议执行 `playwright install chromium`。
   不要新增 Chromium 下载、捆绑、兜底或自动安装逻辑。
3. 全量异步。
   只能用 `playwright.async_api`。
   不准引入 `playwright.sync_api`。
4. async 函数里不准阻塞事件循环。
   不要用 `time.sleep()`、同步网络请求、长时间同步文件 IO、同步等待子进程。
   必须做阻塞系统调用时，用现有封装或 `asyncio.to_thread()` 隔离。
5. 不准把平台题型细节塞进浏览器通用层。
   `software/network/browser/` 只放浏览器能力。
   平台 DOM 规则留在各自 provider。
6. 不准恢复旧浏览器兜底屎山。
   v3 是 Playwright 作答执行层，不是把 HTTP 链路和浏览器链路乱搅在一起。

## architecture_boundaries

- 启动层：`startup.py`
  负责延迟导入 `async_playwright`、启动重试、环境错误分类。
- 参数层：`options.py`
  负责 selector、proxy、launch/context 参数。
  Edge-only 规则放这里。
- owner/context 池：`async_owner_pool.py`
  负责少量浏览器、多 context、并发槽位、断线恢复和 shutdown。
- driver 封装：`runtime_async.py`
  负责把 Playwright async page/element 包成项目内部 `BrowserDriver` 协议。
- 执行引擎：`software/core/engine/`
  负责任务调度、停止信号、页面加载、提交检测、状态回传。
- 平台运行时：`wjx/`、`tencent/`、`credamo/`
  负责 DOM 定位、题型交互、翻页和提交按钮。

## workflow

1. 先定位问题属于哪一层。
   浏览器拉不起看 `startup.py` 和 `options.py`。
   并发卡死看 `async_owner_pool.py` 和 `async_runtime_loop.py`。
   页面加载失败看 `page_loader.py`。
   某题型填错看平台 `runtime_interactions.py`、`runtime_answerers.py` 或 `answering_direct.py`。
   提交后判断错看 `submission_service.py` 和平台 `submission*.py`。
2. 保持异步调用链完整。
   新增 API 默认写成 `async def`。
   调用 Playwright API 必须 `await`。
   清理资源必须能被取消路径触发。
3. 处理异常路径。
   至少考虑启动失败、代理隧道失败、页面关闭、context/browser 断开、导航超时、停止信号、提交校验失败。
4. 改并发时同时看 owner 槽位释放。
   `AsyncBrowserSession.close()`、`PlaywrightAsyncDriver.aclose()`、`release_callback` 不能漏。
5. 改平台作答时优先写 DOM 层小函数。
   不要把一坨 JS 和重试循环塞进主流程。
   屎山就是这么来的。

## testing

优先补 mock 单测。
不要在普通单测访问真实问卷、真实账号或真实代理。

常用检查：

```bash
uv run pytest CI/unit_tests/test_browser_helpers.py
uv run pytest CI/unit_tests/test_browser_runtime_async.py
uv run pytest CI/unit_tests/engine/test_async_owner_pool_large.py
uv run pytest CI/unit_tests/engine/test_async_runtime_loop_large.py
uv run pytest CI/unit_tests/engine
uv run pytest CI/unit_tests/providers
uv run python CI/python_ci.py
```

涉及真实启动、UI、打包或提交链路时，再跑：

```bash
uv run python CI/python_ci.py --full
```

## validation_checklist

- 当前分支是否是 `v3`。
- 是否仍然只启动系统 Microsoft Edge。
- 是否没有 `playwright.sync_api`。
- 是否没有 `playwright install chromium` 或 Chromium 兜底。
- 是否没有在 async 函数里阻塞事件循环。
- context、page、browser、playwright 实例是否都能关闭。
- owner 槽位是否一定释放。
- 停止、超时、断线、代理失败和提交校验失败是否有明确路径。
- 平台 DOM 逻辑是否留在 provider。
- 是否补了相关异步测试；没补要说明原因。
