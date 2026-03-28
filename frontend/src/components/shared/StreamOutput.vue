<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

const props = defineProps<{
  text: string
  color?: string
}>()

const el = ref<HTMLElement>()

watch(() => props.text, async () => {
  await nextTick()
  if (el.value) {
    el.value.scrollTop = el.value.scrollHeight
  }
})
</script>

<template>
  <pre ref="el" class="stream-output" :style="{ color: color || 'var(--green)' }">{{ text }}</pre>
</template>

<style scoped>
.stream-output {
  flex: 1;
  overflow-y: auto;
  padding: 10px 14px;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  background: #141420;
  margin: 0;
}
</style>
