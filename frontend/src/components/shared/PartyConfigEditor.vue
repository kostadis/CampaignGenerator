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
  arc_score: string
  trackless: boolean
}

const props = defineProps<{
  /** Absolute path to the party.yaml file. */
  configPath: string
}>()

const emit = defineEmits<{
  saved: [path: string]
}>()

const open = ref(false)
const characters = ref<PartyChar[]>([])
const loading = ref(false)
const saving = ref(false)
const status = ref<{ kind: 'ok' | 'err'; text: string } | null>(null)
const fileExists = ref<boolean | null>(null)

const canSave = computed(() => {
  if (!props.configPath.trim()) return false
  if (!characters.value.length) return false
  return characters.value.every(c => c.name.trim() && c.sheet.trim())
})

// Sheet/backstory/dossier/arc-score references resolve against the CAMPAIGN
// ROOT, not against party.yaml's own directory — see docs/config/
// grounding-isolation.md Track A' (issues #145/#146). The UI must use the same
// base as the loader, otherwise the green existence check passes for a path
// the loader will reject (or vice versa, once party.yaml lives in config/).
const yamlParentDir = computed(() =>
  (useConfigStore().resolved.campaign_dir || '').trim()
)

async function load() {
  if (!props.configPath.trim()) {
    status.value = { kind: 'err', text: 'Set the party config path first.' }
    return
  }
  loading.value = true
  status.value = null
  try {
    const url = `/api/config/party-yaml?path=${encodeURIComponent(props.configPath)}`
    const data = await apiFetch<{ exists: boolean; characters: PartyChar[] }>(url)
    fileExists.value = data.exists
    characters.value = data.characters.length
      ? data.characters
      : []
    if (!data.exists) {
      status.value = { kind: 'ok', text: 'New file — add characters and Save to create.' }
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
    await apiPut('/api/config/party-yaml', {
      path: props.configPath,
      characters: characters.value,
    })
    fileExists.value = true
    status.value = { kind: 'ok', text: 'Saved.' }
    emit('saved', props.configPath)
  } catch (e: any) {
    status.value = { kind: 'err', text: e?.message || 'Save failed' }
  } finally {
    saving.value = false
  }
}

function addChar() {
  characters.value.push({
    name: '', sheet: '', backstory: '', dossier: '', arc_score: '', trackless: false,
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

watch(() => props.configPath, () => {
  // Path changed; clear loaded state so the next open re-loads.
  characters.value = []
  fileExists.value = null
  status.value = null
})
</script>

<template>
  <div class="editor-wrap">
    <div class="editor-controls">
      <button class="btn-neutral btn-sm" @click="open = !open" type="button">
        {{ open ? 'Hide' : 'Edit' }} party config
      </button>
      <button v-if="open" class="btn-neutral btn-sm" :disabled="loading || !configPath" @click="load" type="button">
        Reload
      </button>
      <span v-if="open && fileExists === false" class="status-pill status-new">New file</span>
      <span v-if="status" :class="['status-text', status.kind === 'err' ? 'err' : 'ok']">
        {{ status.text }}
      </span>
    </div>

    <div v-if="open" class="editor-panel">
      <p v-if="loading" class="muted">Loading…</p>

      <div v-else>
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
.status-text { font-size: 11px; }
.status-text.ok { color: var(--green); }
.status-text.err { color: var(--red); }

.editor-panel {
  margin-top: 10px; padding: 12px;
  background: var(--bg-mantle); border-radius: 4px;
  border: 1px solid var(--bg-surface0);
}

.muted { color: var(--text-muted); font-size: 11px; }
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
