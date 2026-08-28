<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useEnsembleRun, fetchEnsembleConfig, saveEnsembleConfig, type EnsembleConfig } from './useEnsembleRun'
import StreamOutput from '../../components/shared/StreamOutput.vue'
import RunCommandBar from '../../components/shared/RunCommandBar.vue'
import ChapterPicker from './ChapterPicker.vue'
import PathField from '../../components/shared/PathField.vue'

const emit = defineEmits<{ changed: [] }>()
const cfg = ref<EnsembleConfig | null>(null)
const { output, status, returnCode, command, run, abort, clear } = useEnsembleRun()

onMounted(async () => {
  cfg.value = await fetchEnsembleConfig()
  const first = cfg.value.chapters_selected[0]
  if (first) selectNarrationChapter(first)
})

const backendLabel = computed(() => cfg.value?.extract.backend ?? '')
// Principle X — what runs is exactly what was explicitly selected. No glob
// fallback: an empty selection cannot start a run.
const selectedCount = computed(() => cfg.value?.chapters_selected.length ?? 0)
const canRun = computed(() => selectedCount.value > 0)
const narrationChapter = ref('')
const narrationOutput = ref('')

function chapterStem(path: string): string {
  const name = path.split('/').pop() || path
  return name.replace(/\.[^.]+$/, '')
}

function selectNarrationChapter(path: string) {
  narrationChapter.value = path
  if (cfg.value) {
    narrationOutput.value = `${cfg.value.paths.per_chapter_dir}/${chapterStem(path)}/narrative.md`
  }
}

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

function narrateChapter() {
  if (!narrationChapter.value || !narrationOutput.value || status.value === 'running') return
  // Narration always writes approved:false. Approval is a later human edit;
  // this action does not promote or advance into synthesis.
  run('/api/ensemble/run/narrate-chapter', {
    chapter: narrationChapter.value,
    output: narrationOutput.value,
  })
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

    <div class="narration-action">
      <h3>Review chapter narration <span class="tag">human checkpoint</span></h3>
      <p class="hint">
        Narrate one selected chapter into a disk-backed <code>narrative.md</code>.
        The artifact starts <code>approved: false</code>; review it before any
        later synthesis uses it.
      </p>
      <label class="field-label" for="narration-chapter">Chapter</label>
      <select id="narration-chapter" :value="narrationChapter"
        @change="selectNarrationChapter(($event.target as HTMLSelectElement).value)">
        <option value="" disabled>Select a chapter</option>
        <option v-for="chapter in cfg.chapters_selected" :key="chapter" :value="chapter">
          {{ chapter }}
        </option>
      </select>
      <PathField v-model="narrationOutput" label="Narrative output" is-output resolve-base="campaign" />
      <button class="btn-neutral" :disabled="status === 'running' || !narrationChapter || !narrationOutput"
        @click="narrateChapter">
        ▶ Narrate selected chapter
      </button>
    </div>
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
.narration-action { border-top: 1px solid var(--bg-surface0); margin-top: 14px; padding-top: 8px; }
.narration-action h3 { font-size: 13px; margin: 0 0 6px; }
.narration-action .field-label { font-size: 11px; color: var(--text-sub); display: block; margin-bottom: 3px; }
.narration-action select { max-width: 560px; margin-bottom: 8px; }
.tag { font-size: 9px; background: var(--peach); color: var(--bg-mantle); border-radius: 8px; padding: 1px 7px; margin-left: 6px; font-weight: 700; }
</style>
