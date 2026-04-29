# 贡献指南

感谢愿意改进本项目！在开始之前，请先阅读 [行为准则](CODE_OF_CONDUCT.md)。

## 快速开始
- **交流**：首选 GitHub Issues，或加入 QQ 群（见 README）。
- **参考**：服务接口信息统一改为在线查阅，优先看 API 文档：https://api-wjx.hungrym0.top/api/document
- **环境**：Python 3.11+，Windows 10/11。执行 `pip install -r requirements.txt` 安装依赖。

<details>
<summary><b>📂 点击查看项目目录结构</b></summary>

```markdown
仓库根目录
├── .github/
│   ├── workflows/
│   │   ├── python-ci.yml
│   │   ├── release-to-r2.yml
│   │   └── deploy-worker.yml
│   └── ISSUE_TEMPLATE/
├── README.md
├── LICENSE
├── requirements.txt
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── SurveyController.py
├── SurveyController.spec
├── rthook_pyside6.py
├── icon.ico
├── CI/
│   ├── __init__.py
│   ├── python_ci.py
│   ├── live_tests/
│   │   ├── __init__.py
│   │   └── test_survey_parsers.py
│   ├── python_checks/
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── compile_check.py
│   │   ├── import_check.py
│   │   ├── pyright_check.py
│   │   ├── ruff_check.py
│   │   ├── unit_test_check.py
│   │   └── window_smoke_check.py
│   ├── unit_tests/
│   │   ├── __init__.py
│   │   ├── app/
│   │   │   └── test_browser_probe.py
│   │   ├── engine/
│   │   │   ├── test_browser_session_service.py
│   │   │   ├── test_cleanup.py
│   │   │   ├── test_provider_common.py
│   │   │   ├── test_runtime_init_gate.py
│   │   │   ├── test_runtime_control.py
│   │   │   └── test_submission_service.py
│   │   ├── providers/
│   │   │   ├── test_common.py
│   │   │   ├── test_credamo_parser.py
│   │   │   ├── test_credamo_runtime.py
│   │   │   └── test_survey_cache.py
│   │   ├── psychometrics/
│   │   └── questions/
│   │       └── test_validation.py
│   └── worker/
│       ├── wrangler.toml
│       └── src/
├── logs/
├── Setup/
│   ├── InnoSetup.iss
│   └── LICENSE/
│       ├── after_install.txt
│       └── before_install.txt
├── assets/
├── software/
│   ├── __init__.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── browser_probe.py
│   │   ├── config.py
│   │   ├── main.py
│   │   ├── runtime_paths.py
│   │   ├── settings_store.py
│   │   └── version.py
│   ├── assets/
│   │   ├── __init__.py
│   │   ├── area_codes_2022.json
│   │   ├── area.txt
│   │   └── legal/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── ai/
│   │   ├── config/
│   │   ├── engine/
│   │   ├── modes/
│   │   ├── persona/
│   │   ├── psychometrics/
│   │   ├── questions/
│   │   ├── reverse_fill/
│   │   └── task/
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── ai/
│   ├── io/
│   │   ├── __init__.py
│   │   ├── config/
│   │   ├── markdown/
│   │   ├── qr/
│   │   ├── reports/
│   │   └── spreadsheets/
│   ├── logging/
│   │   ├── __init__.py
│   │   ├── action_logger.py
│   │   └── log_utils.py
│   ├── network/
│   │   ├── __init__.py
│   │   ├── session_policy.py
│   │   ├── browser/
│   │   ├── http/
│   │   └── proxy/
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── contracts.py
│   │   ├── survey_cache.py
│   │   └── registry.py
│   ├── system/
│   │   ├── __init__.py
│   │   ├── power_management.py
│   │   ├── registry_manager.py
│   │   └── secure_store.py
│   ├── ui/
│   │   ├── theme.json
│   │   ├── controller/
│   │   ├── dialogs/
│   │   ├── helpers/
│   │   ├── pages/
│   │   │   └── workbench/reverse_fill/
│   │   ├── shell/
│   │   ├── widgets/
│   │   └── workers/
│   └── update/
│       ├── __init__.py
│       └── updater.py
├── tencent/
│   ├── __init__.py
│   └── provider/
│       ├── __init__.py
│       ├── navigation.py
│       ├── parser.py
│       ├── runtime.py
│       ├── runtime_answerers.py
│       ├── runtime_flow.py
│       ├── runtime_interactions.py
│       └── submission.py
├── credamo/
│   ├── __init__.py
│   └── provider/
│       ├── __init__.py
│       ├── parser.py
│       ├── runtime.py
│       └── submission.py
└── wjx/
   ├── __init__.py
   ├── assets/
   ├── cli/
   ├── core/
   ├── modes/
   ├── network/
   ├── provider/
   │   ├── __init__.py
   │   ├── _submission_core.py
   │   ├── detection.py
   │   ├── html_parser.py
   │   ├── html_parser_choice.py
   │   ├── html_parser_common.py
   │   ├── html_parser_matrix.py
   │   ├── html_parser_rules.py
   │   ├── navigation.py
   │   ├── parser.py
   │   ├── questions/
   │   ├── runtime.py
   │   └── submission.py
   ├── ui/
   └── utils/
```

</details>

## PR 流程
1. **Fork** 本仓库并创建特性分支。
2. **开发**：
   - 共享代码进入 `software/`。
   - 平台专属逻辑进入对应的 `provider/` 子目录。
   - 保持顶层包（`wjx/`、`tencent/`、`credamo/`）简洁，仅保留包标记；Credamo 见数没有旧共享兼容转发层，权威实现直接在 `credamo/provider/`。
3. **自测**：
   - 打开拉取请求先确保 CI 能够通过检查（`python CI/python_ci.py`）
   - 最少手动跑一次受影响的核心流程，并在 PR 里写清楚结果。
4. **提交**：
   - PR 描述请写明改动目的、测试结果，如果有的话关联相关 Issue。

## 开发规范
- **模块化**：按职责拆分文件，避免“巨型文件”；新功能应放入对应的子目录。
- **UI 组件**：使用 `QfluentWidgets` 原生组件，保持界面风格统一。
- **友好说明**：输出信息应简洁易懂，面向小白用户，避免过度使用专业术语。
- **文档规范**：尽可能少地使用 emoji 表情符号。使用 HTML 标签折叠过长的文本内容，保持文档清晰。

欢迎贡献新的题型支持、平台适配或性能优化，感谢你的支持！
