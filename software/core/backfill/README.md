# 数据反填模块

数据反填功能的核心集成层，负责样本分发、答案提供、上下文扩展和工作流集成。

## 模块结构

```
software/core/backfill/
├── __init__.py              # 模块导出
├── dispatcher.py            # 样本分发器（线程安全）
├── answer_provider.py       # 答案提供器（从样本获取答案）
├── context_extension.py     # 上下文扩展（非侵入式集成）
├── initializer.py           # 反填初始化器（便捷初始化）
├── survey_converter.py      # 问卷结构转换器（RunController → SurveySchema）
├── workflow.py              # 工作流集成（执行循环包装器）
└── README.md                # 本文档
```

## 核心功能

### 1. SampleDispatcher - 样本分发器

线程安全地分发样本，确保每行只被消费一次。支持并发场景下的样本分配、状态更新和统计。

#### 初始化

```python
from software.core.backfill import SampleDispatcher
from software.io.excel import SampleRow

# 创建待处理样本列表
samples = [
    SampleRow(row_no=2, values={"Q1": "A"}, status="pending"),
    SampleRow(row_no=3, values={"Q1": "B"}, status="pending"),
    # ...
]

# 创建分发器
dispatcher = SampleDispatcher(samples)
```

#### 基本操作

```python
# 1. 取下一个待处理样本（线程安全）
sample = dispatcher.next_sample()
if sample is None:
    # 没有待处理样本了
    break

# 此时 sample.status 已自动从 "pending" 改为 "running"

# 2. 标记成功
dispatcher.mark_success(sample)

# 3. 标记失败（不重试）
dispatcher.mark_failed(sample, "错误信息", retry=False)

# 4. 标记失败（允许重试）
dispatcher.mark_failed(sample, "错误信息", retry=True)
```

#### 统计信息

```python
# 获取实时统计
stats = dispatcher.get_stats()
# {
#     "total": 100,        # 总样本数
#     "pending": 20,       # 待处理数
#     "running": 5,        # 运行中数
#     "success": 70,       # 成功数
#     "failed": 5,         # 失败数
#     "progress": 75.0     # 进度百分比（0-100）
# }
```

#### 辅助方法

```python
# 检查是否还有待处理样本
if dispatcher.has_pending():
    print("还有样本待处理")

# 检查是否所有样本都已完成
if dispatcher.is_completed():
    print("所有样本已处理完成")

# 获取失败样本列表
failed_samples = dispatcher.get_failed_samples()

# 获取成功样本列表
success_samples = dispatcher.get_success_samples()

# 重置失败样本为待处理状态（用于重试）
dispatcher.reset_failed_samples()
```

## 线程安全性

`SampleDispatcher` 使用 `threading.Lock` 确保所有操作都是线程安全的：

- `next_sample()`: 原子性地取出样本并标记为 running
- `mark_success()` / `mark_failed()`: 原子性地更新样本状态
- `get_stats()`: 原子性地读取统计信息
- 所有辅助方法都是线程安全的

### 并发使用示例

```python
import threading
from software.core.backfill import SampleDispatcher

def worker(dispatcher: SampleDispatcher, thread_id: int):
    """工作线程函数。"""
    while True:
        # 线程安全地取样本
        sample = dispatcher.next_sample()
        if sample is None:
            break
        
        try:
            # 处理样本
            process_sample(sample)
            
            # 标记成功
            dispatcher.mark_success(sample)
        except Exception as e:
            # 标记失败
            dispatcher.mark_failed(sample, str(e), retry=False)

# 创建分发器
dispatcher = SampleDispatcher(samples)

# 启动多个工作线程
threads = []
for i in range(10):
    t = threading.Thread(target=worker, args=(dispatcher, i))
    t.start()
    threads.append(t)

# 等待所有线程完成
for t in threads:
    t.join()

# 获取最终统计
stats = dispatcher.get_stats()
print(f"成功: {stats['success']}, 失败: {stats['failed']}")
```

## 状态转换

样本状态的转换流程：

```
pending → running → success
                 → failed
                 → pending (retry=True)
```

- `pending`: 待处理
- `running`: 正在处理
- `success`: 处理成功
- `failed`: 处理失败

## 重试机制

支持两种失败处理方式：

1. **不重试**：`mark_failed(sample, error, retry=False)`
   - 样本状态变为 `failed`
   - 不会再被 `next_sample()` 返回

2. **允许重试**：`mark_failed(sample, error, retry=True)`
   - 样本状态变回 `pending`
   - 会被 `next_sample()` 再次返回

3. **批量重置**：`reset_failed_samples()`
   - 将所有 `failed` 样本重置为 `pending`
   - 用于全局重试失败样本

## 进度追踪

