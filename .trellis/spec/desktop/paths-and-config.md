# 路径与配置规则

## 路径原则
安装目录和用户目录是两套东西，别混。

真实入口：
- 只读运行时路径在 [software/app/runtime_paths.py](/abs/path/D:/Projects/SurveyController/software/app/runtime_paths.py:1)
- 用户可写路径在 [software/app/user_paths.py](/abs/path/D:/Projects/SurveyController/software/app/user_paths.py:1)

`runtime_paths.py` 只处理：
- 程序运行目录
- 打包资源目录
- `assets/` 查找

它不负责用户写入。别往这里塞配置、缓存、日志导出路径。

## 用户可写目录
[software/app/user_paths.py](/abs/path/D:/Projects/SurveyController/software/app/user_paths.py:1) 已把目标目录定死：

- `%AppData%\SurveyController\config.json`
- `%AppData%\SurveyController\configs`
- `%LocalAppData%\SurveyController\logs`
- `%LocalAppData%\SurveyController\cache`
- `%LocalAppData%\SurveyController\updates`

`ensure_user_data_directories()` 会统一创建目录。对应测试在 [CI/unit_tests/app/test_user_paths.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/app/test_user_paths.py:1)。

规则：
- 新增用户文件时，优先复用这些根目录，不要自造顶层散目录。
- 如果需要新的用户子目录，放在 `user_paths.py` 统一定义，再补单测。

## QSettings 只存轻量偏好
QSettings 入口在 [software/app/settings_store.py](/abs/path/D:/Projects/SurveyController/software/app/settings_store.py:1)。

它现在主要做两件事：
- 配置 Qt 的组织名、应用名、域名
- 读写轻量设置，比如配置目录覆盖

规则：
- 不把整份运行配置塞进 QSettings。
- 不把复杂对象序列化到 QSettings 里当数据库用。
- 单测里通过 `SURVEYCONTROLLER_QSETTINGS_FILE` 隔离 QSettings。参考 [CI/unit_tests/conftest.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/conftest.py:1)。

## 配置文件怎么读写
运行配置文件入口在 [software/io/config/store.py](/abs/path/D:/Projects/SurveyController/software/io/config/store.py:1)。

现有模式：
- 默认配置路径来自 `get_default_runtime_config_path()`
- 允许 JSON 注释
- 非 strict 模式下，坏配置回退 `RuntimeConfig()`
- strict 模式下，抛清晰 `ValueError`
- 默认空配置会尝试自动修复成 `{}` 

参考测试：
- [CI/unit_tests/app/test_config_store.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/app/test_config_store.py:1)

规则：
- 配置 schema 兼容性放在 `software/core/config/` 处理，不要在 UI 层手搓版本迁移。
- 配置加载失败时，要么走 strict 抛错，要么按现有非 strict 规则警告并回退，别发明第三套半残逻辑。
- 新字段改动必须同步看 codec/schema 和对应单测，不准只改保存、不改读取。

## 反模式
- 把用户数据写回安装目录。
- 用 `runtime_paths.py` 推断可写目录。
- 让 UI 页面直接读写 JSON 文件，绕过 `software/io/config/store.py`。
- 在测试里直接污染真实系统 QSettings 或真实剪贴板。
