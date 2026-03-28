<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

const docsStr = ref('world_state')
const configFile = ref('')
const output = ref('')
const noLog = ref(false)

const docsList = computed(() =>
  docsStr.value.split(/\s+/).map(d => d.trim()).filter(Boolean)
)

const ready = computed(() => docsList.value.length > 0)

const runParams = computed(() => ({
  docs: docsList.value,
  config: configFile.value,
  output: output.value,
  no_log: noLog.value,
  model: config.model,
}))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>NPC Table</h2>
      <p class="subtitle">Generate a quick-reference NPC table from config documents.</p>
    </div>

    <div class="form-grid">
      <div class="form-section">
        <div class="field">
          <label class="field-label">Document labels</label>
          <input type="text" class="field-input" v-model="docsStr"
            placeholder="world_state planning campaign_state" />
          <div class="field-help">Space-separated labels defined in your config.yaml</div>
        </div>
      </div>

      <div class="form-section">
        <PathField v-model="configFile" label="Config file"
          help="Defaults to config.yaml in CWD." />
        <PathField v-model="output" label="Output file" is-output
          help="Saves the NPC table to a file." />
        <div class="field">
          <label class="checkbox-label">
            <input type="checkbox" v-model="noLog" /> Skip log file
          </label>
        </div>
      </div>

      <RunPanel
        endpoint="/api/prep/run/npc-table"
        :params="runParams"
        :disabled="!ready"
        label="Run NPC Table"
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
.field-help { font-size: 10px; color: var(--text-muted); margin-top: 2px; }

.checkbox-label {
  font-size: 11px; color: var(--text-sub); display: flex;
  align-items: center; gap: 6px; cursor: pointer;
}
.checkbox-label input { accent-color: var(--mauve); }
</style>
