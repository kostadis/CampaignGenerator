<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { apiFetch } from '../../api/client'

interface Chunk {
  name: string
  content: string
}

const chunks = ref<Chunk[]>([])

onMounted(async () => {
  try {
    const data = await apiFetch('/api/editor/vtt')
    chunks.value = data.chunks
  } catch (e) {
    console.error('Failed to load VTT chunks:', e)
  }
})
</script>

<template>
  <div class="vtt-scroll">
    <p v-if="chunks.length === 0" class="loading">Loading...</p>
    <div v-for="c in chunks" :key="c.name" class="vtt-chunk">
      <h3>{{ c.name }}</h3>
      <pre>{{ c.content }}</pre>
    </div>
  </div>
</template>

<style scoped>
.vtt-scroll { flex: 1; overflow-y: auto; padding: 0 12px 12px; }
.loading { color: var(--text-muted); font-size: 12px; padding: 8px 0; }

.vtt-chunk { margin-bottom: 16px; }
.vtt-chunk h3 {
  font-size: 11px;
  font-weight: 600;
  color: var(--blue);
  margin-bottom: 5px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--bg-surface0);
}
.vtt-chunk pre {
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-sub);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--mono);
  margin: 0;
}
</style>
