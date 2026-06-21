<script lang="ts">
  let {
    value,
    options,
  }: {
    value: string
    options: Array<{ value: string; label: string }>
  } = $props()
</script>

<div class="fluent-segmented" role="tablist" aria-label="section switch">
  {#each options as option (option.value)}
    <button
      class:selected={option.value === value}
      class="fluent-segmented__item"
      type="button"
    >
      {option.label}
    </button>
  {/each}
</div>
