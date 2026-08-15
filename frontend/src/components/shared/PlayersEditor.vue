<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { apiFetch, apiPut } from '../../api/client'

/**
 * The player roster — feature 009.
 *
 * This edits `<campaign>/config/players.yaml`, which is the ONE place a
 * player's identity is authored. Everything else that mentions a player — the
 * roster block in a narration prompt, the speaker labels in a transcript, the
 * `Player:` line stamped into a converted character sheet — is rendered from
 * here or reported as drift. Adding a fifteenth hand-synced store is exactly
 * what `docs/design/PlayerIdentity.md` says not to do.
 *
 * `name` and `display_names` are deliberately two fields doing two jobs. The
 * retired `party.yaml` `player:` field was documented as the recording label
 * and rendered into prompts as the person's name, and the half that failed did
 * so silently.
 */
interface Problem {
  kind: 'unknown_character' | 'no_display_name'
  value: string
  detail: string
}

interface PlayerRow {
  id: string
  name: string
  display_names: string[]
  plays: string[]
  gm: boolean
  active: boolean
  dndbeyond_id: string
  /** Server-reported references that do not resolve. Never blocks a save. */
  problems?: Problem[]
  /** Form-local: the list fields bind to a comma-separated string. */
  _displayNames: string
  _plays: string
}

const emit = defineEmits<{ saved: [] }>()

const players = ref<PlayerRow[]>([])
const loading = ref(false)
const saving = ref(false)
const status = ref<{ kind: 'ok' | 'err'; text: string } | null>(null)
const fileExists = ref<boolean | null>(null)

const canSave = computed(() =>
  players.value.every(p => p.id.trim() && p.name.trim()),
)

const problemCount = computed(() =>
  players.value.reduce((n, p) => n + (p.problems?.length ? 1 : 0), 0),
)

function splitList(s: string): string[] {
  return s.split(',').map(v => v.trim()).filter(Boolean)
}

function normalize(rows: any[]): PlayerRow[] {
  // The API omits defaults rather than sending them; the form binds to
  // concrete values.
  return rows.map(p => ({
    id: p.id ?? '',
    name: p.name ?? '',
    display_names: p.display_names ?? [],
    plays: p.plays ?? [],
    gm: !!p.gm,
    active: p.active !== false,
    dndbeyond_id: p.dndbeyond_id ?? '',
    problems: p.problems ?? [],
    _displayNames: (p.display_names ?? []).join(', '),
    _plays: (p.plays ?? []).join(', '),
  }))
}

