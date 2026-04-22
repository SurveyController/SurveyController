# 数据反填执行流程详解

## 文档目的

本文档详细说明数据反填功能的完整执行流程，从用户点击"开始执行"到任务完成的每一个步骤。

## 流程概览

```
用户点击"开始执行"
    ↓
配置验证
    ↓
反填模式初始化
    ↓
多线程并发执行
    ↓
任务完成/导出未完成样本
```

## 详细执行流程

### 阶段 1: 启动前准备

#### 1.1 用户操作
```
1. 输入问卷链接
2. 点击"自动配置问卷"（解析问卷结构）
3. 启用"反填模式"开关
4. 选择 Excel 文件
5. 配置并发线程数（如 3 个线程）
6. 滚动到页面底部
7. 点击"开始执行"按钮
```

#### 1.2 配置验证
**位置**: `software/ui/pages/workbench/dashboard/parts/run_actions.py`

**方法**: `_on_start_clicked()`

**验证内容**:
```python
# 1. 检查是否有配置的题目
if not cfg.question_entries:
    显示错误: "未配置任何题目"
    return

# 2. 如果启用反填模式，验证反填配置
if cfg.backfill_enabled:
    is_valid, error_msg = self.validate_backfill_config()
    if not is_valid:
        显示错误: error_msg
        return
```

**验证项**:
- ✅ 是否选择了 Excel 文件
- ✅ Excel 文件是否存在
- ✅ 问卷是否已解析

#### 1.3 启动任务
**位置**: `software/ui/controller/run_controller_parts/runtime_execution.py`

**方法**: `start_run(config)`

**流程**:
```python
1. 设置 running = True
2. 设置 stop_event（停止信号）
3. 调用 _start_with_initialization_gate(config, [])
```

---

### 阶段 2: 反填模式初始化

#### 2.1 初始化入口
**位置**: `software/ui/controller/run_controller_parts/runtime_init_gate.py`

**方法**: `_prepare_engine_state(config, proxy_pool)`

**判断条件**:
```python
backfill_enabled = bool(getattr(config, "backfill_enabled", False))
backfill_excel_path = str(getattr(config, "backfill_excel_path", "") or "")

if backfill_enabled and backfill_excel_path:
    # 执行反填初始化
```

#### 2.2 读取 Excel 文件
**模块**: `software/io/excel/reader.py`

**步骤**:
```python
from software.io.excel.reader import ExcelReader
reader = ExcelReader()
samples = reader.read(backfill_excel_path)
```

**输出**:
```python
samples = [
    SampleRow(
        row_no=1,
        values={"Q1": "男", "Q2": "25", "Q3": "本科"},
        status="pending"
    ),
    SampleRow(
        row_no=2,
        values={"Q1": "女", "Q2": "30", "Q3": "硕士"},
        status="pending"
    ),
    # ...
]
```

**日志**:
```
读取 Excel 完成，共 10 条样本
```

#### 2.3 转换问卷结构
**模块**: `software/core/backfill/survey_converter.py`

**步骤**:
```python
from software.core.backfill.survey_converter import convert_to_survey_schema
survey_schema = convert_to_survey_schema(self)  # self 是 RunController
```

**输出**:
```python
survey_schema = SurveySchema(
    title="用户调查",
    questions=[
        QuestionSchema(
            qid="Q1",
            index=1,
            title="您的性别是？",
            qtype="single_choice",
            options=[
                OptionSchema(text="男"),
                OptionSchema(text="女"),
            ]
        ),
        # ...
    ]
)
```

**日志**:
```
问卷结构转换完成，共 5 个题目
```

#### 2.4 映射 Excel 列到题目
**模块**: `software/io/excel/mapper.py`

**步骤**:
```python
from software.io.excel.mapper import QuestionMatcher
matcher = QuestionMatcher()
first_sample_keys = list(samples[0].values.keys())  # ["Q1", "Q2", "Q3"]
mapping_plan = matcher.build_mapping(first_sample_keys, survey_schema)
```

**映射策略**:
1. **题号匹配**: Q1 → 题目1（最高优先级）
2. **完整标题匹配**: "您的性别是？" → 题目1
3. **模糊标题匹配**: "性别" → 题目1

**输出**:
```python
mapping_plan = MappingPlan(
    items=[
        MappingItem(
            excel_col="Q1",
            survey_qid="Q1",
            survey_index=1,
            survey_title="您的性别是？",
            confidence=1.0,
            mode="by_index"
        ),
        # ...
    ]
)
```

**日志**:
```
列映射完成，映射了 5 个题目
```

