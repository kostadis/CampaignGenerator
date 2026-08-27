<script setup lang="ts">
/**
 * State Projection — staleness table + per-section rebuild
 * (specs/006-state-projection-service, User Story 4).
 *
 * Deliberately stateless beyond the current picker/selection (FR-022a):
 * every row is re-derived from `GET /api/projections/sections` on load, doc
 * switch, or a completed build — nothing here is cached across a reload.
 * `RunPanel` carries the shared `SelectionPanel` so the model/backend a
 * rebuild will spend tokens on is visible and overridable before the run,
 * never assumed (FR-019).
 */
import { ref, computed, watch, onMounted } from 'vue'
import { apiFetch } from '../../api/client'
import RunPanel from '../../components/shared/RunPanel.vue'

interface Provenance {
  dossier_set: string | null
  importance_list: string | null
}

interface SectionRow {
  name: string
  mode: string
  state: string
  inputs: string[]
  /** The subset of `inputs` that does not exist on disk, computed by
   *  `grounding_sections` where `section_inputs()` already knows (research
   *  D11). The browser cannot stat the disk and must never re-derive this. */
  missing?: string[]
  provenance: Provenance | null
}

// The three documents grounding_sections.py declares (SPECS in
// pipelines/grounding/grounding_sections.py) — a UI-only label list, not a
// path or default this page resolves anything from.
const DOCS: { value: string; label: string }[] = [
  { value: 'campaign_state', label: 'Campaign State' },
  { value: 'world_state', label: 'World State' },
  { value: 'planning', label: 'Planning' },
]

const doc = ref(DOCS[0].value)
const sections = ref<SectionRow[]>([])
const loading = ref(false)
const loadError = ref('')
const selected = ref<Set<string>>(new Set())
const force = ref(false)

async function loadSections() {
  loading.value = true
  loadError.value = ''
  try {
    const body = await apiFetch<{ doc: string; sections: SectionRow[] }>(
      `/api/projections/sections?doc=${encodeURIComponent(doc.value)}`,
    )
    sections.value = body.sections || []
  } catch (e: any) {
    loadError.value = e?.message || 'Failed to load sections'
    sections.value = []
  } finally {
    // Selection resets on every reload — never carries a pick from a
    // section set that may no longer match what's on screen.
    selected.value = new Set()
    loading.value = false
  }
}

function toggle(name: string) {
  const next = new Set(selected.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  selected.value = next
}

const allSelected = computed(
  () => sections.value.length > 0 && sections.value.every((s) => selected.value.has(s.name)),
)

function toggleAll() {
  // Explicit "select all" — Constitution X: the full set is a choice the
  // operator makes here, never an implicit default for an empty pick.
  selected.value = allSelected.value
    ? new Set()
    : new Set(sections.value.map((s) => s.name))
}

const selectedNames = computed(() => Array.from(selected.value))
const canRun = computed(() => selectedNames.value.length > 0)

const runParams = computed(() => ({
  doc: doc.value,
  sections: selectedNames.value,
  force: force.value,
}))

/** Sections that were selected for the failed build and have no input file.
 *  Captured at failure time so the explanation survives the reload below. */
const blockedByMissingInput = ref<SectionRow[]>([])

function onBuildDone(rc: number) {
  if (rc === 0) {
    blockedByMissingInput.value = []
    loadSections()
    return
  }
  // T057 / FR-026 — `assemble()` refuses to write ANY draft while a REQUIRED
  // section's file is missing, and its stderr names a bare path. On its own
  // that is the #337 dead end: a filename the GM has no way to act on. The
  // raw output stays (it is the engine's own words); this adds which section
  // is responsible and, for `threads`, where to go and fix it.
  blockedByMissingInput.value = sections.value.filter(
    (s) => selected.value.has(s.name) && s.state === 'no-input',
  )
}

const STATE_LABEL: Record<string, string> = {
  fresh: 'fresh',
  stale: 'stale',
  unbuilt: 'unbuilt',
  'no-input': 'no input',
  optional: 'optional',
  'per-npc': 'per-npc',
}

function stateClass(state: string): string {
  return `state-${state}`
}

watch(doc, loadSections)
onMounted(loadSections)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>State Projection</h2>
      <p class="subtitle">
        Which sections of each grounding document are fresh, stale, or unbuilt — rebuild just the
        ones that changed, without regenerating the whole document.
      </p>
    </div>

    <div class="form-grid">
      <div class="form-section doc-row">
        <div class="field">
          <label class="field-label">Document</label>
          <select v-model="doc" class="field-input doc-select">
            <option v-for="d in DOCS" :key="d.value" :value="d.value">{{ d.label }}</option>
          </select>
        </div>
        <button class="btn-neutral btn-sm" :disabled="loading" @click="loadSections">
          {{ loading ? 'Loading…' : 'Refresh' }}
        </button>
      </div>

      <div v-if="loadError" class="error-box">{{ loadError }}</div>

      <div class="form-section">
        <table v-if="sections.length" class="sections-table">
          <thead>
            <tr>
              <th class="col-check">
                <input type="checkbox" :checked="allSelected" @change="toggleAll" />
              </th>
              <th>Section</th>
              <th>Mode</th>
              <th>State</th>
              <th>Inputs</th>
              <th>Provenance</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in sections" :key="s.name">
              <td class="col-check">
                <input type="checkbox" :checked="selected.has(s.name)" @change="toggle(s.name)" />
              </td>
              <td class="mono">{{ s.name }}</td>
              <td class="mono muted">{{ s.mode }}</td>
              <td>
                <span class="state-badge" :class="stateClass(s.state)">
                  {{ STATE_LABEL[s.state] || s.state }}
                </span>
              </td>
              <td class="muted inputs-cell">
                <template v-if="s.inputs.length">
                  <div v-for="p in s.inputs" :key="p" class="input-path">
                    <span :class="{ 'input-missing': (s.missing || []).includes(p) }">{{ p }}</span>
                    <span v-if="(s.missing || []).includes(p)" class="missing-tag">missing</span>
                  </div>
                </template>
                <span v-else>—</span>
                <!-- T056: #337's dead end, converted into a signpost BEFORE a
                     build is attempted rather than after its stderr. -->
                <RouterLink
                  v-if="s.name === 'threads' && s.state === 'no-input'"
                  class="signpost"
                  to="/grounding/threads"
                >no thread registry yet → Threads</RouterLink>
              </td>
              <td class="muted prov-cell">
                <template v-if="s.provenance">
                  <span v-if="s.provenance.dossier_set" class="prov-tag">{{ s.provenance.dossier_set }}</span>
                  <span
                    v-if="s.provenance.importance_list"
                    class="prov-tag prov-importance"
                    :title="s.provenance.importance_list"
                  >importance list</span>
                  <span v-if="!s.provenance.dossier_set && !s.provenance.importance_list">—</span>
                </template>
                <span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else-if="!loading && !loadError" class="empty-box">
          No sections declared for this document.
        </div>
      </div>

      <div class="form-section rebuild-row">
        <label class="checkbox-label">
          <input type="checkbox" v-model="force" />
          Force (ignore fresh stamps)
        </label>
        <span class="selection-count">{{ selectedNames.length }} section(s) selected</span>
      </div>

      <RunPanel
        selection-service="projections"
        :selection-can-override="true"
        endpoint="/api/projections/run/build"
        :params="runParams"
        :disabled="!canRun"
        label="Rebuild selected section(s)"
        @done="onBuildDone"
      />

      <div v-if="blockedByMissingInput.length" class="blocked-box">
        <p>
          The build stopped because
          {{ blockedByMissingInput.length === 1 ? 'a required section has' : 'required sections have' }}
          no input file yet:
        </p>
        <ul>
          <li v-for="s in blockedByMissingInput" :key="s.name">
            <strong>{{ s.name }}</strong>
            <span v-if="(s.missing || []).length"> — needs {{ (s.missing || []).join(', ') }}</span>
            <RouterLink v-if="s.name === 'threads'" class="signpost" to="/grounding/threads">
              create it on the Threads page →
            </RouterLink>
          </li>
        </ul>
        <p class="muted">
          A required section with no file blocks the whole document, not just
          its own part of it.
        </p>
      </div>
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

.doc-row { display: flex; align-items: flex-end; gap: 10px; }
.field { flex: 1; max-width: 260px; }
.field-label {
  display: block; font-size: 11px; font-weight: 600;
  color: var(--text-sub); margin-bottom: 3px;
}
.field-input {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--sans); font-size: 12px;
  outline: none; box-sizing: border-box;
}
.field-input:focus { border-color: var(--mauve); }

