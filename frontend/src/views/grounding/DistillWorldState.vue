<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import ExtractSynthesizePanel from '../../components/shared/ExtractSynthesizePanel.vue'
import { useGroundingRun } from '../../composables/useGroundingRun'

const config = useConfigStore()

const input = ref('')
const output = ref('')
const extractDir = ref('')
const splitChapters = ref('# Chapter')
const noLog = ref(false)
const showAdvanced = ref(false)

// `ui.distill` was a WRITE-NEVER section — this page read four keys on mount
// and never called updateSection, so everything typed here was lost on reload.
const { sharedSummaries } = useGroundingRun('distill', {
  input, output, extract_dir: extractDir, split_chapters: splitChapters,
  no_log: noLog,
})

// An empty `input` inherits the shared canonical-timeline pointer server-side.
const effectiveInput = computed(() => input.value.trim() || sharedSummaries.value)

const ready = computed(() =>
  !!(effectiveInput.value && output.value.trim())
)

const runParams = computed(() => ({
  input: input.value,
  output: output.value,
  extract_dir: extractDir.value,
  split_chapters: splitChapters.value,
  no_log: noLog.value,
  model: config.model || undefined,
}))

watch(output, (newOutput) => {
  if (!extractDir.value && newOutput) {
    const idx = newOutput.lastIndexOf('/')
    const parent = idx >= 0 ? newOutput.slice(0, idx) : ''
    extractDir.value = parent ? `${parent}/distill_extractions` : 'distill_extractions'
  }
})

</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Distill World State</h2>
      <p class="subtitle">
        Convert session summaries into world_state.md &mdash; the living canon document organized by NPCs, factions, locations, and threads.
      </p>
    </div>

    <div class="form-grid">
      <div class="form-section">
        <PathField v-model="input" label="Canonical timeline" resolve-base="campaign"
          help="The master narrative bible (one big chronologically-ordered file). Gets chunked and distilled." />
      </div>

      <div class="form-section">
        <PathField v-model="output" label="Output file" required is-output resolve-base="campaign"
          help="world_state.md — the structured canon document." />
      </div>

      <div class="form-section">
        <PathField v-model="extractDir" label="Extractions directory" resolve-base="campaign"
          help="Where per-chunk extracts live. Review these between Extract and Synthesize." />
      </div>

      <!-- Advanced -->
      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </button>

        <div v-if="showAdvanced" class="advanced-panel">
          <div class="field">
            <label class="field-label">Split by chapter prefix</label>
            <input type="text" class="field-input" v-model="splitChapters"
              placeholder="e.g. # Chapter — splits at each chapter heading" />
            <span class="field-help">When set, each chapter becomes one extract chunk.</span>
          </div>
          <div class="field">
            <label class="checkbox-label">
              <input type="checkbox" v-model="noLog" />
              Skip log file
            </label>
          </div>
        </div>
      </div>

      <ExtractSynthesizePanel
        endpoint="/api/grounding/run/distill"
        selection-service="grounding"
        selection-doc="distill"
        :selection-can-override="true"
        :params="runParams"
        :extract-dir="extractDir"
        :disabled="!ready"
        extract-label="1. Extract chunks"
        synth-label="2. Synthesize world_state.md"
      />
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface0);
}
.form-section:last-child { border-bottom: none; }

.field { margin-bottom: 10px; }
.field-label {
  display: block; font-size: 11px; font-weight: 600;
  color: var(--text-sub); margin-bottom: 3px;
}
.field-input {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box;
}
.field-input:focus { border-color: var(--mauve); }

.checkbox-label {
  font-size: 11px; color: var(--text-sub); display: flex;
  align-items: center; gap: 6px; cursor: pointer;
}
.checkbox-label input { accent-color: var(--mauve); }

.field-help { display: block; font-size: 10px; color: var(--text-muted); margin-top: 3px; }
.field-input:disabled { opacity: 0.4; cursor: not-allowed; }

.advanced-panel {
  margin-top: 10px; padding: 10px;
  background: var(--bg-mantle); border-radius: 4px;
}
</style>
