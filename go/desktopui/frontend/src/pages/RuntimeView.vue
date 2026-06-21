<script setup lang="ts">
import SettingField from '../components/SettingField.vue'
import type { SettingsGroup } from '../types'

defineProps<{
  groups: SettingsGroup[]
}>()
</script>

<template>
  <section class="min-h-0 flex-1 overflow-y-auto p-5">
    <div class="mx-auto max-w-4xl space-y-5">
      <div v-for="group in groups" :key="group.title" class="panel overflow-hidden">
        <div class="section-title">{{ group.title }}</div>
        <div class="px-4">
          <SettingField v-for="field in group.fields" :key="field.id" :field="field" />
        </div>
      </div>
    </div>
  </section>
</template>
