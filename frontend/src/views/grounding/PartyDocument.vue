<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

const characters = ref('')
const summaries = ref('')
const backstory = ref('')
const arcScores = ref('')
const context = ref('')
const output = ref('')
const extractDir = ref('')
const chunkSize = ref(60000)
const synthOnly = ref(false)
const noLog = ref(false)
const showAdvanced = ref(false)

function loadFromConfig() {
  const v = config.values
  characters.value = v.party_chars || ''
  summaries.value = v.party_summaries || v.summaries || ''
  backstory.value = v.party_backstory || ''
  arcScores.value = v.party_arc_scores || ''
  context.value = v.party_context || ''
  output.value = v.party_output || ''
  extractDir.value = v.party_extract_dir || ''
  chunkSize.value = v.party_chunk_size || 60000
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

const ready = computed(() => {
  if (synthOnly.value) return !!output.value.trim()
  return !!(charFiles.value.length && output.value.trim())
})

const runParams = computed(() => ({
  character: charFiles.value,
  summaries: summaries.value,
  backstory: backstoryFiles.value,
  arc_scores: arcScoreFiles.value,
  context: contextFiles.value,
  output: output.value,
  extract_dir: extractDir.value,
  chunk_size: chunkSize.value,
  synthesize_only: synthOnly.value,
  no_log: noLog.value,
  model: config.model,
}))

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
      <div class="form-section">
        <div class="field">
          <label class="checkbox-label">
            <input type="checkbox" v-model="synthOnly" />
            Re-synthesize from existing extractions
          </label>
        </div>
      </div>

      <!-- Required: character sheets -->
      <div class="form-section">
        <MultiPathField v-model="characters" label="Character sheet files" required
          help="One character sheet per line (e.g. docs/characters/soma.md). Required." />
      </div>

      <!-- Summaries -->
      <div v-if="!synthOnly" class="form-section">
        <PathField v-model="summaries" label="Session summaries file"
          help="The large summaries.md — chunked for per-character extraction." />
      </div>

      <!-- Output -->
      <div class="form-section">
        <PathField v-model="output" label="Output file" required is-output
          help="party.md — roster, arc scores, relationships." />
      </div>

      <!-- Optional inputs -->
      <div class="form-section">
        <MultiPathField v-model="backstory" label="Backstory files"
          help="One per line. Optional backstory documents for each character." />
        <MultiPathField v-model="arcScores" label="Arc score mechanic files"
          help="One per line. Arc score documents, one per character." />
        <MultiPathField v-model="context" label="Additional context files"
          help="e.g. campaign_state.md — optional extra context for synthesis." />
      </div>

      <!-- Advanced -->
      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </button>

        <div v-if="showAdvanced" class="advanced-panel">
          <PathField v-model="extractDir" label="Extractions directory"
            help="Where intermediate party_extractions/ files are saved." />
          <div class="field">
            <label class="field-label">Chunk size (chars)</label>
            <input type="number" class="field-input" v-model.number="chunkSize" min="10000" step="5000" />
          </div>
          <div class="field">
            <label class="checkbox-label">
              <input type="checkbox" v-model="noLog" />
              Skip log file
            </label>
          </div>
        </div>
      </div>

      <RunPanel
        endpoint="/api/grounding/run/party"
        :params="runParams"
        :disabled="!ready"
        label="Run Party Document"
        @done="() => {}"
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

.advanced-panel {
  margin-top: 10px; padding: 10px;
  background: var(--bg-mantle); border-radius: 4px;
}
</style>
