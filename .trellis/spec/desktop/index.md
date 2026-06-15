# SurveyController Desktop 规范

这个 layer 描述 SurveyController 当前仓库的真实开发约束。它不是通用 Python 后端模板，也不是 Web 项目约定。

## 何时读取
- 改 `software/`、`wjx/`、`tencent/`、`credamo/`、`CI/` 任一目录前
- 设计新功能但拿不准应该放哪一层时
- 准备补测试、改配置、改提交链路、改日志时

## 预开发检查
- [ ] 先确认改动属于哪个目录，不往不相干文件里塞代码
- [ ] 先读相关源码和对应测试，再动手
- [ ] 涉及路径、配置、日志、纯 HTTP 提交链路时，先读对应专题文件
- [ ] 如果需求会改变目录职责、运行时约束或测试边界，先更新 spec 再写代码

## 文件导航
- [desktop-architecture.md](./desktop-architecture.md)
  说明应用入口、主目录分层、平台适配边界和常见落点。
- [paths-and-config.md](./paths-and-config.md)
  说明哪些目录可写、配置怎么落盘、QSettings 只该存什么。
- [provider-http-pipeline.md](./provider-http-pipeline.md)
  说明 provider 合同、平台解析/提交链路、纯 HTTP 约束。
- [error-handling.md](./error-handling.md)
  说明运行前校验、provider/runtime 异常、UI 展示与日志分离。
- [logging-guidelines.md](./logging-guidelines.md)
  说明统一日志入口、去重、脱敏、噪声过滤和会话日志持久化。
- [quality-and-testing.md](./quality-and-testing.md)
  说明检查命令、单测分层、live test 边界和常见验证要求。

## 质量检查
- [ ] 新代码没有绕开 `software/providers/registry.py` 恢复浏览器兜底
- [ ] 用户数据仍写入 `%AppData%` / `%LocalAppData%` 对应目录
- [ ] 日志没有泄露令牌、Authorization 或代理敏感信息
- [ ] 题目解析、provider 合同、配置读写改动都补到对应测试层
- [ ] 运行 `CI/python_ci.py` 或更高等级检查前，没有把临时产物塞进仓库
