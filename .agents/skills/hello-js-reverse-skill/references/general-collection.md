# 通用采集、恢复与改版基线

适用于 JSON API。接口鉴权、动态签名与业务字段由具体需求配置或回调提供；MCP 负责捕获和验证证据，不执行站点特例。

## 配置运行

先按依赖要求选入口：仅标准库任务可直接复用 `templates/python-request/utils/collector.py` 并接 urllib 回调；允许 requests 的任务再复制完整 `templates/python-request/` 到需求工作区、安装 requirements，并将 `config/collection.example.json` 复制为私有任务配置并替换 URL/字段。

```bash
python collect.py --config config/job.json --output artifacts/items.jsonl
python collect.py --config config/job.json --output artifacts/items.jsonl --resume
```

- `items_path` 是 JSON 点路径，例如 `data.items`；空字符串表示顶层数组，数组索引可以写成 `data.0.items`。包含点号的真实属性名请通过自定义 `extract_items` 回调读取。
- `success_path/success_value` 校验业务成功状态；HTTP 成功不代表采集成功。无业务状态字段时可省略，仍需验证数据结构。
- `item_key` 可选，例如 `id`；设置后跨页和恢复过程按该字段去重。不配置时保留原始条目。
- `pagination.mode` 为 `page/offset/cursor/none`。`param` 指定字段；`in="body"` 将分页字段放进 JSON Body，默认在 query。页码默认从 1 开始；offset 默认从 0 开始，并显式设置 `step` 为接口要求的偏移增量。Cursor 指定 `next_path`，下一游标为 null/空字符串时结束，数字 0 仍是有效游标。
- `max_pages` 是包含已完成页数的总上限，默认 100；达到上限返回 `limited`，不会无限翻页。提高上限后可恢复。
- `headers/cookies/params/body/method/timeout` 都来自任务配置。登录态缺失或业务校验失败时停止，不把错误响应当空页。
- GET/HEAD/OPTIONS 对连接异常、超时、429/5xx 有界重试；POST 等不默认重放。自定义客户端可显式设置 `retry_non_idempotent=True`，调用者应先确认业务幂等条件。

## v3.8 可选分页与恢复控制

既有配置与默认值保留，按当前接口契约选择下列选项：

| 配置 / 参数 | 语义 |
|---|---|
| 配置 `max_pages` | 整个 job 累计成功页数上限，包含历史已完成页 |
| CLI `--max-pages N` / 核心 `max_pages_per_run` | 本次运行成功提交的页数上限，业务错误与重复重试不计数；0 只建立/核对 checkpoint |
| CLI `--checkpoint PATH` | 指定断点文件，仍使用 `--resume` 显式恢复；不同任务 CLI 约定由适配层转换 |
| `has_more_path` | 显式结束字段路径（也可放 pagination 内），返回值必须是 bool；true 而无下一游标会报错，空中间页不会被误认为结束 |
| `stop_on_empty` / 核心 `stop_on_empty` | 默认 true 保留空页结束；false 时由 next_cursor 决定；配置 has_more_path 会优先按结束字段判断 |
| `max_cursor_repeats` / `cursor_retry_delay` | 默认 0 次额外重试、0 秒等待；显式允许当前游标重复时才启用；历史游标循环仍立即失败 |
| `retryable_path` / `max_business_retries` | 业务可重试标记必须是真正的 bool，默认重试 0 次；明确配置 GET 才允许启用重试 |
| `retry_after_ms_path` / `max_retry_wait_ms` | 按业务响应的毫秒等待；默认最大接受等待 60000ms，超限停止并保留旧断点，不缩短等待后提前请求 |

重复游标响应在此核心中属于未接受页：不落盘、不推进游标、不占成功页数。只有确认该接口可这样重试时才启用；若同一游标响应承载独有增量数据，需按契约另写提交策略。HTTP 客户端的旧 `max_retries` 指总尝试次数；上述业务/游标预算指额外重试次数，二者不要混淆。

`templates/python-request/utils/collector.py` 只依赖 Python 标准库。任务要求纯标准库时，可复制该核心并使用 urllib 的 fetch_page 回调；不必为了 CLI 使用 requests 而重写已经验证的断点提交逻辑。字段路径、成功标记、登录/签名及返回格式仍由适配层处理，配置示例不包含站点凭据。

## 自定义签名与分页适配

