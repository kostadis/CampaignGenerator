<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useEnsembleRun, fetchEnsembleConfig, saveEnsembleConfig, type EnsembleConfig } from './useEnsembleRun'
import StreamOutput from '../../components/shared/StreamOutput.vue'
import RunCommandBar from '../../components/shared/RunCommandBar.vue'
import ChapterPicker from './ChapterPicker.vue'

const emit = defineEmits<{ changed: [] }>()
const cfg = ref<EnsembleConfig | null>(null)
const { output, status, returnCode, command, run, abort, clear } = useEnsembleRun()

onMounted(async () => {
  cfg.value = await fetchEnsembleConfig()
})

const backendLabel = computed(() => cfg.value?.extract.backend ?? '')
// Principle X — what runs is exactly what was explicitly selected. No glob
// fallback: an empty selection cannot start a run.
const selectedCount = computed(() => cfg.value?.chapters_selected.length ?? 0)
const canRun = computed(() => selectedCount.value > 0)

async function persistChapters() {
  if (!cfg.value) return
  cfg.value = await saveEnsembleConfig({
    chapters_selected: cfg.value.chapters_selected,
    paths: { chapters_glob: cfg.value.paths.chapters_glob },
  })
}

function start() {
  if (!canRun.value || !cfg.value) return
  // Only the per-run choice is sent. Backend/model/endpoints and every path
  // come from ensemble.yaml, which the server reads itself — sending our own
  // copy would reintroduce the drift Phase 3 removed. The echoed command is
  // still fully explicit: the server resolves before building argv.
  run('/api/ensemble/run/extract', {
    chapters: cfg.value.chapters_selected,
  }, (rc) => { if (rc === 0) emit('changed') })
}
</script>

<template>
  <div class="step" v-if="cfg">
    <h2>Stage 1 — Extraction</h2>
    <p class="hint">
      Runs <code>ensemble_batch.py</code> over the chapters you pick below. Resumable:
      chapters already extracted are skipped. Backend: <strong>{{ backendLabel }}</strong>
      (change it on the Setup step). Writes
      <code>docs/ensemble/per_chapter/*/merged.json</code>.
    </p>

    <ChapterPicker
      v-model:glob="cfg.paths.chapters_glob"
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
