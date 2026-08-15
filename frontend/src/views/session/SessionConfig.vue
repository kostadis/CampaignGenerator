<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import { apiFetch } from '../../api/client'
import PathField from '../../components/shared/PathField.vue'

const config = useConfigStore()

// ── Primary inputs ──
const campaignDir = ref('')
const sessionDir = ref('')

// ── Derived / overridable fields ──
const sdSession = ref('')
const voiceDir = ref('')
const examplesDir = ref('')
const summaries = ref('')
const showOverrides = ref(false)

// Not directly editable on this page — carried through so persistTypedSections
// doesn't clobber the Session Doc Editor drawer's session_summary/party
// overrides with a default. Sourced from store.editorConfig (paths.*), the
// session-editor's single source of truth (session_doc's sd_* flat overlay
// was retired — see docs/config/session-editor-isolation.md).
const sessionSummaryPath = ref('')
const partyPath = ref('')

function loadFromConfig() {
  // `v` (config.values) still carries this page's OWN client-side-only
  // derive broadcast (see saveToConfig/deriveAll below) for any field a
  // sibling page may have written to it earlier in the session. Everything
  // else is read from the persisted, typed view.
  const v = config.values
  const r = config.resolved
  const ec = config.editorConfig
  campaignDir.value = r.campaign_dir || v.campaign_dir || ''
  sessionDir.value = r.runtime?.session_dir || v.session_dir || ''
  sdSession.value = ec?.paths?.session_recap || ''
  voiceDir.value = ec?.paths?.voice_dir || ''
  examplesDir.value = ec?.paths?.examples_dir || ''
  sessionSummaryPath.value = ec?.paths?.session_summary || 'session-summary.md'
  partyPath.value = ec?.paths?.party || ''
  // Shared canonical-timeline pointer — grounding.yaml's root (ui.grounding
  // is retired; see docs/config/grounding-isolation.md).
  summaries.value = config.groundingConfig?.summaries || v.summaries || ''
}

function saveToConfig() {
  // Mirror onto config.values (client-side only) so sibling pages still
  // reading the flat-key fallback see this page's edits immediately, without
  // a round trip. Persistence happens in saveConfig() (typed sections) and
  // onBlur (debounced auto-save below).
  Object.assign(config.values, {
    campaign_dir: campaignDir.value,
    session_dir: sessionDir.value,
    summaries: summaries.value,
  })
}

async function persistTypedSections() {
  await Promise.all([
    config.updateEditor({
      paths: {
        session_recap: sdSession.value || null,
        // scene_extractions_dir / narration_dir are owned exclusively by the
        // Session Doc Editor drawer. Do NOT seed them here — doing so clobbers
        // any override the user set in the editor.
        session_summary: sessionSummaryPath.value || 'session-summary.md',
        party: partyPath.value || null,
        voice_dir: voiceDir.value || null,
        examples_dir: examplesDir.value || null,
      },
    }),
    // The shared canonical-timeline pointer now lives at grounding.yaml's
    // root, owned by GroundingConfigService — `ui.grounding` is retired
    // (docs/config/grounding-isolation.md). All four grounding runs inherit
    // this when their own `input` is blank.
    config.updateGrounding({ summaries: summaries.value || null }),
  ])
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
 *
 * `/api/config/campaign-paths` (PlatformConfigService.discover_campaign_paths,
 * docs/config/platform-isolation.md O2) returns only genuine filesystem
 * DISCOVERY — a probe for something whose name or presence can't be known in
 * advance: gm_recap, summaries, party_config, plan_npc,
 * session_summary, voice_dir/examples_dir, and the docs/*.md exist-checks
 * (campaign_state, world_state, party, planning). Every one of those is `""`
 * or absent when nothing is found, which is why each read below is guarded —
 * this function runs on a debounced watch, so an unguarded assignment would
 * overwrite the GM's own entry on every campaign/session edit.
 *
 * It deliberately does NOT return the context/plan_context aggregates: those
 * are pure joins over fields this function already holds, so computing them
 * here avoids a second server-side expression of the same thing. Nor does it
 * return output_dir or the scene extractions dir — that was layout DERIVATION
 * duplicating PlatformConfigService.resolve_path, and O2 deleted it (those
 * paths belong to the Session Doc Editor). The raw *.vtt is likewise not
 * discovered here any more: the editor globs for it itself.
 */
async function deriveAll() {
  const cd = campaignDir.value.trim()
  const sd = sessionDir.value.trim()
  if (!cd || !sd) return

  try {
    const d = await apiFetch(
      `/api/config/campaign-paths?campaign_dir=${encodeURIComponent(cd)}&session_dir=${encodeURIComponent(sd)}`
    )

    // Session-level files (relative to session_dir) — genuine discovery.
    if (d.gm_recap) sdSession.value = stripPrefix(d.gm_recap, sd)

    // Campaign-level directories (absolute). Guarded because the server
    // returns "" when the conventional directory is absent — this function
    // fires on a debounced watch, so an unguarded assignment would wipe a
    // GM's custom path on every session switch.
    if (d.voice_dir) voiceDir.value = d.voice_dir
    if (d.examples_dir) examplesDir.value = d.examples_dir
    if (d.summaries) summaries.value = d.summaries

    // Context files: whichever of campaign_state/world_state/party the
    // server found to exist. The join is pure computation over
    // already-discovered facts, so it happens here rather than as a
    // separate server-computed aggregate field. Consumed downstream as
    // `plan_context` (PlanningDocument.vue's fallback).
    const contextFiles = [d.campaign_state, d.world_state, d.party].filter(Boolean)

    // Downstream pages pick these up from the config store. session_doc
    // paths (party/session_summary) are carried via sessionSummaryPath /
    // partyPath instead — the sd_* flat overlay was retired, and
    // scene_extractions_dir / narration_dir stay the Session Doc Editor
    // drawer's sole ownership (never seeded here).
    Object.assign(config.values, {
      // Campaign-level (absolute)
      cs_output: d.campaign_state || '',
      distill_output: d.world_state || '',
      campaign_state_output: d.campaign_state || '',
      world_state_output: d.world_state || '',
      party_output: d.party || '',
      party_config_path: d.party_config || '',
      summaries: d.summaries || '',
      plan_npc: d.plan_npc || '',
      plan_context: contextFiles.join('\n'),
      planning_output: d.planning || '',
    })

    partyPath.value = d.party || ''
    if (d.session_summary)
      sessionSummaryPath.value = stripPrefix(d.session_summary, sd)

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
  // Typed sections — survive a server restart through the unified service.
  await persistTypedSections()
  // session_dir lives in ui_state.runtime, not under a typed UI section.
  // campaign_dir is encoded by where ui_state.yaml lives and is never
  // persisted to disk.
  if (sessionDir.value.trim()) {
    await config.updateRuntime({ session_dir: sessionDir.value.trim() })
  }
}

onMounted(async () => {
  await config.load()
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
          v-model="sdSession"
          label="GMassistant recap file"
          help="Auto-detected gm-assist.md from session directory."
        />
      </div>

      <!-- Shared config -->
      <div class="form-section">
        <div class="field-help">
          The narrating cast comes from <code>party.yaml</code>, and who plays each
          character — including the labels the recording uses for them and for the
          GM — is configured on the
          <router-link to="/setup/players">Players</router-link> page. Both used to
          be typed here a second time, and both were stale against their own roster.
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
            label="Canonical timeline"
            absolute
            help="The master narrative bible (one big file) consumed by all grounding tools."
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
