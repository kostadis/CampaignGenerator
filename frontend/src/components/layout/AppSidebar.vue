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

// The MODEL control is ONE input on every backend (024). It used to fork — a
// <select> over the MODELS registry on anthropic/claude-code, a free-text
// <input> on the other three — which made a hand-maintained snapshot
// authoritative on exactly the two backends where it goes stale: a Claude
// model released after the last CampaignGenerator release was unreachable
// from the UI at any price. The engine never agreed; selection.py's
// compatible() gates on id *shape* and says so at length:
//
//   testing against it would silently reject a legitimate Claude id that
//   simply hadn't been added yet
//
// So the fork was removed rather than widened. One element cannot drift from
// itself, and Principle XI's Orphaned Capability — a choice the engine offers
// that no human can reach — is closed by construction.
//
// MODELS is the Anthropic registry, so it is offered as suggestions only where
// it means something. A claude-* id suggested against a DGX endpoint would be
// an actively wrong hint, not merely a useless one.
const suggestedModels = computed(() =>
  currentBackend.value === 'anthropic' || currentBackend.value === 'claude-code'
    ? config.models
    : [],
)
const modelPlaceholder = computed(() => {
  switch (currentBackend.value) {
    case 'codex-cli': return 'optional — Codex default'
    case 'dgx': return 'e.g. Qwen3-Next-80B'
    case 'openrouter': return 'e.g. qwen/qwen3-next-80b'
    // anthropic and claude-code. Naming one id as an example, not as a limit.
    default: return 'e.g. claude-opus-5 — or type any id'
  }
})
// A <select> commits the instant an option is picked; a text input commits on
// blur or Enter. That gap did not exist on anthropic/claude-code before 024,
// and it has a real edge: a GM who types an id and triggers a run WITHOUT ever
// leaving the field (a keyboard shortcut, a control that does not steal focus)
// would have had `change` never fire — so `config.model`, which every run view
// forwards explicitly and which BEATS runtime.default_model at the server,
// still held the previous id. The field showed one model and the run used
// another.
//
// So the two halves are split. `stageModel` is synchronous and local: it keeps
// `config.model` honest on every keystroke, which is what a run reads. Nothing
// is written to disk from here — a PUT per keystroke would be absurd, and
// platform.yaml is not a scratchpad.
function stageModel(value: string) {
  const model = value.trim()
  modelMemory.value[currentBackend.value] = model
  config.model = model
}
async function setModel(value: string) {
  // Persist on commit (blur or Enter). Trim once and write that single value
  // everywhere: this used to trim into the memory map and persist the raw
  // string as default_model, so one pasted id wrote two different strings for
  // one choice, from one function, in one request (024 R5). Trimming is the
  // ONLY normalisation permitted here — no case folding, no substitution, and
  // above all no rejection: an id absent from `config.models` is a model the
  // GM is entitled to run.
  stageModel(value)
  await config.updateRuntime({
    default_model: config.model,
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
          :value="displayedModel"
          class="model-select"
          list="cg-model-ids"
          :placeholder="modelPlaceholder"
          title="Type any model id this backend serves — the suggestions are a shortlist, not a limit"
          @input="stageModel(($event.target as HTMLInputElement).value)"
          @change="setModel(($event.target as HTMLInputElement).value)"
        />
        <datalist id="cg-model-ids">
          <option v-for="m in suggestedModels" :key="m" :value="m" />
        </datalist>
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
