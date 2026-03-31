<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { apiFetch, apiPost } from '../../api/client'
import QuoteRow from './QuoteRow.vue'
import type { Quote } from './QuoteRow.vue'
import type { Scene } from './SceneList.vue'

const props = defineProps<{
  currentScene: number | null
  scenes: Scene[]
}>()

const emit = defineEmits<{
  'status': [msg: string]
  'quotes-changed': []
  'generate': [sceneNum: number]
  'show-picker': []
}>()

// ── Quote data ───────────────────────────────────────────────────
const quotes = ref<Quote[]>([])
const loading = ref(false)

async function loadSceneQuotes() {
  if (props.currentScene === null) {
    quotes.value = []
    return
  }
  loading.value = true
  try {
    const data = await apiFetch(`/api/ledger/scene/${props.currentScene}`)
    quotes.value = data.quotes || []
  } catch {
    quotes.value = []
  }
  loading.value = false
}

watch(() => props.currentScene, loadSceneQuotes, { immediate: true })

defineExpose({ reload: loadSceneQuotes })

// ── Selection state ──────────────────────────────────────────────
const selected = ref<Set<number>>(new Set())
const lastClickedIndex = ref<number | null>(null)
const expandedId = ref<number | null>(null)

const selectedCount = computed(() => selected.value.size)
const allSelected = computed(() =>
  quotes.value.length > 0 && selected.value.size === quotes.value.length
)

function toggleSelect(id: number, event: MouseEvent) {
  const idx = quotes.value.findIndex(q => q.id === id)
  if (idx === -1) return

  if (event.shiftKey && lastClickedIndex.value !== null) {
    // Range selection
    const start = Math.min(lastClickedIndex.value, idx)
    const end = Math.max(lastClickedIndex.value, idx)
    const newSet = new Set(selected.value)
    for (let i = start; i <= end; i++) {
      newSet.add(quotes.value[i].id)
    }
    selected.value = newSet
  } else {
    const newSet = new Set(selected.value)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    selected.value = newSet
    lastClickedIndex.value = idx
  }
}

function toggleSelectAll() {
  if (allSelected.value) {
    selected.value = new Set()
  } else {
    selected.value = new Set(quotes.value.map(q => q.id))
  }
}

function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

function clearSelection() {
  selected.value = new Set()
  lastClickedIndex.value = null
}

// ── Bulk actions ─────────────────────────────────────────────────
const selectedIds = computed(() => Array.from(selected.value))

const moveTarget = ref<number | ''>('')
const showMoveDropdown = ref(false)

async function bulkDelete() {
  if (!selectedIds.value.length) return
  await apiPost('/api/ledger/bulk-unassign', { quote_ids: selectedIds.value })
  clearSelection()
  emit('status', `Removed ${selectedIds.value.length} quotes`)
  await loadSceneQuotes()
  emit('quotes-changed')
}

async function bulkExclusive() {
  if (!selectedIds.value.length || props.currentScene === null) return
  await apiPost('/api/ledger/exclusive', {
    quote_ids: selectedIds.value,
    scene_index: props.currentScene,
  })
  emit('status', `Made ${selectedIds.value.length} quotes exclusive`)
  clearSelection()
  await loadSceneQuotes()
  emit('quotes-changed')
}

async function bulkMoveNext() {
  if (!selectedIds.value.length || props.currentScene === null) return
  const nextScene = props.currentScene + 1
  if (nextScene > props.scenes.length) {
    emit('status', 'No next scene')
    return
  }
  await apiPost('/api/ledger/bulk-assign', {
    quote_ids: selectedIds.value,
    scene_index: nextScene,
  })
  clearSelection()
  emit('status', `Moved to Scene ${nextScene}`)
  await loadSceneQuotes()
  emit('quotes-changed')
}

async function bulkMoveTo() {
  if (!selectedIds.value.length || !moveTarget.value) return
  const target = Number(moveTarget.value)
  await apiPost('/api/ledger/bulk-assign', {
    quote_ids: selectedIds.value,
    scene_index: target,
  })
  clearSelection()
  showMoveDropdown.value = false
  moveTarget.value = ''
  emit('status', `Moved to Scene ${target}`)
  await loadSceneQuotes()
  emit('quotes-changed')
}

async function quickDelete(id: number) {
  await apiPost('/api/ledger/bulk-unassign', { quote_ids: [id] })
  selected.value.delete(id)
  emit('status', 'Quote removed')
  await loadSceneQuotes()
  emit('quotes-changed')
}