```python
from utils.collector import collect_to_jsonl
from utils.request import RequestClient

client = RequestClient()

def fetch_page(cursor):
    params = {"page": cursor}
    # 在这里用已验证的签名函数处理 params/body/headers；每次请求现算。
    response = client.get("https://example.test/api/items", params=params)
    payload = response.json()
    if payload["code"] != 0:
        raise ValueError("API business status failed")
    return payload

try:
    result = collect_to_jsonl(
        fetch_page,
        extract_items=lambda payload: payload["data"]["items"],
        next_cursor=lambda payload, current: current + 1 if payload["data"]["has_more"] else None,
        output_path="artifacts/items.jsonl",
        job_key="items-api-v1-signer-v2",  # 语义变化时更新，不填写凭据
        item_key=lambda item: item["id"],
        max_pages=100,
    )
finally:
    client.close()
```

签名函数接收 URL/Body/时间/随机输入的方式由证据确定。不要在通用组件里加入目标域名或固定 Cookie。需要 jsdom/第三方 JS SDK 时在需求项目建立独立签名模块，并用 fixture 验证。

## 恢复语义

每页完整验证并序列化后写 JSONL，flush/fsync 后原子更新 checkpoint。恢复时核对 job key、输出路径、已提交前缀的 SHA-256；未提交的尾部写入会被截除，然后从 checkpoint 的下一游标继续。

- 这是本地输出的页级恢复，不代表远端请求恰好执行一次。崩溃后可能重新请求最后未提交的一页；该回调应为读取操作或具有幂等保证。
- 查询/接口/签名逻辑变化需使用新 job key 或新输出。CLI 配置哈希排除可刷新 Headers/Cookie，但这些字段若代表不同账号/数据范围，应换输出，不能混合数据。
- 为防止两个实例写同一文件，运行持有 `.lock`。强制终止后可能留下 stale lock，确认旧进程已结束再移除锁；不要自动抢锁。
- 去重键和已访问游标存放在 checkpoint，适用于有界任务。大规模长任务应改用数据库索引/任务队列，不能把内存集合称为无限容量。
- 若要求追踪数据更新而不是按主键保留第一次出现，请省略 `item_key` 或按版本构造复合键。

## 捕获样本与独立验签

先在 MCP 中 `network_capture(start)`，触发操作，再 `network_capture(stop, wait_timeout_ms=3000)`。检查 pending、dropped、body_state 和截断元数据后调用 `export_network_capture`。默认导出掩码版，需要原始 Headers/Query/Body 时显式开启并保留在私有目录。

`verify_signer_offline(..., runtime="node")` 不启动浏览器；默认 browser runtime 保留旧行为。独立进程支持异步函数与 `crypto/node:crypto`，有总运行期限；复杂签名工程使用自己的 Node 项目测试入口。两种方式都要求非空 expected，字段缺失不能算通过。

## 改版基线

使用 Skill 的绝对脚本路径，在需求项目根目录执行：

```bash
python /path/to/skill/scripts/project-baseline.py create --root . \
  --files config/sdk.js utils/sign.py fixtures/samples.json \
  --mcp-version 1.6.0 --browser-version 152.0.4-beta.30
python /path/to/skill/scripts/project-baseline.py check --root .
```

脚本只记录相对路径、SHA-256 与版本字符串，不写源码或凭据；不会覆盖已有 manifest。`check` 返回 changed/missing，检测到差异退出码为 1。需要新基线时使用新的 `--manifest` 路径，保留旧版本供比较。版本号由实际运行环境填写，哈希未变仍需行为回归。

## 依赖与离线测试

```bash
python /path/to/skill/scripts/check-deps.py --mode python --json
python /path/to/skill/scripts/check-deps.py --mode browser --json
python test.py
```

`check-deps.sh` 仍可用，通过 `JS_REVERSE_PYTHON` 选择解释器。Node 依赖在复制后的模板目录安装，不假设全局 npm 包可以被项目加载。模板的 `npm test` 和 `node main.js --test` 均为离线测试；它们验证通用组件，不表示目标站点已经采集成功。

读取 JSONL 时按 LF 分隔（例如 Python 逐行迭代文件），不要对整段 Unicode 文本使用 `str.splitlines()`：它也会把字符串值内部的 U+2028 等字符当分隔符。记录内容中的 Unicode 必须原样保留，不能为读日志而改写签名输入或数据。

CLI 为保持既有语义，将下一 cursor 的 null/空字符串视为结束或缺失；若接口允许初始空字符串作为可重试的真实游标，使用核心的自定义 next_cursor 回调明确区分这些状态。CLI 的固定 cursor_retry_delay 也不代替逐响应等待策略，需动态提示时由协议适配层处理。
