<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

const recap = ref('')
const output = ref('')
const roleplayDir = ref('')
const summaryDir = ref('')
const context = ref('')
const party = ref('')
const noLog = ref(false)

const contextFiles = computed(() =>
  context.value.split('\n').map(l => l.trim()).filter(Boolean)
)

const ready = computed(() =>
  !!(recap.value.trim() && output.value.trim())
)

const runParams = computed(() => ({
  recap: recap.value,
  output: output.value,
  roleplay_extract_dir: roleplayDir.value,
  summary_extract_dir: summaryDir.value,
  context: contextFiles.value,
  party: party.value,
  no_log: noLog.value,
  model: config.model,
}))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Enhance Recap</h2>
      <p class="subtitle">
        Improve an existing session recap with richer narrative, more memorable moments, and a plot consistency check.
      </p>
    </div>

    <div class="form-grid">
      <div class="form-section">
        <PathField v-model="recap" label="Recap file" required
          help="The recap to enhance, e.g. from gmassistant.app" />
        <PathField v-model="output" label="Output file" required is-output
          help="e.g. docs/session-mar-enhanced.md" />
      </div>

      <div class="form-section">
        <PathField v-model="roleplayDir" label="Roleplay extractions directory"
          help="vtt_roleplay_extractions/ — quoted dialogue and character moments." />
        <PathField v-model="summaryDir" label="Summary extractions directory"
          help="vtt_extractions/ — action detail and environmental context." />
      </div>

      <div class="form-section">
        <MultiPathField v-model="context" label="Context files"
          help="campaign_state.md, world_state.md, party.md — used to catch errors in the recap." />
        <PathField v-model="party" label="Party document"
          help="party.md — for character voice in the enhanced summary." />
      </div>

      <div class="form-section">
        <div class="field">
          <label class="checkbox-label">
            <input type="checkbox" v-model="noLog" /> Skip log file
          </label>
        </div>
      </div>

      <RunPanel
        endpoint="/api/experimental/run/enhance-recap"
        :params="runParams"
        :disabled="!ready"
        label="Run Enhance Recap"
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

.checkbox-label {
  font-size: 11px; color: var(--text-sub); display: flex;
  align-items: center; gap: 6px; cursor: pointer;
}
.checkbox-label input { accent-color: var(--mauve); }
</style>
