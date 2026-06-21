<div align="center">
  <img src="assets/icon.png" alt="SurveyController" width="120" height="120" />
  <h1>SurveyController</h1>
</div>

> 本分支是 Go+Wails 重构分支。旧 Python 运行链路已移除。

## 当前状态

当前仓库以 `go/` 为主。

- `go/proxycore`：代理核心，包含代理租约、TTL、脱敏、并发池、官方随机 IP session。
- `go/desktopui`：Wails v3 桌面壳，前端使用 Vue 3、TypeScript、TailwindCSS。
- `go/surveycore`：问卷核心，包含公开门面 API、通用模型、Credamo 解析与提交闭环。
- `software/ui`：旧 PySide6/QFluentWidgets 界面参考，不再作为可运行入口。
- `software/assets`、`assets`：旧 UI 和 README 资源参考。

旧 Python 核心、uv、Python CI、三家平台 Python 实现已从本分支移除。

## 常用命令

```bash
go test ./go/proxycore/... ./go/surveycore/...
```

也可以分别进入模块运行：

```bash
cd go/proxycore
go test ./...

cd ../surveycore
go test ./...
```

## 目录结构

```text
.
├── go/
│   ├── proxycore/           # Go 代理核心
│   ├── desktopui/           # Wails 桌面 UI 壳
│   └── surveycore/          # Go 问卷核心
├── software/
│   ├── assets/              # 旧应用资源参考
│   └── ui/                  # 旧 PySide UI 参考
├── assets/                  # README、图标、图片资源
├── go.work                  # Go workspace
└── PLAN.md                  # Go+Wails 迁移计划
```

## 开发边界

- 新核心能力放进 `go/`。
- Wails 应用壳后续单独建模块，不塞进核心库。
- `go/proxycore` 不读取 `configs/`，不接 UI。
- `go/surveycore` 根包只放公开 API、通用模型和编排。
- 平台实现放各自子包，例如 `go/surveycore/credamo/`。
- 普通单测不访问真实问卷、真实账号、真实付费代理。

## 许可

见 [LICENSE](LICENSE)。
