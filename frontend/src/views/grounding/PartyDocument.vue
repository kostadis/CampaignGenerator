<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import ExtractSynthesizePanel from '../../components/shared/ExtractSynthesizePanel.vue'

const config = useConfigStore()

const characters = ref('')
const summaries = ref('')
const backstory = ref('')
const arcScores = ref('')
const context = ref('')
const output = ref('')
const extractDir = ref('')
const chunkSize = ref(60000)
const splitChapters = ref('')
const noLog = ref(false)
const showAdvanced = ref(false)

function loadFromConfig() {
  const v = config.values
  characters.value = v.party_chars || ''
  summaries.value = v.party_summaries || v.summaries || ''
  backstory.value = v.party_backstory || ''
  arcScores.value = v.party_arc_scores || ''
  context.value = v.party_context || ''
  output.value = v.party_output || v.party || ''
  extractDir.value = v.party_extract_dir || ''
  chunkSize.value = v.party_chunk_size || 60000
  splitChapters.value = v.party_split_chapters || ''
}

const charFiles = computed(() =>
  characters.value.split('\n').map(l => l.trim()).filter(Boolean)
)
const backstoryFiles = computed(() =>
  backstory.value.split('\n').map(l => l.trim()).filter(Boolean)
)
const arcScoreFiles = computed(() =>
  arcScores.value.split('\n').map(l => l.trim()).filter(Boolean)
)
const contextFiles = computed(() =>
  context.value.split('\n').map(l => l.trim()).filter(Boolean)
)

const ready = computed(() =>
  !!(charFiles.value.length && output.value.trim())
)

// Extract phase needs summaries; the two-phase panel appends extract_only=true.
// When the user hits Synthesize, the panel auto-adds synthesize_only=true so
// the CLI skips the extract pass and just reads the cached files.
const runParams = computed(() => ({
  character: charFiles.value,
  summaries: summaries.value,
  backstory: backstoryFiles.value,
  arc_scores: arcScoreFiles.value,
  context: contextFiles.value,
  output: output.value,
  extract_dir: extractDir.value,
  chunk_size: chunkSize.value,
  split_chapters: splitChapters.value,
  no_log: noLog.value,
  model: config.model,
}))

const hasSummaries = computed(() => !!summaries.value.trim())

watch(output, (newOutput) => {
  if (!extractDir.value && newOutput) {
    const idx = newOutput.lastIndexOf('/')
    const parent = idx >= 0 ? newOutput.slice(0, idx) : ''
    extractDir.value = parent ? `${parent}/party_extractions` : 'party_extractions'
  }
})

onMounted(() => { loadFromConfig() })
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Party Document</h2>
      <p class="subtitle">
        Generate party.md from character sheets, session summaries, backstories, and arc score mechanics.
      </p>
    </div>

    <div class="form-grid">
      <!-- Required: character sheets -->
      <div class="form-section">
        <MultiPathField v-model="characters" label="Character sheet files" required resolve-base="campaign"
          help="One character sheet per line (e.g. docs/characters/soma.md). Required." />
      </div>

      <!-- Summaries -->
      <div class="form-section">
        <PathField v-model="summaries" label="Session summaries file" resolve-base="campaign"
          help="Optional. Omit to skip the Extract pass (characters-only mode)." />
      </div>

      <div class="form-section">
        <PathField v-model="extractDir" label="Extractions directory" resolve-base="campaign"
          help="Where intermediate party_extractions/ files live. Review these between Extract and Synthesize." />
      </div>

      <!-- Output -->
      <div class="form-section">
        <PathField v-model="output" label="Output file" required is-output resolve-base="campaign"
          help="party.md — roster, arc scores, relationships." />
      </div>

      <!-- Optional inputs -->
      <div class="form-section">
        <MultiPathField v-model="backstory" label="Backstory files" resolve-base="campaign"
          help="One per line. Optional backstory documents for each character." />
        <MultiPathField v-model="arcScores" label="Arc score mechanic files" resolve-base="campaign"
          help="One per line. Arc score documents, one per character." />
        <MultiPathField v-model="context" label="Additional context files" resolve-base="campaign"
          help="e.g. campaign_state.md — optional extra context for synthesis." />
      </div>

      <!-- Advanced -->
      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </button>

        <div v-if="showAdvanced" class="advanced-panel">
          <div class="field">
            <label class="field-label">Split by session prefix</label>
            <input type="text" class="field-input" v-model="splitChapters"
              placeholder="e.g. # Session — splits at each session heading" />
            <span class="field-help">When set, each session becomes one extract chunk. Overrides chunk size.</span>
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
        endpoint="/api/grounding/run/party"
        :params="runParams"
        :extract-dir="extractDir"
        :disabled="!ready"
        :extract-disabled="!hasSummaries"
        extract-label="1. Extract character info from summaries"
        synth-label="2. Synthesize party.md"
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
