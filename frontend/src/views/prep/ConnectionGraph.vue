<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useConfigStore } from '../../stores/config'
import { apiFetch, apiPost } from '../../api/client'
import PathField from '../../components/shared/PathField.vue'
import FileTree from '../../components/shared/FileTree.vue'

const config = useConfigStore()

// Connection Graph owns no config document — it always inherits the
// platform-wide backend (server/routers/connections.py's resolve_selection
// comment), so unlike RunPanel/ExtractSynthesizePanel there is no per-service
// SelectionPanel to read a resolved backend from. `config.backend` (the
// sidebar's own tracked value) IS the backend this run will use, which is why
// the run button names it rather than asserting "calls Claude API". Nothing
// here gates on a credential: #342 deleted that predicate outright, and each
// backend refuses for itself at the call.

// Form state is deliberately stateless — see docs/config/ui-state-retirement.md
// D1 (the reserved `ui.connections` section was never written by anything and
// is retired). The extracted graph itself IS persisted, but on disk via
// `cachePath`, which is the durable artifact here — not this form.
const docsDir = ref('')
const dossierDir = ref('')
const cachePath = ref('')
const extraFiles = ref('')
const availableFiles = ref<string[]>([])
const selectedFiles = ref<string[]>([])
const basePath = ref('')
const loading = ref(false)
const extracting = ref(false)
const replaceExisting = ref(false)
const error = ref('')
const fileSearch = ref('')
const graphHtml = ref('')
const searchQuery = ref('')

// Connection data
const data = ref<{ entities: any[]; edges: any[] } | null>(null)
const cacheInfo = ref('')

// Path finder state
const pathSource = ref('')
const pathTarget = ref('')
const pathMaxHops = ref(4)
const pathResults = ref<any[]>([])
const pathError = ref('')
const pathLoading = ref(false)

// Context panel state
const contextEntityId = ref('')
const contextResult = ref<any | null>(null)
const contextLoading = ref(false)

// Entity type filters
const allTypes = ['npc', 'faction', 'location', 'plot', 'arc_score', 'party']
const filterTypes = ref<Set<string>>(new Set(allTypes))

// Tab state
const activeTab = ref<'build' | 'graph'>('build')

const NODE_COLORS: Record<string, string> = {
  npc: '#4e9af1',
  faction: '#f1814e',
  location: '#4ef1a0',
  plot: '#c44ef1',
  arc_score: '#f1e14e',
  party: '#4ef1e1',
}

const EDGE_LEGEND: Record<string, string> = {
  hostile: 'hostile / enemy / hunts',
  allied: 'ally / serves / supports',
  member: 'member of / controls / leads',
  located: 'located in / based at',
  triggers: 'triggers / linked to',
  seeks: 'seeks / pursues',
  default: 'other relationship',
}
const EDGE_COLORS: Record<string, string> = {
  hostile: '#ff4444',
  allied: '#44ff88',
  member: '#ffaa44',
  located: '#44aaff',
  triggers: '#ff44ff',
  seeks: '#ffff44',
  default: '#cccccc',
}

function shortLabel(fullPath: string): string {
  if (basePath.value && fullPath.startsWith(basePath.value)) {
    return fullPath.slice(basePath.value.length + 1)
  }
  return fullPath.split('/').pop() || fullPath
}

const GROUNDING_DOCS = ['world_state.md', 'campaign_state.md', 'party.md', 'planning.md']

async function scanDocs() {
  const dir = docsDir.value.trim()
  if (!dir) { availableFiles.value = []; return }
  try {
    const res = await apiFetch(`/api/connections/list-docs?docs_dir=${encodeURIComponent(dir)}`)
    availableFiles.value = res.files || []
    basePath.value = res.base || ''
    // Default selection: the four grounding docs. Fall back to first 4 if none match.
    const matches = availableFiles.value.filter(
      (f: string) => GROUNDING_DOCS.includes((f.split('/').pop() || '').toLowerCase())
    )
    selectedFiles.value = matches.length
      ? matches
      : availableFiles.value.slice(0, Math.min(4, availableFiles.value.length))
  } catch {
    availableFiles.value = []
  }
}

const allSelected = computed(() => {
  const extra = extraFiles.value.split('\n').map(s => s.trim()).filter(Boolean)
  return [...selectedFiles.value, ...extra]
})

