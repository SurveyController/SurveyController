<script lang="ts">
  import type { QuickAction } from '../types'
  import AppIcon from './AppIcon.svelte'

  let { action }: { action: QuickAction } = $props()
</script>

<button class:primary={action.emphasis === 'primary'} class="command-button">
  <AppIcon name={action.icon} size={16} />
  <span>{action.label}</span>
</button>
