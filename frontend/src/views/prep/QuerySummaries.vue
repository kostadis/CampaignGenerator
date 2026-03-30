<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

const input = ref('')
const query = ref('')
const hitsOnly = ref(false)
const verbose = ref(false)
const output = ref('')
const chunkSize = ref(40000)
const showAdvanced = ref(false)

function loadFromConfig() {
  const v = config.values
  input.value = v.query_input || v.summaries || ''
}

const ready = computed(() =>
  !!(input.value.trim() && query.value.trim())
)

const runParams = computed(() => ({
  input: input.value,
  query: query.value,
  hits_only: hitsOnly.value,
  verbose: verbose.value,
  output: output.value,
  chunk_size: chunkSize.value,
  model: config.model,
}))

onMounted(() => { loadFromConfig() })
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Query Summaries</h2>
      <p class="subtitle">Search session summaries for a specific event, NPC, or topic.</p>
    </div>

    <div class="form-grid">
      <div class="form-section">
        <PathField v-model="input" label="Session summaries file" required resolve-base="campaign" />
      </div>

      <div class="form-section">
        <div class="field">
          <label class="field-label">Query <span class="required">*</span></label>
          <input type="text" class="field-input" v-model="query"
            placeholder='e.g. "Did the party clear Gnomengarde?"' />
        </div>
      </div>

      <div class="form-section">
        <div class="field">
          <label class="checkbox-label">
            <input type="checkbox" v-model="hitsOnly" />
            Raw hits only (no synthesis)
          </label>
        </div>
      </div>

      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </button>

        <div v-if="showAdvanced" class="advanced-panel">
          <PathField v-model="output" label="Output file" is-output resolve-base="campaign"
            help="Save the answer to a file." />
          <div class="field">
            <label class="field-label">Chunk size (chars)</label>
            <input type="number" class="field-input" v-model.number="chunkSize" min="10000" step="5000" />
            <div class="field-help">Smaller chunks = more precise hits (default: 40,000)</div>
          </div>
          <div class="field">
            <label class="checkbox-label">
              <input type="checkbox" v-model="verbose" />
              Verbose (show per-chunk progress)
            </label>
          </div>
        </div>
      </div>

      <RunPanel
        endpoint="/api/prep/run/query"
        :params="runParams"
        :disabled="!ready"
        label="Run Query"
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
.required { color: var(--red); }
.field-input {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box;
}
.field-input:focus { border-color: var(--mauve); }
.field-help { font-size: 10px; color: var(--text-muted); margin-top: 2px; }

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
