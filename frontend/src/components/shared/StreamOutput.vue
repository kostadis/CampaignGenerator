<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'

const props = defineProps<{
  text: string
  color?: string
}>()

const el = ref<HTMLElement>()
const codexRunIdentity = computed(() =>
  props.text.split(/\r?\n/).find(line => line.startsWith('Codex run:')) || '',
)

watch(() => props.text, async () => {
  await nextTick()
  if (el.value) {
    el.value.scrollTop = el.value.scrollHeight
  }
})
</script>

<template>
  <div class="stream-shell">
    <div v-if="codexRunIdentity" class="run-identity">{{ codexRunIdentity }}</div>
    <pre ref="el" class="stream-output" :style="{ color: color || 'var(--green)' }">{{ text }}</pre>
  </div>
</template>

<style scoped>
.stream-shell { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.run-identity {
  padding: 6px 14px;
  color: var(--mauve);
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface1);
  font-family: var(--mono);
  font-size: 11px;
}
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