async function extract() {
  if (!allSelected.value.length) return
  extracting.value = true
  error.value = ''
  try {
    const res = await apiPost('/api/connections/extract', {
      files: allSelected.value,
      model: config.model || undefined,
      dossier_dir: dossierDir.value.trim(),
      cache_path: cachePath.value.trim(),
      replace: replaceExisting.value,
    })
    if (res.error) {
      error.value = res.error
    } else {
      data.value = res.data
      const mergedNote = res.merged ? ' (merged into cache)' : ''
      cacheInfo.value = `${res.entities} entities, ${res.edges} edges${mergedNote}`
      await renderGraph()
      activeTab.value = 'graph'
    }
  } catch (e: any) {
    error.value = e.message || 'Extraction failed'
  } finally {
    extracting.value = false
  }
}

async function findPaths() {
  if (!pathSource.value || !pathTarget.value) return
  pathLoading.value = true
  pathError.value = ''
  pathResults.value = []
  try {
    const params = new URLSearchParams({
      source: pathSource.value,
      target: pathTarget.value,
      max_hops: String(pathMaxHops.value),
    })
    if (cachePath.value.trim()) params.set('cache_path', cachePath.value.trim())
    const res = await apiFetch(`/api/connections/paths?${params}`)
    if (res.error) {
      pathError.value = res.error
    } else {
      pathResults.value = res.paths || []
      if (!pathResults.value.length) {
        pathError.value = `No paths found within ${pathMaxHops.value} hops.`
      }
    }
  } catch (e: any) {
    pathError.value = e.message || 'Path search failed'
  } finally {
    pathLoading.value = false
  }
}

async function loadContext(eid: string) {
  contextEntityId.value = eid
  contextLoading.value = true
  contextResult.value = null
  try {
    const params = new URLSearchParams({ entity_id: eid })
    if (docsDir.value.trim()) params.set('docs_dir', docsDir.value.trim())
    if (dossierDir.value.trim()) params.set('dossier_dir', dossierDir.value.trim())
    if (cachePath.value.trim()) params.set('cache_path', cachePath.value.trim())
    const res = await apiFetch(`/api/connections/context?${params}`)
    contextResult.value = res
  } catch (e: any) {
    contextResult.value = { error: e.message || 'Context lookup failed' }
  } finally {
    contextLoading.value = false
  }
}

function useAsPathSource(eid: string) {
  pathSource.value = eid
}

function useAsPathTarget(eid: string) {
  pathTarget.value = eid
}

async function loadCached() {
  data.value = null
  cacheInfo.value = ''
  graphHtml.value = ''
  try {
    const params = cachePath.value.trim()
      ? `?cache_path=${encodeURIComponent(cachePath.value.trim())}`
      : ''
    const res = await apiFetch(`/api/connections/data${params}`)
    if (res.data) {
      data.value = res.data
      const ents = res.data.entities?.length || 0
      const edgs = res.data.edges?.length || 0
      cacheInfo.value = `${ents} entities, ${edgs} edges (cached)`
      await renderGraph()
    }
  } catch { /* no cache */ }
}

