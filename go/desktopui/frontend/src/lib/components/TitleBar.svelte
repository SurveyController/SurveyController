<script lang="ts">
  import { shellState, cycleThemeMode } from '../shell-state.svelte'
  import WindowControls from './WindowControls.svelte'
  import AppIcon from './AppIcon.svelte'
</script>

<header class="titlebar">
  <div class="titlebar__brand">
    <div class="brand-mark">
      <span></span>
      <span></span>
      <span></span>
    </div>
    <div class="brand-copy">
      <strong>{shellState.payload.appTitle}</strong>
      <span>Fluent Shell</span>
    </div>
  </div>

  <div class="titlebar__actions">
    <button class="theme-button" title="切换主题模式" onclick={cycleThemeMode}>
      <AppIcon name="sliders" size={15} />
      <span>{shellState.payload.themeMode}</span>
    </button>
    <WindowControls />
  </div>
</header>
