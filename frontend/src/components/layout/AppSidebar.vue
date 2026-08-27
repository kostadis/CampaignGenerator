<script setup lang="ts">
import { computed } from 'vue'
import { useConfigStore } from '../../stores/config'
import { useRouter, useRoute } from 'vue-router'

const config = useConfigStore()
const router = useRouter()
const route = useRoute()

// LLM backend selector (app-wide). Feature 003 moved this from the Session
// Doc Editor's backends.active (PUT /api/editor/config) to the platform tier
// (PUT /api/config/runtime), beside the MODEL picker below. The two controls
// sit together and are presented as global, so they must be owned by the same
// thing: while BACKEND lived in session_doc.yaml, grounding.py had to read
// another service's config to find it, and editing the Session Doc Editor
// silently re-targeted every Grounding run.
// 'claude-code' routes generation through the Claude Code CLI, billing the
// Pro/Max subscription instead of the metered Anthropic API.
type Backend = 'anthropic' | 'dgx' | 'openrouter' | 'claude-code'
const currentBackend = computed<Backend>(() => {
  const b = config.backend
  return b === 'dgx' || b === 'openrouter' || b === 'claude-code' ? b : 'anthropic'
})
async function setBackend(b: Backend) {
  if (currentBackend.value === b) return
  await config.updateRuntime({ default_backend: b })
}

// The MODELS registry is Anthropic-only — DGX and OpenRouter ids are
// free-form and not enumerable from the repo. So the dropdown can only
// express a valid pair for anthropic/claude-code; on the other two the
// operator must be able to type an id. Without this the platform pair is
// permanently incompatible on a local backend (every listed model is a
// claude-* id) and the 003 refusal would block every run.
const modelIsFreeText = computed(() => currentBackend.value === 'dgx' || currentBackend.value === 'openrouter')
async function setModel(value: string) {
  config.model = value
  await config.updateRuntime({ default_model: value })
}

// Batch selector (app-wide, 005-ui-batch-selection). Platform tier, same
// write path as backend/model above — PUT /api/config/runtime is the ONLY
// app-wide write door (feature 003's design; this feature reuses it rather
// than inventing a second one). Every SelectionPanel on every page re-
// resolves when this changes, so it shows up everywhere as "inherited"
// without a reload (T023's sidebar<->page round trip).
async function setBatch(b: boolean) {
  if (config.batch === b) return
  await config.updateRuntime({ default_batch: b })
}

interface NavItem {
  label: string
  path: string
}

interface NavGroup {
  title: string
  items: NavItem[]
}

const navGroups: NavGroup[] = [
  {
    title: 'SESSION WORKFLOW',
    items: [
      { label: '\u2460 Session Config', path: '/workflow/config' },
      { label: '\u2461 Session Doc Editor', path: '/workflow/editor' },
    ],
  },
  {
    title: 'GROUNDING DOCS',
    items: [
      { label: 'Campaign State', path: '/grounding/campaign-state' },
      { label: 'World State', path: '/grounding/distill' },
      { label: 'Party Document', path: '/grounding/party' },
      { label: 'Planning Document', path: '/grounding/planning' },
      { label: 'State Projection', path: '/grounding/projections' },
      { label: 'Threads', path: '/grounding/threads' },
    ],
  },
  {
    title: 'ENSEMBLE WORKFLOW',
    items: [
      { label: 'Ensemble Grounding Docs', path: '/ensemble/setup' },
    ],
  },
  {
    title: 'PREP',
    items: [
      { label: 'Session Prep', path: '/prep/session-prep' },
      { label: 'NPC Table', path: '/prep/npc-table' },
      { label: 'Query Summaries', path: '/prep/query' },
      { label: 'Connection Graph', path: '/prep/connections' },
    ],
  },
  {
    title: 'SETUP',
    items: [
      { label: 'Players', path: '/setup/players' },
      { label: 'D&D Sheet', path: '/setup/dnd-sheet' },
      { label: 'Make Tracking', path: '/setup/make-tracking' },
    ],
  },
]

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(path + '/')
}

