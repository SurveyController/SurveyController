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
├── .editorconfig
├── .github/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/
├── .gitignore
├── AGENTS.md
├── assets/
├── build/
│   └── SurveyController/
├── CI/
│   ├── live_tests/
│   │   └── test_survey_parsers.py
│   ├── python_checks/
│   │   ├── common.py
│   │   ├── compile_check.py
│   │   ├── import_check.py
│   │   ├── pyright_check.py
│   │   ├── ruff_check.py
│   │   ├── unit_test_check.py
│   │   └── window_smoke_check.py
│   ├── python_ci.py
│   ├── unit_tests/
│   │   ├── app/
│   │   ├── engine/
│   │   ├── providers/
│   │   ├── psychometrics/
│   │   └── questions/
│   └── worker/
│       ├── src/
│       │   ├── constants.js
│       │   ├── github.js
│       │   ├── index.js
│       │   ├── message.js
│       │   ├── request.js
│       │   ├── response.js
│       │   └── telegram.js
│       └── wrangler.toml
├── CLAUDE.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── credamo/
│   └── provider/
├── desktop.ini
├── icon.ico
├── LICENSE
├── pytest.ini
├── README.md
├── requirements.txt
├── rthook_pyside6.py
├── Setup/
│   ├── LICENSE/
│   ├── 使用教程.docx
│   ├── 使用教程.pdf
│   ├── bg.bmp
│   ├── ChineseSimplified.isl
│   ├── icon.bmp
│   └── sign.pfx
├── SurveyController.py
├── SurveyController.spec
├── software/
│   ├── app/
│   │   ├── browser_probe.py
│   │   ├── config.py
│   │   ├── legacy_data_migration.py
│   │   ├── main.py
│   │   ├── runtime_paths.py
│   │   ├── settings_store.py
│   │   ├── user_paths.py
│   │   └── version.py
│   ├── assets/
│   │   ├── area.txt
│   │   ├── area_codes_2022.json
│   │   └── legal/
│   │       ├── privacy_statement.txt
│   │       └── service_terms.txt
│   ├── core/
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
│   │   └── ai/
│   ├── io/
│   │   ├── config/
│   │   ├── markdown/
│   │   ├── qr/
│   │   ├── reports/
│   │   └── spreadsheets/
│   ├── logging/
│   ├── network/
│   │   ├── browser/
│   │   ├── http/
│   │   └── proxy/
│   ├── providers/
│   ├── system/
│   ├── ui/
│   │   ├── controller/
│   │   ├── dialogs/
│   │   ├── helpers/
│   │   ├── pages/
│   │   │   └── workbench/
│   │   │       ├── dashboard/
│   │   │       ├── log_panel/
│   │   │       ├── question_editor/
│   │   │       ├── reverse_fill/
│   │   │       ├── runtime_panel/
│   │   │       ├── shared/
│   │   │       └── strategy/
│   │   ├── shell/
│   │   ├── widgets/
│   │   ├── workers/
│   │   └── theme.json
│   └── update/
├── tencent/
│   └── provider/
│       ├── navigation.py
│       ├── parser.py
│       ├── runtime.py
│       ├── runtime_answerers.py
│       ├── runtime_flow.py
│       ├── runtime_interactions.py
│       └── submission.py
└── wjx/
   ├── assets/
   ├── cli/
   ├── core/
   ├── modes/
   ├── network/
   ├── provider/
   │   ├── detection.py
   │   ├── html_parser.py
   │   ├── navigation.py
   │   ├── parser.py
   │   ├── runtime.py
   │   ├── runtime_dispatch.py
   │   ├── submission.py
   │   ├── submission_pages.py
   │   ├── submission_proxy.py
   │   ├── _submission_core.py
   │   └── questions/
   │       ├── dropdown.py
   │       ├── matrix.py
   │       ├── multiple.py
   │       ├── multiple_dom.py
   │       ├── multiple_limits.py
   │       ├── multiple_rules.py
   │       ├── reorder.py
   │       ├── scale.py
   │       ├── score.py
   │       ├── single.py
   │       ├── slider.py
   │       └── text.py
   ├── ui/
   └── utils/

</details>

## 打包与更新

- Windows 安装版现在使用 `PyInstaller + Velopack`。
- `SurveyController.spec` 继续输出 `dist/lib` 目录包，不改 `onefile`。
- GitHub Actions 会调用 `vpk pack` 生成：
  - `SurveyController_<tag>_setup.exe`
  - `releases.stable.json`
  - `*-full.nupkg`
  - `*-delta.nupkg`
- 应用内更新主 feed 固定为 `https://dl.hungrym0.top/surveycontroller/win/stable/`。
- GitHub Releases 仍会同步这些资产，但客户端不再把 GitHub 当更新源。

## 用户数据目录

- 仓库里的 `configs/`、`logs/` 现在只保留为源码环境/历史结构参考，不再是安装版运行时写入位置。
- 安装版运行时改为写入：
  - `%AppData%\SurveyController\config.json`
  - `%AppData%\SurveyController\configs`
  - `%LocalAppData%\SurveyController\logs`
  - `%LocalAppData%\SurveyController\cache`
- `software/app/runtime_paths.py` 现在只负责“安装目录/只读资源目录”，别再把它当可写目录用。
