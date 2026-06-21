<script lang="ts">
  let {
    value = 0,
    size = 104,
  }: {
    value?: number
    size?: number
  } = $props()

  const clamped = $derived(Math.max(0, Math.min(100, value)))
  const stroke = 8
  const radius = $derived((size - stroke) / 2)
  const circumference = $derived(2 * Math.PI * radius)
  const dashoffset = $derived(circumference * (1 - clamped / 100))
</script>

<svg class="fluent-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
  <defs>
    <linearGradient id="ring-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="var(--accent)"></stop>
      <stop offset="100%" stop-color="var(--accent-2)"></stop>
    </linearGradient>
  </defs>
  <circle
    class="fluent-ring__base"
    cx={size / 2}
    cy={size / 2}
    r={radius}
    stroke-width={stroke}
  ></circle>
  <circle
    class="fluent-ring__value"
    cx={size / 2}
    cy={size / 2}
    r={radius}
    stroke-width={stroke}
    stroke-dasharray={circumference}
    stroke-dashoffset={dashoffset}
  ></circle>
</svg>