进度计算公式：

```python
progress = (success + failed) / total * 100
```

- 只有 `success` 和 `failed` 状态的样本才算完成
- `pending` 和 `running` 状态的样本不算完成
- 进度范围：0.0 - 100.0

## 测试

运行测试：

```bash
conda activate spider
python tests/test_dispatcher.py
```

测试覆盖：
- ✓ 基本操作（取样本、标记状态、统计）
- ✓ 线程安全性（10 个线程并发处理 100 个样本）
- ✓ 重试机制（失败重试、批量重置）
- ✓ 辅助方法（has_pending、is_completed、get_failed_samples 等）

## 性能

在测试中，10 个线程并发处理 100 个样本：
- 耗时：约 0.02 秒
- 无重复处理
- 无样本丢失
- 线程间负载均衡

## 使用场景

`SampleDispatcher` 适用于以下场景：

1. **多线程填写问卷**：多个浏览器实例并发填写
2. **失败重试**：自动或手动重试失败样本
3. **进度监控**：实时显示处理进度
4. **结果统计**：统计成功/失败数量

### 2. BackfillAnswerProvider - 答案提供器

从反填样本中获取答案，替代随机生成。

#### 函数式接口

```python
from software.core.backfill import (
    get_backfill_answer,
    has_backfill_answer,
    get_all_backfill_answers,
)

# 获取单个答案
answer = get_backfill_answer(execution_state, "Q1")
if answer is not None:
    # 使用反填答案
    fill_with_answer(answer)
else:
    # 使用随机答案
    fill_with_random()

# 检查是否有答案
if has_backfill_answer(execution_state, "Q1"):
    print("有反填答案")

# 获取所有答案
all_answers = get_all_backfill_answers(execution_state)
# {"Q1": "男", "Q2": "18-25岁", ...}
```

#### 面向对象接口

```python
from software.core.backfill import BackfillAnswerProvider

# 方式 1：从 ExecutionState 创建
provider = BackfillAnswerProvider(execution_state)

# 方式 2：从答案字典创建（用于测试）
provider = BackfillAnswerProvider({"Q1": "男", "Q2": "18-25岁"})

# 获取答案
answer = provider.get("Q1", default="未知")

# 检查是否有答案
if provider.has("Q1"):
    print("有答案")

# 获取所有答案
all_answers = provider.get_all()

# 根据题号获取答案（用于 answer_context）
answer = provider.get_answer_for_question(1)  # 题号 1 -> Q1
```

### 3. BackfillInitializer - 反填初始化器

便捷地初始化反填模式，封装所有初始化步骤。

```python
from software.core.backfill import initialize_backfill_mode
from software.core.backfill.survey_converter import convert_to_survey_schema

# 1. 转换问卷结构
survey_schema = convert_to_survey_schema(run_controller)

# 2. 初始化反填模式
result = initialize_backfill_mode(
    execution_state,
    excel_path="data.xlsx",
    survey_schema=survey_schema,
    fuzzy_threshold=90.0,
    qualification_rules={"Q1": ["否"]}  # 可选
)

# 3. 查看初始化结果
print(f"总行数: {result['total_rows']}")
print(f"有效样本: {result['valid_samples']}")
print(f"失败样本: {result['failed_samples']}")
print(f"映射项数: {result['mapping_items']}")
```

初始化器会自动完成：
1. 读取 Excel 文件
2. 建立题目映射
3. 校验并标准化答案
4. 创建样本分发器
5. 启用反填模式

### 4. 上下文扩展 - 非侵入式集成

通过扩展而不是修改的方式，为 `ExecutionState` 添加反填模式支持。

```python
from software.core.backfill import enable_backfill_mode

# 启用反填模式（自动扩展 ExecutionState）
enable_backfill_mode(
    execution_state,
    excel_path="data.xlsx",
    survey_schema=survey_schema,
    mapping_plan=mapping_plan,
    dispatcher=dispatcher,
    fuzzy_threshold=90.0,
    qualification_rules={"Q1": ["否"]},
)

# 之后可以使用反填功能
if execution_state.is_backfill_mode():
    sample = execution_state.get_current_sample()
    print(f"当前样本: {sample.row_no}")
```

扩展的方法：
- `is_backfill_mode()`: 检查是否启用反填模式
- `get_current_sample(thread_name)`: 获取当前线程的样本
- `set_current_sample(sample, thread_name)`: 设置当前线程的样本
- `backfill_config`: 反填配置（BackfillConfig）
- `backfill_state`: 反填状态（BackfillState）

### 5. 工作流集成 - 执行循环包装器

在执行循环中集成反填模式，自动处理样本获取和状态更新。

