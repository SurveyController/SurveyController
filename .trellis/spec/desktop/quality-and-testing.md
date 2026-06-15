# 质量门禁与测试分层

## 默认检查命令
项目文档已经把主命令定了：

- 快速检查：`uv run python CI/python_ci.py`
- 完整检查：`uv run python CI/python_ci.py --full`
- 单测：`uv run pytest CI/unit_tests`

入口实现见 [CI/python_ci.py](/abs/path/D:/Projects/SurveyController/CI/python_ci.py:1)。

默认 quick 模式会跑：
- compile checks
- Ruff
- type ignore checks
- unicode escape checks
- Pyright
- `CI/unit_tests`

`--full` 额外跑：
- module import checks
- main window smoke check

## 什么改动该补什么测试
文档和现有测试目录已经形成稳定分层：

- 配置、路径、迁移：`CI/unit_tests/app/`
- provider 解析、提交流程：`CI/unit_tests/providers/`
- 题型归一化、规则：`CI/unit_tests/questions/`
- 引擎、运行时准备、异步循环：`CI/unit_tests/engine/`
- 代理、网络策略：`CI/unit_tests/test_proxy_*`、`test_session_policy.py` 等
- UI 页面和窗口行为：`CI/unit_tests/app/` 下对应页面/窗口测试

参考目录：
- [CI/unit_tests](/abs/path/D:/Projects/SurveyController/CI/unit_tests:1)

## 测试隔离约定
[CI/unit_tests/conftest.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/conftest.py:1) 已经统一做了这些隔离：
- QSettings 指向临时 ini
- 系统剪贴板替换成内存实现
- 一批常用 mock/factory fixture

规则：
- 新测试优先复用这些 fixture，别重复手造一套。
- 不要让单测直接污染真实系统设置、真实剪贴板、真实用户目录。

## live test 边界
`CI/live_tests/` 只放明确需要真实环境的回归。

规则：
- 普通单测不访问真实问卷、真实账号、真实付费代理。
- 需要真实问卷或发布链路的，进 live tests。
- 改纯展示 UI 时，可以不强制补单测，但至少要考虑启动或冒烟验证。

## 提交前应该检查什么
- 改配置/路径：至少跑快速检查，并补 `CI/unit_tests/app/`
- 改启动链路、UI、HTTP 提交链路、路径迁移：优先跑 `--full`
- 改 provider 合同或平台解析：补 `providers/` 或 `questions/` 层测试
- 改日志：至少看 `test_log_utils.py`、`test_action_logger.py` 一类现有测试是否需要补

## 常见反模式
- 只改代码不补对应层测试
- 在 unit test 里打真实网络、真实付费资源
- 新增临时覆盖率文件、缓存目录却不清理
- 看到 quick 绿了就当一切没问题，明明改的是启动链路还不跑 `--full`
