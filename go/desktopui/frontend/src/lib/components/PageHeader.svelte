<script lang="ts">
  let {
    eyebrow = '',
    title,
    description = '',
  }: {
    eyebrow?: string
    title: string
    description?: string
  } = $props()
</script>

<div class="page-header">
  {#if eyebrow}
    <span class="page-header__eyebrow">{eyebrow}</span>
  {/if}
  <h1>{title}</h1>
  {#if description}
    <p>{description}</p>
  {/if}
</div>
