<script lang="ts">
  let {
    class: className = '',
    children,
  }: {
    class?: string
    children?: import('svelte').Snippet
  } = $props()
</script>

<div class={`acrylic-pane ${className}`}>
  {@render children?.()}
</div>
