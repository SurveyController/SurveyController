# 贡献指南

开始前请先阅读 [行为准则](CODE_OF_CONDUCT.md)。

本分支以 Go+Wails 重构为主线。旧 Python 运行链路已移除。

## 开发环境

需要准备：

- Windows 10/11
- Go 1.26 或更新版本
- Git
- Wails v3（只在开发 Wails 应用壳时需要）
- Node.js 与 npm（只在开发 Wails 前端时需要）

当前发布只面向 Windows 安装包。
macOS 只保留源码启动和开发验证。

## 常用命令

根目录已提供 `go.work`。

```bash
go test ./packages/proxycore/... ./packages/surveycore/...
```

分别检查模块：

```bash
cd packages/proxycore
go test ./...

cd ../../packages/surveycore
go test ./...
```

Wails 模块建好后再使用：

```bash
wails3 dev
wails3 build
wails3 generate bindings
```

## 目录边界

| 目标 | 目录 |
| --- | --- |
| 代理核心 | `packages/proxycore/` |
| Go 原生桌面 UI 前端壳 | `apps/desktop/` |
| 问卷核心和公开门面 API | `packages/surveycore/` |
| Credamo Go 实现 | `packages/surveycore/credamo/` |
| 腾讯问卷 Go 实现 | `packages/surveycore/tencent/` |
| 问卷星 Go 实现 | `packages/surveycore/wjx/` |
| 手动验证命令 | `packages/surveycore/cmd/` |
| README 和图片资源 | `assets/` |

不要把平台实现塞进通用根包。
不要把 Wails 服务、任务持久化、代理池混进 `surveycore`。
不要把 UI 状态和弹窗逻辑搬进 Go 核心库。

## 代码要求

- 一个文件只承担一个主要职责。
- 文件接近 250 行或出现三类以上职责时，先拆文件。
- Go 核心使用显式配置、`context.Context`、接口和 fake 测试。
- 普通单测不访问真实问卷、真实账号、真实付费代理。
- 真实链路验证必须显式环境变量开启，并放到独立 live/integration 流程。
- Wails WebView 只做桌面 UI，不承担问卷提交自动化。

## PR 要求

PR 描述写清楚：

- 改了什么。
- 影响哪些模块。
- 跑过哪些检查。
- 是否有用户可见变化。

提交信息使遵循 Conventional Commits 规范：

```text
feat: 增加 Credamo 提交事件
fix: 修复代理租约 TTL 判断
refactor: 拆分 surveycore 配置生成
docs: 更新 Go 迁移说明
```

## 仓库结构

```text
.
├── .github/                 # GitHub Actions
├── assets/                  # README、图标、图片资源
├── apps/                    # 应用入口
│   └── desktop/
├── packages/                # 可复用核心包
│   ├── proxycore/
│   └── surveycore/
├── go.work
└── README.md
```
