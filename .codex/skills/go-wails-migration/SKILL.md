---
name: go-wails-migration
description: 面向 SurveyController 当前 refactor/go 分支的 Go+Wails 桌面端迁移技能。用于新增或迁移 Go 核心模块、Wails 应用壳、前端绑定、桌面端配置/路径、打包发布链路、Python 到 Go 的模块替换和迁移测试。适合处理从 PySide6/Python 逐步迁到 Go+Wails 的架构设计、目录拆分、文件职责审查、接口对齐、测试策略和兼容边界。
---

# Go Wails Migration

## overview

这个 skill 处理 SurveyController 从 Python/PySide6 到 Go+Wails 的迁移。
目标是小步替换核心能力，保留可运行基线，避免把旧屎山原样搬进 Go。

## migration_rules

1. 先确认当前基线。
   必读：
   - `AGENTS.md`
   - `PLAN.md`
   - `CONTRIBUTING.md`
   - 目标 Python 模块和对应测试
   - 相关 `go/` 模块和 Go 测试
2. Go 代码放在 `go/` 下。
   - 纯核心库优先独立 Go module，例如 `go/proxycore`。
   - Wails 应用壳后续单独建模块，不要把 UI 壳塞进核心库。
   - 核心库不读取 `configs/`，不碰 UI，不访问真实外网测试。
3. 迁移顺序保持窄边界。
   - 先迁移纯计算、解析、网络策略、并发池。
   - 再做服务接口和 Wails 绑定。
   - 最后接桌面 UI、设置、打包和更新。
4. Go+Wails 目标仍保持纯 HTTP 提交链路。
   - 不恢复 Playwright、Selenium 或浏览器自动化兜底。
   - Wails WebView 只做桌面 UI，不承担问卷提交自动化。
5. 不要照搬 Python 全局状态。
   - QSettings、安全存储、UI 弹窗、线程 stop_signal 这类耦合要重新设计接口。
   - Go 核心优先用显式配置、context、接口和单测 fake。
6. 平台边界继续隔离。
   - 问卷星、腾讯问卷、Credamo 的解析和提交逻辑不能混进通用核心。
   - 公共类型和接口必须稳定后再被 Wails 服务层暴露。

## structure_rules

- 新增 Go 代码前先确定职责桶，再决定文件名。
  - `lease.go`：代理租约、地址归一化、TTL、脱敏。
  - `pool.go`：池状态、占用、成功用过、冷却、合并和分配。
  - `fetcher.go`：通用 fetcher 接口和适配函数。
  - `parser.go`：自定义代理 API payload 解析。
  - `quota.go`：额度归一化、额度快照、数值解析。
  - `official_session.go`：官方随机 IP session、设备 ID、持久化接口。
  - `official_client.go`：官方后端 HTTP 方法和请求编排。
  - `official_parse.go`：官方后端响应解析、错误解析、DTO 到 lease 转换。
  - `official_fetcher.go`：官方 client 到 `Fetcher` 的适配。
- 一个文件只承担一个主要职责。
  - 不把 HTTP 请求、响应解析、状态持久化、池调度、UI/Wails 编排混在同一文件。
  - 文件接近 250 行或出现三类以上职责时，先拆文件再继续加功能。
  - 测试文件可以按被测文件对应拆分，避免一个巨型测试文件覆盖所有行为。
- Go 子目录按 package 边界建，不按 Python 文件夹习惯建。
  - 原型期优先保持 `go/proxycore` 单 package，减少公开 API 抖动。
  - 只有当某块能独立被复用或需要隐藏实现细节时，才建子包或 `internal/`。
  - Wails 应用壳必须单独成模块，不能塞进 `go/proxycore`。
- 每次结构调整后检查公开接口。
  - 保留既有导出类型和函数，除非调用方和测试同步更新。
  - 文件移动后立刻跑对应 `go test ./...`。
  - 完成 `PLAN.md` 事项才勾选复选框，不用复选框粉饰半成品。

## wails_rules

- 使用 Wails v3 命令时以官方文档为准：`wails3 dev`、`wails3 build`、`wails3 generate bindings`。
- 生成的 frontend bindings 不手写；改 Go 服务后重新生成。
- Wails 服务方法只做应用层编排，不塞具体平台解析细节。
- 前端不要写解释迁移状态的界面文案，除非用户明确要求。

## validation

- Go 核心模块：在对应模块目录跑 `go test ./...`。
- 新增 Wails 服务或绑定：跑 `wails3 generate bindings`，再跑对应 Go 测试。
- 影响 Python 基线：跑 `uv run python CI/python_ci.py`。
- 涉及启动、UI、路径、配置迁移、发布链路：跑 `uv run python CI/python_ci.py --full`，并补对应 Go/Wails 检查。
- 单元测试不访问真实问卷、真实账号、真实付费代理。
- 完成 `PLAN.md` 中的事项后，同步把对应复选框改成 `[x]`。

## common_commands

```bash
cd go/proxycore
go test ./...

wails3 dev
wails3 build
wails3 generate bindings

uv run python CI/python_ci.py
uv run python CI/python_ci.py --full
```
