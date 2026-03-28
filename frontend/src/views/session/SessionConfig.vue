<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import { apiFetch, apiPut } from '../../api/client'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'

const config = useConfigStore()

// ── Primary inputs ──
const campaignDir = ref('')
const sessionDir = ref('')

// ── Derived / overridable fields ──
const vttInput = ref('')
const sdSession = ref('')
const characters = ref('')
const voiceDir = ref('')
const examplesDir = ref('')
const vttContext = ref('')
const vttDate = ref('')
const vttSessionName = ref('')
const summaries = ref('')
const showOverrides = ref(false)

function loadFromConfig() {
  const v = config.values
  campaignDir.value = v.campaign_dir || ''
  sessionDir.value = v.session_dir || ''
  vttInput.value = v.vtt_input || ''
  sdSession.value = v.sd_session || ''
  characters.value = v.sd_characters || v.session_doc_characters || ''
  voiceDir.value = v.sd_voice_dir || v.session_doc_voice_dir || ''
  examplesDir.value = v.sd_examples_dir || v.session_doc_examples_dir || ''
  vttContext.value = v.vtt_context || ''
  vttDate.value = v.vtt_date || ''
  vttSessionName.value = v.vtt_session_name || ''
  summaries.value = v.summaries || ''
}

function saveToConfig() {
  Object.assign(config.values, {
    campaign_dir: campaignDir.value,
    session_dir: sessionDir.value,
    vtt_input: vttInput.value,
    sd_session: sdSession.value,
    sd_characters: characters.value,
    sd_voice_dir: voiceDir.value,
    sd_examples_dir: examplesDir.value,
    vtt_context: vttContext.value,
    vtt_date: vttDate.value,
    vtt_session_name: vttSessionName.value,
    summaries: summaries.value,
  })
}

/**
 * Strip a directory prefix from an absolute path, returning the relative part.
 */
function stripPrefix(absPath: string, dir: string): string {
  if (!absPath) return ''
  const prefix = dir.replace(/\/+$/, '') + '/'
  if (absPath.startsWith(prefix)) return absPath.slice(prefix.length)
  return absPath
}

/**
 * Derive everything from campaign_dir + session_dir.
 */
async function deriveAll() {
  const cd = campaignDir.value.trim()
  const sd = sessionDir.value.trim()
  if (!cd || !sd) return

  try {
    const d = await apiFetch(
      `/api/config/campaign-paths?campaign_dir=${encodeURIComponent(cd)}&session_dir=${encodeURIComponent(sd)}`
    )

    // Session-level files (relative to session_dir)
    if (d.vtt_input) vttInput.value = stripPrefix(d.vtt_input, sd)
    if (d.gm_recap) sdSession.value = stripPrefix(d.gm_recap, sd)

    // Campaign-level paths (absolute — not relative to session_dir)
    if (d.voice_dir) voiceDir.value = d.voice_dir
    if (d.examples_dir) examplesDir.value = d.examples_dir
    if (d.summaries) summaries.value = d.summaries

    // Context files (absolute paths, one per line)
    if (d.context && d.context.length) {
      vttContext.value = d.context.join('\n')
    }

    // Downstream pages pick these up from the config store
    Object.assign(config.values, {
      // Session-level (relative — resolvePath adds session_dir prefix)
      vtt_output: 'session-summary.md',
      vtt_roleplay_output: 'session-roleplay.md',
      sd_extract_dir: 'scene_extractions',
      sd_roleplay_dir: 'vtt_roleplay_extractions',
      sd_summary_dir: 'vtt_extractions',
      sd_output_dir: sd,
      // Campaign-level (absolute)
      sd_party: d.party || '',
      cs_output: d.campaign_state || '',
      distill_output: d.world_state || '',
      campaign_state_output: d.campaign_state || '',
      world_state_output: d.world_state || '',
      party_output: d.party || '',
      summaries: d.summaries || '',
    })

    if (d.session_summary)
      config.values.sd_session_summary = stripPrefix(d.session_summary, sd)
    if (d.roleplay_summary)
      config.values.sd_roleplay_summary = stripPrefix(d.roleplay_summary, sd)

    saveToConfig()
  } catch (e) {
    console.error('Failed to derive paths:', e)
  }
}

// Debounced derivation when either input changes
let deriveTimer: ReturnType<typeof setTimeout> | null = null
function schedulDerive() {
  if (deriveTimer) clearTimeout(deriveTimer)
  deriveTimer = setTimeout(deriveAll, 500)
}
watch(campaignDir, schedulDerive)
watch(sessionDir, schedulDerive)

