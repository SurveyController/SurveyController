<script lang="ts">
  let { checked = false }: { checked?: boolean } = $props()
</script>

<button
  class:checked
  class="fluent-toggle"
  type="button"
  aria-pressed={checked}
  aria-label={checked ? '已启用' : '已关闭'}
>
  <span></span>
</button>
