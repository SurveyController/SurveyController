<script setup lang="ts">
import SettingField from '../components/SettingField.vue'
import type { SettingsGroup } from '../types'

defineProps<{
  groups: SettingsGroup[]
}>()

const emit = defineEmits<{
  fieldChange: [id: string, value: string | boolean]
}>()
</script>

<template>
  <section class="min-h-0 flex-1 overflow-y-auto p-3">
    <div class="mx-auto max-w-4xl space-y-3">
      <div v-for="group in groups" :key="group.title" class="panel overflow-hidden">
        <div class="section-title">{{ group.title }}</div>
        <div class="px-3">
          <SettingField
            v-for="field in group.fields"
            :key="field.id"
            :field="field"
            @change="(id, value) => emit('fieldChange', id, value)"
          />
        </div>
      </div>
    </div>
  </section>
</template>
