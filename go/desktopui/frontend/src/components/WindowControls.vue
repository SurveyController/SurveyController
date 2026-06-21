<script setup lang="ts">
import { ref } from 'vue'
import { Minus, Square, X } from '@lucide/vue'
import { Window } from '@wailsio/runtime'

const maximised = ref(false)

async function syncMaximised() {
  maximised.value = await Window.IsMaximised()
}

async function toggleMaximise() {
  if (await Window.IsMaximised()) {
    await Window.Restore()
  } else {
    await Window.Maximise()
  }
  await syncMaximised()
}

void syncMaximised()
</script>

<template>
  <div class="flex h-11 items-center">
    <button class="titlebar-button" title="最小化" @click="Window.Minimise()">
      <Minus :size="15" />
    </button>
    <button class="titlebar-button" :title="maximised ? '还原' : '最大化'" @click="toggleMaximise">
      <Square :size="13" />
    </button>
    <button class="titlebar-button hover:bg-red-500 hover:text-white" title="关闭" @click="Window.Close()">
      <X :size="16" />
    </button>
  </div>
</template>
