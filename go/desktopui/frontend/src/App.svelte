<script lang="ts">
  import { onMount } from 'svelte'
  import { AppService } from '../bindings/github.com/hungrym0/SurveyController/go/desktopui/index.js'
  import AcrylicPane from './lib/components/AcrylicPane.svelte'
  import NavigationRail from './lib/components/NavigationRail.svelte'
  import TitleBar from './lib/components/TitleBar.svelte'
  import DashboardPage from './lib/pages/DashboardPage.svelte'
  import InfoPage from './lib/pages/InfoPage.svelte'
  import ReverseFillPage from './lib/pages/ReverseFillPage.svelte'
  import RuntimePage from './lib/pages/RuntimePage.svelte'
  import SettingsPage from './lib/pages/SettingsPage.svelte'
  import StrategyPage from './lib/pages/StrategyPage.svelte'
  import { loadShellState, shellState } from './lib/shell-state.svelte'

  onMount(async () => {
    const payload = await AppService.GetShellState()
    loadShellState(payload)
  })

  const currentPage = $derived(shellState.payload.currentPage)
  const themeClass = $derived(
    shellState.payload.themeMode === 'dark'
      ? 'fds-theme-dark'
      : shellState.payload.themeMode === 'light'
        ? 'fds-theme-light'
        : ''
  )
</script>

<svelte:head>
  <title>SurveyController Desktop UI</title>
</svelte:head>

<div class={`shell-root ${themeClass}`}>
  <div class="shell-backdrop shell-backdrop--a"></div>
  <div class="shell-backdrop shell-backdrop--b"></div>

  {#if shellState.ready}
    <AcrylicPane class="shell-frame">
      <TitleBar />

      <div class="shell-body">
        <NavigationRail />

        <main class="content-pane">
          {#if currentPage === 'dashboard'}
            <DashboardPage />
          {:else if currentPage === 'runtime'}
            <RuntimePage />
          {:else if currentPage === 'strategy'}
            <StrategyPage />
          {:else if currentPage === 'reverse-fill'}
            <ReverseFillPage />
          {:else if currentPage === 'settings'}
            <SettingsPage />
          {:else if currentPage === 'logs'}
            <InfoPage
              eyebrow="Logs"
              title="日志"
              description="懒加载页先用骨架承接，后面再接结构化日志流。"
              items={shellState.payload.logLines}
            />
          {:else if currentPage === 'community'}
            <InfoPage
              eyebrow="Community"
              title="社区"
              description="保留旧版社区页入口位置，先挂内容列表。"
              items={shellState.payload.communityItems}
            />
          {:else if currentPage === 'more'}
            <InfoPage
              eyebrow="More"
              title="更多"
              description="这里先承接关于、捐助和 IP 使用记录的入口信息。"
              items={[
                ...shellState.payload.aboutItems,
                ...shellState.payload.donateItems,
                ...shellState.payload.ipUsageItems,
              ]}
            />
          {/if}
        </main>
      </div>
    </AcrylicPane>
  {:else}
    <div class="boot-screen">
      <div class="boot-brand">
        <div class="brand-mark">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <strong>SurveyController</strong>
      </div>
      <p>正在加载 WinUI 3 Fluent 壳层...</p>
    </div>
  {/if}
</div>
