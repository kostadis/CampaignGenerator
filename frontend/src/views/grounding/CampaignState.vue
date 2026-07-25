<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import ExtractSynthesizePanel from '../../components/shared/ExtractSynthesizePanel.vue'
import { useGroundingRun } from '../../composables/useGroundingRun'

const config = useConfigStore()

const input = ref('')
const output = ref('')
// One list, not three fields. track_file (singular) + track_files_extra
// (textarea) + track (inline) collapsed in Phase 8 — the CLI has always taken
// --track-file as action="append", so the split existed only in the UI.
const trackFilesText = ref('')
const trackItemsText = ref('')
const extractDir = ref('')
const splitChapters = ref('# Chapter')
const noLog = ref(false)
const showAdvanced = ref(false)

// Everything on this page now loads from and persists to grounding.yaml.
// `ui.campaign_state` was a WRITE-NEVER section: this page read six keys on
// mount and never called updateSection, so every value evaporated on reload.
const trackFiles = computed({
  get: () => trackFilesText.value.split('\n').map(l => l.trim()).filter(Boolean),
  set: (v: string[]) => { trackFilesText.value = v.join('\n') },
})
const trackItems = computed({
  get: () => trackItemsText.value.split('\n').map(l => l.trim()).filter(Boolean),
  set: (v: string[]) => { trackItemsText.value = v.join('\n') },
})

const { sharedSummaries } = useGroundingRun('campaign_state', {
  input, output, extract_dir: extractDir, split_chapters: splitChapters,
  no_log: noLog, track_files: trackFiles, track_items: trackItems,
})

// An empty `input` inherits the shared canonical-timeline pointer server-side,
// so the page is ready either way.
const effectiveInput = computed(() => input.value.trim() || sharedSummaries.value)

const ready = computed(() =>
  !!(effectiveInput.value && output.value.trim())
)

const runParams = computed(() => ({
  input: input.value,
  output: output.value,
  track_file: '',
  track_file_extra: trackFiles.value,
  track: trackItems.value,
  extract_dir: extractDir.value,
  split_chapters: splitChapters.value,
  no_log: noLog.value,
  model: config.model,
}))

watch(output, (newOutput) => {
  if (!extractDir.value && newOutput) {
    const idx = newOutput.lastIndexOf('/')
    const parent = idx >= 0 ? newOutput.slice(0, idx) : ''
    extractDir.value = parent ? `${parent}/state_extractions` : 'state_extractions'
  }
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Campaign State</h2>
      <p class="subtitle">
        Generate campaign_state.md &mdash; a grounding document that tells planning scripts what has been completed and what is currently true.
      </p>
    </div>

    <div class="form-grid">
      <div class="form-section">
        <PathField v-model="input" label="Canonical timeline" resolve-base="campaign"
          :help="sharedSummaries
            ? `Leave blank to use the campaign's shared timeline (${sharedSummaries}).`
            : 'The master narrative bible (one big chronologically-ordered file). Gets chunked and extracted into per-chunk state notes.'" />
      </div>

      <div class="form-section">
        <PathField v-model="output" label="Output file" required is-output resolve-base="campaign"
          help="campaign_state.md — loaded first by prep.py as grounding context." />
      </div>

      <div class="form-section">
        <div class="field">
          <label class="field-label">Adventure module tracking lists</label>
          <textarea class="field-textarea" v-model="trackFilesText" rows="4"
            placeholder="One file path per line — e.g. notes/oota_module_tracking.txt" />
          <span class="field-help">Events from your adventure module to explicitly verify (done or not done), plus any per-arc or homebrew tracking files. Generate with Make Tracking List, or write your own. Each line becomes another --track-file. Not for PC arc scores — those belong in Party Document.</span>
        </div>
      </div>

      <div class="form-section">
        <PathField v-model="extractDir" label="Extractions directory" resolve-base="campaign"
          help="Where intermediate state_extractions/ files live. Review these between Extract and Synthesize." />
      </div>

      <div class="form-section">
        <div class="field">
          <label class="field-label">Additional events to track (inline)</label>
          <textarea class="field-textarea" v-model="trackItemsText" rows="4"
            placeholder="One item per line — added to the tracking list above" />
          <span class="field-help">Extra event descriptions typed directly (NOT file paths — for paths use the tracking lists above).</span>
        </div>
      </div>

      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </button>

        <div v-if="showAdvanced" class="advanced-panel">
          <div class="field">
            <label class="field-label">Split by session prefix</label>
            <input type="text" class="field-input" v-model="splitChapters"
              placeholder="e.g. # Session — splits at each session heading" />
            <span class="field-help">When set, each session becomes one extract chunk.</span>
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
        endpoint="/api/grounding/run/campaign-state"
        selection-service="grounding"
        selection-doc="campaign_state"
        :selection-can-override="true"
        :params="runParams"
        :extract-dir="extractDir"
        :disabled="!ready"
        extract-label="1. Extract per-chunk state"
        synth-label="2. Synthesize campaign_state.md"
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
.field-input, .field-textarea {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box;
}
.field-textarea { resize: vertical; }
.field-input:focus, .field-textarea:focus { border-color: var(--mauve); }

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