async function load() {
  loading.value = true
  status.value = null
  try {
    const rows = await apiFetch<any[]>('/api/players/players')
    players.value = normalize(rows)
    fileExists.value = rows.length > 0
    if (!rows.length) {
      status.value = { kind: 'ok', text: 'No players recorded yet — add one and Save to create the file.' }
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
    // `problems` is server-reported output, not an input field, and Player is
    // extra="forbid" — sending it back makes every save a 422. Strip it, and
    // the two form-local mirrors, rather than loosening the model.
    const payload = players.value.map(p => ({
      id: p.id.trim(),
      name: p.name.trim(),
      display_names: splitList(p._displayNames),
      plays: splitList(p._plays),
      gm: p.gm,
      active: p.active,
      dndbeyond_id: p.dndbeyond_id.trim() || null,
    }))
    // One atomic PUT of the whole roster, not delete-all-then-recreate: row
    // order is meaningful and the file is never briefly empty.
    const rows = await apiPut<any[]>('/api/players/players', payload)
    players.value = normalize(rows)
    fileExists.value = true
    const n = problemCount.value
    status.value = n
      ? { kind: 'ok', text: `Saved. ${n} player(s) have something to look at.` }
      : { kind: 'ok', text: 'Saved.' }
    emit('saved')
  } catch (e: any) {
    status.value = { kind: 'err', text: e?.message || 'Save failed' }
  } finally {
    saving.value = false
  }
}

function addPlayer() {
  players.value.push({
    id: '', name: '', display_names: [], plays: [], gm: false, active: true,
    dndbeyond_id: '', problems: [], _displayNames: '', _plays: '',
  })
}

function removePlayer(i: number) {
  players.value.splice(i, 1)
}

function movePlayer(i: number, dir: -1 | 1) {
  const j = i + dir
  if (j < 0 || j >= players.value.length) return
  const a = players.value
  ;[a[i], a[j]] = [a[j], a[i]]
}

onMounted(load)
</script>

<template>
  <div class="editor-wrap">
    <div class="editor-controls">
      <button class="btn-neutral btn-sm" :disabled="loading" @click="load" type="button">
        Reload
      </button>
      <span v-if="fileExists === false" class="status-pill status-new">New file</span>
      <span v-if="problemCount" class="status-pill status-missing"
        title="These are saved. The references just do not resolve yet.">
        {{ problemCount }} with notes
      </span>
      <span v-if="status" :class="['status-text', status.kind === 'err' ? 'err' : 'ok']">
        {{ status.text }}
      </span>
    </div>

    <p v-if="loading" class="muted">Loading…</p>

    <div v-else class="editor-panel">
      <div v-if="!players.length" class="empty">
        Nobody recorded yet. Click "Add player" to start.
      </div>

      <div v-for="(p, i) in players" :key="i" class="player-card" :class="{ inactive: !p.active }">
        <div class="player-header">
          <input type="text" class="id-input" v-model="p.id" placeholder="id (e.g. wade)" />
          <input type="text" class="name-input" v-model="p.name" placeholder="Name (e.g. Wade Brown)" />
          <div class="player-actions">
            <button class="icon-btn" @click="movePlayer(i, -1)" :disabled="i === 0" type="button" title="Move up">↑</button>
            <button class="icon-btn" @click="movePlayer(i, 1)" :disabled="i === players.length - 1" type="button" title="Move down">↓</button>
            <button class="icon-btn danger" @click="removePlayer(i)" type="button" title="Remove">✕</button>
          </div>
        </div>

        <div class="player-body">
          <div class="field">
            <label class="field-label">Display names</label>
            <input type="text" class="text-input" v-model="p._displayNames"
                   placeholder="Wade, Wade Brown" />
            <p class="field-help">
              Comma-separated. Every label the recording has <em>ever</em> used for this
              person, not just the current one — speaker matching is exact, and the back
              catalogue of transcripts still carries the old label. Leave empty if this
              player never appears in a recording.
            </p>
          </div>

          <div class="field">
            <label class="field-label">Plays</label>
            <input type="text" class="text-input" v-model="p._plays"
                   placeholder="Soma" />
            <p class="field-help">
              Comma-separated character names from <code>party.yaml</code>. One person may
              play several; one character may be co-piloted by several people.
            </p>
          </div>

          <div class="field">
            <label class="field-label">D&amp;D Beyond id</label>
            <input type="text" class="text-input" v-model="p.dndbeyond_id"
                   placeholder="67390528" />
            <p class="field-help">
              Optional. From the export filename. Recorded only — nothing reads it yet.
            </p>
          </div>

          <div class="flag-row">
            <label class="checkbox-label">
              <input type="checkbox" v-model="p.gm" />
              Runs the game
              <span class="hint">— their lines are labelled GM, even when they also play a character</span>
            </label>
            <label class="checkbox-label">
              <input type="checkbox" v-model="p.active" />
              Still at the table
              <span class="hint">— uncheck instead of deleting; old transcripts still carry their label</span>
            </label>
          </div>

          <ul v-if="p.problems?.length" class="problems">
            <li v-for="(pr, k) in p.problems" :key="k">{{ pr.detail }}</li>
          </ul>
        </div>
      </div>

      <div class="editor-footer">
        <button class="btn-neutral btn-sm" @click="addPlayer" type="button">+ Add player</button>
        <button class="btn-primary btn-sm" :disabled="!canSave || saving" @click="save" type="button">
          {{ saving ? 'Saving…' : 'Save players.yaml' }}
        </button>
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
.empty {
  color: var(--text-muted); font-size: 11px;
  padding: 12px; text-align: center;
  border: 1px dashed var(--bg-surface1); border-radius: 4px;
}

.player-card {
  background: var(--bg-base); border: 1px solid var(--bg-surface0);
  border-radius: 4px; padding: 10px; margin-bottom: 10px;
}
.player-card.inactive { opacity: 0.65; }

.player-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.id-input, .name-input {
  padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-mantle);
  color: var(--text); font-size: 12px; outline: none; box-sizing: border-box;
}
.id-input { width: 120px; font-family: var(--font-mono, monospace); }
.name-input { flex: 1; font-weight: 600; }
.id-input:focus, .name-input:focus { border-color: var(--mauve); }

.player-actions { display: flex; gap: 4px; }
.icon-btn {
  width: 24px; height: 24px; border-radius: 3px;
  background: var(--bg-surface0); color: var(--text-sub);
  border: 1px solid var(--bg-surface1); cursor: pointer; font-size: 11px;
}
.icon-btn:hover { background: var(--bg-surface1); color: var(--text); }
.icon-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.icon-btn.danger:hover { background: var(--red); color: var(--bg-base); border-color: var(--red); }

.player-body { display: flex; flex-direction: column; gap: 8px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field-label { font-size: 11px; color: var(--text-sub); font-weight: 600; }
.text-input {
  padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-mantle);
  color: var(--text); font-size: 12px; outline: none; box-sizing: border-box;
}
.text-input:focus { border-color: var(--mauve); }
.field-help { font-size: 10px; color: var(--text-muted); line-height: 1.5; }

.flag-row { display: flex; flex-direction: column; gap: 6px; }
.checkbox-label {
  font-size: 11px; color: var(--text-sub);
  display: flex; align-items: center; gap: 6px; cursor: pointer;
}
.checkbox-label input { accent-color: var(--mauve); }
.checkbox-label .hint { color: var(--text-muted); font-weight: 400; }

.problems {
  margin: 4px 0 0; padding-left: 18px;
  font-size: 10px; color: var(--yellow); line-height: 1.6;
}

.editor-footer {
  display: flex; justify-content: space-between; align-items: center;
  margin-top: 12px;
}
</style>
