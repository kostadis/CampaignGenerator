<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useConfigStore } from '../../stores/config'
import { useEnsembleRun, readEnsembleConfig, type EnsembleConfig } from './useEnsembleRun'
import StreamOutput from '../../components/shared/StreamOutput.vue'
import RunCommandBar from '../../components/shared/RunCommandBar.vue'
import ChapterPicker from './ChapterPicker.vue'

const emit = defineEmits<{ changed: [] }>()
const config = useConfigStore()
const cfg = ref<EnsembleConfig>(readEnsembleConfig({}))
const { output, status, returnCode, command, run, abort, clear } = useEnsembleRun()

onMounted(async () => {
  await config.load()
  cfg.value = readEnsembleConfig(config.resolved)
})

const backendLabel = computed(() => cfg.value.extract.backend)
// Principle X — what runs is exactly what was explicitly selected. No glob
// fallback: an empty selection cannot start a run.
const selectedCount = computed(() => cfg.value.chapters_selected.length)
const canRun = computed(() => selectedCount.value > 0)

async function persistChapters() {
  await config.updateSection('ensemble', {
    chapters_glob: cfg.value.chapters_glob,
    chapters_selected: cfg.value.chapters_selected,
  })
}

function start() {
  if (!canRun.value) return
  run('/api/ensemble/run/extract', {
    chapters: cfg.value.chapters_selected,
    backend: cfg.value.extract.backend,
    endpoints: cfg.value.extract.endpoints,
    model: cfg.value.extract.model,
  }, (rc) => { if (rc === 0) emit('changed') })
}
</script>

<template>
  <div class="step">
    <h2>Stage 1 — Extraction</h2>
    <p class="hint">
      Runs <code>ensemble_batch.py</code> over the chapters you pick below. Resumable:
      chapters already extracted are skipped. Backend: <strong>{{ backendLabel }}</strong>
      (change it on the Setup step). Writes
      <code>docs/ensemble/per_chapter/*/merged.json</code>.
    </p>

    <ChapterPicker
      v-model:glob="cfg.chapters_glob"
      v-model:selected="cfg.chapters_selected"
      @update:glob="persistChapters"
      @update:selected="persistChapters" />

    <RunCommandBar :command="command" />

    <div class="controls">
      <button class="btn-success" :disabled="status === 'running' || !canRun" @click="start">
        {{ status === 'running' ? 'Running…'
           : canRun ? `▶ Run extraction (${selectedCount})` : '▶ Run extraction' }}
      </button>
      <button v-if="status === 'running'" class="btn-warn btn-sm" @click="abort">Abort</button>
      <span v-if="!canRun && status !== 'running'" class="need">Select at least one chapter to run.</span>
      <span v-if="status === 'done'" class="ok">Done</span>
      <span v-else-if="status === 'error'" class="err">Exit {{ returnCode }}</span>
      <span v-else-if="status === 'aborted'" class="aborted">Aborted</span>
      <span style="flex:1"></span>
      <button v-if="output && status !== 'running'" class="btn-neutral btn-sm" @click="clear">Clear</button>
    </div>
    <StreamOutput v-if="output" :text="output" />
  </div>
</template>

<style scoped>
.step { padding: 16px 20px; overflow-y: auto; display: flex; flex-direction: column; }
h2 { font-size: 16px; margin-bottom: 6px; }
.hint { font-size: 12px; color: var(--text-muted); margin-bottom: 12px; max-width: 64ch; }
.controls { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.ok { color: var(--green); font-size: 12px; font-weight: 600; }
.err { color: var(--red); font-size: 12px; font-weight: 600; }
.aborted { color: var(--peach); font-size: 12px; font-weight: 600; }
.need { color: var(--peach); font-size: 12px; }
</style>