#### 2.5 标准化所有样本
**模块**: `software/io/excel/normalizer.py`, `software/io/excel/validator.py`

**步骤**:
```python
from software.io.excel.normalizer import AnswerNormalizer
from software.io.excel.validator import SampleValidator

normalizer = AnswerNormalizer()
validator = SampleValidator(normalizer)
validator.validate_and_normalize(samples, survey_schema, mapping_plan)
```

**标准化过程**:
```python
# 原始数据
sample.values = {"Q1": "男", "Q4": "A┋B┋C"}

# 标准化后
sample.normalized_answers = {
    "Q1": "男",           # 单选题：保持不变
    "Q4": ["A", "B", "C"] # 多选题：分割为列表
}
```

**验证内容**:
- ✅ 选项是否存在
- ✅ 答案类型是否匹配
- ✅ 必填题是否有答案

**状态更新**:
```python
# 验证成功
sample.status = "pending"

# 验证失败
sample.status = "failed"
sample.error = "选项不存在: X"
```

**日志**:
```
样本标准化完成，有效样本 8 条
```

#### 2.6 创建样本分发器
**模块**: `software/core/backfill/dispatcher.py`

**步骤**:
```python
from software.core.backfill.dispatcher import SampleDispatcher
dispatcher = SampleDispatcher(samples)
```

**分发器功能**:
- 线程安全的样本分发
- 样本状态管理
- 失败重试机制
- 统计信息收集

#### 2.7 注入到执行状态
**步骤**:
```python
# 1. 注入分发器
execution_state.sample_dispatcher = dispatcher

# 2. 更新目标数量为有效样本数量
valid_samples = [s for s in samples if s.status == "pending"]
execution_config.target_num = len(valid_samples)
```

**日志**:
```
反填模式初始化完成，目标数量已更新为 8
```

---

### 阶段 3: 多线程并发执行

#### 3.1 启动工作线程
**位置**: `software/core/engine/runner.py`

**步骤**:
```python
# 假设配置了 3 个线程
for i in range(3):
    thread = threading.Thread(
        target=loop.run_thread,
        args=(window_x, window_y, stop_signal),
        name=f"Thread-{i+1}"
    )
    thread.start()
```

**线程状态**:
```
Thread-1: 启动
Thread-2: 启动
Thread-3: 启动
```

#### 3.2 线程执行循环
**位置**: `software/core/engine/execution_loop.py`

**方法**: `run_thread()`

**主循环结构**:
```python
while True:
    # 1. 检查停止信号
    if stop_signal.is_set():
        break
    
    # 2. 检查完成条件
    if 反填模式 and 所有样本已完成:
        break
    
    # 3. 获取样本（反填模式）
    current_sample = dispatcher.get_next_sample(thread_name)
    if current_sample is None:
        break  # 没有更多样本
    
    # 4. 创建浏览器会话
    session = create_browser_session()
    
    # 5. 导航到问卷页面
    navigate_to_survey(session.driver, config.url)
    
    # 6. 填写问卷（反填模式）
    finished = _fill_survey_with_backfill(
        session.driver,
        current_sample,
        stop_signal,
        thread_name
    )
    
    # 7. 提交问卷
    if finished:
        outcome = submit_survey(session.driver)
        
        # 8. 处理提交结果
        if outcome.status == "success":
            dispatcher.mark_sample_success(current_sample.row_no)
        else:
            dispatcher.mark_sample_failed(current_sample.row_no, "提交失败", retry=True)
    else:
        dispatcher.mark_sample_failed(current_sample.row_no, "填写未完成", retry=True)
    
    # 9. 清理资源
    session.dispose()
    
    # 10. 等待提交间隔
    wait_for_submit_interval()
```

#### 3.3 样本分发过程

**初始状态**:
```
样本池:
- 样本1: pending
- 样本2: pending
- 样本3: pending
- 样本4: pending
- 样本5: pending
```

**Thread-1 获取样本**:
```python
sample = dispatcher.get_next_sample("Thread-1")
# 返回: 样本1
# 样本1 状态: pending → running
```

**Thread-2 获取样本**:
```python
sample = dispatcher.get_next_sample("Thread-2")
# 返回: 样本2
# 样本2 状态: pending → running
```

**Thread-3 获取样本**:
```python
sample = dispatcher.get_next_sample("Thread-3")
# 返回: 样本3
# 样本3 状态: pending → running
```

**当前状态**:
```
样本池:
- 样本1: running (Thread-1)
- 样本2: running (Thread-2)
- 样本3: running (Thread-3)
- 样本4: pending
- 样本5: pending
```

