# SurveyController Go+Wails Migration Plan

本文件是 `refactor/go` 分支的项目级迁移计划。
Agent 每次处理 Go+Wails 迁移任务前必须先读本文件。
完成一个可验证任务后，必须把对应复选框改成 `[x]`，并在最终回复里说明验证命令。

## 总原则

- Python/PySide6 代码只作为稳定基线和行为参考。
- 不再花时间解耦 Python 旧代码，除非是紧急 bug 修复或为了提取迁移事实。
- 新能力优先写在 `go/`。
- 先迁纯核心，再接 Wails，再做正式 UI。
- Go 核心不读取 `configs/`，不接 UI，不访问真实外网普通单测。
- Wails WebView 只做桌面 UI，不承担问卷提交自动化。
- 普通测试不访问真实问卷、真实账号、真实付费代理。
- 真实链路验证只放 live/integration 测试，并用环境变量显式开启。

## 工期目标

| 阶段 | 目标 | 预计 |
| --- | --- | --- |
| P1 | Go 代理核心闭环 | 1-3 天 |
| P2 | 一个平台 Go 原生提交闭环 | 2-4 天 |
| P3 | Wails 调试壳闭环 | 1-2 天 |
| P4 | Go 执行引擎和日志状态 | 3-6 天 |
| P5 | 正式 UI alpha | 5-10 天 |
| P6 | WJX 大头迁移和发布链路 | 1-3 周 |

## P1 代理核心

- [x] 新增 `go/proxycore` 独立 Go module。
- [x] 实现 `ProxyLease`、payload 解析、地址归一化、脱敏、TTL 判断。
- [x] 实现代理池去重、占用、成功用过、冷却和并发 fetch。
- [x] 为 `go/proxycore` 补 mock 单测并跑通 `go test ./...`。
- [ ] 增加自定义代理 API fetcher，使用 `net/http`，支持超时和 context 取消。
- [ ] 增加代理健康检查，默认目标用可配置 URL，不写死真实业务页面。
- [ ] 增加 live test：仅在 `SC_PROXY_API_URL` 存在时访问真实代理 API。
- [x] 重新设计官方随机 IP session：账号、额度、设备 ID、持久化都走接口，不照搬 Python 全局状态。
- [x] 为官方随机 IP session 增加 mock 单测。

## P2 平台提交闭环

- [ ] 定义 Go 通用 survey 模型：题目、选项、提交请求、提交结果、错误类型。
- [ ] 选一个最小平台作为首迁目标，优先腾讯问卷或 Credamo，暂不碰 WJX。
- [ ] 实现 HTTP 获取、参数提取、题目解析。
- [ ] 实现答案构造和提交。
- [ ] 增加 fixture 单测：HTML/JSON 样本来自本地文件，不访问真实平台。
- [ ] 增加 live test：仅在显式环境变量存在时提交测试问卷。

## P3 Wails 调试壳

- [ ] 用 Wails v3 初始化独立应用模块。
- [ ] 确认本机模板：先跑 `wails3 init -l`，再选择 Svelte/TypeScript 模板。
- [ ] 接入 Go 核心模块，不把核心代码塞进 Wails 服务文件。
- [ ] 暴露最小服务方法：代理状态、平台解析、测试提交。
- [ ] 跑 `wails3 generate bindings`。
- [ ] 做最小调试 UI：URL 输入、按钮、日志区、结果区。
- [ ] 跑 `wails3 dev` 验证前后端通信。

## P4 Go 执行引擎

- [ ] 设计任务上下文：context 取消、并发数、限流、重试、代理租约、日志事件。
- [ ] 实现 worker 调度，不照搬 Python 线程/async 锁。
- [ ] 实现结构化日志事件流，供 Wails 前端订阅。
- [ ] 实现失败重试和错误分类。
- [ ] 实现任务停止、资源释放、代理归还。
- [ ] 增加并发和取消单测。

## P5 UI alpha

- [ ] 确定前端组件栈：Svelte + TailwindCSS。
- [ ] 先做工作台主流程，不做营销页。
- [ ] 迁移配置输入、问卷 URL、运行按钮、日志、进度、结果。
- [ ] 做代理状态面板。
- [ ] 做平台解析预览。
- [ ] 做任务运行态和取消态。
- [ ] 用 Wails dev 手动验证 UI 不遮挡、不溢出、状态清晰。

## P6 WJX 和发布

- [ ] 梳理 WJX Python 行为，只提取协议事实，不重构旧代码。
- [ ] 迁移 WJX HTML 解析和题型映射。
- [ ] 迁移 WJX 提交参数构造。
- [ ] 增加 WJX fixture 单测。
- [ ] 增加 WJX live test，显式环境变量开启。
- [ ] 设计 Wails 打包产物目录。
- [ ] 迁移更新链路，保持主 feed 为 `https://dl.hungrym0.com/surveycontroller/win/stable/`。
- [ ] 验证 Windows 安装包和升级流程。

## 每次任务的收尾要求

- [ ] 更新本文件相关复选框。
- [ ] 说明改了什么文件。
- [ ] 说明跑了哪些检查。
- [ ] 如果没跑检查，说明原因。
