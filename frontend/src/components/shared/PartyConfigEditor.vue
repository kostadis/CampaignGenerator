<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { apiFetch, apiPut } from '../../api/client'
import { useConfigStore } from '../../stores/config'
import PathField from './PathField.vue'

interface PartyChar {
  name: string
  sheet: string
  backstory: string
  dossier: string
  /**
   * This character's voice specification and style examples (feature 009).
   *
   * DECLARATIONS, not conventions: a render follows the path. They replaced a
   * rule that matched a filename against the character's first name, which
   * resolved a renamed `Gyrgum` to nothing and told nobody. Every field here
   * must round-trip — the save PUTs the whole roster, so a field this
   * component does not read back is a field the next save deletes.
   */
  voice: string
  examples: string
  arc_score: string
  trackless: boolean
  /** Fields whose referenced file doesn't exist. Server-reported (D4). */
  missing_files?: string[]
}

// No `configPath` prop any more: party.yaml has ONE declared location and
// PartyConfigService owns it (docs/config/grounding-isolation.md Track 0 +
// Phase 5). The old /api/config/party-yaml pair took the target path as a
// browser-supplied parameter.
const emit = defineEmits<{
  saved: []
}>()

const open = ref(false)
const characters = ref<PartyChar[]>([])
const loading = ref(false)
const saving = ref(false)
const status = ref<{ kind: 'ok' | 'err'; text: string } | null>(null)
const fileExists = ref<boolean | null>(null)

const canSave = computed(() => {
  if (!characters.value.length) return false
  return characters.value.every(c => c.name.trim() && c.sheet.trim())
})

// Referenced files the server reports as absent. Saving is still allowed —
// naming a sheet before writing it is a legitimate workflow (D4) — so this is
// a warning, not a gate.
const missingCount = computed(() =>
  characters.value.reduce((n, c) => n + (c.missing_files?.length ? 1 : 0), 0)
)

// Sheet/backstory/dossier/arc-score references resolve against the CAMPAIGN
// ROOT, not against party.yaml's own directory — see docs/config/
// grounding-isolation.md Track A' (issues #145/#146). The UI must use the same
// base as the loader, otherwise the green existence check passes for a path
// the loader will reject (or vice versa, once party.yaml lives in config/).
const yamlParentDir = computed(() =>
  (useConfigStore().resolved.campaign_dir || '').trim()
)

function normalize(rows: PartyChar[]): PartyChar[] {
  // The API omits optional fields rather than sending ""; the form binds to
  // strings.
  return rows.map(c => ({
    name: c.name ?? '',
    sheet: c.sheet ?? '',
    backstory: c.backstory ?? '',
    dossier: c.dossier ?? '',
    voice: c.voice ?? '',
    examples: c.examples ?? '',
    arc_score: c.arc_score ?? '',
    trackless: !!c.trackless,
    missing_files: c.missing_files ?? [],
  }))
}

async function load() {
  loading.value = true
  status.value = null
  try {
    const rows = await apiFetch<PartyChar[]>('/api/party/characters')
    characters.value = normalize(rows)
    fileExists.value = rows.length > 0
    if (!rows.length) {
      status.value = { kind: 'ok', text: 'No roster yet — add characters and Save to create one.' }
    }
  } catch (e: any) {
    status.value = { kind: 'err', text: e?.message || 'Failed to load' }
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  status.value = null
  try {
    // `missing_files` is server-reported output, not an input field, and
    // PartyCharacter is extra="forbid" — sending it back makes every save a
    // 422. Strip it here rather than loosening the model: the strictness is
    // what turns a typo'd key into an error instead of silent overflow.
    const payload = characters.value.map(({ missing_files, ...row }) => row)
    // One atomic PUT of the whole roster, not delete-all-then-recreate: row
    // order is meaningful here and the file is never briefly empty.
    const rows = await apiPut<PartyChar[]>('/api/party/characters', payload)
    characters.value = normalize(rows)
    fileExists.value = true
    const missing = missingCount.value
    status.value = missing
      ? { kind: 'ok', text: `Saved. ${missing} character(s) reference a file that doesn't exist yet.` }
      : { kind: 'ok', text: 'Saved.' }
    emit('saved')
  } catch (e: any) {
    status.value = { kind: 'err', text: e?.message || 'Save failed' }
  } finally {
    saving.value = false
  }
}

function addChar() {
  characters.value.push({
    name: '', sheet: '', backstory: '', dossier: '', voice: '', examples: '',
    arc_score: '', trackless: false, missing_files: [],
  })
}

function removeChar(i: number) {
  characters.value.splice(i, 1)
}

function moveChar(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= characters.value.length) return
  const a = characters.value
  ;[a[i], a[j]] = [a[j], a[i]]
}