#### 3.4 反填答题过程

**位置**: `software/core/engine/execution_loop.py`

**方法**: `_fill_survey_with_backfill()`

**步骤**:
```python
def _fill_survey_with_backfill(driver, sample, stop_signal, thread_name):
    # 1. 创建答案提供者
    from software.core.backfill.answer_provider import BackfillAnswerProvider
    provider = BackfillAnswerProvider(sample.normalized_answers)
    
    # 2. 使用上下文管理器
    from software.core.questions.answer_context import backfill_answer_context
    with backfill_answer_context(provider):
        # 3. 调用 provider 填写问卷
        # 在上下文中，所有 smart_select_* 函数会自动使用反填数据
        finished = _provider_fill_survey(
            driver,
            config,
            state,
            stop_signal=stop_signal,
            thread_name=thread_name,
            provider=config.survey_provider,
        )
    
    return finished
```

**上下文管理器作用**:
```python
# 进入上下文
with backfill_answer_context(provider):
    # 此时 _context_storage.provider = provider
    
    # 所有 smart_select_* 函数会检测到上下文
    # 并使用 provider 提供的答案
    
    # 例如：单选题
    selected_index = smart_select_option(
        current=1,
        option_texts=["男", "女"],
        probabilities=[0.5, 0.5]
    )
    # 返回: 0（因为 provider 提供的答案是"男"）

# 退出上下文
# _context_storage.provider = None
```

#### 3.5 智能选择函数

**位置**: `software/core/questions/answer_context.py`

**单选题示例**:
```python
def smart_select_option(current, option_texts, probabilities):
    # 1. 检查是否在反填上下文中
    provider = _context_storage.provider
    
    if provider:
        # 2. 反填模式：从 provider 获取答案
        answer = provider.get_answer_for_question(current)
        
        if answer:
            # 3. 在选项中查找匹配
            for i, text in enumerate(option_texts):
                if answer in text or text in answer:
                    return i  # 找到匹配，返回索引
            
            # 4. 找不到匹配，降级到随机
            logging.warning(f"Q{current}: 找不到匹配选项 '{answer}'，使用随机选择")
    
    # 5. 随机模式：使用概率分布
    from software.core.questions.utils import weighted_index
    return weighted_index(probabilities)
```

**多选题示例**:
```python
def smart_select_multiple_options(current, option_texts, probabilities):
    provider = _context_storage.provider
    
    if provider:
        # 反填模式：获取答案列表
        answers = provider.get_answer_for_question(current)
        
        if isinstance(answers, list):
            # 匹配每个答案到选项索引
            selected_indices = []
            for answer in answers:
                for i, text in enumerate(option_texts):
                    if answer in text or text in answer:
                        selected_indices.append(i)
                        break
            
            if selected_indices:
                return selected_indices
    
    # 随机模式
    from software.core.questions.utils import weighted_multi_select
    return weighted_multi_select(probabilities)
```

#### 3.6 提交处理

**成功提交**:
```python
outcome = submission_service.finalize_after_submit(...)

if outcome.status == "success":
    # 标记样本成功
    dispatcher.mark_sample_success(current_sample.row_no)
    logging.info(f"样本 {current_sample.row_no} 提交成功")
    
    # 更新状态
    # 样本1: running → success
```

**失败提交（允许重试）**:
```python
else:
    # 标记样本失败，返回池中
    dispatcher.mark_sample_failed(
        current_sample.row_no,
        "提交失败",
        retry=True
    )
    
    # 更新状态
    # 样本1: running → pending（返回池中）
```

**失败提交（不允许重试）**:
```python
dispatcher.mark_sample_failed(
    current_sample.row_no,
    "AI 生成失败",
    retry=False
)

# 更新状态
# 样本1: running → failed（永久失败）
```

#### 3.7 异常处理

**填写异常**:
```python
try:
    finished = _fill_survey_with_backfill(...)
except Exception as exc:
    # 标记样本失败，允许重试
    dispatcher.mark_sample_failed(
        current_sample.row_no,
        str(exc),
        retry=True
    )
    logging.error(f"填写异常: {exc}", exc_info=True)
```

**提交异常**:
```python
try:
    outcome = submission_service.finalize_after_submit(...)
except ProxyConnectionError as exc:
    # 代理连接错误，允许重试
    dispatcher.mark_sample_failed(
        current_sample.row_no,
        "代理连接失败",
        retry=True
    )
except AIRuntimeError as exc:
    # AI 运行时错误，不允许重试
    dispatcher.mark_sample_failed(
        current_sample.row_no,
        "AI 生成失败",
        retry=False
    )
```

