# 贡献指南

开始前请先阅读 [行为准则](CODE_OF_CONDUCT.md)。

本分支以 Go+Wails 重构为主线。旧 Python 运行链路已移除，`software/ui/` 只保留为界面参考。

## 开发环境

需要准备：

- Windows 10/11
- Go 1.26 或更新版本
- Git
- Wails v3（只在开发 Wails 应用壳时需要）

## 常用命令

根目录已提供 `go.work`。

```bash
go test ./go/proxycore/... ./go/surveycore/...
```

分别检查模块：

```bash
cd go/proxycore
go test ./...

cd ../surveycore
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
| 代理核心 | `go/proxycore/` |
| 问卷核心和公开门面 API | `go/surveycore/` |
| Credamo Go 实现 | `go/surveycore/credamo/` |
| 手动验证命令 | `go/surveycore/cmd/` |
| 旧 UI 参考 | `software/ui/` |
| 旧应用资源参考 | `software/assets/` |
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

提交信息使用中文 Conventional Commits：

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
├── go/                      # Go 核心模块和后续 Wails 模块
│   ├── proxycore/
│   └── surveycore/
├── software/                # 旧 UI 与资源参考
│   ├── assets/
│   └── ui/
├── go.work
├── PLAN.md
└── README.md
```
