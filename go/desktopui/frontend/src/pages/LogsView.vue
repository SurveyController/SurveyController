<script setup lang="ts">
defineProps<{
  logs: string[]
}>()
</script>

<template>
  <section class="min-h-0 flex-1 overflow-y-auto p-3">
    <div class="panel mx-auto max-w-5xl overflow-hidden">
      <div class="section-title">日志</div>
      <div class="space-y-1.5 p-3 font-mono text-[11px] text-slate-700 dark:text-slate-300">
        <div v-for="line in logs" :key="line" class="rounded-md bg-slate-50 px-2.5 py-1.5 dark:bg-slate-900">{{ line }}</div>
      </div>
    </div>
  </section>
</template>