#### 3.8 完成条件检查

**反填模式完成条件**:
```python
if self.config.backfill_enabled:
    # 检查是否所有样本都已完成
    if self.state.sample_dispatcher.is_all_success():
        logging.info("所有样本已成功提交，线程退出")
        break
    
    # 或者没有更多待处理样本
    current_sample = self.state.sample_dispatcher.get_next_sample(thread_name)
    if current_sample is None:
        logging.info("没有更多待处理样本，线程退出")
        break
```

**随机模式完成条件**:
```python
else:
    # 检查是否达到目标数量
    with self.state.lock:
        if self.state.cur_num >= self.config.target_num:
            break
```

---

### 阶段 4: 任务完成

#### 4.1 线程退出
**步骤**:
```python
# 1. 释放资源
session.shutdown()

# 2. 标记线程完成
state.mark_thread_finished(thread_name, status_text="已停止")

# 3. 线程退出
return
```

#### 4.2 所有线程完成
**位置**: `software/ui/controller/run_controller_parts/runtime_execution.py`

**方法**: `_on_run_finished()`

**步骤**:
```python
def _on_run_finished(adapter_snapshot):
    # 1. 导出未完成的样本（如果是反填模式）
    _export_incomplete_samples_if_needed()
    
    # 2. 清理浏览器资源
    _schedule_cleanup(adapter_snapshot)
    
    # 3. 停止状态定时器
    _status_timer.stop()
    
    # 4. 更新运行状态
    running = False
    runStateChanged.emit(False)
    
    # 5. 发送任务停止事件
    _event_bus.emit(EVENT_TASK_STOPPED)
```

#### 4.3 导出未完成样本
**位置**: `software/ui/controller/run_controller_parts/runtime_execution.py`

**方法**: `_export_incomplete_samples_if_needed()`

**步骤**:
```python
def _export_incomplete_samples_if_needed():
    # 1. 检查是否是反填模式
    if not execution_state or not execution_state.sample_dispatcher:
        return
    
    # 2. 获取配置中的 Excel 路径
    backfill_excel_path = config.backfill_excel_path
    if not backfill_excel_path:
        return
    
    # 3. 导出未完成的样本
    output_path = sample_dispatcher.export_incomplete_samples(backfill_excel_path)
    
    # 4. 显示提示
    if output_path:
        logging.info(f"已导出未完成样本到: {output_path}")
        显示消息框: "有未完成的样本已导出到：\n\n{output_path}"
    else:
        logging.info("所有样本都已完成，无需导出")
```

**导出文件格式**:
```
原始文件: demo/demo.xlsx
导出文件: demo/demo_未完成.xlsx

内容:
| Q1   | Q2   | Q3   | 状态   | 错误信息        |
|------|------|------|--------|----------------|
| 男   | 25   | 本科 | 失败   | 提交失败：网络错误 |
| 女   | 30   | 硕士 | 待处理 |                |
```

---

## 执行流程时序图

```
用户                Dashboard           RunController        ExecutionLoop        SampleDispatcher
 |                      |                    |                    |                    |
 |--点击"开始执行"----->|                    |                    |                    |
 |                      |                    |                    |                    |
 |                      |--验证配置--------->|                    |                    |
 |                      |<--验证通过---------|                    |                    |
 |                      |                    |                    |                    |
 |                      |--start_run()------>|                    |                    |
 |                      |                    |                    |                    |
 |                      |                    |--初始化反填------->|                    |
 |                      |                    |  (读取Excel)       |                    |
 |                      |                    |  (映射列名)        |                    |
 |                      |                    |  (标准化样本)      |                    |
 |                      |                    |                    |                    |
 |                      |                    |--创建dispatcher------------------->|
 |                      |                    |<--dispatcher创建完成----------------|
 |                      |                    |                    |                    |
 |                      |                    |--启动线程--------->|                    |
 |                      |                    |                    |                    |
 |                      |                    |                    |--获取样本--------->|
 |                      |                    |                    |<--返回样本---------|
 |                      |                    |                    |                    |
 |                      |                    |                    |--填写问卷          |
 |                      |                    |                    |  (使用反填数据)    |
 |                      |                    |                    |                    |
 |                      |                    |                    |--提交问卷          |
 |                      |                    |                    |                    |
 |                      |                    |                    |--标记成功--------->|
 |                      |                    |                    |<--状态已更新-------|
 |                      |                    |                    |                    |
 |                      |                    |                    |--获取下一个样本--->|
 |                      |                    |                    |<--返回样本---------|
 |                      |                    |                    |                    |
 |                      |                    |                    |  (循环执行...)     |
 |                      |                    |                    |                    |
 |                      |                    |                    |--所有样本完成----->|
 |                      |                    |                    |<--确认完成---------|
 |                      |                    |                    |                    |
 |                      |                    |<--线程退出---------|                    |
 |                      |                    |                    |                    |
 |                      |                    |--导出未完成样本------------------->|
 |                      |                    |<--导出完成-------------------------|
 |                      |                    |                    |                    |
 |                      |<--任务完成---------|                    |                    |
 |<--显示完成提示-------|                    |                    |                    |
 |                      |                    |                    |                    |
```