function navigate(path: string) {
  router.push(path)
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1>Campaign Generator</h1>
    </div>

    <nav class="sidebar-nav">
      <div v-for="group in navGroups" :key="group.title" class="nav-group">
        <h2 class="nav-group-title">{{ group.title }}</h2>
        <div
          v-for="item in group.items"
          :key="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
          @click="navigate(item.path)"
        >
          {{ item.label }}
        </div>
      </div>

      <!-- Settings (standalone) -->
      <div class="nav-group">
        <div
          class="nav-item"
          :class="{ active: isActive('/settings') }"
          @click="navigate('/settings')"
        >
          Settings
        </div>
      </div>
    </nav>

    <div class="sidebar-footer">
      <div class="backend-selector">
        <label class="model-label">BACKEND</label>
        <div class="backend-toggle">
          <button
            class="backend-btn"
            :class="{ active: currentBackend === 'anthropic' }"
            title="Anthropic API — metered, billed to ANTHROPIC_API_KEY"
            @click="setBackend('anthropic')"
          >API</button>
          <button
            class="backend-btn"
            :class="{ active: currentBackend === 'claude-code' }"
            title="Claude Code CLI — bills your Pro/Max subscription, no per-token API charge"
            @click="setBackend('claude-code')"
          >Sub</button>
          <button
            class="backend-btn"
            :class="{ active: currentBackend === 'dgx' }"
            title="Local DGX / vLLM endpoint"
            @click="setBackend('dgx')"
          >DGX</button>
          <button
            class="backend-btn"
            :class="{ active: currentBackend === 'openrouter' }"
            title="OpenRouter — hosted gateway, billed to OPENROUTER_API_KEY"
            @click="setBackend('openrouter')"
          >OR</button>
        </div>
      </div>
      <div class="batch-selector">
        <label class="model-label">BATCH</label>
        <div class="backend-toggle">
          <button
            class="backend-btn"
            :class="{ active: !config.batch }"
            @click="setBatch(false)"
          >Off</button>
          <button
            class="backend-btn"
            :class="{ active: config.batch }"
            title="Use Anthropic Message Batches (50% off list price; replaces streaming with poll-progress)"
            @click="setBatch(true)"
          >On</button>
        </div>
        <div class="batch-help">
          Use Anthropic Message Batches (50% off list price; replaces streaming with poll-progress)
        </div>
      </div>
      <div class="model-selector">
        <label class="model-label">MODEL</label>
        <input
          v-if="modelIsFreeText"
          :value="config.model"
          class="model-select"
          :placeholder="currentBackend === 'dgx' ? 'e.g. Qwen3-Next-80B' : 'e.g. qwen/qwen3-next-80b'"
          title="This backend's model ids are free-form — type the id your endpoint serves"
          @change="setModel(($event.target as HTMLInputElement).value)"
        />
        <select v-else :value="config.model" class="model-select" @change="setModel(($event.target as HTMLSelectElement).value)">
          <option v-for="m in config.models" :key="m" :value="m">{{ m }}</option>
        </select>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 210px;
  min-width: 210px;
  background: var(--bg-mantle);
  border-right: 1px solid var(--bg-surface0);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.sidebar-header {
  padding: 12px 14px;
  border-bottom: 1px solid var(--bg-surface0);
}
.sidebar-header h1 {
  font-size: 13px;
  font-weight: 700;
  color: var(--mauve);
  letter-spacing: 0.02em;
}

.sidebar-nav {
  flex: 1;
  padding: 8px 0;
}

.nav-group { margin-bottom: 12px; }
.nav-group-title {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  padding: 8px 14px 4px;
}

.nav-item {
  padding: 7px 14px;
  font-size: 12px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background .1s;
  color: var(--text-sub);
}
.nav-item:hover { background: #252535; }
.nav-item.active {
  background: #252535;
  border-left-color: var(--mauve);
  color: var(--text);
  font-weight: 600;
}

.sidebar-footer {
  padding: 12px 14px;
  border-top: 1px solid var(--bg-surface0);
}

.model-label {
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  display: block;
  margin-bottom: 4px;
}

.backend-selector {
  margin-bottom: 10px;
}

.backend-toggle {
  display: flex;
  gap: 2px;
  background: var(--bg-surface0);
  border: 1px solid var(--bg-surface1);
  border-radius: 4px;
  padding: 2px;
}

.backend-btn {
  flex: 1;
  font-size: 10px;
  font-family: var(--mono);
  padding: 3px 0;
  border: none;
  border-radius: 3px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.backend-btn:hover {
  color: var(--text);
}

.backend-btn.active {
  background: var(--bg-surface1);
  color: var(--text);
  font-weight: 600;
}

.batch-selector {
  margin-bottom: 10px;
}

.batch-help {
  margin-top: 4px;
  font-size: 9px;
  line-height: 1.4;
  color: var(--text-muted);
  font-style: italic;
}

.model-select {
  width: 100%;
  font-size: 10px;
  padding: 4px 6px;
  border-radius: 4px;
  background: var(--bg-surface0);
  color: var(--text);
  border: 1px solid var(--bg-surface1);
  font-family: var(--mono);
}

</style>
