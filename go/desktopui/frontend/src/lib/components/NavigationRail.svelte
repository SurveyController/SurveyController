<script lang="ts">
  import FluentBadge from './FluentBadge.svelte'
  import { shellState, setCurrentPage } from '../shell-state.svelte'
  import type { NavItem } from '../types'
  import AppIcon from './AppIcon.svelte'

  const topItems = $derived(shellState.payload.topNav)
  const bottomItems = $derived(shellState.payload.bottomNav)

  function activate(item: NavItem) {
    setCurrentPage(item.id)
  }
</script>

<aside class="nav-rail">
  <div class="nav-rail__top">
    {#each topItems as item (item.id)}
      <button
        class:selected={item.selected}
        class="nav-item"
        onclick={() => activate(item)}
      >
        <span class="nav-item__icon">
          <AppIcon name={item.icon} />
        </span>
        <span class="nav-item__label">{item.label}</span>
        {#if item.badge}
          <FluentBadge class="nav-item__badge">{item.badge}</FluentBadge>
        {/if}
      </button>
    {/each}
  </div>

  <div class="nav-rail__bottom">
    {#each bottomItems as item (item.id)}
      <button class="nav-item" onclick={() => activate(item)}>
        <span class="nav-item__icon">
          <AppIcon name={item.icon} />
        </span>
        <span class="nav-item__label">{item.label}</span>
      </button>
    {/each}
  </div>
</aside>
