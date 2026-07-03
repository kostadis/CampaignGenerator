<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { apiFetch } from '../../api/client'

interface Chapter {
  path: string
  stem: string
  size: number
  extracted: boolean
}

const props = defineProps<{
  glob: string
  /** Explicitly selected chapter paths. Empty == "all" (run the whole glob). */
  selected: string[]
}>()
const emit = defineEmits<{
  'update:glob': [v: string]
  'update:selected': [v: string[]]
}>()

const chapters = ref<Chapter[]>([])
const loading = ref(false)
const error = ref('')
const sortDir = ref<'asc' | 'desc'>('asc')

// Local editable copy of the glob so typing doesn't re-resolve on every keystroke.
const globText = ref(props.glob)
watch(() => props.glob, (v) => { globText.value = v })

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })
const sorted = computed(() => {
  const c = [...chapters.value].sort((a, b) => collator.compare(a.stem, b.stem))
  return sortDir.value === 'asc' ? c : c.reverse()
})

// The checked set IS the selection. Empty == no explicit pick → extraction
// falls back to the full glob (clearly labeled below). No ambiguous "empty=all".
const checked = computed<Set<string>>(() => new Set(props.selected))
const selectedCount = computed(() => chapters.value.filter(c => checked.value.has(c.path)).length)

async function resolve() {
  const g = globText.value.trim()
  emit('update:glob', g)
  if (!g) { chapters.value = []; return }
  loading.value = true
  error.value = ''
  try {
    // Allow several whitespace/newline-separated globs in the one field.
    const params = g.split(/\s+/).filter(Boolean)
      .map(p => `glob=${encodeURIComponent(p)}`).join('&')
    const r = await apiFetch(`/api/ensemble/chapters?${params}`)
    chapters.value = r.chapters || []
    // Drop any persisted selections that no longer resolve.
    if (props.selected.length) {
      const live = new Set(chapters.value.map(c => c.path))
      const pruned = props.selected.filter(p => live.has(p))
      if (pruned.length !== props.selected.length) emit('update:selected', pruned)
    }
  } catch (e: any) {
    error.value = e?.message || 'failed to resolve glob'
    chapters.value = []
  } finally {
    loading.value = false
  }
}

function toggle(path: string) {
  const next = new Set(checked.value)
  if (next.has(path)) next.delete(path); else next.add(path)
  emit('update:selected', [...next])
}

function selectAll() { emit('update:selected', chapters.value.map(c => c.path)) }
function selectNone() { emit('update:selected', []) }
function only(path: string) { emit('update:selected', [path]) }

onMounted(resolve)
</script>

<template>
  <div class="picker">
    <label class="fld">
      <span>Chapters glob <small>(space-separate for several; e.g. <code>docs/chapters/chapter_*.md</code>)</small></span>
      <div class="globrow">
        <input v-model="globText" type="text" @keyup.enter="resolve" />
        <button class="btn-neutral btn-sm" :disabled="loading" @click="resolve">
          {{ loading ? 'Resolving…' : 'Resolve' }}
        </button>
      </div>
    </label>

    <p v-if="error" class="err">{{ error }}</p>

    <div v-if="chapters.length" class="toolbar">
      <button class="btn-neutral btn-sm" @click="selectAll">Select all</button>
      <button class="btn-neutral btn-sm" @click="selectNone">Select none</button>
      <button class="btn-neutral btn-sm"
              @click="sortDir = sortDir === 'asc' ? 'desc' : 'asc'">
        Sort {{ sortDir === 'asc' ? '▲ A→Z' : '▼ Z→A' }}
      </button>
      <span class="count">{{ selectedCount }} / {{ chapters.length }} selected</span>
    </div>

    <ul v-if="chapters.length" class="list">
      <li v-for="c in sorted" :key="c.path" :class="{ on: checked.has(c.path) }">
        <label class="row">
          <input type="checkbox" :checked="checked.has(c.path)" @change="toggle(c.path)" />
          <span class="name">{{ c.stem }}</span>
          <span v-if="c.extracted" class="badge done" title="merged.json exists on disk">extracted</span>
          <span v-else class="badge pending">pending</span>
        </label>
        <button class="only" title="Select only this chapter" @click="only(c.path)">only</button>
      </li>
    </ul>
    <p v-else-if="!loading && !error" class="hint">No chapters match this glob.</p>

    <p v-if="!selected.length && chapters.length" class="hint warnnote">
      Nothing selected — extraction will <strong>refuse to run</strong>. Tick the
      chapters you want, or click <strong>Select all</strong> to choose every one.
    </p>
  </div>
</template>

<style scoped>
.picker { margin-bottom: 12px; }
.fld { display: block; font-size: 12px; }
.fld > span { display: block; margin-bottom: 3px; color: var(--text-sub); }
.fld small { color: var(--text-muted); font-weight: 400; }
.globrow { display: flex; gap: 8px; }
.globrow input {
  flex: 1; max-width: 520px; font-size: 12px; padding: 5px 7px;
  background: var(--bg-surface0); color: var(--text);
  border: 1px solid var(--bg-surface1); border-radius: 4px; font-family: var(--mono);
}
.toolbar { display: flex; align-items: center; gap: 8px; margin: 8px 0 6px; }
.count { font-size: 11px; color: var(--text-muted); margin-left: auto; }
.list { list-style: none; margin: 0; padding: 0; max-height: 260px; overflow-y: auto;
  border: 1px solid var(--bg-surface1); border-radius: 5px; }
.list li { display: flex; align-items: center; padding: 3px 8px; border-bottom: 1px solid var(--bg-surface0); }
.list li:last-child { border-bottom: none; }
.list li.on { background: var(--bg-surface0); }
.row { display: flex; align-items: center; gap: 8px; flex: 1; font-size: 12px; cursor: pointer; }
.name { font-family: var(--mono); }
.badge { font-size: 9px; border-radius: 8px; padding: 1px 7px; font-weight: 700; }
.badge.done { background: var(--green); color: var(--bg-mantle); }
.badge.pending { background: var(--bg-surface1); color: var(--text-muted); }
.only { font-size: 10px; background: none; border: 1px solid var(--bg-surface1); color: var(--text-muted);
  border-radius: 4px; padding: 1px 7px; cursor: pointer; }
.only:hover { color: var(--text); border-color: var(--mauve); }
.hint { font-size: 11px; color: var(--text-muted); margin: 6px 0 0; }
.hint.warnnote { color: var(--peach); }
.err { font-size: 12px; color: var(--red); }
</style>
