# 桌面应用架构与目录边界

## 总体形状
SurveyController 是单仓 Windows 桌面应用。启动入口在 [SurveyController.py](/abs/path/D:/Projects/SurveyController/SurveyController.py:1)，真正的启动链在 [software/app/main.py](/abs/path/D:/Projects/SurveyController/software/app/main.py:1)：

- 先配置 Qt 元数据
- 再创建用户目录
- 再启用故障日志和统一日志
- 然后预热 HTTP 客户端
- 最后创建主窗口

这种顺序别乱改。路径、日志和 UI 生命周期互相咬着。

## 顶层目录怎么分
- `software/app/`
  启动、路径、QSettings、应用级配置和运行时元数据。
- `software/core/`
  核心业务、执行配置、题目规则、心理测量、运行时状态。
- `software/io/`
  配置文件、二维码、表格、报告等文件 I/O。
- `software/logging/`
  日志接管、缓冲、落盘、动作日志。
- `software/network/`
  HTTP 客户端、代理策略、会话策略、结果上报。
- `software/providers/`
  多平台公共合同、统一入口、provider 归一化逻辑。
- `software/system/`
  安全存储、电源管理、注册表之类系统能力封装。
- `software/ui/`
  PySide6 / QFluentWidgets 页面、控制器、窗口分块、运行时联动。
- `software/update/`
  Velopack 更新链路和更新探针。
- `wjx/`、`tencent/`、`credamo/`
  各平台专属解析、答题构造、HTTP 提交实现。
- `CI/`
  检查脚本、单测、live tests、发布/更新回归工具。

参考文档：
- [AGENTS.md](/abs/path/D:/Projects/SurveyController/AGENTS.md:1)
- [CONTRIBUTING.md](/abs/path/D:/Projects/SurveyController/CONTRIBUTING.md:1)

## 统一入口和平台边界
平台接入统一走 [software/providers/registry.py](/abs/path/D:/Projects/SurveyController/software/providers/registry.py:1)。这里把：

- 问卷解析
- HTTP 提交
- 旧浏览器填答兜底报错

都挂到同一套 adapter 合同上。

规则：
- 新平台能力先落到对应平台目录，再从 `registry.py` 接入。
- 不要让 UI、engine 或别的模块直接 import 某个平台的私有实现来绕过合同。
- 不要在公共层偷偷恢复浏览器兜底。当前实现明确抛错，说明这是硬约束，不是临时方案。

## 常见改动应该放哪
- 改题型解析、平台字段归一化：`wjx/provider/`、`tencent/provider/`、`credamo/provider/`
- 改 provider 合同或跨平台归一化：`software/providers/`
- 改运行引擎、执行状态、运行时准备：`software/core/`、`software/ui/controller/run_controller_parts/`
- 改配置文件格式或迁移：`software/core/config/`、`software/io/config/`、`software/app/`
- 改纯展示页面：`software/ui/pages/` 或 `software/ui/widgets/`
- 改主窗口行为：`software/ui/shell/`
- 改检查命令或质量门禁：`CI/python_ci.py`、`CI/python_checks/`

## 反模式
- 把新功能塞进不相干文件，只因为“这里已经很大了，顺手”。
- 让 `software/ui/` 直接持有平台私有解析细节。
- 在 `software/app/runtime_paths.py` 上加用户写入逻辑。
- 在公共层写只适用于某一个 provider 的临时分支，然后没人知道它藏在哪。
