<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { apiFetch, apiPut } from '../../api/client'
import PathField from './PathField.vue'

interface PlanningEntry {
  name: string
  dossier: string
  arc_score: string
  trackless: boolean
}

const props = defineProps<{
  /** Absolute path to the planning.yaml file. */
  configPath: string
}>()

const emit = defineEmits<{
  saved: [path: string]
}>()

const open = ref(false)
const npcs = ref<PlanningEntry[]>([])
const factions = ref<PlanningEntry[]>([])
const loading = ref(false)
const saving = ref(false)
const status = ref<{ kind: 'ok' | 'err'; text: string } | null>(null)
const fileExists = ref<boolean | null>(null)

// NPCs require name + dossier. Factions require only name. At least one
// entry total. Matches the loader (planning.py:load_planning_config).
const canSave = computed(() => {
  if (!props.configPath.trim()) return false
  if (!npcs.value.length && !factions.value.length) return false
  const npcOk = npcs.value.every(e => e.name.trim() && e.dossier.trim())
  const factionOk = factions.value.every(e => e.name.trim())
  return npcOk && factionOk
})

const yamlParentDir = computed(() => {
  const p = props.configPath.trim()
  if (!p) return ''
  const i = p.lastIndexOf('/')
  return i >= 0 ? p.slice(0, i) : ''
})

