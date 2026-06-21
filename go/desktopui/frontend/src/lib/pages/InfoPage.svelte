<script lang="ts">
  import PageHeader from '../components/PageHeader.svelte'
  import type { PageMetric } from '../types'

  let {
    title,
    eyebrow,
    description,
    items,
  }: {
    title: string
    eyebrow: string
    description: string
    items: PageMetric[] | string[]
  } = $props()
</script>

<section class="page info-page">
  <PageHeader {eyebrow} {title} {description} />

  <article class="panel">
    <div class="info-list">
      {#each items as item, index (typeof item === 'string' ? item : `${item.label}-${index}`)}
        {#if typeof item === 'string'}
          <div class="info-row">
            <strong>{item}</strong>
          </div>
        {:else}
          <div class="info-row">
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        {/if}
      {/each}
    </div>
  </article>
</section>
