# 真实开源源码的本地实战

本组案例使用实际 GitHub 项目的编译器、解释器和 SDK；业务请求与风控服务在本地模拟。不要把本地通过写成某商业站点的风控绕过成功率。

| 场景 | 固定上游 | 当前执行路径 |
|---|---|---|
| JSVMP | KProtect `da4ea8a3095a14dbb7cdf3126cb9cc2e076fdf2a` | 真实编译器产生字节码，原解释器执行；包含未修改的上游子串用例和自写业务输入 |
| 控制流平坦化 | javascript-obfuscator 4.1.1 `828a190cf80a86227ef77be38e99aad9838aed70` | 真正 obfuscate 输出，与关闭 CFF 的控制组、原函数对比，核对分派器结构 |
| 加解密 | CryptoJS 4.2.0 `808f499ec789fcd68416328a40b8735a5c962116` | AES-256-CBC/PKCS7 与 HMAC-SHA256，请求/响应方向独立密钥，由 Node/Python 独立验证 |
| 指纹与原生 trace | FingerprintJS 5.2.0 `e196578ba35362fdf15647e013d66ac28b3c9fb5` | monitoring=false、局部组件与完整结果区分，定制浏览器真实77点追踪 |

复现入口：[准备与真实 MCP 验证](../scripts/real_cases/README.md)。完整来源链接、实操结果及失败边界见配套 MCP 的[验证记录](https://github.com/WhiteNightShadow/camoufox-reverse-mcp/blob/v1.8.0/docs/REAL_SOURCE_VALIDATION.md)。

## 取证与执行

1. 先保存未经改写的源码、来源commit和哈希；对真实 VM 输出核对编译器/字节码/解释器来源，不能把手写 switch 当成上游 VM。
2. 原始产物先运行并与基线比对，再安装 Hook/源码插桩。编译器本身也可能有不支持的语法或语义差异，先区分上游产物问题与观测导致的问题。
3. VM/CFF 公共函数可用主世界 hook_function；闭包内 VM 的 PC/堆栈等不能假定挂在 window，可按实际源码定位后做选择性源码插桩。
4. instrumentation 的 log 从页面主世界读取；SDK 在 iframe 中时传相应 frame_url/frame_name/frame_index。源码已改写、tap标记存在但默认页无日志时，先确认 Frame 与世界，不立即换算法或把空日志当未执行。
5. 属性过滤同时约束方法调用；filter_object_names支持this.bytecode等静态对象路径，不解析动态对象表达式。大文件优先按属性过滤并设置 rewrite_calls=False；确认需要后再扩大。日志达到容量时保留 possibly_capped，不根据缺失尾部事件下否定结论。
6. 精确保留字符串时可用evaluate_js(result_format="json_ascii")，返回ASCII JSON文本后再在本地解码；NaN/Infinity/-0/undefined等需先显式标签化，JSON本身不保留这些区别。默认auto仍保留旧清洗行为，value_raw也不能恢复传输中已被替换的代理项。执行或序列化失败不会自动重放表达式。比较改写前后的结果、异常、参数/状态副作用、this 与随机源调用次数；日志默认只预览primitive，对象/函数为类型占位，不能将占位看成真实 I/O。需要对象字段时做明确、受控的单独采样。函数Hook可选serialization="preview"避免对象getter/toJSON；默认json为兼容旧用法仍可能有序列化副作用。同步throw应检查outcome="throw"与thrownValue字段；completion="sync"仅记录同步调用结束，Promise返回不能视为settled成功。
7. AST 优先使用本地 esprima；现代语法可通过本地 Node 和随MCP打包的Acorn解析，不需页面CDN。正则模式不支持属性/对象过滤，非空过滤会明确拒绝并提示使用AST；正则降级只支持明确子集，跳过时检查 last_skip_reason，不能把 files_seen 当真正改写成功。
8. 纯协议交付可复用捕获到的真实 VM/SDK，在独立 Node 环境提供明确输入，验证新的输入和状态变化。禁止只回放已捕获答案。

跨导航的get_trace_data可能包含保留的旧调用，相同URL不代表同一次页面生命周期；结合帧、时间和callIndex区分，必要时先保存再清理本任务日志。

## Crypto 与本地风控

明确原始key/口令、AES模式、IV、padding、编码及MAC覆盖范围。CryptoJS的WordArray和CipherParams不是普通字符串；不要把OpenSSL口令格式与裸ciphertext混用。响应先认证再解密，期望上下文来自本地保存的请求，不能从收到的响应反推。

本地模拟检查 challenge、时间窗、nonce重放、指纹绑定及应答一致性。至少验证正常往返、MAC/密文篡改、过期、重放、指纹变化、错误应答，并核对拒绝未消费合法状态。公开演示key仅用于样例，不提供真实身份认证保证。

## 指纹 trace 的证据边界

- 必须选择真实定制版并检查 engine_trace.enabled/acknowledged，官方版不可用时要明确失败，不能用JS日志假冒原生记录。
- 记录空白操作窗口与SDK采集窗口；比较前后应使用同一浏览器配置。不同launch可生成不同指纹，不能把跨配置差异归因于trace。
- 普通JS读次数不等于native getter调用次数，缓存/JIT可能合并。一次循环读100次userAgent而仅一个native事件，不足以认定丢失99条。
- 原生77点覆盖DOM/Web API，不包含所有JS对象访问或VM opcode。只有已确认命中可作正证据；缺失与达到cap均有明确限制。
- snapshot_values是stop之后在当前活动页面主Frame、隔离世界中的安全快照，不是事件发生时或事件所在窗口的值；查看snapshot_context。Cookie/Canvas/WebGL/Audio等路径可能跳过。未知项保留未知。
- 检查多实例run隔离、clear/stop后其他实例继续可用，避免全局清理影响其他任务。

许可证与资产：VM上游为GPL，CFF工具为BSD-2-Clause，CryptoJS/FingerprintJS为MIT。测试资产单独下载并保留来源/许可证；MCP通用实现不捆绑GPL解释器。源码级观测会改变源码和耗时，不承诺不可检测或全程序等价。