```python
from software.core.backfill.workflow import (
    backfill_workflow_wrapper,
    should_continue_backfill,
    get_backfill_stats,
)

# 在执行循环中使用
while not execution_state.stop_event.is_set():
    # 检查是否应该继续
    if not should_continue_backfill(execution_state):
        break  # 所有样本已处理完
    
    # 使用包装器执行填写
    backfill_workflow_wrapper(
        execution_state,
        fill_survey,
        driver, execution_state, ...
    )
    
    # 获取统计信息
    stats = get_backfill_stats(execution_state)
    if stats:
        print(f"进度: {stats['progress']:.1f}%")
```

包装器会自动：
1. 从分发器获取样本
2. 设置为当前样本
3. 执行填写函数
4. 标记成功/失败
5. 清除当前样本

### 6. 问卷结构转换器

将 `RunController` 的问卷信息转换为标准的 `SurveySchema`。

```python
from software.core.backfill.survey_converter import convert_to_survey_schema

# 转换问卷结构
survey_schema = convert_to_survey_schema(run_controller)

# survey_schema 包含：
# - title: 问卷标题
# - questions: 题目列表（QuestionSchema）
#   - qid: 题目 ID（如 "Q1", "Q2", "Q3_1"）
#   - index: 题号
#   - title: 题目标题
#   - qtype: 题目类型
#   - required: 是否必填
#   - options: 选项列表（OptionSchema）
```

支持的题目类型：
- 单选题、多选题、文本题
- 量表题、评分题、矩阵题
- 下拉题、滑块题、排序题
- 矩阵题自动拆分为多个子题目（Q3_1, Q3_2, ...）

## 完整使用示例

### 方式 1：使用便捷函数（推荐）

```python
from software.core.backfill import initialize_backfill_mode
from software.core.backfill.survey_converter import convert_to_survey_schema
from software.core.backfill.workflow import (
    backfill_workflow_wrapper,
    should_continue_backfill,
)

# 1. 转换问卷结构
survey_schema = convert_to_survey_schema(run_controller)

# 2. 初始化反填模式
result = initialize_backfill_mode(
    execution_state,
    excel_path="data.xlsx",
    survey_schema=survey_schema,
)

# 3. 执行循环
while not execution_state.stop_event.is_set():
    if not should_continue_backfill(execution_state):
        break
    
    backfill_workflow_wrapper(
        execution_state,
        fill_survey,
        driver, execution_state, ...
    )
```

### 方式 2：手动集成

```python
from software.io.excel import (
    ExcelReader,
    QuestionMatcher,
    AnswerNormalizer,
    SampleValidator,
)
from software.core.backfill import (
    SampleDispatcher,
    enable_backfill_mode,
    get_backfill_answer,
)

# 1. 读取并校验样本
reader = ExcelReader()
samples = reader.read("data.xlsx")

matcher = QuestionMatcher()
plan = matcher.build_mapping(excel_columns, survey_schema)

normalizer = AnswerNormalizer()
validator = SampleValidator(normalizer)
validator.validate_and_normalize(samples, survey_schema, plan)

# 2. 创建分发器
valid_samples = [s for s in samples if s.status == "pending"]
dispatcher = SampleDispatcher(valid_samples)

# 3. 启用反填模式
enable_backfill_mode(
    execution_state,
    excel_path="data.xlsx",
    survey_schema=survey_schema,
    mapping_plan=plan,
    dispatcher=dispatcher,
)

# 4. 在 provider 中使用
def fill_question(execution_state, question_id):
    # 尝试从反填样本获取答案
    answer = get_backfill_answer(execution_state, question_id)
    if answer is not None:
        return answer
    
    # 回退到随机生成
    return generate_random_answer()
```

## 模块依赖关系

```
software/core/backfill/
│
├── dispatcher.py           # 独立模块，无依赖
│
├── answer_provider.py      # 依赖：ExecutionState, SampleRow
│
├── context_extension.py    # 依赖：SurveySchema, MappingPlan, SampleDispatcher
│
├── initializer.py          # 依赖：excel 模块, dispatcher, context_extension
│
├── survey_converter.py     # 依赖：RunController, excel.schema
│
└── workflow.py             # 依赖：ExecutionState, dispatcher
```

## 注意事项

1. **初始状态**：传入分发器的样本应该都是 `status="pending"` 的
2. **线程安全**：所有方法都是线程安全的，可以放心在多线程环境使用
3. **状态一致性**：不要在外部直接修改样本状态，应该通过分发器的方法修改
4. **内存占用**：所有样本都保存在内存中，大量样本时注意内存使用
5. **非侵入式**：通过扩展而不是修改的方式集成，不影响原有代码
6. **向后兼容**：如果不启用反填模式，所有功能保持原样
