<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import ExtractSynthesizePanel from '../../components/shared/ExtractSynthesizePanel.vue'

const config = useConfigStore()

const input = ref('')
const output = ref('')
const extractDir = ref('')
const chunkSize = ref(60000)
const splitChapters = ref('')
const noLog = ref(false)
const showAdvanced = ref(false)

function loadFromConfig() {
  const v = config.values
  input.value = v.distill_input || v.summaries || ''
  output.value = v.distill_output || v.world_state_output || v.world_state || ''
  extractDir.value = v.distill_extract_dir || ''
  chunkSize.value = v.distill_chunk_size || 60000
  splitChapters.value = v.distill_split_chapters || ''
}

const ready = computed(() =>
  !!(input.value.trim() && output.value.trim())
)

const runParams = computed(() => ({
  input: input.value,
  output: output.value,
  extract_dir: extractDir.value,
  chunk_size: chunkSize.value,
  split_chapters: splitChapters.value,
  no_log: noLog.value,
  model: config.model,
}))

onMounted(() => { loadFromConfig() })
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
        <PathField v-model="input" label="Session summaries file" required resolve-base="campaign"
          help="The large summaries.md file that gets chunked and distilled." />
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
            <span class="field-help">When set, each chapter becomes one extract chunk. Overrides chunk size.</span>
          </div>
          <div class="field">
            <label class="field-label">Chunk size (chars)</label>
            <input type="number" class="field-input" v-model.number="chunkSize" min="10000" step="5000"
              :disabled="!!splitChapters" />
            <span class="field-help">Ignored when split-by-prefix is set. Default 60,000.</span>
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
.page { padding: 20px 24px; max-width: 700px; }
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
