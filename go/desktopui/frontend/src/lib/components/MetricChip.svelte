<script lang="ts">
  import type { PageMetric } from '../types'

  let { metric }: { metric: PageMetric } = $props()
</script>

<div class:success={metric.tone === 'success'} class:warning={metric.tone === 'warning'} class:danger={metric.tone === 'danger'} class="metric-chip">
  <span>{metric.label}</span>
  <strong>{metric.value}</strong>
</div>