function toggleTrackless(c: PartyChar) {
  c.trackless = !c.trackless
  if (c.trackless) c.arc_score = ''
}

watch(() => open.value, (o) => {
  if (o && !characters.value.length) load()
})
</script>

<template>
  <div class="editor-wrap">
    <div class="editor-controls">
      <button class="btn-neutral btn-sm" @click="open = !open" type="button">
        {{ open ? 'Hide' : 'Edit' }} party config
      </button>
      <button v-if="open" class="btn-neutral btn-sm" :disabled="loading" @click="load" type="button">
        Reload
      </button>
      <span v-if="open && fileExists === false" class="status-pill status-new">New file</span>
      <span v-if="open && missingCount" class="status-pill status-missing"
        :title="'These are saved, but the referenced files do not exist yet.'">
        {{ missingCount }} with missing file(s)
      </span>
      <span v-if="status" :class="['status-text', status.kind === 'err' ? 'err' : 'ok']">
        {{ status.text }}
      </span>
    </div>

    <div v-if="open" class="editor-panel">
      <p v-if="loading" class="muted">Loading…</p>

      <div v-else>
        <p class="cross-link">
          The people at the table — their names, the labels a recording uses for them,
          and who plays what — are configured on the
          <router-link to="/setup/players">Players</router-link> page. This roster owns
          the characters and their files.
        </p>

        <div v-if="!characters.length" class="empty">
          No characters yet. Click "Add character" to start.
        </div>

        <div v-for="(c, i) in characters" :key="i" class="char-card">
          <div class="char-header">
            <input
              type="text"
              class="name-input"
              v-model="c.name"
              placeholder="Character name (e.g. Soma)"
            />
            <div class="char-actions">
              <button class="icon-btn" @click="moveChar(i, -1)" :disabled="i === 0" type="button" title="Move up">↑</button>
              <button class="icon-btn" @click="moveChar(i, 1)" :disabled="i === characters.length - 1" type="button" title="Move down">↓</button>
              <button class="icon-btn danger" @click="removeChar(i)" type="button" title="Remove">✕</button>
            </div>
          </div>

          <div class="char-body">
            <PathField
              :model-value="c.sheet"
              @update:model-value="(v: string) => (c.sheet = v)"
              label="Sheet (required)"
              required
              :base-dir="yamlParentDir"
              help="Path relative to the campaign root (e.g. docs/party/soma.md)."
            />
            <PathField
              :model-value="c.backstory"
              @update:model-value="(v: string) => (c.backstory = v)"
              label="Backstory"
              :base-dir="yamlParentDir"
              help="Optional. Path relative to the campaign root."
            />
            <PathField
              :model-value="c.dossier"
              @update:model-value="(v: string) => (c.dossier = v)"
              label="Ensemble dossier"
              :base-dir="yamlParentDir"
              help="Optional. This PC's own docs/ensemble/merged_dossiers/npc_*.md — narrative facts (relationships, decisions, arc progression) from actual play."
            />
            <PathField
              :model-value="c.voice"
              @update:model-value="(v: string) => (c.voice = v)"
              label="Voice specification"
              :base-dir="yamlParentDir"
              help="Optional. This character's register rules and banned-tic list (e.g. voice/gyrgum_voice.md). Named here, not matched by filename — a render follows this path, and a file it cannot find stops the run rather than leaving the narrator silently without its voice."
            />
            <PathField
              :model-value="c.examples"
              @update:model-value="(v: string) => (c.examples = v)"
              label="Style examples"
              :base-dir="yamlParentDir"
              help="Optional. This character's style reference (e.g. examples/gyrgum.md). Reaches only this narrator. Campaign-wide examples go in party.yaml's shared_examples list."
            />

            <div class="arc-row">
              <label class="checkbox-label trackless-toggle">
                <input
                  type="checkbox"
                  :checked="c.trackless"
                  @change="toggleTrackless(c)"
                />
                Intentionally trackless
                <span class="hint">— synthesizer will not invent an arc score for this PC</span>
              </label>

              <PathField
                v-if="!c.trackless"
                :model-value="c.arc_score"
                @update:model-value="(v: string) => (c.arc_score = v)"
                label="Arc score mechanic"
                :base-dir="yamlParentDir"
                help="Optional. Path relative to the campaign root."
              />
            </div>
          </div>
        </div>

        <div class="editor-footer">
          <button class="btn-neutral btn-sm" @click="addChar" type="button">+ Add character</button>
          <button
            class="btn-primary btn-sm"
            :disabled="!canSave || saving"
            @click="save"
            type="button"
          >
            {{ saving ? 'Saving…' : 'Save party.yaml' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.editor-wrap { margin-top: 8px; }
.editor-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.status-pill {
  font-size: 10px; padding: 2px 6px; border-radius: 3px;
  background: var(--bg-surface1); color: var(--text-sub);
}
.status-pill.status-new { background: var(--peach); color: var(--bg-base); }
.status-pill.status-missing { background: var(--yellow); color: var(--bg-base); }
.status-text { font-size: 11px; }
.status-text.ok { color: var(--green); }
.status-text.err { color: var(--red); }

.editor-panel {
  margin-top: 10px; padding: 12px;
  background: var(--bg-mantle); border-radius: 4px;
  border: 1px solid var(--bg-surface0);
}

.muted { color: var(--text-muted); font-size: 11px; }
.cross-link {
  margin: 0 0 10px; font-size: 10px; color: var(--text-muted); line-height: 1.6;
}
.empty {
  color: var(--text-muted); font-size: 11px;
  padding: 12px; text-align: center;
  border: 1px dashed var(--bg-surface1); border-radius: 4px;
}

.char-card {
  background: var(--bg-base); border: 1px solid var(--bg-surface0);
  border-radius: 4px; padding: 10px; margin-bottom: 10px;
}
.char-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
}
.name-input {
  flex: 1; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-mantle);
  color: var(--text); font-size: 12px; font-weight: 600;
  outline: none; box-sizing: border-box;
}
.name-input:focus { border-color: var(--mauve); }