---

## 关键数据流

### 1. 样本数据流

```
Excel 文件
    ↓ (ExcelReader)
原始样本 (SampleRow)
    values = {"Q1": "男", "Q4": "A┋B┋C"}
    status = "pending"
    ↓ (AnswerNormalizer)
标准化样本 (SampleRow)
    normalized_answers = {"Q1": "男", "Q4": ["A", "B", "C"]}
    status = "pending"
    ↓ (SampleDispatcher)
分发给线程
    status = "running"
    ↓ (ExecutionLoop)
填写问卷
    ↓ (SubmissionService)
提交问卷
    ↓
标记状态
    status = "success" / "failed"
```

### 2. 答案数据流

```
标准化答案
    normalized_answers = {"Q1": "男", "Q4": ["A", "B", "C"]}
    ↓ (BackfillAnswerProvider)
答案提供者
    get_answer_for_question(1) → "男"
    get_answer_for_question(4) → ["A", "B", "C"]
    ↓ (backfill_answer_context)
上下文管理器
    _context_storage.provider = provider
    ↓ (smart_select_option)
智能选择函数
    检测到上下文 → 使用反填数据
    找到匹配选项 → 返回索引
    ↓ (Provider)
填写到页面
    driver.find_element(...).click()
```

### 3. 状态数据流

```
样本状态变化:
pending → running → success
pending → running → failed → pending (重试)
pending → running → failed (永久失败)

线程状态变化:
启动 → 获取样本 → 填写问卷 → 提交问卷 → 等待间隔 → 获取下一个样本 → ... → 完成

任务状态变化:
初始化 → 运行中 → 完成 → 导出未完成样本 → 清理资源
```

---

## 错误处理流程

### 1. Excel 读取错误

```
读取 Excel 失败
    ↓
显示错误: "无法读取 Excel 文件: {错误信息}"
    ↓
任务不启动
```

### 2. 映射失败

```
列名无法映射到题目
    ↓
记录警告: "列 'XXX' 无法映射到任何题目"
    ↓
继续执行（该列数据被忽略）
```

### 3. 标准化失败

```
答案标准化失败
    ↓
样本状态 = "failed"
样本错误 = "标准化失败: {原因}"
    ↓
该样本不参与执行
    ↓
任务结束时导出到"_未完成.xlsx"
```

### 4. 填写失败

```
填写问卷失败
    ↓
标记样本失败 (retry=True)
    ↓
样本返回池中
    ↓
其他线程可以重新获取
```

### 5. 提交失败

```
提交问卷失败
    ↓
判断错误类型:
    - 网络错误 → retry=True
    - AI 错误 → retry=False
    ↓
标记样本失败
    ↓
retry=True: 返回池中
retry=False: 永久失败
```

---

## 性能优化点

### 1. 多线程并发

```
单线程: 10 个样本 × 30秒/样本 = 300秒
3 线程:  10 个样本 ÷ 3 × 30秒/样本 ≈ 100秒
```

### 2. 智能匹配缓存

```
第一次匹配: 遍历所有选项
后续匹配: 使用缓存结果
```

### 3. 失败重试

```
临时失败（网络错误）: 自动重试
永久失败（数据错误）: 不重试，避免浪费时间
```

---

## 总结

反填执行流程的关键特点：

1. **清晰的阶段划分**: 初始化 → 执行 → 完成
2. **线程安全**: 使用锁保护共享资源
3. **智能匹配**: 支持多种匹配策略
4. **失败重试**: 自动处理临时失败
5. **完整的日志**: 每个步骤都有日志记录
6. **友好的错误处理**: 详细的错误信息
7. **未完成样本导出**: 方便后续处理

这个流程确保了数据反填功能的可靠性和易用性。

