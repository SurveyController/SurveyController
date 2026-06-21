<script lang="ts">
  import type { Tone } from '../types'

  let {
    tone = 'warning',
    class: className = '',
    children,
  }: {
    tone?: Tone
    class?: string
    children?: import('svelte').Snippet
  } = $props()
</script>

<span class={`fluent-badge fluent-badge--${tone || 'warning'} ${className}`}>
  {@render children?.()}
</span>