async function renderGraph() {
  loading.value = true
  try {
    const qs = cachePath.value.trim()
      ? `?cache_path=${encodeURIComponent(cachePath.value.trim())}`
      : ''
    const res = await fetch(`/api/connections/graph${qs}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filter_types: [...filterTypes.value] }),
    })
    graphHtml.value = await res.text()
  } catch {
    graphHtml.value = '<p style="color:#fab387">Failed to render graph</p>'
  } finally {
    loading.value = false
  }
}

function toggleFilter(t: string) {
  if (filterTypes.value.has(t)) {
    filterTypes.value.delete(t)
  } else {
    filterTypes.value.add(t)
  }
  filterTypes.value = new Set(filterTypes.value) // trigger reactivity
  if (data.value) renderGraph()
}

// Computed entity stats
const visibleEntities = computed(() => {
  if (!data.value) return []
  return data.value.entities.filter((e: any) => filterTypes.value.has(e.type))
})

const visibleEdges = computed(() => {
  if (!data.value) return []
  const ids = new Set(visibleEntities.value.map((e: any) => e.id))
  return data.value.edges.filter((e: any) => ids.has(e.source) && ids.has(e.target))
})

const filteredEntities = computed(() => {
  const q = searchQuery.value.toLowerCase()
  if (!q) return visibleEntities.value
  return visibleEntities.value.filter((e: any) =>
    e.label.toLowerCase().includes(q) || (e.summary || '').toLowerCase().includes(q)
  )
})

// Watch docs dir changes
let scanTimer: ReturnType<typeof setTimeout> | null = null
watch(docsDir, () => {
  if (scanTimer) clearTimeout(scanTimer)
  scanTimer = setTimeout(scanDocs, 500)
})

// Watch cache path changes — reload from the new location
let cacheTimer: ReturnType<typeof setTimeout> | null = null
watch(cachePath, () => {
  if (cacheTimer) clearTimeout(cacheTimer)
  cacheTimer = setTimeout(loadCached, 500)
})

onMounted(() => {
  // Default paths from campaign config — always per-campaign, never the server CWD.
  const cd = config.resolved.campaign_dir || ''
  if (cd) {
    const base = cd.replace(/\/+$/, '')
    docsDir.value = base + '/docs'
    dossierDir.value = base + '/docs/npcs'
    cachePath.value = base + '/docs/connections.json'
  }
  loadCached()
})

// Entity options for path finder dropdowns — sorted by type then label
const entityOptions = computed(() => {
  if (!data.value) return []
  return [...data.value.entities].sort((a: any, b: any) => {
    if (a.type !== b.type) return a.type.localeCompare(b.type)
    return a.label.localeCompare(b.label)
  })
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Connection Graph</h2>
      <p class="subtitle">Visualize relationships between NPCs, factions, locations, and plot threads.</p>
    </div>

    <!-- Tab switcher -->
    <div class="tab-bar">
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'build' }"
        @click="activeTab = 'build'"
      >Create Graph</button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'graph' }"
        :disabled="!data"
        @click="activeTab = 'graph'"
      >Graph{{ data ? '' : ' (extract first)' }}</button>
    </div>

    <!-- BUILD TAB -->
    <div v-show="activeTab === 'build'">
    <!-- File selection -->
    <div class="form-section">
      <PathField
        v-model="docsDir"
        label="Campaign docs directory"
        absolute
        help="Folder to scan for .md files"
      />

      <PathField
        v-model="dossierDir"
        label="NPC dossier directory (optional)"
        absolute
        help="Use alias frontmatter to canonicalize NPC names before extraction. Typically docs/npcs/"
      />

      <PathField
        v-model="cachePath"
        label="Connections cache file"
        absolute
        help="Per-campaign connections.json — all extract/query operations read and write here"
      />

      <div v-if="availableFiles.length" class="file-selector">
        <div class="file-selector-header">
          <label class="field-label">
            Documents to include ({{ selectedFiles.length }} selected / {{ availableFiles.length }} total)
          </label>
          <input
            type="text"
            class="field-input tree-search"
            v-model="fileSearch"
            placeholder="Filter files or folders..."
          />
        </div>
        <FileTree
          :files="availableFiles"
          :base-path="basePath"
          v-model="selectedFiles"
          :search-query="fileSearch"
        />
      </div>

      <div class="field">
        <label class="field-label">Additional files (one per line)</label>
        <textarea
          class="field-textarea"
          v-model="extraFiles"
          rows="3"
          placeholder="Paste absolute paths to files outside docs/"
        ></textarea>
      </div>
    </div>

    <!-- Extract button -->
    <div class="form-section action-row">
      <button
        class="btn-primary"
        :disabled="!allSelected.length || extracting"
        @click="extract"
      >
        {{ extracting ? 'Extracting...' : `Extract Connections (runs on ${config.backend})` }}
      </button>
      <label class="replace-toggle" title="If unchecked, results merge into existing connections.json">
        <input type="checkbox" v-model="replaceExisting" />
        Replace cache (don't merge)
      </label>
      <span v-if="cacheInfo" class="cache-info">{{ cacheInfo }}</span>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <!-- Graph and controls -->
    <template v-if="data">
      <!-- Entity context panel -->
      <div v-if="contextResult" class="form-section context-panel">
        <h3 class="section-title">Context: {{ contextResult.entity?.label || contextEntityId }}</h3>
        <div v-if="contextLoading" class="loading-note">Loading…</div>
        <div v-else-if="contextResult.error" class="error-msg">{{ contextResult.error }}</div>
        <template v-else-if="contextResult.entity">
          <p class="context-summary">{{ contextResult.entity.summary }}</p>

          <div class="context-sub">
            <div class="context-label">1-hop neighbors ({{ contextResult.neighbors.length }})</div>
            <ul v-if="contextResult.neighbors.length" class="neighbor-list">
              <li v-for="(n, i) in contextResult.neighbors" :key="i" class="neighbor-item">
                <span class="neighbor-arrow">{{ n.direction === 'out' ? '→' : '←' }}</span>
                <span class="neighbor-label">{{ n.edge_label }}</span>
                <span class="neighbor-arrow">{{ n.direction === 'out' ? '' : '' }}</span>
                <a class="neighbor-name" @click="loadContext(n.entity.id)">{{ n.entity.label }}</a>
                <span class="type-badge small" :style="{ background: NODE_COLORS[n.entity.type] || '#888' }">{{ n.entity.type }}</span>
              </li>
            </ul>
            <p v-else class="no-results">No direct connections.</p>
          </div>

          <div class="context-sub" v-if="contextResult.source_files !== undefined">
            <div class="context-label">
              Source files ({{ contextResult.source_files.length }})
              <span v-if="!docsDir" class="context-hint">— set docs dir above to populate</span>
            </div>
            <ul v-if="contextResult.source_files.length" class="source-list">
              <li v-for="f in contextResult.source_files" :key="f" class="source-item">{{ shortLabel(f) }}</li>
            </ul>
          </div>
        </template>
      </div>
    </template>
    </div>
    <!-- /BUILD TAB -->

    <!-- GRAPH TAB -->
    <div v-show="activeTab === 'graph'" class="graph-tab">
      <!-- Filter chip row -->
      <div v-if="data" class="graph-toolbar">
        <div class="filter-row">
          <label
            v-for="t in allTypes"
            :key="t"
            class="filter-chip"
            :class="{ active: filterTypes.has(t) }"
            :style="{ '--chip-color': NODE_COLORS[t] }"
          >
            <input type="checkbox" :checked="filterTypes.has(t)" @change="toggleFilter(t)" />
            {{ t.replace('_', ' ') }}
          </label>
        </div>
        <div class="stats">
          {{ visibleEntities.length }} / {{ data.entities.length }} nodes &middot;
          {{ visibleEdges.length }} / {{ data.edges.length }} edges
        </div>
      </div>

      <!-- Graph + sidebar -->
      <div class="graph-body">
        <div class="graph-container-full">
          <div v-if="loading" class="graph-loading">Rendering graph...</div>
          <iframe
            v-else-if="graphHtml"
            :srcdoc="graphHtml"
            class="graph-iframe"
            sandbox="allow-scripts"
          ></iframe>
          <div v-else class="graph-loading">No graph yet — extract connections on the Create Graph tab.</div>
        </div>

        <aside v-if="data" class="graph-sidebar">
          <!-- Legend -->
          <details class="sidebar-legend" open>
            <summary class="section-title">Legend</summary>
            <div class="legend-grid">
              <div class="legend-col">
                <h4 class="legend-title">Node types</h4>
                <div v-for="(color, etype) in NODE_COLORS" :key="etype" class="legend-item">
                  <span class="legend-swatch" :style="{ background: color }"></span>
                  {{ etype.replace('_', ' ') }}
                </div>
              </div>
              <div class="legend-col">
                <h4 class="legend-title">Edge colors</h4>
                <div v-for="(desc, key) in EDGE_LEGEND" :key="key" class="legend-item">
                  <span class="legend-swatch" :style="{ background: EDGE_COLORS[key] }"></span>
                  {{ desc }}
                </div>
              </div>
            </div>
          </details>

          <input
            type="text"
            class="field-input search-input"
            v-model="searchQuery"
            placeholder="Search entities..."
          />
          <div class="sidebar-list">
            <table class="entity-table" v-if="filteredEntities.length">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th class="actions-col">A/B</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="e in filteredEntities"
                  :key="e.id"
                  :class="{ selected: contextEntityId === e.id }"
                  @click="loadContext(e.id)"
                >
                  <td class="ent-name">{{ e.label }}</td>
                  <td><span class="type-badge" :style="{ background: NODE_COLORS[e.type] || '#888' }">{{ e.type.replace('_', ' ') }}</span></td>
                  <td class="actions-col" @click.stop>
                    <button class="mini-btn" @click="useAsPathSource(e.id)" title="Use as path source">A</button>
                    <button class="mini-btn" @click="useAsPathTarget(e.id)" title="Use as path target">B</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-else class="no-results">No entities match your search.</p>
          </div>

          <!-- Path finder -->
          <div class="sidebar-pathfinder">
            <h3 class="section-title">Path Finder — A to B</h3>
            <div class="path-controls-compact">
              <div class="field">
                <label class="field-label">Source (A)</label>
                <select class="field-input" v-model="pathSource">
                  <option value="">— select —</option>
                  <option v-for="e in entityOptions" :key="e.id" :value="e.id">
                    [{{ e.type }}] {{ e.label }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label class="field-label">Target (B)</label>
                <select class="field-input" v-model="pathTarget">
                  <option value="">— select —</option>
                  <option v-for="e in entityOptions" :key="e.id" :value="e.id">
                    [{{ e.type }}] {{ e.label }}
                  </option>
                </select>
              </div>
              <div class="pathfinder-row">
                <div class="field path-hops">
                  <label class="field-label">Max hops</label>
                  <input class="field-input" type="number" min="1" max="8" v-model.number="pathMaxHops" />
                </div>
                <button
                  class="btn-primary path-btn"
                  :disabled="!pathSource || !pathTarget || pathLoading"
                  @click="findPaths"
                >
                  {{ pathLoading ? 'Searching...' : 'Find Paths' }}
                </button>
              </div>
            </div>
            <div v-if="pathError" class="error-msg">{{ pathError }}</div>
            <div v-if="pathResults.length" class="path-results">
              <div class="path-results-header">
                {{ pathResults.length }} path{{ pathResults.length === 1 ? '' : 's' }}
                (shortest: {{ pathResults[0].length }} hop{{ pathResults[0].length === 1 ? '' : 's' }})
              </div>
              <ol class="path-list">
                <li v-for="(p, i) in pathResults" :key="i" class="path-item">
                  <span class="path-length">{{ p.length }} hop{{ p.length === 1 ? '' : 's' }}</span>
                  <span class="path-chain">
                    <template v-for="(node, j) in p.nodes" :key="j">
                      <span
                        class="path-node"
                        :style="{ borderColor: NODE_COLORS[node.type] || '#888' }"
                      >{{ node.label }}</span>
                      <span v-if="j < p.edges.length" class="path-edge">
                        <span class="path-arrow">{{ p.edges[j].source === node.id ? '→' : '←' }}</span>
                        <span class="path-label">{{ p.edges[j].label }}</span>
                      </span>
                    </template>
                  </span>
                </li>
              </ol>
            </div>
          </div>
        </aside>
      </div>
    </div>
    <!-- /GRAPH TAB -->
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box;
        display: flex; flex-direction: column; }

.tab-bar {
  display: flex; gap: 4px; margin-bottom: 16px;
  border-bottom: 1px solid var(--bg-surface1);
}
.tab-btn {
  padding: 8px 16px; background: transparent; border: none;
  color: var(--text-muted); font-size: 12px; font-weight: 600;
  cursor: pointer; border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.tab-btn:hover:not(:disabled) { color: var(--text); }
.tab-btn.active { color: var(--mauve); border-bottom-color: var(--mauve); }
.tab-btn:disabled { opacity: 0.4; cursor: default; }

.graph-tab { flex: 1; display: flex; flex-direction: column; min-height: 0; gap: 10px; }
.graph-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; flex-wrap: wrap; flex-shrink: 0;
}
.graph-toolbar .filter-row { margin-bottom: 0; }
.graph-toolbar .stats { white-space: nowrap; }
.graph-body { flex: 1; display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.graph-container-full {
  flex: 0 0 auto; height: 600px; min-height: 500px;
  border: 1px solid var(--bg-surface1); border-radius: 6px;
  overflow: hidden; background: #1a1a2e;
  display: flex; flex-direction: column;
}
.graph-container-full .graph-iframe { flex: 1; width: 100%; border: none; }
.graph-container-full .graph-loading {
  flex: 1; display: flex; align-items: center; justify-content: center;
  color: var(--text-muted); font-size: 13px;
}
.graph-sidebar {
  width: 100%; flex-shrink: 0; display: flex; flex-direction: column;
  gap: 6px; min-height: 0;
}
.graph-sidebar .search-input { margin-bottom: 0; }
.sidebar-list {
  flex: 1; max-height: 400px; overflow-y: auto; border: 1px solid var(--bg-surface1);
  border-radius: 4px; background: var(--bg-base);
}
.sidebar-list .entity-table { font-size: 10px; }
.sidebar-list .entity-table th { position: sticky; top: 0;
  background: var(--bg-base); z-index: 1; }
.sidebar-list .ent-name { font-size: 11px; }

.sidebar-legend {
  flex-shrink: 0; border: 1px solid var(--bg-surface1);
  border-radius: 4px; padding: 6px 10px; background: var(--bg-base);
}
.sidebar-legend > summary {
  cursor: pointer; list-style: none; margin-bottom: 0;
  display: flex; align-items: center;
}
.sidebar-legend > summary::-webkit-details-marker { display: none; }
.sidebar-legend > summary::before {
  content: '▸'; display: inline-block; margin-right: 6px;
  transition: transform .15s; font-size: 8px;
}
.sidebar-legend[open] > summary::before { transform: rotate(90deg); }
.legend-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px; }

.sidebar-pathfinder {
  flex-shrink: 0; border-top: 1px solid var(--bg-surface1);
  padding-top: 8px;
}
.sidebar-pathfinder .section-title { margin-bottom: 6px; }
.path-controls-compact { display: flex; flex-direction: column; gap: 6px; }
.path-controls-compact .field { margin-bottom: 0; }
.pathfinder-row { display: flex; gap: 6px; align-items: end; }
.pathfinder-row .path-hops { flex: 0 0 80px; }
.pathfinder-row .path-btn { flex: 1; height: 28px; }
.page-header { margin-bottom: 16px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.form-section {
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface0);
}
.section-title {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .08em; color: var(--text-muted); margin-bottom: 8px;
}
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

.file-selector { margin-bottom: 10px; }
.file-selector-header {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 4px;
}
.file-selector-header .field-label { margin: 0; flex-shrink: 0; }
.tree-search { flex: 1; max-width: 320px; }

.action-row { display: flex; align-items: center; gap: 12px; }
.cache-info { font-size: 11px; color: var(--text-muted); }
.warning { font-size: 11px; color: var(--peach); font-weight: 600; }
.error-msg {
  background: #402020; color: #f38ba8; padding: 8px 12px;
  border-radius: 4px; font-size: 12px; margin-bottom: 12px;
}

.filter-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.filter-chip {
  display: flex; align-items: center; gap: 4px;
  padding: 4px 10px; border-radius: 4px; font-size: 11px;
  cursor: pointer; text-transform: capitalize;
  background: var(--bg-surface0); color: var(--text-sub);
  border: 1px solid var(--bg-surface1); transition: all .15s;
}
.filter-chip input { display: none; }
.filter-chip.active {
  background: color-mix(in srgb, var(--chip-color) 20%, transparent);
  border-color: var(--chip-color);
  color: var(--text);
}
.stats { font-size: 11px; color: var(--text-muted); }

.graph-container {
  width: 100%; height: min(85vh, 1100px); min-height: 600px;
  border: 1px solid var(--bg-surface1); border-radius: 6px;
  overflow: hidden; margin-bottom: 16px; background: #1a1a2e;
  resize: vertical;
}
.graph-iframe {
  width: 100%; height: 100%; border: none;
}
.graph-loading {
  display: flex; align-items: center; justify-content: center;
  height: 100%; color: var(--text-muted); font-size: 13px;
}

.legend { display: flex; gap: 32px; }
.legend-col { flex: 1; }
.legend-title {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  color: var(--text-muted); margin-bottom: 6px;
}
.legend-item {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--text-sub); margin-bottom: 3px;
  text-transform: capitalize;
}
.legend-swatch {
  width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0;
}

.search-input { margin-bottom: 8px; }
.entity-table {
  width: 100%; border-collapse: collapse; font-size: 11px;
}
.entity-table th {
  text-align: left; padding: 6px 8px; font-size: 10px;
  font-weight: 700; text-transform: uppercase; color: var(--text-muted);
  border-bottom: 1px solid var(--bg-surface1);
}
.entity-table td {
  padding: 5px 8px; border-bottom: 1px solid var(--bg-surface0);
  color: var(--text-sub);
}
.ent-name { font-weight: 600; color: var(--text); }
.ent-summary { font-size: 10px; }
.type-badge {
  display: inline-block; padding: 1px 6px; border-radius: 3px;
  font-size: 9px; font-weight: 700; color: #000; text-transform: capitalize;
}
.no-results { font-size: 12px; color: var(--text-muted); }

.btn-primary {
  padding: 7px 14px; border: none; border-radius: 4px;
  background: var(--mauve); color: var(--bg-base);
  font-size: 12px; font-weight: 600; cursor: pointer;
}
.btn-primary:disabled { opacity: .4; cursor: default; }

/* Replace-cache toggle next to extract */
.replace-toggle {
  display: flex; align-items: center; gap: 4px;
  font-size: 11px; color: var(--text-muted); cursor: pointer;
}
.replace-toggle input { accent-color: var(--mauve); }

/* Clickable entity rows */
.entity-table tbody tr { cursor: pointer; }
.entity-table tbody tr:hover { background: var(--bg-surface0); }
.entity-table tbody tr.selected { background: color-mix(in srgb, var(--mauve) 15%, transparent); }
.actions-col { width: 60px; text-align: right; white-space: nowrap; }
.mini-btn {
  padding: 2px 6px; border: 1px solid var(--bg-surface1);
  background: var(--bg-surface0); color: var(--text-sub);
  border-radius: 3px; font-size: 10px; cursor: pointer;
  font-weight: 700; margin-left: 2px;
}
.mini-btn:hover { background: var(--mauve); color: var(--bg-base); border-color: var(--mauve); }

/* Path finder */
.path-controls {
  display: grid;
  grid-template-columns: 1fr 1fr 80px auto;
  gap: 8px; align-items: end; margin-bottom: 10px;
}
.path-field { margin-bottom: 0; }
.path-hops { margin-bottom: 0; }
.path-btn { height: 30px; }
.path-results { margin-top: 6px; }
.path-results-header {
  font-size: 11px; color: var(--text-muted); margin-bottom: 8px;
}
.path-list { list-style: none; padding: 0; margin: 0; }
.path-item {
  padding: 8px; border: 1px solid var(--bg-surface1);
  border-radius: 4px; margin-bottom: 6px; background: var(--bg-base);
  font-size: 11px;
}
.path-length {
  display: inline-block; margin-right: 10px;
  padding: 1px 6px; background: var(--bg-surface0);
  color: var(--text-muted); border-radius: 3px;
  font-size: 10px; font-weight: 600;
}
.path-chain { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.path-node {
  padding: 2px 8px; border: 1px solid; border-radius: 3px;
  color: var(--text); font-weight: 600;
  background: var(--bg-base);
}
.path-edge {
  display: inline-flex; align-items: center; gap: 3px;
  color: var(--text-muted); font-style: italic;
}
.path-arrow { color: var(--mauve); font-weight: 700; }
.path-label { font-size: 10px; }

/* Context panel */
.context-panel { background: var(--bg-surface0); padding: 12px; border-radius: 4px; border-bottom: none; }
.context-summary { font-size: 12px; color: var(--text-sub); margin-bottom: 10px; font-style: italic; }
.context-sub { margin-top: 10px; }
.context-label {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  color: var(--text-muted); margin-bottom: 4px;
}
.context-hint { font-weight: 400; text-transform: none; color: var(--text-muted); opacity: 0.7; }
.neighbor-list, .source-list { list-style: none; padding: 0; margin: 0; }
.neighbor-item {
  display: flex; align-items: center; gap: 6px;
  padding: 3px 0; font-size: 11px;
}
.neighbor-arrow { color: var(--mauve); font-weight: 700; }
.neighbor-label { color: var(--text-muted); font-style: italic; font-size: 10px; }
.neighbor-name {
  color: var(--blue); cursor: pointer; font-weight: 600;
  text-decoration: none;
}
.neighbor-name:hover { text-decoration: underline; }
.type-badge.small { font-size: 8px; padding: 1px 4px; }
.source-item {
  padding: 2px 0; font-size: 11px; color: var(--text-sub);
  font-family: var(--mono);
}
.loading-note { font-size: 11px; color: var(--text-muted); font-style: italic; }
</style>
