---
name: app-settings-migration
description: 面向 SurveyController 仓库的设置、路径与配置迁移技能。用于修改 `software/app/`、`software/io/config/`、`software/core/config/` 里的 QSettings 键、用户目录、配置文件路径、序列化字段、默认值和兼容策略，避免升级后读错配置、写错目录或把旧配置直接干爆。适合做预防性演进，不适合只修表面报错。
---

# App Settings Migration

这个 skill 处理“配置怎么演进才不炸”。
重点是路径、QSettings、配置字段、默认值和 UI 同步一起看，不让升级把用户数据搞烂。配置 JSON 不使用 schema 版本字段、兼容检查或迁移链；旧 JSON 字段仍由现有归一化逻辑处理。

## must_read

- `software/app/settings_store.py`
- `software/app/user_paths.py`
- `software/app/runtime_paths.py`
- `software/io/config/store.py`
- `software/core/config/codec.py`
- `software/core/config/schema.py`
- 涉及配置展示时再读对应 UI 页面

## workflow

1. 先分清这次改的是哪层。
   - QSettings 键和值：`software/app/settings_store.py`
   - 用户目录、日志、缓存、更新目录：`software/app/user_paths.py`
   - 安装目录和只读资源目录：`software/app/runtime_paths.py`
   - 配置文件读写：`software/io/config/store.py`
   - 配置模型、字段归一化、序列化：`software/core/config/schema.py`、`software/core/config/codec.py`
2. 先判断是不是兼容改动。
   - 只加默认值
   - 改字段语义
   - 改路径来源
   - 改 JSON 字段或字段语义
   - 删旧字段
3. 优先保旧配置可读。
   - 新字段先给默认值
   - 旧字段要删时，先决定是迁移、忽略还是明确报错
   - 不准偷偷把用户配置写到安装目录
4. UI 和存储一起改。
   - 设置页显示
   - 运行时 config snapshot
   - 保存和加载
   - 报错文案
5. 改完后补回归。

## hard_rules

1. 用户可写数据只能走 `software/app/user_paths.py`。
2. `software/app/runtime_paths.py` 只表示安装目录和只读资源目录，别拿去存配置。
3. `CONFIG_DIRECTORY_SETTING_KEY` 这类 QSettings 键改名时，要同步考虑旧值读取和页面回填；AI API Key 按下一条规则处理，不读取旧值。
4. 不要添加配置 schema 版本常量、JSON 版本字段、版本兼容检查或迁移链；保持既有 JSON 字段归一化和旧配置读取能力。
5. AI API Key 只保存在当前进程。历史 QSettings 密钥值必须忽略，不迁移也不清理；常规设置保存不得写入密钥。仅用户主动导出配置时允许将密钥明文写入 JSON，默认序列化必须脱敏。
6. 不要把密钥写进仓库、日志或测试样本。

## migration_patterns

常见改法：

- 新增配置字段：
  - 在 `RuntimeConfig` 增字段
  - 在 `normalize_runtime_config_payload()` 给默认值
  - 在 `serialize_runtime_config()` 和相关 UI 同步路径确认能 round-trip
- 调整字段范围或格式：
  - 在 codec 里做归一化
  - 保持旧输入还能落到新格式
  - 补边界测试
- 改默认配置目录：
  - 改 `user_paths.py`
  - 检查设置页是否还允许自定义目录
  - 检查 `ensure_user_data_directories()` 和打开目录行为
- 删除旧字段：
  - 检查旧 JSON 输入是否仍由字段归一化和默认值处理
  - 只在明确的产品行为要求下改变字段读取语义，不添加 schema 版本机制
  - AI API Key 的历史 QSettings 值按 hard_rules 忽略，不迁移、不清理

## project_conventions

- 默认配置文件路径来自 `get_default_runtime_config_path()`。
- 当前配置文件允许带 JSON 注释，清洗逻辑在 `software/io/config/store.py::_strip_json_comments()`。
- 配置读取不做 schema 版本检查；严格模式下，JSON 无法解析、顶层不是对象或反序列化失败时会抛 `ValueError`。
- AI 配置保存在进程内会话；QSettings 不持久化 API Key，配置默认序列化也会省略密钥。
- QSettings 隔离测试依赖 `SURVEYCONTROLLER_QSETTINGS_FILE`，`CI/unit_tests/conftest.py` 已经有夹具。
- 配置快照和序列化会影响 UI、执行引擎、反填和平台 provider，别只改一头。

## common_commands

代码改动先由远端 CI 验证；仅在 CI 失败后，按仓库规则做最小本地复现。以下命令用于只读定位：

```bash
rg "QSettings|ai_api_key|config_directory|user_paths|load_config|save_config" software CI
```

## validation_checklist

- 是否先分清了 QSettings、用户路径、配置字段和序列化这几层。
- 是否没有把可写数据放进安装目录。
- 新增字段是否有默认值，旧配置是否还能读。
- 是否保留旧 JSON 字段归一化，并避免重新引入 schema 版本机制。
- 是否忽略历史 QSettings API Key，且仅在主动导出时写出明文密钥。
- 设置页展示、保存、重新加载是否一致。
- 是否补了 `test_config_codec.py`、`test_config_store.py` 或相关 `qtbot` 测试。
- 涉及启动或页面装配时，相关远端 CI 是否通过；只有 CI 失败后才按仓库规则做最小本地复现。
