<script setup lang="ts">
import { computed } from 'vue'
import { useConfigStore } from '../../stores/config'
import { useRouter, useRoute } from 'vue-router'

const config = useConfigStore()
const router = useRouter()
const route = useRoute()

// LLM backend selector (global). Persisted to the Session Doc Editor's
// backends.active (GET/PUT /api/editor/config) — the same field
// _llm_env() reads server-side — so the editor's own toggle stays in
// sync. 'claude-code' routes generation through the Claude Code CLI,
// billing the Pro/Max subscription instead of the metered Anthropic API.
type Backend = 'anthropic' | 'dgx' | 'openrouter' | 'claude-code'
const currentBackend = computed<Backend>(() => {
  const b = config.editorConfig?.backends?.active
  return b === 'dgx' || b === 'openrouter' || b === 'claude-code' ? b : 'anthropic'
})
async function setBackend(b: Backend) {
  if (currentBackend.value === b) return
  await config.updateEditor({ backends: { active: b } })
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
      <div class="model-selector">
        <label class="model-label">MODEL</label>
        <select v-model="config.model" class="model-select" @change="config.updateRuntime({ default_model: config.model })">
          <option v-for="m in config.models" :key="m" :value="m">{{ m }}</option>
        </select>
      </div>
      <div v-if="!config.apiKeyPresent && currentBackend !== 'claude-code'" class="api-warning">
        ANTHROPIC_API_KEY not set
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

.api-warning {
  margin-top: 8px;
  font-size: 10px;
  color: var(--peach);
  font-weight: 600;
}
</style>
