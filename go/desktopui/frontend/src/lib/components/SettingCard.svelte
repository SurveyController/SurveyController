<script lang="ts">
  import FluentToggle from './FluentToggle.svelte'
  import type { SettingField } from '../types'

  let { field }: { field: SettingField } = $props()

  const isChecked = $derived(field.value === 'true')
</script>

<article class="setting-card">
  <div class="setting-card__copy">
    <strong>{field.label}</strong>
    <p>{field.description}</p>
  </div>

  <div class="setting-card__control">
    {#if field.kind === 'toggle'}
      <FluentToggle checked={isChecked} />
    {:else if field.kind === 'select'}
      <button class="select-chip">{field.value}</button>
    {:else}
      <span class="value-chip">{field.value}</span>
    {/if}
  </div>
</article>