// Scene label for current scene
const sceneLabel = computed(() => {
  if (props.currentScene === null) return ''
  const s = props.scenes.find(s => s.index === props.currentScene)
  if (!s) return `Scene ${props.currentScene}`
  return `Scene ${s.index}: ${s.narrator}` + (s.scene ? ` \u2014 ${s.scene}` : '')
})
</script>

<template>
  <div class="assignment-panel">
    <!-- Empty state -->
    <div v-if="currentScene === null" class="empty-state">
      Select a scene from the list to view and manage its quotes.
    </div>

    <template v-else>
      <!-- Toolbar -->
      <div class="toolbar">
        <div class="toolbar-top">
          <label class="select-all" title="Select all">
            <input type="checkbox" :checked="allSelected" @change="toggleSelectAll" />
          </label>
          <span class="scene-title">{{ sceneLabel }}</span>
          <span class="quote-count">{{ quotes.length }} quotes</span>
        </div>
        <div class="toolbar-actions">
          <button class="btn-neutral btn-sm" :disabled="!selectedCount" @click="bulkDelete">
            Delete
          </button>
          <button class="btn-neutral btn-sm" :disabled="!selectedCount" @click="bulkExclusive">
            Keep Exclusive
          </button>
          <button class="btn-neutral btn-sm" :disabled="!selectedCount" @click="bulkMoveNext">
            Move Next
          </button>
          <div class="move-to-group">
            <button class="btn-neutral btn-sm" :disabled="!selectedCount"
              @click="showMoveDropdown = !showMoveDropdown">
              Move to...
            </button>
            <div v-if="showMoveDropdown" class="move-dropdown" @click.stop>
              <select v-model="moveTarget" class="move-select">
                <option value="">Select scene</option>
                <option v-for="s in scenes" :key="s.index" :value="s.index"
                  :disabled="s.index === currentScene">
                  Scene {{ s.index }}: {{ s.narrator }}
                </option>
              </select>
              <button class="btn-primary btn-sm" :disabled="!moveTarget" @click="bulkMoveTo">
                Go
              </button>
            </div>
          </div>
          <button class="btn-primary btn-sm" @click="emit('show-picker')">
            Add Quote
          </button>
          <div class="toolbar-spacer" />
          <button class="btn-primary btn-sm" @click="emit('generate', currentScene)">
            Generate Extraction
          </button>
        </div>
      </div>

      <!-- Quote list -->
      <div class="quote-list">
        <div v-if="loading" class="loading">Loading...</div>
        <div v-else-if="quotes.length === 0" class="empty-quotes">
          No quotes assigned to this scene.<br>
          Click <b>Add Quote</b> or run <b>Auto-Assign</b>.
        </div>
        <QuoteRow
          v-for="q in quotes"
          :key="q.id"
          :quote="q"
          :selected="selected.has(q.id)"
          :expanded="expandedId === q.id"
          @toggle-select="toggleSelect"
          @toggle-expand="toggleExpand"
          @quick-delete="quickDelete"
        />
      </div>
    </template>
  </div>
</template>

<style scoped>
.assignment-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: var(--text-muted);
  font-size: 12px;
  padding: 20px;
}

.toolbar {
  flex-shrink: 0;
  border-bottom: 1px solid var(--bg-surface0);
  padding: 8px 12px;
  background: var(--bg-mantle);
}

.toolbar-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.select-all input { accent-color: var(--mauve); cursor: pointer; }
.scene-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
}
.quote-count {
  font-size: 10px;
  color: var(--text-muted);
  margin-left: auto;
}

.toolbar-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  align-items: center;
}
.toolbar-spacer { flex: 1; }

.move-to-group { position: relative; }
.move-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  background: var(--bg-surface0);
  border: 1px solid var(--bg-surface1);
  border-radius: 4px;
  padding: 6px;
  display: flex;
  gap: 4px;
  z-index: 10;
}
.move-select {
  font-size: 10px;
  padding: 2px 4px;
  border-radius: 3px;
  background: var(--bg-base);
  color: var(--text);
  border: 1px solid var(--bg-surface1);
}

.quote-list {
  flex: 1;
  overflow-y: auto;
}

.loading, .empty-quotes {
  padding: 20px;
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
}
.empty-quotes b { color: var(--mauve); }
</style>
