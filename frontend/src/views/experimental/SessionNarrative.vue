<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

const roleplayDir = ref('')
const summaryDir = ref('')
const examples = ref('')
const roleplay = ref('')
const summary = ref('')
const party = ref('')
const characters = ref('')
const sessionName = ref('')
const voiceDir = ref('')
const output = ref('')
const planOnly = ref(false)
const fast = ref(false)
const noLog = ref(false)

function loadFromConfig() {
  const v = config.values
  party.value = v.narr_party || v.party_output || ''
}

const exampleFiles = computed(() =>
  examples.value.split('\n').map(l => l.trim()).filter(Boolean)
)

const ready = computed(() => !!output.value.trim())

const runParams = computed(() => ({
  roleplay_extract_dir: roleplayDir.value,
  summary_extract_dir: summaryDir.value,
  examples: exampleFiles.value,
  roleplay: roleplay.value,
  summary: summary.value,
  party: party.value,
  characters: characters.value,
  session_name: sessionName.value,
  voice_dir: voiceDir.value,
  output: output.value,
  plan_only: planOnly.value,
  fast: fast.value,
  no_log: noLog.value,
  model: config.model,
}))

onMounted(() => { loadFromConfig() })
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Session Narrative</h2>
      <p class="subtitle">
        First-person story driven by roleplay moments. The system picks which character narrates each section based on who was most present.
      </p>
    </div>

    <div class="form-grid">
      <!-- Primary inputs -->
      <div class="form-section">
        <PathField v-model="roleplayDir" label="Roleplay extractions directory"
          help="vtt_roleplay_extractions/ — dialogue, character voice, emotional beats." />
        <PathField v-model="summaryDir" label="Summary extractions directory"
          help="vtt_extractions/ — action detail, events, environmental context." />
      </div>

      <div v-if="!roleplayDir.trim()" class="info-box">
        Set the Roleplay extractions directory for best results. Without it, the narrative relies on the synthesized roleplay highlights fallback.
      </div>

      <!-- Style and context -->
      <div class="form-section">
        <MultiPathField v-model="examples" label="Style example files"
          help="Handcrafted session summaries. Claude studies their voice, structure, humour, and dialogue style." />
        <PathField v-model="roleplay" label="Roleplay highlights (fallback)"
          help="Synthesized roleplay highlights. Used only if no extractions directory is set." />
        <PathField v-model="summary" label="Session summary"
          help="Used as an event skeleton only — context, not foreground." />
      </div>

      <!-- Character config -->
      <div class="form-section">
        <PathField v-model="party" label="Party document"
          help="party.md — backstory, personality, and relationships." />
        <div class="field">
          <label class="field-label">Party roster</label>
          <input type="text" class="field-input" v-model="characters"
            placeholder="Brewbarry, Soma, Valphine, Vukradin" />
          <div class="field-help">Comma-separated character names</div>
        </div>
        <PathField v-model="voiceDir" label="Voice files directory"
          help="Per-character voice files ({name}_voice.md)." />
      </div>

      <!-- Output -->
      <div class="form-section">
        <div class="field">
          <label class="field-label">Session name</label>
          <input type="text" class="field-input" v-model="sessionName"
            placeholder="Session 12 — Icespire Hold" />
        </div>
        <PathField v-model="output" label="Output file" required is-output
          help="e.g. docs/narratives/session_12.md" />
      </div>

      <!-- Options -->
      <div class="form-section">
        <div class="field">
          <label class="checkbox-label">
            <input type="checkbox" v-model="planOnly" />
            Plan only (preview section outline)
          </label>
        </div>
        <div class="field">
          <label class="checkbox-label">
            <input type="checkbox" v-model="fast" />
            Fast mode (Haiku — cheaper, slightly lower quality)
          </label>
        </div>
        <div class="field">
          <label class="checkbox-label">
            <input type="checkbox" v-model="noLog" />
            Skip log file
          </label>
        </div>
      </div>

      <RunPanel
        endpoint="/api/experimental/run/narrative"
        :params="runParams"
        :disabled="!ready"
        label="Run Narrative"
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

.info-box {
  padding: 10px 14px; background: #1e3a5f; border-radius: 4px;
  font-size: 11px; color: var(--blue); line-height: 1.5;
}
</style>
