<script lang="ts">
  import { Window } from '@wailsio/runtime'
  import AppIcon from './AppIcon.svelte'

  let maximised = $state(false)

  async function syncMaximised() {
    maximised = await Window.IsMaximised()
  }

  async function toggleMaximise() {
    if (await Window.IsMaximised()) {
      await Window.Restore()
    } else {
      await Window.Maximise()
    }
    await syncMaximised()
  }

  async function minimise() {
    await Window.Minimise()
  }

  async function close() {
    await Window.Close()
  }

  $effect(() => {
    syncMaximised()
  })
</script>

<div class="window-controls">
  <button class="window-button" title="最小化" onclick={minimise}>
    <AppIcon name="min" size={14} />
  </button>
  <button class="window-button" title={maximised ? '还原' : '最大化'} onclick={toggleMaximise}>
    <AppIcon name={maximised ? 'restore' : 'max'} size={14} />
  </button>
  <button class="window-button danger" title="关闭" onclick={close}>
    <AppIcon name="close" size={14} />
  </button>
</div>
