<script lang="ts">
  import { icons } from '../icons'

  let {
    name,
    size = 18,
    stroke = 1.6,
    class: className = '',
  }: {
    name: string
    size?: number
    stroke?: number
    class?: string
  } = $props()

  const path = $derived(icons[name] ?? icons.grid)
</script>

<svg
  class={className}
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width={stroke}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  <path d={path}></path>
</svg>
