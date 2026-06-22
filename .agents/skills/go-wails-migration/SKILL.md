---
name: go-wails-migration
description: 面向 SurveyController 当前 Go+Wails 重构分支的桌面端迁移技能。用于修改 packages/proxycore、packages/surveycore、apps/desktop、Wails 服务、前端绑定、桌面配置路径、构建发布链路和 Go 测试策略。适合处理 Go 核心模块、Wails 桌面壳、Windows/Linux/macOS 原生构建、目录边界和迁移兼容问题；不用于恢复 Python、浏览器自动化、Docker、server mode 或 iOS 适配。
---

# Go Wails Migration

## overview

这个 skill 处理 SurveyController 的 Go+Wails 桌面端迁移和维护。
当前仓库已经移除旧 Python 运行链路，核心代码在 `packages/`，桌面壳在 `apps/desktop/`。
目标是保持纯 HTTP 问卷提交、清晰包边界和可测试基线。

## migration_rules

1. 先确认当前基线。
   必读：
   - `AGENTS.md`
   - `CONTRIBUTING.md`
   - 目标模块和对应 Go 测试
   - `apps/desktop/Taskfile.yml` 与 `apps/desktop/build/` 中相关平台 Taskfile
2. Go 代码按现有模块放置。
   - 代理核心放 `packages/proxycore/`。
   - 问卷核心和平台实现放 `packages/surveycore/`。
   - Wails 桌面壳放 `apps/desktop/`。
   - 核心库不读取 `configs/`，不碰 UI，不访问真实外网测试。
3. 迁移顺序保持窄边界。
   - 先迁移纯计算、解析、网络策略、并发池。
   - 再做服务接口和 Wails 绑定。
   - 最后接桌面 UI、设置、打包和更新。
4. Go+Wails 目标仍保持纯 HTTP 提交链路。
   - 不恢复 Playwright、Selenium 或浏览器自动化兜底。
   - Wails WebView 只做桌面 UI，不承担问卷提交自动化。
5. 不恢复已移除链路。
   - 不恢复 Python、uv、Python CI、`software/` 或顶层平台 Python 包。
   - 不恢复 Docker 构建、server mode、iOS 适配。
   - macOS 只保留原生 darwin 构建和 `.app` 打包，不做 Docker 跨编译。
6. 不照搬旧全局状态。
   - QSettings、安全存储、UI 弹窗、线程 stop_signal 这类耦合要重新设计接口。
   - Go 核心优先用显式配置、`context.Context`、接口和 fake 测试。
7. 平台边界继续隔离。
   - 问卷星、腾讯问卷、Credamo 的解析和提交逻辑不能混进通用核心。
   - 公共类型和接口必须稳定后再被 Wails 服务层暴露。

## structure_rules

- 新增 Go 代码前先确定职责桶，再决定文件名。
  - `packages/proxycore/`：代理租约、fetcher、TTL、代理池、官方随机 IP session。
  - `packages/surveycore/`：公开 API、通用模型、编排、配置生成。
  - `packages/surveycore/{credamo,tencent,wjx}/`：平台实现。
  - `packages/surveycore/cmd/`：手动验证命令。
  - `apps/desktop/`：Wails 服务、桌面配置路径、前端绑定、桌面 UI 壳。
- 一个文件只承担一个主要职责。
  - 不把 HTTP 请求、响应解析、状态持久化、池调度、UI/Wails 编排混在同一文件。
  - 文件接近 250 行或出现三类以上职责时，先拆文件再继续加功能。
  - 测试文件可以按被测文件对应拆分，避免一个巨型测试文件覆盖所有行为。
- Go 子目录按 package 边界建。
  - 优先沿用现有 `packages/proxycore`、`packages/surveycore`、`apps/desktop` 边界。
  - 只有当某块能独立被复用或需要隐藏实现细节时，才建子包或 `internal/`。
  - Wails 应用壳不能塞进核心库。
- 每次结构调整后检查公开接口。
  - 保留既有导出类型和函数，除非调用方和测试同步更新。
  - 文件移动后立刻跑对应 `go test ./...`。

## wails_rules

- 使用 Wails v3 命令时以官方文档为准：`wails3 dev`、`wails3 build`、`wails3 generate bindings`。
- 生成的 frontend bindings 不手写；改 Go 服务后重新生成。
- Wails 服务方法只做应用层编排，不塞具体平台解析细节。
- 前端不要写解释迁移状态的界面文案，除非用户明确要求。
- 构建平台边界：
  - 保留 Windows、Linux、macOS 原生构建。
  - 保留 Android 现有模板，除非用户明确要求再删。
  - 禁止恢复 Docker 跨编译、server mode、iOS 目录或 iOS 任务。
  - Windows stable feed 仍使用 `https://dl.hungrym0.com/surveycontroller/win/stable/`。

## validation

- Go 核心模块：跑 `go test ./packages/proxycore/... ./packages/surveycore/...`。
- Wails 桌面模块：跑 `cd apps/desktop; go test ./...`。
- 新增或修改 Wails 服务绑定：跑 `cd apps/desktop; wails3 generate bindings`，再跑桌面模块测试。
- 修改 Taskfile 或构建入口：跑 `cd apps/desktop; wails3 task --list`，确认没有恢复 Docker、server mode、iOS 入口。
- 单元测试不访问真实问卷、真实账号、真实付费代理。

## common_commands

```bash
go test ./packages/proxycore/... ./packages/surveycore/...

cd apps/desktop
go test ./...
wails3 task --list
wails3 dev
wails3 build
wails3 generate bindings
```
