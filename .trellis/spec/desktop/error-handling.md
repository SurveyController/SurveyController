# 错误处理规则

## 先分清错误属于哪层
这个仓库的错误处理不是“一把 `except Exception` 包天下”，而是分层处理：

- 配置与运行前校验错误：尽量在准备阶段抛可读业务错误
- provider / HTTP 解析与提交错误：抛带平台上下文的 `RuntimeError` 或专用异常
- UI 清理、提示、后台刷新失败：很多场景只记日志，不打断主流程

## 运行前业务错误模式
[software/ui/controller/run_controller_parts/runtime_preparation.py](/abs/path/D:/Projects/SurveyController/software/ui/controller/run_controller_parts/runtime_preparation.py:1) 里的 `RuntimePreparationError` 是当前最清晰的模式之一：

- `user_message`
  给用户看的短消息
- `log_message`
  给日志看的详细上下文
- `detailed`
  标记是否需要更细粒度展示

规则：
- 用户能立刻修复的配置问题，优先走这种业务错误，不要直接扔低层堆栈。
- 记录日志时用 `log_message`，别把技术细节原样塞给普通用户。

## Provider / HTTP 错误要带业务上下文
平台实现里大量错误都会带：
- 平台名
- 题号
- 题目标题或字段名
- 当前失败动作

例子集中在：
- [tencent/provider/parser.py](/abs/path/D:/Projects/SurveyController/tencent/provider/parser.py:1)
- [tencent/provider/http_runtime.py](/abs/path/D:/Projects/SurveyController/tencent/provider/http_runtime.py:1)
- [credamo/provider/parser.py](/abs/path/D:/Projects/SurveyController/credamo/provider/parser.py:1)
- [credamo/provider/http_runtime.py](/abs/path/D:/Projects/SurveyController/credamo/provider/http_runtime.py:1)
- [wjx/provider/http_runtime.py](/abs/path/D:/Projects/SurveyController/wjx/provider/http_runtime.py:1)

规则：
- 抛错要让人一眼知道是哪个平台、哪个题、哪个字段炸了。
- 解析失败、提交失败、问卷不可用要区分开，不要全塞成一个“请求失败”。

## 什么时候吞异常
可以吞，但得有边界。

当前仓库常见模式：
- UI 清理、状态同步、窗口前置失败：`logging.info(..., exc_info=True)` 后继续
- 日志内部故障：写回 `_safe_internal_log()`，避免递归炸日志系统
- 启动前问卷星状态复查失败：只记 `info`，放行到运行时处理

证据：
- [software/logging/log_utils.py](/abs/path/D:/Projects/SurveyController/software/logging/log_utils.py:1)
- [software/ui/shell/main_window.py](/abs/path/D:/Projects/SurveyController/software/ui/shell/main_window.py:1)
- [software/ui/shell/main_window_parts/update.py](/abs/path/D:/Projects/SurveyController/software/ui/shell/main_window_parts/update.py:1)
- [software/ui/controller/run_controller_parts/runtime_preparation.py](/abs/path/D:/Projects/SurveyController/software/ui/controller/run_controller_parts/runtime_preparation.py:1)

规则：
- 吞异常只能用于非关键清理、提示、后台刷新这类旁路逻辑。
- 吞之前至少记日志；完全静默会把问题埋死。
- 关键业务链路别为了“稳”把异常吞光，最后只剩行为错乱。

## 测试怎么兜
错误处理改动至少要补一种：
- strict / non-strict 分支测试，参考 [CI/unit_tests/app/test_config_store.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/app/test_config_store.py:1)
- provider 合同或提交错误测试，参考 [CI/unit_tests/providers/test_http_runtime.py](/abs/path/D:/Projects/SurveyController/CI/unit_tests/providers/test_http_runtime.py:1)
- 运行前校验测试，参考 `CI/unit_tests/engine/` 下对应文件

## 反模式
- 全部统一 `raise RuntimeError("失败")`
- UI 直接展示底层堆栈或原始异常 repr
- 为了不报错，把关键异常吞掉继续跑
- 新写一套和 `RuntimePreparationError` 平行、语义却更差的异常协议
