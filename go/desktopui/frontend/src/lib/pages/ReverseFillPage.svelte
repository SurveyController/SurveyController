<script lang="ts">
  import FluentInput from '../components/FluentInput.svelte'
  import FluentToggle from '../components/FluentToggle.svelte'
  import PageHeader from '../components/PageHeader.svelte'
  import { shellState } from '../shell-state.svelte'
</script>

<section class="page reverse-fill-page">
  <PageHeader
    eyebrow="Reverse Fill"
    title="反填"
    description="独立保留旧版反填工作流，不往概览页里硬塞。"
  />

  <div class="dashboard-grid reverse-fill-grid">
    <article class="panel">
      <div class="panel__title">
        <h3>问卷与数据源</h3>
      </div>
      <div class="stack-fields">
        <FluentInput value={shellState.payload.dashboard.surveyUrl} placeholder="问卷链接" />
        <FluentInput value="D:\\data\\answers.xlsx" placeholder="Excel 路径" />
      </div>
    </article>

    <article class="panel">
      <div class="panel__title">
        <h3>执行参数</h3>
      </div>
      <div class="quick-grid">
        <div class="quick-field">
          <span>反填线程数</span>
          <strong>4</strong>
        </div>
        <div class="quick-field quick-field--toggle">
          <div>
            <span>随机 IP</span>
            <span>沿用主页配置</span>
          </div>
          <FluentToggle checked={shellState.payload.dashboard.randomIpEnabled} />
        </div>
      </div>
    </article>

    <article class="panel panel--questions">
      <div class="panel__title">
        <h3>映射预览</h3>
        <span>{shellState.payload.reverseFillPlan.length} 项</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>题目</th>
              <th>列</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {#each shellState.payload.reverseFillPlan as row (`${row.question}-${row.column}`)}
              <tr>
                <td>{row.question}</td>
                <td>{row.column}</td>
                <td>{row.state}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </article>
  </div>
</section>
