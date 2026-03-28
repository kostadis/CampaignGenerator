<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import { resolvePath, resolvePathList } from '../../utils/paths'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

// ── Form state ──
const characters = ref('')
const sessionName = ref('')
const sdSession = ref('')
const sessionSummary = ref('')
const roleplaySummary = ref('')
const extractDir = ref('')
const roleplayDir = ref('')
const summaryDir = ref('')
const party = ref('')
const campaignState = ref('')
const worldState = ref('')
const voiceDir = ref('')
const examplesDir = ref('')
const sdContext = ref('')
const showOverrides = ref(false)

function loadFromConfig() {
  const v = config.values
  characters.value = v.sd_characters || v.session_doc_characters || ''
  sessionName.value = v.sd_session_name || ''
  sdSession.value = v.sd_session || ''
  sessionSummary.value = v.sd_session_summary || ''
  roleplaySummary.value = v.sd_roleplay_summary || ''
  extractDir.value = v.sd_extract_dir || ''
  roleplayDir.value = v.sd_roleplay_dir || ''
  summaryDir.value = v.sd_summary_dir || ''
  party.value = v.sd_party || ''
  campaignState.value = v.cs_output || v.campaign_state_output || ''
  worldState.value = v.distill_output || v.world_state_output || ''
  voiceDir.value = v.sd_voice_dir || v.session_doc_voice_dir || ''
  examplesDir.value = v.sd_examples_dir || v.session_doc_examples_dir || ''
  sdContext.value = v.sd_context || v.vtt_context || ''
}

const contextFiles = computed(() => resolvePathList(sdContext.value))

const ready = computed(() =>
  !!(sdSession.value.trim() && extractDir.value.trim() &&
     roleplayDir.value.trim() && characters.value.trim())
)

const runParams = computed(() => ({
  session: resolvePath(sdSession.value),
  roleplay_dir: resolvePath(roleplayDir.value),
  extract_dir: resolvePath(extractDir.value),
  summary_dir: resolvePath(summaryDir.value),
  session_summary: resolvePath(sessionSummary.value),
  roleplay_summary: resolvePath(roleplaySummary.value),
  characters: characters.value,
  party: resolvePath(party.value),
  voice_dir: resolvePath(voiceDir.value),
  examples_dir: resolvePath(examplesDir.value),
  campaign_state: resolvePath(campaignState.value),
  world_state: resolvePath(worldState.value),
  context: contextFiles.value,
  session_name: sessionName.value,
  model: config.model,
}))

onMounted(() => {
  loadFromConfig()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Scene Extraction</h2>
      <p class="subtitle">
        Run passes 1-4 of session_doc.py: consistency check, section enhancement,
        narrative plan, and per-scene character extraction.
      </p>
    </div>

    <div class="form-grid">
      <!-- Required fields -->
      <div class="form-section">
        <div class="field">
          <label class="field-label">Characters <span class="required">*</span></label>
          <input type="text" class="field-input" v-model="characters"
                 placeholder='Zalthir, Grygum, Daz, Thorin' />
          <div class="field-help">Comma-separated narrator roster</div>
        </div>
        <div class="field">
          <label class="field-label">Session name</label>
          <input type="text" class="field-input" v-model="sessionName"
                 placeholder="Override the document title (default: recap filename)" />
        </div>
      </div>

      <!-- Key paths -->
      <div class="form-section">
        <PathField v-model="sdSession" label="GMassistant recap file" required />
        <PathField v-model="extractDir" label="Scene extractions directory" required />
        <PathField v-model="roleplayDir" label="Roleplay extractions directory" required />
      </div>

      <!-- Path overrides (collapsed by default) -->
      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showOverrides = !showOverrides">
          {{ showOverrides ? 'Hide' : 'Show' }} path overrides
        </button>

        <div v-if="showOverrides" class="advanced-panel">
          <PathField v-model="sessionSummary" label="VTT session summary"
            help="session-summary.md — used in passes 1, 3, and 4. Auto-detected from session directory." />
          <PathField v-model="roleplaySummary" label="Roleplay summary"
            help="session-roleplay.md — injected into every narration pass." />
          <PathField v-model="summaryDir" label="Session extractions directory"
            help="vtt_extractions/ — event context for extraction passes." />
          <PathField v-model="party" label="Party document" />
          <PathField v-model="campaignState" label="Campaign state"
            help="campaign_state.md — passed as context for the consistency check." />
          <PathField v-model="worldState" label="World state"
            help="world_state.md — passed as context for the consistency check." />
          <PathField v-model="voiceDir" label="Voice files directory"
            help="Directory of {name}_voice.md files." />
          <PathField v-model="examplesDir" label="Examples directory"
            help="Directory of handcrafted .md files used as style references." />
          <MultiPathField v-model="sdContext" label="Additional context files"
            help="Any extra context beyond campaign_state and world_state." />
        </div>
      </div>

      <!-- Ready check -->
      <div v-if="!ready" class="info-box">
        Fill in the required fields above to enable extraction.
        Set a session directory on the Config page to auto-populate paths.
      </div>

      <!-- Run panel -->
      <RunPanel
        endpoint="/api/workflow/run/scene-extraction"
        :params="runParams"
        :disabled="!ready"
        label="Run Extraction (Passes 1-4)"
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

.advanced-panel {
  margin-top: 10px; padding: 10px;
  background: var(--bg-mantle); border-radius: 4px;
}

.info-box {
  padding: 10px 14px;
  background: #1e3a5f;
  border-radius: 4px;
  font-size: 11px;
  color: var(--blue);
  line-height: 1.5;
}
</style>
