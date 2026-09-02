<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { BACKENDS, type Backend, useConfigStore } from '../../stores/config'
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
// Pro/Max subscription instead of the metered Anthropic API. `codex-cli` is
// the saved-login Codex CLI path; this component never invokes either CLI.
const availableBackends = computed<Backend[]>(() =>
  config.backends.length ? config.backends : [...BACKENDS],
)
const currentBackend = computed<Backend>(() => {
  const b = config.backend
  return availableBackends.value.includes(b) ? b : 'anthropic'
})

// Runtime stores one global model, while the editor/service profiles already
// keep model ids per backend. Preserve that same intent when the sidebar
// switches to Codex, especially so a Claude default is not presented as a
// Codex model. An empty value means "let this backend choose its own default".
const modelMemory = ref<Partial<Record<Backend, string>>>({})
watch(
  [() => config.defaultModels, () => config.loaded],
  ([stored, loaded]) => {
    if (!loaded) return
    modelMemory.value = { ...stored }
  },
  { immediate: true, deep: true },
)
const displayedModel = computed(() => modelMemory.value[currentBackend.value] ?? config.model)

async function setBackend(b: Backend) {
  if (currentBackend.value === b) return
  modelMemory.value[currentBackend.value] = config.model
  if (b === 'codex-cli' && modelMemory.value[b] === undefined) modelMemory.value[b] = ''
  const nextModel = modelMemory.value[b] ?? (b === 'anthropic' || b === 'claude-code' ? config.defaultModel : '')
  config.model = nextModel
  const update: Record<string, unknown> = {
    default_backend: b,
    default_model: nextModel,
    default_models: { ...modelMemory.value },
  }
  await config.updateRuntime(update)
}

// The MODELS registry is Anthropic-only — DGX and OpenRouter ids are
// free-form and not enumerable from the repo. So the dropdown can only
// express a valid pair for anthropic/claude-code; on the other two the
// operator must be able to type an id. Without this the platform pair is
// permanently incompatible on a local backend (every listed model is a
// claude-* id) and the 003 refusal would block every run.
const modelIsFreeText = computed(() =>
  currentBackend.value === 'dgx'
  || currentBackend.value === 'openrouter'
  || currentBackend.value === 'codex-cli',
)
async function setModel(value: string) {
  modelMemory.value[currentBackend.value] = value.trim()
  config.model = value
  await config.updateRuntime({
    default_model: value,
    default_models: { ...modelMemory.value },
  })
}

async function setCodexReasoning(value: string) {
  // Empty is the persisted omission state: let Codex choose its own default.
  config.codexReasoningEffort = value as typeof config.codexReasoningEffort
  await config.updateRuntime({ default_codex_reasoning_effort: value || null })
}

async function setClaudeCodeThinking(value: string) {
  // Three states, and the empty one is not the same as 'off': '' defers to
  // CG_CLAUDE_CODE_THINKING, 'off' is a sticky choice that beats it.
  config.claudeCodeThinking = value as typeof config.claudeCodeThinking
  await config.updateRuntime({
    default_claude_code_thinking: value === 'on' ? true : value === 'off' ? false : null,
  })
}

async function setClaudeCodeEffort(value: string) {
  // Empty persists as omission (null), NOT as the level the platform happens
  // to hold today: on this backend omission is a real behaviour — a
  // compatibility clamp, or the operator's own settings.json — and storing a
  // guessed level would silently take that decision away from them.
  config.claudeCodeEffort = value as typeof config.claudeCodeEffort
  await config.updateRuntime({ default_claude_code_effort: value || null })
}

// Batch selector (app-wide, 005-ui-batch-selection). Platform tier, same
// write path as backend/model above — PUT /api/config/runtime is the ONLY
// app-wide write door (feature 003's design; this feature reuses it rather
// than inventing a second one). Every SelectionPanel on every page re-
// resolves when this changes, so it shows up everywhere as "inherited"
// without a reload (T023's sidebar<->page round trip).
async function setBatch(b: boolean) {
  if (b && currentBackend.value !== 'anthropic') return
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
      { label: '③ Narration Wiki', path: '/workflow/wiki' },
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
  {
    title: 'INTEGRATIONS',
    items: [
      { label: 'Scabard Sync', path: '/integrations/scabard' },
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
            :class="{ active: currentBackend === 'codex-cli' }"
            title="Codex CLI — uses the saved Codex login, no metered API key"
            @click="setBackend('codex-cli')"
          >Codex</button>
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
            :disabled="currentBackend !== 'anthropic'"
            title="Use Anthropic Message Batches (50% off list price; replaces streaming with poll-progress)"
            @click="setBatch(true)"
          >On</button>
        </div>
        <div class="batch-help">
          Use Anthropic Message Batches (50% off list price; replaces streaming with poll-progress)
        </div>
      </div>
      <div v-if="currentBackend === 'claude-code'" class="codex-reasoning-selector">
        <label class="model-label">THINKING</label>
        <select
          :value="config.claudeCodeThinking"
          class="model-select"
          @change="setClaudeCodeThinking(($event.target as HTMLSelectElement).value)"
        >
          <option value="">(defer to CG_CLAUDE_CODE_THINKING)</option>
          <option value="on">On</option>
          <option value="off">Off</option>
        </select>
        <div class="batch-help">
          Off by default — suppressing the reasoning trace is measurably faster.
          Required for effort xhigh and max. Always on for Fable/Mythos models.
        </div>
      </div>
      <div v-if="currentBackend === 'claude-code'" class="codex-reasoning-selector">
        <label class="model-label">EFFORT</label>
        <select
          :value="config.claudeCodeEffort"
          class="model-select"
          :disabled="!config.claudeCodeEfforts.length"
          @change="setClaudeCodeEffort(($event.target as HTMLSelectElement).value)"
        >
          <option value="">Claude Code default</option>
          <option v-for="effort in config.claudeCodeEfforts" :key="effort" :value="effort">
            {{ effort }}
          </option>
        </select>
        <div class="batch-help">
          {{ config.claudeCodeCompatibilityError || 'Higher effort can take longer. xhigh and max require Thinking above (or CG_CLAUDE_CODE_THINKING=1); without it the run is refused rather than quietly lowered.' }}
        </div>
      </div>
      <div v-if="currentBackend === 'codex-cli'" class="codex-reasoning-selector">
        <label class="model-label">REASONING</label>
        <select
          :value="config.codexReasoningEffort"
          class="model-select"
          :disabled="!config.codexReasoningEfforts.length"
          @change="setCodexReasoning(($event.target as HTMLSelectElement).value)"
        >
          <option value="">Codex default</option>
          <option v-for="effort in config.codexReasoningEfforts" :key="effort" :value="effort">
            {{ effort }}
          </option>
        </select>
        <div class="batch-help">
          {{ config.codexReasoningCompatibilityError || 'Higher effort can take longer; model support varies. gpt-5.6-sol supports max.' }}
        </div>
      </div>

      <div class="model-selector">
        <label class="model-label">MODEL</label>
        <input
          v-if="modelIsFreeText"
          :value="displayedModel"
          class="model-select"
          :placeholder="currentBackend === 'codex-cli' ? 'optional — Codex default' : currentBackend === 'dgx' ? 'e.g. Qwen3-Next-80B' : 'e.g. qwen/qwen3-next-80b'"
          title="This backend's model ids are free-form — type the id your endpoint serves"
          @change="setModel(($event.target as HTMLInputElement).value)"
        />
        <select v-else :value="displayedModel" class="model-select" @change="setModel(($event.target as HTMLSelectElement).value)">
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

.codex-reasoning-selector {
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
