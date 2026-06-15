---
name: async-http-pipeline
description: 面向 SurveyController 仓库的全异步 HTTP 解析与执行链路技能。用于修改或排查 software/network/http/、software/core/engine/、software/providers/、software/network/proxy/ 以及各平台 provider 的异步请求、响应解析、任务调度、并发控制、超时、重试、取消和资源释放问题。适合处理纯 HTTP 提交链路，不适合恢复浏览器自动化兜底。
---

# async-http-pipeline

## name

`async-http-pipeline`

## description

这个 skill 处理异步 HTTP 链路。
重点是请求发送、响应解析、任务调度、并发限制、超时、取消、重试和资源释放。
适用范围是项目现有纯 HTTP 提交架构。

## when_to_use

出现这些情况时用：

- `software/network/http/async_client.py`、`software/core/engine/`、`software/providers/` 的异步链路要改。
- 并发执行时卡住、超时、泄漏连接、取消不生效、异常吞掉。
- 平台 HTTP 提交流程需要补重试、限流、超时或代理逻辑。
- 需要给异步执行链路补测试，尤其是 `CI/unit_tests/engine/`、`CI/unit_tests/test_http_client.py` 这类位置。

这些情况别乱用：

- 只是改静态解析规则，不碰异步执行。
- 想加浏览器自动化兜底。

## instructions

1. 先确认现有异步基础设施。
   必读：
   - `software/network/http/async_client.py`
   - `software/network/http/client.py`
   - `software/providers/registry.py`
   - 相关 `software/core/engine/` 模块
   - 目标平台的 `wjx/provider/http_runtime.py`、`tencent/provider/http_runtime.py`、`credamo/provider/http_runtime.py`
2. 优先复用现有 HTTP 客户端。
   当前项目依赖是 `httpx`，不要新塞别的 HTTP 栈。
3. 严禁在 async 函数里阻塞事件循环。
   不要直接塞长时间同步 IO、`time.sleep()`、阻塞网络调用、重 CPU 循环。
4. 分清四层职责：
   - 网络层：请求、连接、代理、cookie、headers、超时
   - 解析层：响应转题目结构或提交参数
   - 执行层：任务调度、并发、取消、重试
   - 状态回传层：线程状态、日志、UI 状态同步
5. 处理这些异常路径：
   - 超时
   - 连接失败
   - 重定向异常
   - 编码异常
   - 取消信号触发
   - 重试后仍失败
6. 代理和会话相关逻辑，优先检查：
   - `software/network/proxy/api/`
   - `software/network/proxy/pool/`
   - `software/network/proxy/session/`
   - `software/network/proxy/areas/`
7. 改完后补异步测试。
   优先用 mock 或假响应，不要依赖真实外部服务。
   参考 `pytest-asyncio` 和现有 `CI/unit_tests/engine/`、`CI/unit_tests/test_http_client.py`。
8. 不要把平台特定参数拼装写回通用 HTTP 客户端。
   通用层只管请求能力，平台细节留在 provider。

## project_conventions

- 当前分支固定走纯 HTTP 提交链路。
- `software/providers/registry.py` 已明确移除浏览器填答兜底，别手贱恢复。
- `httpx>=0.27,<1` 在 `pyproject.toml` 已锁定。
- 代理策略在 `software/network/proxy/`，不要把代理逻辑散到 UI 或平台解析文件。
- UI 线程不能直接吃长耗时异步工作，状态回传要走已有控制层。
- 测试目录是真实的 `CI/unit_tests/`，不是 `tests/`。

## common_commands

```bash
uv run pytest CI/unit_tests/test_http_client.py
uv run pytest CI/unit_tests/engine
uv run pytest CI/unit_tests/test_proxy_pool.py
uv run pytest CI/unit_tests/test_proxy_api_provider.py
uv run pytest CI/unit_tests/test_session_policy.py
uv run python CI/python_ci.py
rg "async def|await " software/core software/network software/providers wjx tencent credamo
```

## validation_checklist

- 是否沿用现有 `httpx` 客户端和异步架构。
- async 函数里是否没有阻塞事件循环。
- 超时、异常、重试、取消、并发限制、资源释放是否都考虑到了。
- cookie、headers、代理、编码、重定向、限流是否按原有边界处理。
- 平台特定逻辑是否仍留在各自 provider。
- 是否补了异步测试；若没补，是否说明原因。
