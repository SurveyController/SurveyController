<div align="center">
  <img src="assets/icon.png" alt="SurveyController" width="120" height="120" />
  <h1>SurveyController</h1>
  
  [![GitHub Stars](https://img.shields.io/github/stars/SurveyController/SurveyController?style=flat&logo=github&color=yellow)](https://github.com/SurveyController/SurveyController/stargazers)
  [![Contributors](https://img.shields.io/github/contributors/SurveyController/SurveyController?style=flat&logo=github)](https://github.com/SurveyController/SurveyController/graphs/contributors)
  [![GitHub Release](https://img.shields.io/github/v/release/SurveyController/SurveyController?style=flat&logo=github&color=blue)](https://github.com/SurveyController/SurveyController/releases/latest)
  ![Downloads](https://img.shields.io/github/downloads/SurveyController/SurveyController/total?style=flat&logo=github&color=green)
  [![Issues](https://img.shields.io/github/issues/SurveyController/SurveyController?style=flat&logo=github)](https://github.com/SurveyController/SurveyController/issues)
  [![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
  [![License](https://img.shields.io/github/license/SurveyController/SurveyController?style=flat&color=orange)](./LICENSE)

  <p><strong>一站式问卷自动化处理程序，适配问卷星、腾讯问卷、Credamo见数平台</strong></p>
  <p>支持指定ip填写地区、信度系数、作答时长与分布比例</p>
  
</div>

> [!WARNING]
> **该项目仅供 Playwright 自动化学习与测试使用。** 请确保拥有目标测试问卷的授权再使用，**严禁污染他人问卷数据！**

---

## 主要特性

1. **多平台支持** - 同时支持问卷星、腾讯问卷、Credamo见数平台，一套工具搞定三个平台
2. **Fluent 界面** - 无需复杂配置，通过可视化UI完成所有操作
3. **支持二维码解析** - 拖入问卷二维码图片自动转链接
4. **定制答案比例** - 支持自定义各选项权重与多选题命中概率分布
5. **指定ip地区** - 支持随机IP或指定特定地区IP提交
6. **配置导入导出** - 保存配置文件便于后续复用，跨设备同步
7. **AI 主观题作答** - 填空题自动生成作答内容（限时免费），由 [@dAwn-Rebirth](https://github.com/dAwn-Rebirth) 和 [@LING71671](https://github.com/LING71671) 贡献

## 开始使用

> [!TIP]
> **安装包：** 前往 [发行版](https://github.com/SurveyController/SurveyController/releases/latest) 下载最新版本 .exe 安装包，安装后直接运行即可

建议配合[教程文档](https://surveydoc.hungrym0.com/)食用。二开可前往 [SurveyCore](https://github.com/SurveyController/SurveyCore)

### 从源码运行

**环境要求：** Windows 10/11，Python 3.11+，Git，Microsoft Edge

### <summary>Windows 使用</summary>
<details>

克隆、安装依赖、运行源码：
```bash
git clone https://github.com/SurveyController/SurveyController.git
cd SurveyController
uv sync
uv run python SurveyController.py
```

如果还没装 `uv`，先执行：
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
</details>

## Mac 系统支持

如果你需要查看支持 macOS 系统的源码，请切换到 [main 分支](https://github.com/SurveyController/SurveyController/tree/main)。

**分支由社区维护，不受长期支持。**

## 使用方法

1. **输入问卷** - 粘贴问卷链接，或上传/拖入二维码图片
2. **自动解析** - 点击 `自动配置问卷`，自动识别平台和题目结构
3. **调整配置** - 在配置向导中，拖动滑块对各题设置答案权重和概率分布
4. **设置运行参数** - 指定目标提交份数、并发浏览器数、随机IP等设置项
5. **启动任务** - 点击 `开始执行` 并等待任务完成

## 关键配置说明

| 配置项 | 说明 |
|--------|------|
| **目标份数** | 计划提交的问卷总数。建议先测试 3~5 份，确认配置没问题后再增加 |
| **并发浏览器数** | 同时运行的浏览器会话数量。并发越高速度越快，但失败率也可能更高 |
| **AI 填空** | 开启后可自动生成填空题内容。需要先确认 AI 配置可用 |
| **随机 IP** | 使用代理 IP 模拟不同地区访问。会消耗随机 IP 额度或自备代理资源 |
| **User-Agent** | 浏览器标识字符串，决定问卷后台看到的访问设备来源 |
| **作答时长** | 控制每份问卷提交时的作答时长参数 |

详细配置项请参考[教程文档](https://surveydoc.hungrym0.com/runtime.html)。

## ~~技术架构~~ 屎山预览

```mermaid
flowchart TB
  ui["PySide6 / QFluentWidgets 界面"]
  config["执行配置<br/>题目权重 / AI 填空 / 作答时长 / 并发 / 代理"]
  engine_client["AsyncEngineClient<br/>UI 同步入口"]
  engine["AsyncRuntimeEngine<br/>后台 asyncio 事件循环"]
  registry["Provider Registry<br/>平台识别和适配器分发"]
  cache["Survey Cache<br/>URL 归一化 / singleflight / 本地缓存"]
  http["httpx 客户端<br/>解析接口 / 缓存指纹 / 代理服务"]
  scheduler["AsyncScheduler<br/>并发令牌 / 延迟重排"]
  proxy["代理和 UA 策略<br/>代理池 / 可用性检测 / 会话上报"]
  browser_pool["AsyncBrowserOwnerPool<br/>Microsoft Edge owner / context 池"]
  status["AsyncStatusBus<br/>线程状态 / 进度 / 停止信号"]
  submit_service["SubmissionService<br/>完成页 / 验证 / 补答恢复 / 失败归因"]
  result["执行结果<br/>成功 / 失败 / 暂停 / 停止"]

  ui --> config --> engine_client --> engine
  engine_client --> registry
  registry --> cache --> http
  engine --> scheduler
  engine --> browser_pool
  engine --> status
  scheduler --> proxy
  proxy --> browser_pool
  browser_pool --> registry
  registry --> submit_service --> result
  status --> ui

  subgraph providers["平台 provider"]
    wjx["问卷星<br/>HTML 解析 / 分页答题 / 提交验证恢复"]
    qq["腾讯问卷<br/>API 解析 / 页面批量答题 / 安全验证识别"]
    credamo["Credamo 见数<br/>detail 接口解析 / DOM 动态题目 / 免登录问卷"]
  end

  registry --> wjx
  registry --> qq
  registry --> credamo
  wjx --> browser_pool
  qq --> browser_pool
  credamo --> browser_pool
  wjx --> http
  qq --> http
  credamo --> http
```

```mermaid
sequenceDiagram
  participant UI as 界面
  participant C as AsyncEngineClient
  participant E as AsyncRuntimeEngine
  participant R as Provider Registry
  participant Cache as Survey Cache
  participant HTTP as httpx
  participant Pool as Edge 会话池
  participant P as 平台 Provider
  participant S as SubmissionService

  UI->>C: 解析问卷或启动任务
  C->>E: 投递到后台 asyncio loop
  E->>R: parse_survey(url)
  R->>Cache: 查询解析缓存
  Cache->>HTTP: 缓存缺失时拉取页面或接口
  HTTP-->>Cache: 返回 HTML / JSON / 指纹
  Cache-->>R: SurveyDefinition
  R-->>UI: 标准题目结构
  UI->>C: start_run(config, state)
  C->>E: 创建 stop / pause / status 上下文
  E->>Pool: 按并发启动 Microsoft Edge owner/context
  E->>P: 按 provider 分发 fill_survey
  P->>Pool: 页面加载、批量答题、翻页、提交
  P-->>E: 本轮作答完成
  E->>S: 提交后结果判定
  S-->>E: 成功、验证、失败或重试策略
  E-->>UI: 状态、进度和终止原因
```

## 交流群

如有疑问或需要技术支持，可加入QQ群：
346131215

<img width="256" alt="qq" src="assets/community_qr.jpg" />

## 参与贡献

欢迎提交 Pull Request，改进方向包括但不限于：
- 增加对更多题型的支持
- 增加对更多问卷平台的支持
- 性能优化与代码重构

## 贡献者

感谢以下贡献者对本项目的支持：

<div style="display: flex; gap: 10px;">
  <a href="https://github.com/shiaho777">
    <img src="https://github.com/shiaho777.png" width="50" height="50" alt="shiaho777" style="border-radius: 50%;" />
  </a>
  <a href="https://github.com/BingBuLiang">
    <img src="https://github.com/BingBuLiang.png" width="50" height="50" alt="BingBuLiang" style="border-radius: 50%;" />
  </a>
  <a href="https://github.com/dAwn-Rebirth">
    <img src="https://github.com/dAwn-Rebirth.png" width="50" height="50" alt="dAwn-Rebirth" style="border-radius: 50%;" />
  </a>
  <a href="https://github.com/Moyuin-aka">
    <img src="https://github.com/Moyuin-aka.png" width="50" height="50" alt="Moyuin-aka" style="border-radius: 50%;" />
  </a>
  <a href="https://github.com/zioug">
    <img src="https://github.com/zioug.png" width="50" height="50" alt="zioug" style="border-radius: 50%;" />
  </a>
  <a href="https://github.com/qintaiyang">
    <img src="https://github.com/qintaiyang.png" width="50" height="50" alt="qintaiyang" style="border-radius: 50%;" />
  </a>
  <a href="https://github.com/LING71671">
    <img src="https://github.com/LING71671.png" width="50" height="50" alt="LING71671" style="border-radius: 50%;" />
  </a>
</div>

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=SurveyController/SurveyController&type=date&legend=top-left)](https://www.star-history.com/#SurveyController/SurveyController&type=date&legend=top-left)
