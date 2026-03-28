<script setup lang="ts">
import { ref } from 'vue'
import { apiFetch, apiPost } from '../../api/client'

interface Quote {
  id: number
  speaker: string
  character: string
  context: string
  quote_text: string
  scene_index: number | null
  pinned: number
}

interface LedgerScene {
  index: number
  narrator: string
  scene_name: string
  quotes: Quote[]
}

interface LedgerData {
  scenes: LedgerScene[]
  unassigned: Quote[]
}

const props = defineProps<{
  currentScene: number | null
}>()

const ledgerData = ref<LedgerData | null>(null)
const stats = ref('')
const expandedQuote = ref<number | null>(null)
const statusMsg = ref('')
const assignSelections = ref<Record<number, string>>({})

async function sync() {
  statusMsg.value = 'Syncing...'
  try {
    const result = await apiPost('/api/ledger/sync')
    stats.value = `${result.total} quotes \u00b7 ${result.matched} matched \u00b7 ${result.unassigned} unassigned`
    statusMsg.value = `Synced: ${result.total} quotes`
    setTimeout(() => { statusMsg.value = '' }, 3000)
    await loadQuotes()
  } catch (e) {
    statusMsg.value = 'Sync error'
  }
}

async function loadQuotes() {
  const data = await apiFetch('/api/ledger/quotes')
  ledgerData.value = data
}

function toggleExpand(qid: number) {
  expandedQuote.value = expandedQuote.value === qid ? null : qid
}

async function assignQuote(qid: number, sceneIndex: number | string) {
  const idx = sceneIndex === '' ? null : Number(sceneIndex)
  const res = await apiPost('/api/ledger/assign', { quote_id: qid, scene_index: idx })
  if (res.ok) {
    statusMsg.value = 'Quote reassigned.'
    setTimeout(() => { statusMsg.value = '' }, 2000)
    await loadQuotes()
  }
}

function truncate(text: string, len: number = 80): string {
  return text.length > len ? text.substring(0, len) + '\u2026' : text
}

// Collapsible sections
const collapsedSections = ref<Set<string>>(new Set())

function toggleSection(key: string) {
  if (collapsedSections.value.has(key)) {
    collapsedSections.value.delete(key)
  } else {
    collapsedSections.value.add(key)
  }
}

function isSectionOpen(key: string): boolean {
  return !collapsedSections.value.has(key)
}
</script>

