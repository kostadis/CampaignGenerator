<script setup lang="ts">
import { ref } from 'vue'
import { apiFetch } from '../../api/client'
import StreamOutput from '../shared/StreamOutput.vue'

const props = defineProps<{
  output: string
  currentScene: number | null
}>()

const emit = defineEmits<{
  clear: []
}>()

const rawVisible = ref(false)
const rawPreview = ref('')

async function toggleRaw() {
  rawVisible.value = !rawVisible.value
  if (!rawVisible.value || props.currentScene === null) return
  try {
    const data = await apiFetch(`/api/editor/raw/${props.currentScene}`)
    rawPreview.value = data.exists ? data.preview : '(no output file yet)'
  } catch {
    rawPreview.value = '(no output file yet)'
  }
}
</script>

<template>
  <div class="narration-panel">
    <div class="narration-header">
      <span>Narration output</span>
      <span style="flex:1"></span>
      <button class="btn-neutral btn-sm" @click="toggleRaw" :disabled="currentScene === null">
        {{ rawVisible ? 'Hide raw' : 'Raw' }}
      </button>
      <button class="btn-neutral btn-sm" @click="emit('clear')" style="margin-left:4px">Clear</button>
    </div>
    <div v-if="rawVisible" class="raw-preview">{{ rawPreview }}</div>
    <StreamOutput :text="output" />
  </div>
</template>

<style scoped>
.narration-panel {
  height: 220px;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  border-top: 2px solid var(--bg-surface0);
}
.narration-header {
  background: var(--bg-mantle);
  padding: 5px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.narration-header span {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
}
.raw-preview {
  padding: 8px 14px;
  background: #0d0d1a;
  border-bottom: 1px solid var(--bg-surface0);
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-muted);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 120px;
  overflow-y: auto;
}
</style>