async function load() {
  if (!props.configPath.trim()) {
    status.value = { kind: 'err', text: 'Set the planning config path first.' }
    return
  }
  loading.value = true
  status.value = null
  try {
    const url = `/api/config/planning-yaml?path=${encodeURIComponent(props.configPath)}`
    const data = await apiFetch<{
      exists: boolean
      npcs: PlanningEntry[]
      factions: PlanningEntry[]
    }>(url)
    fileExists.value = data.exists
    npcs.value = data.npcs ?? []
    factions.value = data.factions ?? []
    if (!data.exists) {
      status.value = { kind: 'ok', text: 'New file — add entries and Save to create.' }
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
    await apiPut('/api/config/planning-yaml', {
      path: props.configPath,
      npcs: npcs.value,
      factions: factions.value,
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

function blank(): PlanningEntry {
  return { name: '', dossier: '', arc_score: '', trackless: false }
}

function addNpc() { npcs.value.push(blank()) }
function addFaction() { factions.value.push(blank()) }
function removeEntry(list: PlanningEntry[], i: number) { list.splice(i, 1) }
function moveEntry(list: PlanningEntry[], i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= list.length) return
  ;[list[i], list[j]] = [list[j], list[i]]
}

function toggleTrackless(e: PlanningEntry) {
  e.trackless = !e.trackless
  if (e.trackless) e.arc_score = ''
}

watch(() => open.value, (o) => {
  if (o && !npcs.value.length && !factions.value.length) load()
})

watch(() => props.configPath, () => {
  npcs.value = []
  factions.value = []
  fileExists.value = null
  status.value = null
})
</script>

<template>
  <div class="editor-wrap">
    <div class="editor-controls">
      <button class="btn-neutral btn-sm" @click="open = !open" type="button">
        {{ open ? 'Hide' : 'Edit' }} planning config
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
        <!-- NPCs -->
        <div class="group-header">
          <h4>NPCs</h4>
          <span class="group-hint">Per-NPC dossier (required) + optional arc score. Use trackless for NPCs the synthesizer should not invent a score for.</span>
        </div>

        <div v-if="!npcs.length" class="empty">
          No NPCs yet. Click "Add NPC" to start.
        </div>

        <div v-for="(e, i) in npcs" :key="`npc-${i}`" class="char-card">
          <div class="char-header">
            <input
              type="text"
              class="name-input"
              v-model="e.name"
              placeholder="NPC name (e.g. Adabra)"
            />
            <div class="char-actions">
              <button class="icon-btn" @click="moveEntry(npcs, i, -1)" :disabled="i === 0" type="button" title="Move up">↑</button>
              <button class="icon-btn" @click="moveEntry(npcs, i, 1)" :disabled="i === npcs.length - 1" type="button" title="Move down">↓</button>
              <button class="icon-btn danger" @click="removeEntry(npcs, i)" type="button" title="Remove">✕</button>
            </div>
          </div>

          <div class="char-body">
            <PathField
              :model-value="e.dossier"
              @update:model-value="(v: string) => (e.dossier = v)"
              label="Dossier (required)"
              required
              :base-dir="yamlParentDir"
              help="Path relative to planning.yaml (e.g. docs/npcs/adabra.md)."
            />

            <div class="arc-row">
              <label class="checkbox-label trackless-toggle">
                <input
                  type="checkbox"
                  :checked="e.trackless"
                  @change="toggleTrackless(e)"
                />
                Intentionally trackless
                <span class="hint">— synthesizer will not invent an arc score for this NPC</span>
              </label>

              <PathField
                v-if="!e.trackless"
                :model-value="e.arc_score"
                @update:model-value="(v: string) => (e.arc_score = v)"
                label="Arc score mechanic"
                :base-dir="yamlParentDir"
                help="Optional. Path relative to planning.yaml (e.g. docs/tracking/adabra-quest.md)."
              />
            </div>
          </div>
        </div>

        <div class="row-action">
          <button class="btn-neutral btn-sm" @click="addNpc" type="button">+ Add NPC</button>
        </div>

        <!-- Factions -->
        <div class="group-header group-header-second">
          <h4>Factions</h4>
          <span class="group-hint">Faction-level arc scores (Kraken Society, Splinter Colony…). Dossier is optional — usually it's just name + arc score.</span>
        </div>

        <div v-if="!factions.length" class="empty">
          No factions yet. Click "Add faction" to start.
        </div>

        <div v-for="(e, i) in factions" :key="`fac-${i}`" class="char-card">
          <div class="char-header">
            <input
              type="text"
              class="name-input"
              v-model="e.name"
              placeholder="Faction name (e.g. Kraken Society)"
            />
            <div class="char-actions">
              <button class="icon-btn" @click="moveEntry(factions, i, -1)" :disabled="i === 0" type="button" title="Move up">↑</button>
              <button class="icon-btn" @click="moveEntry(factions, i, 1)" :disabled="i === factions.length - 1" type="button" title="Move down">↓</button>
              <button class="icon-btn danger" @click="removeEntry(factions, i)" type="button" title="Remove">✕</button>
            </div>
          </div>

          <div class="char-body">
            <PathField
              :model-value="e.dossier"
              @update:model-value="(v: string) => (e.dossier = v)"
              label="Faction overview"
              :base-dir="yamlParentDir"
              help="Optional. Path relative to planning.yaml."
            />

            <div class="arc-row">
              <label class="checkbox-label trackless-toggle">
                <input
                  type="checkbox"
                  :checked="e.trackless"
                  @change="toggleTrackless(e)"
                />
                Intentionally trackless
                <span class="hint">— synthesizer will not invent an arc score for this faction</span>
              </label>

              <PathField
                v-if="!e.trackless"
                :model-value="e.arc_score"
                @update:model-value="(v: string) => (e.arc_score = v)"
                label="Arc score mechanic"
                :base-dir="yamlParentDir"
                help="Optional. Path relative to planning.yaml."
              />
            </div>
          </div>
        </div>

        <div class="row-action">
          <button class="btn-neutral btn-sm" @click="addFaction" type="button">+ Add faction</button>
        </div>

        <div class="editor-footer">
          <button
            class="btn-primary btn-sm"
            :disabled="!canSave || saving"
            @click="save"
            type="button"
          >
            {{ saving ? 'Saving…' : 'Save planning.yaml' }}
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
  margin-bottom: 10px;
}

.group-header {
  display: flex; flex-direction: column; gap: 2px;
  padding-bottom: 6px; margin-bottom: 10px;
  border-bottom: 1px solid var(--bg-surface0);
}
.group-header-second { margin-top: 18px; }
.group-header h4 { font-size: 12px; font-weight: 700; color: var(--text); margin: 0; }
.group-hint { font-size: 10px; color: var(--text-muted); }

.row-action { margin: 4px 0 6px; }

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
  display: flex; justify-content: flex-end; align-items: center;
  margin-top: 12px;
}
</style>
