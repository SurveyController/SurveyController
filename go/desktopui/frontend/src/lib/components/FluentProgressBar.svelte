<script lang="ts">
  let { value = 0 }: { value?: number } = $props()
  const clamped = $derived(Math.max(0, Math.min(100, value)))
</script>

<div class="fluent-progress">
  <div class="fluent-progress__track" style={`width:${clamped}%`}></div>
</div>
