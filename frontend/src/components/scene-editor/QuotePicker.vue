<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { apiFetch, apiPost } from '../../api/client'
import QuoteRow from './QuoteRow.vue'
import type { Quote } from './QuoteRow.vue'

const props = defineProps<{
  currentScene: number
  scenes: { index: number; narrator: string; scene: string }[]
}>()

const emit = defineEmits<{
  close: []
  added: [count: number]
}>()

const allQuotes = ref<Quote[]>([])
const loading = ref(true)
const filter = ref('')
const selected = ref<Set<number>>(new Set())

// IDs already assigned to the current scene (shown as checked+disabled)
const currentSceneIds = computed(() =>
  new Set(allQuotes.value.filter(q => q.scene_index === props.currentScene).map(q => q.id))
)

// Grouped by source file
interface QuoteGroup {
  source: string
  quotes: Quote[]
}

const filteredGroups = computed<QuoteGroup[]>(() => {
  const f = filter.value.toLowerCase().trim()
  const filtered = f
    ? allQuotes.value.filter(q =>
        q.character.toLowerCase().includes(f) ||
        q.quote_text.toLowerCase().includes(f) ||
        q.context.toLowerCase().includes(f)
      )
    : allQuotes.value

  const groups: Map<string, Quote[]> = new Map()
  for (const q of filtered) {
    const src = q.source_file || 'unknown'
    if (!groups.has(src)) groups.set(src, [])
    groups.get(src)!.push(q)
  }
  return Array.from(groups.entries()).map(([source, quotes]) => ({ source, quotes }))
})

const selectedCount = computed(() => selected.value.size)

// Collapsed groups
const collapsed = ref<Set<string>>(new Set())
function toggleGroup(source: string) {
  if (collapsed.value.has(source)) {
    collapsed.value.delete(source)
  } else {
    collapsed.value.add(source)
  }
}

function toggleSelect(id: number) {
  // Don't allow toggling quotes already in this scene
  if (currentSceneIds.value.has(id)) return
  const newSet = new Set(selected.value)
  if (newSet.has(id)) {
    newSet.delete(id)
  } else {
    newSet.add(id)
  }
  selected.value = newSet
}

function sceneLabel(q: Quote): string | undefined {
  if (q.scene_index === null) return undefined
  if (q.scene_index === props.currentScene) return undefined // handled by disabled
  const s = props.scenes.find(s => s.index === q.scene_index)
  return s ? `Sc ${s.index}` : `Sc ${q.scene_index}`
}

async function addSelected() {
  if (!selected.value.size) return
  const ids = Array.from(selected.value)
  await apiPost('/api/ledger/bulk-assign', {
    quote_ids: ids,
    scene_index: props.currentScene,
  })
  emit('added', ids.length)
  emit('close')
}

onMounted(async () => {
  loading.value = true
  try {
    const data = await apiFetch('/api/ledger/all-quotes')
    allQuotes.value = data.quotes || []
  } catch {
    allQuotes.value = []
  }
  loading.value = false
})
</script>

<template>
  <div class="picker-backdrop" @click.self="emit('close')">
    <div class="picker-modal">
      <div class="picker-header">
        <h3>Add Quotes to Scene {{ currentScene }}</h3>
        <input
          type="text"
          class="filter-input"
          v-model="filter"
          placeholder="Filter by character or text..."
        />
        <button class="picker-close" @click="emit('close')">&times;</button>
      </div>

      <div class="picker-body">
        <div v-if="loading" class="picker-loading">Loading quotes...</div>
        <template v-else>
          <div v-for="group in filteredGroups" :key="group.source" class="quote-group">
            <div class="group-header" @click="toggleGroup(group.source)">
              <span class="arrow" :class="{ open: !collapsed.has(group.source) }">&#x25B6;</span>
              {{ group.source }}
              <span class="group-count">{{ group.quotes.length }}</span>
            </div>
            <div v-show="!collapsed.has(group.source)" class="group-quotes">
              <QuoteRow
                v-for="q in group.quotes"
                :key="q.id"
                :quote="q"
                :selected="selected.has(q.id) || currentSceneIds.has(q.id)"
                :expanded="false"
                :disabled="currentSceneIds.has(q.id)"
                :scene-label="sceneLabel(q)"
                @toggle-select="() => toggleSelect(q.id)"
                @toggle-expand="() => {}"
                @quick-delete="() => {}"
              />
            </div>
          </div>
        </template>
      </div>

      <div class="picker-footer">
        <span class="selected-count" v-if="selectedCount > 0">
          {{ selectedCount }} selected
        </span>
        <button class="btn-neutral btn-sm" @click="emit('close')">Cancel</button>
        <button class="btn-primary btn-sm" :disabled="!selectedCount" @click="addSelected">
          Add Selected
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.picker-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.picker-modal {
  background: var(--bg-base);
  border: 1px solid var(--bg-surface1);
  border-radius: 8px;
  width: 700px;
  max-width: 90vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}

.picker-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--bg-surface0);
  flex-shrink: 0;
}
.picker-header h3 {
  font-size: 13px;
  font-weight: 700;
  color: var(--mauve);
  white-space: nowrap;
}
.filter-input {
  flex: 1;
  padding: 5px 8px;
  border-radius: 4px;
  border: 1px solid var(--bg-surface1);
  background: var(--bg-mantle);
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  outline: none;
}
.filter-input:focus { border-color: var(--mauve); }
.picker-close {
  font-size: 18px;
  color: var(--text-muted);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0 4px;
}
.picker-close:hover { color: var(--text); }

.picker-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}
.picker-loading {
  padding: 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}

.quote-group { margin-bottom: 4px; }
.group-header {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-muted);
  padding: 6px 16px;
  cursor: pointer;
  user-select: none;
  display: flex;
  align-items: center;
  gap: 6px;
}
.arrow {
  font-size: 8px;
  transition: transform .15s;
  display: inline-block;
}
.arrow.open { transform: rotate(90deg); }
.group-count { font-size: 9px; color: var(--blue); }

.picker-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--bg-surface0);
  flex-shrink: 0;
  justify-content: flex-end;
}
.selected-count {
  font-size: 11px;
  color: var(--mauve);
  font-weight: 600;
  margin-right: auto;
}
</style>