.char-actions { display: flex; gap: 4px; }
.icon-btn {
  width: 24px; height: 24px; border-radius: 3px;
  background: var(--bg-surface0); color: var(--text-sub);
  border: 1px solid var(--bg-surface1); cursor: pointer;
  font-size: 11px;
}
.icon-btn:hover { background: var(--bg-surface1); color: var(--text); }
.icon-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.icon-btn.danger:hover { background: var(--red); color: var(--bg-base); border-color: var(--red); }

.char-body { display: flex; flex-direction: column; gap: 8px; }
.arc-row { display: flex; flex-direction: column; gap: 6px; }

.field { display: flex; flex-direction: column; gap: 4px; }
.field-label { font-size: 11px; color: var(--text-sub); font-weight: 600; }
.text-input {
  padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-mantle);
  color: var(--text); font-size: 12px;
  outline: none; box-sizing: border-box;
}
.text-input:focus { border-color: var(--mauve); }
.field-help { font-size: 10px; color: var(--text-muted); line-height: 1.5; }

.checkbox-label {
  font-size: 11px; color: var(--text-sub);
  display: flex; align-items: center; gap: 6px; cursor: pointer;
}
.checkbox-label input { accent-color: var(--mauve); }
.trackless-toggle .hint { color: var(--text-muted); font-weight: 400; }

.editor-footer {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 12px;
}
</style>
