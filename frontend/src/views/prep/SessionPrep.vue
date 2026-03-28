<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

const inputMode = ref<'beat' | 'session_file' | 'session_text'>('beat')
const beat = ref('')
const sessionFile = ref('')
const sessionText = ref('')
const prepMode = ref<'single' | 'pipeline'>('single')
const configFile = ref('')
const output = ref('')
const noLog = ref(false)

const ready = computed(() => {
  if (inputMode.value === 'beat') return !!beat.value.trim()
  if (inputMode.value === 'session_file') return !!sessionFile.value.trim()
  if (inputMode.value === 'session_text') return !!sessionText.value.trim()
  return false
})

const runParams = computed(() => ({
  input_mode: inputMode.value,
  beat: beat.value,
  session_file: sessionFile.value,
  session_text: sessionText.value,
  prep_mode: prepMode.value,
  config: configFile.value,
  output: output.value,
  no_log: noLog.value,
  model: config.model,
}))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Session Prep</h2>
      <p class="subtitle">Generate encounter documents from a session beat or numbered outline.</p>
    </div>

    <div class="form-grid">
      <!-- Input mode -->
      <div class="form-section">
        <label class="field-label">Input mode</label>
        <div class="radio-group">
          <label class="radio-label">
            <input type="radio" v-model="inputMode" value="beat" /> Single beat
          </label>
          <label class="radio-label">
            <input type="radio" v-model="inputMode" value="session_file" /> Session file
          </label>
          <label class="radio-label">
            <input type="radio" v-model="inputMode" value="session_text" /> Session text (inline)
          </label>
        </div>
      </div>

      <!-- Input fields -->
      <div class="form-section">
        <div v-if="inputMode === 'beat'" class="field">
          <label class="field-label">Session beat <span class="required">*</span></label>
          <textarea class="field-textarea" v-model="beat" rows="3"
            placeholder="The party arrives at Icespire Hold and confronts Xal'vosh" />
          <div class="field-help">Text or path to a .md file</div>
        </div>

        <PathField v-if="inputMode === 'session_file'"
          v-model="sessionFile" label="Session outline file" required />

        <div v-if="inputMode === 'session_text'" class="field">
          <label class="field-label">Session outline <span class="required">*</span></label>
          <textarea class="field-textarea" v-model="sessionText" rows="5"
            placeholder="1. Travel to Icespire Hold&#10;2. Confront Xal'vosh&#10;3. Cryovain reveal" />
        </div>
      </div>

      <!-- Prep mode -->
      <div class="form-section">
        <label class="field-label">Prep mode</label>
        <div class="radio-group">
          <label class="radio-label">
            <input type="radio" v-model="prepMode" value="single" /> Single (Campaign Architect)
          </label>
          <label class="radio-label">
            <input type="radio" v-model="prepMode" value="pipeline" /> Pipeline (Lore Oracle &rarr; Encounter Architect &rarr; Voice Keeper)
          </label>
        </div>
      </div>

      <!-- Optional -->
      <div class="form-section">
        <PathField v-model="configFile" label="Config file"
          help="Defaults to config.yaml in CWD." />
        <PathField v-model="output" label="Output file" is-output
          help="Saves the final response to a file." />
        <div class="field">
          <label class="checkbox-label">
            <input type="checkbox" v-model="noLog" /> Skip log file
          </label>
        </div>
      </div>

      <RunPanel
        endpoint="/api/prep/run/session-prep"
        :params="runParams"
        :disabled="!ready"
        label="Run Session Prep"
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
.field-textarea {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box; resize: vertical;
}
.field-textarea:focus { border-color: var(--mauve); }
.field-help { font-size: 10px; color: var(--text-muted); margin-top: 2px; }

.radio-group { display: flex; gap: 16px; flex-wrap: wrap; }
.radio-label {
  font-size: 11px; color: var(--text-sub); display: flex;
  align-items: center; gap: 5px; cursor: pointer;
}
.radio-label input { accent-color: var(--mauve); }

.checkbox-label {
  font-size: 11px; color: var(--text-sub); display: flex;
  align-items: center; gap: 6px; cursor: pointer;
}
.checkbox-label input { accent-color: var(--mauve); }
</style>
