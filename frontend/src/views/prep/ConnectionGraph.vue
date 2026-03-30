<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useConfigStore } from '../../stores/config'
import { apiFetch, apiPost } from '../../api/client'
import PathField from '../../components/shared/PathField.vue'

const config = useConfigStore()

const docsDir = ref('')
const extraFiles = ref('')
const availableFiles = ref<string[]>([])
const selectedFiles = ref<string[]>([])
const basePath = ref('')
const loading = ref(false)
const extracting = ref(false)
const error = ref('')
const graphHtml = ref('')
const searchQuery = ref('')

// Connection data
const data = ref<{ entities: any[]; edges: any[] } | null>(null)
const cacheInfo = ref('')

// Entity type filters
const allTypes = ['npc', 'faction', 'location', 'plot', 'arc_score', 'party']
const filterTypes = ref<Set<string>>(new Set(allTypes))

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

async function scanDocs() {
  const dir = docsDir.value.trim()
  if (!dir) { availableFiles.value = []; return }
  try {
    const res = await apiFetch(`/api/connections/list-docs?docs_dir=${encodeURIComponent(dir)}`)
    availableFiles.value = res.files || []
    basePath.value = res.base || ''
    // Auto-select first 4
    selectedFiles.value = availableFiles.value.slice(0, Math.min(4, availableFiles.value.length))
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
      model: config.model,
    })
    if (res.error) {
      error.value = res.error
    } else {
      data.value = res.data
      cacheInfo.value = `${res.entities} entities, ${res.edges} edges`
      await renderGraph()
    }
  } catch (e: any) {
    error.value = e.message || 'Extraction failed'
  } finally {
    extracting.value = false
  }
}

async function loadCached() {
  try {
    const res = await apiFetch('/api/connections/data')
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
    const res = await fetch('/api/connections/graph', {
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

onMounted(() => {
  // Default docs dir from campaign config
  const cd = config.values.campaign_dir || ''
  if (cd) {
    docsDir.value = cd.replace(/\/+$/, '') + '/docs'
  }
  loadCached()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Connection Graph</h2>
      <p class="subtitle">Visualize relationships between NPCs, factions, locations, and plot threads.</p>
    </div>

    <!-- File selection -->
    <div class="form-section">
      <PathField
        v-model="docsDir"
        label="Campaign docs directory"
        absolute
        help="Folder to scan for .md files"
      />

      <div v-if="availableFiles.length" class="file-selector">
        <label class="field-label">Documents to include ({{ selectedFiles.length }} selected)</label>
        <div class="file-list">
          <label
            v-for="f in availableFiles"
            :key="f"
            class="file-item"
          >
            <input
              type="checkbox"
              :value="f"
              v-model="selectedFiles"
            />
            <span class="file-name">{{ shortLabel(f) }}</span>
          </label>
        </div>
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
        :disabled="!allSelected.length || extracting || !config.apiKeyPresent"
        @click="extract"
      >
        {{ extracting ? 'Extracting...' : 'Extract Connections (calls Claude API)' }}
      </button>
      <span v-if="cacheInfo" class="cache-info">{{ cacheInfo }}</span>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <!-- Graph and controls -->
    <template v-if="data">
      <!-- Filters -->
      <div class="form-section">
        <h3 class="section-title">Filters</h3>
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
          {{ visibleEntities.length }} nodes &middot; {{ visibleEdges.length }} edges visible
          <span v-if="data">(total: {{ data.entities.length }} entities, {{ data.edges.length }} relationships)</span>
        </div>
      </div>

      <!-- Graph iframe -->
      <div class="graph-container">
        <div v-if="loading" class="graph-loading">Rendering graph...</div>
        <iframe
          v-else-if="graphHtml"
          :srcdoc="graphHtml"
          class="graph-iframe"
          sandbox="allow-scripts"
        ></iframe>
      </div>

      <!-- Legend -->
      <div class="form-section legend">
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

      <!-- Entity table -->
      <div class="form-section">
        <h3 class="section-title">Entity List</h3>
        <input
          type="text"
          class="field-input search-input"
          v-model="searchQuery"
          placeholder="Search entities..."
        />
        <table class="entity-table" v-if="filteredEntities.length">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in filteredEntities" :key="e.id">
              <td class="ent-name">{{ e.label }}</td>
              <td><span class="type-badge" :style="{ background: NODE_COLORS[e.type] || '#888' }">{{ e.type.replace('_', ' ') }}</span></td>
              <td class="ent-summary">{{ e.summary }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="no-results">No entities match your search.</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 900px; }
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
.file-list {
  max-height: 200px; overflow-y: auto;
  background: var(--bg-base); border: 1px solid var(--bg-surface1);
  border-radius: 4px; padding: 6px;
}
.file-item {
  display: flex; align-items: center; gap: 6px;
  padding: 3px 4px; font-size: 11px; cursor: pointer;
  border-radius: 3px;
}
.file-item:hover { background: var(--bg-surface0); }
.file-item input { accent-color: var(--mauve); }
.file-name { font-family: var(--mono); color: var(--text-sub); }

.action-row { display: flex; align-items: center; gap: 12px; }
.cache-info { font-size: 11px; color: var(--text-muted); }
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
  width: 100%; height: 600px;
  border: 1px solid var(--bg-surface1); border-radius: 6px;
  overflow: hidden; margin-bottom: 16px; background: #1a1a2e;
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
</style>