.inputs-cell { max-width: 22rem; }
.input-path { font-family: monospace; font-size: 11px; line-height: 1.5; }
.input-missing { text-decoration: line-through; opacity: 0.75; }
.missing-tag {
  margin-left: 4px; font-family: inherit; font-size: 10px;
  color: #b45309; font-weight: 600;
}
.signpost { display: inline-block; margin-top: 2px; font-size: 11px; }
.blocked-box {
  margin-top: 12px; padding: 10px 12px; border-radius: 4px;
  border: 1px solid #f5c2c7; background: #fff5f5; color: #842029;
}
.blocked-box ul { margin: 6px 0; padding-left: 18px; }
.blocked-box .muted { color: inherit; opacity: 0.8; font-size: 11px; }

.error-box {
  padding: 8px 12px; background: #3a1e1e; border-radius: 4px;
  font-size: 11px; color: var(--red); line-height: 1.5;
}
.empty-box {
  padding: 10px 12px; font-size: 11px; color: var(--text-muted);
}

.sections-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.sections-table th {
  text-align: left;
  padding: 6px 8px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: var(--text-muted);
  border-bottom: 1px solid var(--bg-surface1);
}
.sections-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--bg-surface0);
  vertical-align: middle;
}
.sections-table tr:last-child td { border-bottom: none; }
.col-check { width: 28px; }
.mono { font-family: var(--mono); color: var(--text); }
.muted { color: var(--text-sub); }

.state-badge {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: .03em;
}
.state-fresh    { background: #1e3a2a; color: var(--green); }
.state-stale    { background: #3a2e1e; color: var(--peach); }
.state-unbuilt  { background: var(--bg-surface0); color: var(--text-muted); }
.state-no-input { background: #3a1e1e; color: var(--red); }
.state-optional { background: #1e2d3a; color: var(--blue); }
.state-per-npc  { background: #2d1e3a; color: var(--mauve); }

.prov-cell { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.prov-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--bg-surface0);
  color: var(--text-sub);
  white-space: nowrap;
}
.prov-importance { cursor: help; }

.rebuild-row {
  display: flex;
  align-items: center;
  gap: 16px;
}
.checkbox-label {
  font-size: 11px; color: var(--text-sub); display: flex;
  align-items: center; gap: 6px; cursor: pointer;
}
.checkbox-label input { accent-color: var(--mauve); }
.selection-count { font-size: 11px; color: var(--text-muted); }
</style>
