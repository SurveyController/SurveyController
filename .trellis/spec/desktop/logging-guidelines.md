# 日志规则

## 统一入口
日志主入口在：
- [software/logging/log_utils.py](/abs/path/D:/Projects/SurveyController/software/logging/log_utils.py:1)
- [software/logging/action_logger.py](/abs/path/D:/Projects/SurveyController/software/logging/action_logger.py:1)

[software/app/main.py](/abs/path/D:/Projects/SurveyController/software/app/main.py:1) 启动时会调用 `setup_logging()`。这一步会：

- 接管 root logger
- 注册内存日志缓冲
- 创建会话日志文件
- 接管 `stdout` / `stderr`
- 接管未处理异常

不要自己再私搭一套独立 logger 初始化流程。

## 记录什么
普通业务日志：
- 状态变化
- 运行前校验失败
- provider 解析/提交关键节点
- 更新、代理、AI 连接等跨层行为

动作日志：
- 用 `log_action()` / `bind_logged_action()` 记录关键 UI/配置/运行动作
- 只记录重要事件，不做全量噪声埋点

参考：
- [software/logging/action_logger.py](/abs/path/D:/Projects/SurveyController/software/logging/action_logger.py:1)
- [CI/unit_tests/test_action_logger.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/test_action_logger.py:1)

## 去重、脱敏、噪声过滤
`log_utils.py` 里已经有几套现成机制：

- `log_deduped_message()`
  同一 key + 同一消息只打一次
- `_should_filter_noise()`
  过滤已知运行时噪声
- `_should_filter_sensitive()`
  过滤 `Authorization: Bearer`、`refresh_token`、`access_token`
- `mask_proxy_for_log()` 一类代理脱敏逻辑在别处配合使用

规则：
- 重复失败提示优先用去重日志，不要刷爆日志面板。
- 新增敏感字段时，记得补脱敏或过滤。
- 不要把 HTTP token、完整授权头、完整账号秘钥直接打进日志。

参考测试：
- [CI/unit_tests/test_log_utils.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/test_log_utils.py:1)
- [CI/unit_tests/test_log_utils_concurrency.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/test_log_utils_concurrency.py:1)

## 会话日志持久化
会话日志默认落在用户日志目录。相关行为包括：
- 当前会话日志文件
- `last_session.log`
- 按保留数量裁剪历史 `session_*.log`

规则：
- 日志文件写入仍然走用户目录，不写回安装目录。
- 导出或清理逻辑尽量复用现有 helper，不要自己手写第二套保留策略。

## 级别选择
- `debug`
  开发态细节、清理失败、恢复失败这类不影响主流程的信息
- `info`
  正常流程节点、可预期回退、后台任务状态
- `warning`
  业务可继续，但说明出现异常或回退
- `error`
  关键流程失败、用户操作失败、无法继续

当前仓库很多 UI 辅助失败会用 `info(..., exc_info=True)`。这属于现实模式，别强行按教科书改成满屏 warning/error。

## 反模式
- 重复刷同一条错误几十次
- 把敏感信息原样打进日志
- 跳过 `setup_logging()` 自己手配 handler
- 在 UI 层为每个按钮乱写一条无上下文的 `clicked`