function onBlur() {
  saveToConfig()
}

async function saveConfig() {
  saveToConfig()
  await apiPut('/api/config/', { values: config.values })
}

onMounted(() => {
  loadFromConfig()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Session Config</h2>
      <p class="subtitle">Set your campaign and session directories. Everything else is derived automatically.</p>
    </div>

    <div class="form-grid" @focusout="onBlur">
      <!-- Two primary inputs -->
      <div class="form-section primary-inputs">
        <PathField
          v-model="campaignDir"
          label="Campaign directory"
          placeholder="/home/user/campaigns/Phandalin"
          absolute
          help="Root of your campaign. Contains docs/, voice/, examples/, and summaries/."
        />
        <PathField
          v-model="sessionDir"
          label="Session directory"
          placeholder="/home/user/campaigns/Phandalin/summaries/20260318"
          absolute
          help="This session's folder inside summaries/. VTT, GM recap, extractions, and outputs all live here."
        />
      </div>

      <!-- Auto-detected files (relative to session_dir) -->
      <div class="form-section">
        <h3 class="section-title">Auto-detected</h3>
        <PathField
          v-model="vttInput"
          label="VTT transcript file"
          help="Auto-detected .vtt file from session directory."
        />
        <PathField
          v-model="sdSession"
          label="GMassistant recap file"
          help="Auto-detected gm-assist.md from session directory."
        />
      </div>

      <!-- Shared config -->
      <div class="form-section">
        <div class="field">
          <label class="field-label">Characters</label>
          <input
            type="text"
            class="field-input"
            v-model="characters"
            placeholder='Zalthir, Grygum, Daz, Thorin'
          />
          <div class="field-help">Comma-separated narrator roster</div>
        </div>
      </div>

      <!-- Session metadata -->
      <div class="form-section">
        <div class="form-row">
          <div class="field">
            <label class="field-label">Session date</label>
            <input type="text" class="field-input" v-model="vttDate" placeholder="2026-03-15" />
          </div>
          <div class="field">
            <label class="field-label">Session name</label>
            <input type="text" class="field-input" v-model="vttSessionName" placeholder="Session 12 — Icespire Hold" />
          </div>
        </div>
      </div>

      <!-- Overrides (collapsed) -->
      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showOverrides = !showOverrides">
          {{ showOverrides ? 'Hide' : 'Show' }} overrides
        </button>

        <div v-if="showOverrides" class="advanced-panel">
          <p class="override-note">These are auto-derived from your campaign and session directories. Override only if your layout differs.</p>
          <PathField
            v-model="voiceDir"
            label="Voice files directory"
            absolute
            help="Default: <campaign>/voice/"
          />
          <PathField
            v-model="examplesDir"
            label="Examples directory"
            absolute
            help="Default: <campaign>/examples/"
          />
          <PathField
            v-model="summaries"
            label="Session summaries file"
            absolute
            help="The big summaries.md used by grounding tools."
          />
          <MultiPathField
            v-model="vttContext"
            label="Campaign context files"
            help="Default: campaign_state.md, world_state.md, party.md from docs/."
          />
        </div>
      </div>

      <!-- Save button -->
      <div class="form-section">
        <button class="btn-primary" @click="saveConfig">Save Config</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  padding: 20px 24px;
  max-width: 700px;
}
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface0);
}
.form-section:last-child { border-bottom: none; }

.primary-inputs {
  background: var(--bg-mantle);
  padding: 14px;
  border-radius: 6px;
  border: 1px solid var(--bg-surface1);
}

.section-title {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .08em; color: var(--text-muted);
  margin-bottom: 8px;
}

.form-row { display: flex; gap: 12px; }
.form-row > .field { flex: 1; }

.field { margin-bottom: 10px; }
.field-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-sub);
  margin-bottom: 3px;
}
.field-input {
  width: 100%;
  padding: 6px 8px;
  border-radius: 4px;
  border: 1px solid var(--bg-surface1);
  background: var(--bg-base);
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  outline: none;
  transition: border-color .1s;
  box-sizing: border-box;
}
.field-input:focus { border-color: var(--mauve); }
.field-help { font-size: 10px; color: var(--text-muted); margin-top: 2px; }

.advanced-panel {
  margin-top: 10px; padding: 10px;
  background: var(--bg-mantle); border-radius: 4px;
}
.override-note {
  font-size: 10px; color: var(--text-muted); margin-bottom: 10px; line-height: 1.4;
}
</style>
