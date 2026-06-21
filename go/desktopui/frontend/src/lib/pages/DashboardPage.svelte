<script lang="ts">
  import FluentInput from '../components/FluentInput.svelte'
  import FluentProgressBar from '../components/FluentProgressBar.svelte'
  import FluentProgressRing from '../components/FluentProgressRing.svelte'
  import FluentSegmentedControl from '../components/FluentSegmentedControl.svelte'
  import FluentToggle from '../components/FluentToggle.svelte'
  import { shellState } from '../shell-state.svelte'
  import CommandButton from '../components/CommandButton.svelte'
  import MetricChip from '../components/MetricChip.svelte'
  import PageHeader from '../components/PageHeader.svelte'

  let segment = $state<'questions' | 'sessions'>('questions')
  const dashboard = $derived(shellState.payload.dashboard)
</script>

<section class="page dashboard-page">
  <PageHeader
    eyebrow="Workbench"
    title="概览"
    description="复刻旧 QFluentWidgets 主工作台的信息密度和层级。先保留壳，后面再接 Go 核心。"
  />

  <div class="hero-card">
    <div class="hero-card__copy">
      <span class="platform-pill">{dashboard.platformLabel}</span>
      <h2>{dashboard.surveyTitle}</h2>
      <p>状态：{dashboard.statusText}</p>
    </div>
    <div class="hero-card__metrics">
      {#each dashboard.metrics as metric (metric.label)}
        <MetricChip {metric} />
      {/each}
    </div>
  </div>

  <div class="dashboard-grid">
    <article class="panel panel--url">
      <div class="panel__title">
        <h3>问卷入口</h3>
        <div class="command-row">
          {#each dashboard.quickActions as action (action.id)}
            <CommandButton {action} />
          {/each}
        </div>
      </div>
      <div class="panel__body">
        <FluentInput value={dashboard.surveyUrl} placeholder="请输入问卷链接" />
      </div>
    </article>

    <article class="panel panel--quick">
      <div class="panel__title">
        <h3>快捷设置</h3>
        <span>{dashboard.targetCount} 目标份数</span>
      </div>
      <div class="quick-grid">
        <div class="quick-field">
          <span>目标份数</span>
          <strong>{dashboard.targetCount}</strong>
        </div>
        <div class="quick-field">
          <span>并发数</span>
          <strong>{dashboard.threadCount}</strong>
        </div>
        <div class="quick-field quick-field--toggle">
          <div>
            <span>随机 IP</span>
            <span>{dashboard.proxySource} 代理源</span>
          </div>
          <FluentToggle checked={dashboard.randomIpEnabled} />
        </div>
      </div>
    </article>

    <article class="panel panel--quota">
      <div class="panel__title">
        <h3>随机 IP 额度</h3>
        <span class={`tone-${dashboard.randomIpStatusTone}`}>{dashboard.randomIpStatus}</span>
      </div>
      <div class="quota-layout">
        <div class="quota-ring">
          <FluentProgressRing size={104} value={dashboard.randomIpQuota} />
          <strong>{dashboard.randomIpQuota}%</strong>
        </div>
        <div class="quota-copy">
          <p>{dashboard.randomIpQuotaLabel}</p>
          <button class="link-button">额度兑换</button>
        </div>
      </div>
    </article>

    <article class="panel panel--questions">
      <div class="panel__title">
        <h3>题目清单与会话进度</h3>
        <FluentSegmentedControl
          value={segment}
          options={[
            { value: 'questions', label: '题目清单' },
            { value: 'sessions', label: '会话进度' },
          ]}
        />
      </div>

      {#if segment === 'questions'}
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>序号</th>
                <th>类型</th>
                <th>维度</th>
                <th>策略</th>
              </tr>
            </thead>
            <tbody>
              {#each dashboard.questionRows as row (row.index)}
                <tr>
                  <td>{row.index}</td>
                  <td>{row.type}</td>
                  <td>{row.dimension}</td>
                  <td>{row.strategy}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else}
        <div class="session-list">
          {#each dashboard.sessionRows as row (row.thread)}
            <div class="session-card">
              <div class="session-card__head">
                <strong>{row.thread}</strong>
                <span>{row.status}</span>
              </div>
              <FluentProgressBar value={row.progress} />
            </div>
          {/each}
        </div>
      {/if}
    </article>

    <article class="panel panel--status">
      <div class="panel__title">
        <h3>运行状态</h3>
        <span>{dashboard.progressCurrent}/{dashboard.progressTarget}</span>
      </div>
      <div class="status-block">
        <FluentProgressBar value={dashboard.progressPercent} />
        <strong>{dashboard.progressPercent}%</strong>
      </div>
    </article>
  </div>
</section>