<template>
  <div class="ledger-container">
    <div class="ledger-toolbar">
      <button class="btn-neutral btn-sm" @click="sync">Sync</button>
      <span class="ledger-stats">{{ stats }}</span>
    </div>
    <div v-if="statusMsg" class="ledger-status">{{ statusMsg }}</div>

    <div class="ledger-scroll">
      <p v-if="!ledgerData" class="hint">
        Click <b>Sync</b> to scan extraction files and build the quote ledger.
      </p>

      <template v-if="ledgerData">
        <!-- Unassigned -->
        <div v-if="ledgerData.unassigned.length > 0" class="ledger-section">
          <div class="ledger-section-header unassigned" @click="toggleSection('unassigned')">
            <span class="arrow" :class="{ open: isSectionOpen('unassigned') }">&#x25B6;</span>
            Unassigned
            <span class="count">{{ ledgerData.unassigned.length }}</span>
          </div>
          <div v-show="isSectionOpen('unassigned')" class="ledger-quotes">
            <div
              v-for="q in ledgerData.unassigned"
              :key="q.id"
              class="quote-item"
              :class="{ expanded: expandedQuote === q.id }"
              @click="toggleExpand(q.id)"
            >
              <div class="q-speaker">
                {{ q.character }}
                <span v-if="q.pinned" class="q-pinned">pinned</span>
              </div>
              <div class="q-context">{{ q.context }}</div>
              <div class="q-text">
                {{ expandedQuote === q.id ? q.quote_text : truncate(q.quote_text) }}
              </div>
              <div v-if="expandedQuote === q.id" class="quote-assign" @click.stop>
                <select v-model="assignSelections[q.id]">
                  <option value="">&mdash; Unassign &mdash;</option>
                  <option v-for="s in ledgerData.scenes" :key="s.index" :value="String(s.index)">
                    Scene {{ s.index }}: {{ s.narrator }}
                  </option>
                </select>
                <button class="btn-primary btn-sm" @click="assignQuote(q.id, assignSelections[q.id] || '')">
                  Move
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Per-scene -->
        <div v-for="s in ledgerData.scenes" :key="s.index" class="ledger-section">
          <div
            class="ledger-section-header"
            :style="currentScene === s.index ? { color: 'var(--mauve)' } : {}"
            @click="toggleSection('s-' + s.index)"
          >
            <span class="arrow" :class="{ open: isSectionOpen('s-' + s.index) && s.quotes.length > 0 }">&#x25B6;</span>
            Scene {{ s.index }}: {{ s.narrator }}
            <template v-if="s.scene_name"> &mdash; {{ s.scene_name }}</template>
            <span class="count">{{ s.quotes.length }}</span>
          </div>
          <div v-show="isSectionOpen('s-' + s.index) && s.quotes.length > 0" class="ledger-quotes">
            <div
              v-for="q in s.quotes"
              :key="q.id"
              class="quote-item"
              :class="{ expanded: expandedQuote === q.id }"
              @click="toggleExpand(q.id)"
            >
              <div class="q-speaker">
                {{ q.character }}
                <span v-if="q.pinned" class="q-pinned">pinned</span>
              </div>
              <div class="q-context">{{ q.context }}</div>
              <div class="q-text">
                {{ expandedQuote === q.id ? q.quote_text : truncate(q.quote_text) }}
              </div>
              <div v-if="expandedQuote === q.id" class="quote-assign" @click.stop>
                <select v-model="assignSelections[q.id]">
                  <option value="">&mdash; Unassign &mdash;</option>
                  <option v-for="ls in ledgerData!.scenes" :key="ls.index" :value="String(ls.index)">
                    Scene {{ ls.index }}: {{ ls.narrator }}
                  </option>
                </select>
                <button class="btn-primary btn-sm" @click="assignQuote(q.id, assignSelections[q.id] || '')">
                  Move
                </button>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.ledger-container {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}
.ledger-toolbar {
  padding: 8px 12px;
  display: flex;
  gap: 6px;
  align-items: center;
  border-bottom: 1px solid var(--bg-surface0);
  flex-shrink: 0;
}
.ledger-stats { font-size: 10px; color: var(--text-muted); margin-left: auto; }
.ledger-status { font-size: 10px; color: var(--blue); padding: 4px 12px; }
.ledger-scroll { flex: 1; overflow-y: auto; }
.hint { color: var(--text-muted); font-size: 12px; padding: 8px 12px; }
.hint b { color: var(--mauve); }

.ledger-section { margin-bottom: 12px; }
.ledger-section-header {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-muted);
  padding: 8px 12px 4px;
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
.count { font-size: 9px; font-weight: 600; color: var(--blue); }
.unassigned .count { color: var(--peach); }

.quote-item {
  padding: 5px 12px;
  font-size: 11px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background .1s;
}
.quote-item:hover { background: #252535; }
.quote-item.expanded { background: #252535; border-left-color: var(--mauve); }

.q-speaker { font-weight: 600; font-size: 10px; color: var(--mauve); }
.q-context {
  font-size: 10px;
  color: var(--text-muted);
  font-style: italic;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.q-text {
  color: var(--text-sub);
  font-size: 11px;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.quote-item.expanded .q-text {
  white-space: pre-wrap;
  word-break: break-word;
}
.q-pinned {
  font-size: 8px;
  color: var(--green);
  text-transform: uppercase;
  font-weight: 700;
}
.quote-assign {
  margin-top: 4px;
  display: flex;
  gap: 4px;
  align-items: center;
}
.quote-assign select {
  font-size: 10px;
  padding: 2px 4px;
  border-radius: 3px;
  background: var(--bg-surface0);
  color: var(--text);
  border: 1px solid var(--bg-surface1);
}
</style>
