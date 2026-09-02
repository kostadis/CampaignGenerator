<script setup lang="ts">
/**
 * Feature 003 — what this run will actually use, before you spend on it.
 *
 * Shows the resolved model and backend together with the ORIGIN of each
 * (platform default vs this service's own override), because the value alone
 * doesn't tell you whether changing the sidebar will move it. When the pair is
 * incompatible it says so and blocks the run here rather than letting the
 * operator discover it from a 409 mid-stream — that is the whole point of a
 * pre-run display (FR-012), and it is why the refusal carries a `remedy` the
 * panel can act on directly (FR-010).
 *
 * Services that own a config document also get the override editor inline, so
 * setting a per-service model never means leaving the page you're running from
 * (SC-007). The five stateless services pass `can-override={false}` and see the
 * inherited selection read-only — they have nothing to set, by design (FR-004).
 */
import { ref, computed, watch, onMounted } from 'vue'
import { apiFetch, apiPut, apiDelete } from '../../api/client'
import { useConfigStore } from '../../stores/config'

const props = defineProps<{
  /** Service key: grounding | party | planning | ensemble | editor | prep | setup | connections */
  service: string
  /** Grounding only — selects which owning tier to preview (party/planning/…) */
  doc?: string
  /** Whether this service owns a config document and may hold an override */
  canOverride?: boolean
}>()

const emit = defineEmits<{ compatible: [boolean]; backend: [string] }>()

const config = useConfigStore()

interface Resolved {
  model: string | null
  backend: string
  model_origin: string
  backend_origin: string
  compatible: boolean
  refusal: string | null
  batch: boolean
  batch_origin: string
  codex_reasoning_effort: string | null
  codex_reasoning_effort_origin: string
  codex_reasoning_override: boolean
  claude_code_effort: string | null
  claude_code_effort_origin: string
  claude_code_effort_override: boolean
  claude_code_thinking: boolean | null
  claude_code_thinking_origin: string
}

const resolved = ref<Resolved | null>(null)
const editing = ref(false)
const draftModel = ref('')
const draftBackend = ref('')
// '' = inherit platform, 'on'/'off' = this service's own explicit choice.
// A plain boolean can't express "defer" separately from "explicitly off" —
// see ModelSelection.batch's `bool | null` (data-model.md's tier table).
const draftBatch = ref<'' | 'on' | 'off'>('')
const codexReasoning = ref('')
const claudeEffort = ref('')
// '' = defer to the environment, 'on'/'off' = this service's own choice —
// the same three-state shape draftBatch uses, and for the same reason.
const claudeThinking = ref<'' | 'on' | 'off'>('')
const busy = ref(false)
const error = ref('')

// Batch capability, per service (feature 005-ui-batch-selection). The
// /selection/resolved payload carries the resolved batch value and the
// refusal/compatible outcome, but not the static per-service CAPABILITY
// (full/degraded/incompatible/excluded) that decides whether a degradation
// notice is warranted — the server deliberately keeps that reasoning out of
// the wire payload (Constitution VI), so it is mirrored here as a small,
// reviewable constant instead. Keep this in sync with
// server/platform_config_service.py's BATCH_CAPABILITY map — see
// specs/005-ui-batch-selection/data-model.md's "Batch capability map".
// Only `degraded` matters to this component: `full` needs no notice,
// `excluded` services (Connection Graph) never mount this panel at all, and
// no `incompatible` service is reachable from the UI today.
const DEGRADED_BATCH_SERVICES = new Set(['prep', 'session_doc'])

const resolvedUrl = computed(() => {
  const base = `/api/${props.service}/selection/resolved`
  return props.doc ? `${base}?doc=${encodeURIComponent(props.doc)}` : base
})

async function load() {
  try {
    resolved.value = await apiFetch<Resolved>(resolvedUrl.value)
    emit('compatible', resolved.value?.compatible !== false)
    emit('backend', resolved.value?.backend || 'anthropic')
  } catch (e: any) {
    // A preview that fails must not block the page — the run itself still
    // resolves server-side and will refuse if it has to.
    resolved.value = null
    emit('compatible', true)
    // Unknown backend — assume anthropic so a stale/failed preview still
    // requires an API key rather than silently exempting a run that turns
    // out to need one.
    emit('backend', 'anthropic')
  }
}

async function loadOverride() {
  if (!props.canOverride) return
  try {
    const sel = await apiFetch<{
      model: string | null
      backend: string | null
      batch: boolean | null
      codex_reasoning_effort: string | null
      claude_code_effort: string | null
      claude_code_thinking: boolean | null
    }>(
      `/api/${props.service}/selection`,
    )
    draftModel.value = sel.model || ''
    draftBackend.value = sel.backend || ''
    draftBatch.value = sel.batch === true ? 'on' : sel.batch === false ? 'off' : ''
    codexReasoning.value = sel.codex_reasoning_effort || ''
    claudeEffort.value = sel.claude_code_effort || ''
    claudeThinking.value = sel.claude_code_thinking === true
      ? 'on' : sel.claude_code_thinking === false ? 'off' : ''
  } catch {
    draftModel.value = ''
    draftBackend.value = ''
    draftBatch.value = ''
    codexReasoning.value = ''
    claudeEffort.value = ''
    claudeThinking.value = ''
  }
}

async function save() {
  busy.value = true
  error.value = ''
  try {
    // PUT replaces the whole stored selection (ModelSelection.model_validate
    // of exactly this body) — omitting `batch` here would silently reset any
    // existing batch override back to "defer" every time the operator saves
    // a model/backend edit. All three fields always travel together.
    await apiPut(`/api/${props.service}/selection`, {
      model: draftModel.value.trim() || null,
      backend: draftBackend.value.trim() || null,
      batch: draftBatch.value === 'on' ? true : draftBatch.value === 'off' ? false : null,
      codex_reasoning_effort: codexReasoning.value || null,
      // Travels with the others for the same reason: PUT replaces the whole
      // stored selection, so omitting this would reset the operator's effort
      // to "defer" every time they saved an unrelated model edit. It is also
      // why setting one backend's effort never disturbs the other's — both
      // are always sent as they stand.
      claude_code_effort: claudeEffort.value || null,
      claude_code_thinking: claudeThinking.value === 'on' ? true
        : claudeThinking.value === 'off' ? false : null,
    })
    editing.value = false
    await load()
  } catch (e: any) {
    error.value = e?.message || 'Save failed'
  } finally {
    busy.value = false
  }
}

async function clearOverride() {
  busy.value = true
  error.value = ''
  try {
    await apiDelete(`/api/${props.service}/selection`)
    draftModel.value = ''
    draftBackend.value = ''
    draftBatch.value = ''
    codexReasoning.value = ''
    claudeEffort.value = ''
    claudeThinking.value = ''
    editing.value = false
    await load()
  } catch (e: any) {
    error.value = e?.message || 'Clear failed'
  } finally {
    busy.value = false
  }
}

/** FR-006a's batch-specific remedy: force batch OFF for this service, while
 *  preserving any model/backend override untouched. Deliberately NOT the
 *  same as clearOverride() — that resets to "defer", which would leave the
 *  run refused when batch is inherited from a platform-wide selection that
 *  is still on. Setting an explicit `false` here fixes the refusal whether
 *  batch came from this service or from the platform (batch_origin-
 *  independent, per data-model.md's D3). */
async function clearBatchSelection() {
  if (!props.canOverride) return
  busy.value = true
  error.value = ''
  try {
    const current = await apiFetch<{
      model: string | null
      backend: string | null
      codex_reasoning_effort: string | null
      claude_code_effort: string | null
      claude_code_thinking: boolean | null
    }>(
      `/api/${props.service}/selection`,
    )
    await apiPut(`/api/${props.service}/selection`, {
      model: current.model || null,
      backend: current.backend || null,
      batch: false,
      codex_reasoning_effort: current.codex_reasoning_effort || null,
      claude_code_effort: current.claude_code_effort || null,
      claude_code_thinking: current.claude_code_thinking,
    })
    if (editing.value) draftBatch.value = 'off'
    await load()
  } catch (e: any) {
    error.value = e?.message || 'Clear failed'
  } finally {
    busy.value = false
  }
}

function beginEdit() {
  loadOverride()
  editing.value = true
}

/** "platform default" reads better than the raw origin token. */
function originLabel(origin: string): string {
  switch (origin) {
    case 'platform': return 'platform default'
    case 'service': return 'this service'
    case 'request': return 'this run'
    case 'literal': return 'built-in fallback'
    default: return origin
  }
}

const hasOverride = computed(() =>
  resolved.value?.model_origin === 'service'
  || resolved.value?.backend_origin === 'service'
  || resolved.value?.batch_origin === 'service'
  || resolved.value?.codex_reasoning_effort_origin === 'service'
  || resolved.value?.claude_code_effort_origin === 'service'
  || resolved.value?.claude_code_thinking_origin === 'service',
)

const draftUsesCodex = computed(() =>
  (draftBackend.value || resolved.value?.backend) === 'codex-cli',
)

const draftUsesClaudeCode = computed(() =>
  (draftBackend.value || resolved.value?.backend) === 'claude-code',
)

// A batch selection that cannot be honoured populates `refusal` naming batch
// as the cause (server/platform_config_service.py's resolve_selection) —
// distinguished from a model/backend-pair refusal, which never mentions it,
// so the panel can show the right remedy without a second refusal field.
const batchCausedRefusal = computed(() => {
  const r = resolved.value?.refusal
  return !!r && r.toLowerCase().includes('batch')
})

// Provider message batching is an Anthropic API feature. Keep the application
// level grouping controls elsewhere available, but do not let this per-service
// editor create a known-invalid Codex batch selection.
const providerBatchUnsupported = computed(() => resolved.value?.backend !== 'anthropic')

// FR-010: state the trade-off before a run that will actually execute as
// batch on a `degraded` service — not when the run is refused outright (that
// case is covered by the refusal block instead).
const showDegradationNotice = computed(() =>
  !!resolved.value?.batch
  && resolved.value?.compatible !== false
  && DEGRADED_BATCH_SERVICES.has(props.service),
)

onMounted(load)
// The sidebar writes the platform tier, so a change there moves every
// inheriting service's answer — re-resolve rather than showing a stale one.
watch(
  () => [config.model, config.backend, config.batch, config.codexReasoningEffort,
    config.claudeCodeEffort, props.doc],
  load,
)
</script>

<template>
  <div v-if="resolved" class="selection-panel" :class="{ bad: !resolved.compatible }">
    <div class="row">
      <span class="label">Will run</span>
      <span class="pair">
        <code>{{ resolved.model || '(script default)' }}</code>
        <span class="origin">{{ originLabel(resolved.model_origin) }}</span>
        <span class="sep">on</span>
        <code>{{ resolved.backend }}</code>
        <span class="origin">{{ originLabel(resolved.backend_origin) }}</span>
      </span>
      <span style="flex:1"></span>
      <button
        v-if="canOverride && !editing"
        class="mini"
        @click="beginEdit"
      >{{ hasOverride ? 'Edit override' : 'Override' }}</button>
      <button
        v-if="canOverride && hasOverride && !editing"
        class="mini"
        :disabled="busy"
        @click="clearOverride"
      >Clear override</button>
    </div>

    <!-- 005-ui-batch-selection — same visibility rule as model/backend above:
         effective state + origin, always shown, never hidden to dodge a
         refusal (contract "What it must forbid"). -->
    <div class="row batch-row">
      <span class="label">Batch</span>
      <span class="pair">
        <code>{{ resolved.batch ? 'on' : 'off' }}</code>
        <span class="origin">{{ originLabel(resolved.batch_origin) }}</span>
      </span>
    </div>
    <div v-if="resolved.backend === 'codex-cli'" class="row batch-row">
      <span class="label">Reasoning</span>
      <span class="pair">
        <code>{{ resolved.codex_reasoning_effort || 'Codex default' }}</code>
        <span class="origin">{{ originLabel(resolved.codex_reasoning_effort_origin) }}</span>
      </span>
    </div>
    <div v-if="resolved.backend === 'claude-code'" class="row batch-row">
      <span class="label">Thinking</span>
      <span class="pair">
        <code>{{ resolved.claude_code_thinking === null ? 'defer to environment'
          : resolved.claude_code_thinking ? 'on' : 'off' }}</code>
        <span class="origin">{{ originLabel(resolved.claude_code_thinking_origin) }}</span>
      </span>
    </div>
    <div v-if="resolved.backend === 'claude-code'" class="row batch-row">
      <span class="label">Effort</span>
      <span class="pair">
        <code>{{ resolved.claude_code_effort || 'Claude Code default' }}</code>
        <span class="origin">{{ originLabel(resolved.claude_code_effort_origin) }}</span>
      </span>
    </div>
    <div class="batch-copy">
      Use Anthropic Message Batches (50% off list price; replaces streaming with poll-progress)
    </div>
    <div v-if="showDegradationNotice" class="degraded-notice">
      This service's steps run one at a time under batch — same discount, slower than a normal run (FR-010).
    </div>

    <!-- T041 — the incompatibility is visible BEFORE the run, with the fix
         attached. The Run button is disabled by the parent via @compatible. -->
    <div v-if="!resolved.compatible" class="refusal">
      <strong>Incompatible selection.</strong>
      {{ resolved.refusal }}
      <template v-if="batchCausedRefusal && canOverride">
        Clear the batch selection for this service, or change its backend to
        <code>anthropic</code>.
      </template>
      <template v-else-if="batchCausedRefusal">
        This inherits the platform's batch and backend choice — turn batch
        off, or switch backends, in the sidebar.
      </template>
      <template v-else-if="resolved.model_origin === 'service'">
        This service's override cannot run on the
        <code>{{ resolved.backend }}</code> backend.
      </template>
      <template v-else>
        The platform model cannot run on the
        <code>{{ resolved.backend }}</code> backend — change one in the sidebar.
      </template>
      <div class="refusal-actions">
        <button
          v-if="canOverride && batchCausedRefusal"
          class="mini"
          :disabled="busy"
          @click="clearBatchSelection"
        >Clear batch selection</button>
        <button
          v-if="canOverride && resolved.model_origin === 'service'"
          class="mini"
          :disabled="busy"
          @click="clearOverride"
        >Clear override</button>
        <button v-if="canOverride" class="mini" @click="beginEdit">Edit</button>
      </div>
    </div>

    <div v-if="editing" class="editor">
      <label>
        Model
        <input v-model="draftModel" placeholder="blank = inherit platform" />
      </label>
      <label>
        Backend
        <select v-model="draftBackend">
          <option value="">(inherit platform)</option>
          <option v-for="b in config.backends" :key="b" :value="b">{{ b }}</option>
        </select>
      </label>
      <label>
        Batch
        <select v-model="draftBatch">
          <option value="">(inherit platform)</option>
          <option value="on" :disabled="providerBatchUnsupported">On</option>
          <option value="off">Off</option>
        </select>
      </label>
      <label v-if="draftUsesCodex">
        Codex reasoning
        <select
          v-model="codexReasoning"
          :disabled="!config.codexReasoningEfforts.length"
        >
          <option value="">Codex default</option>
          <option v-for="effort in config.codexReasoningEfforts" :key="effort" :value="effort">
            {{ effort }}
          </option>
        </select>
        <span class="field-help">
          {{ config.codexReasoningCompatibilityError || 'Higher effort can take longer; model support varies.' }}
        </span>
      </label>
      <label v-if="draftUsesClaudeCode">
        Thinking
        <select v-model="claudeThinking">
          <option value="">(defer to CG_CLAUDE_CODE_THINKING)</option>
          <option value="on">On</option>
          <option value="off">Off</option>
        </select>
        <span class="field-help">
          Off by default — suppressing the trace is measurably faster. Required
          for effort xhigh and max. Always on for Fable/Mythos models.
        </span>
      </label>
      <label v-if="draftUsesClaudeCode">
        Effort
        <select
          v-model="claudeEffort"
          :disabled="!config.claudeCodeEfforts.length"
        >
          <option value="">Claude Code default</option>
          <option v-for="effort in config.claudeCodeEfforts" :key="effort" :value="effort">
            {{ effort }}
          </option>
        </select>
        <span class="field-help">
          {{ config.claudeCodeCompatibilityError
            || 'Higher effort can take longer. xhigh and max require Thinking above (or CG_CLAUDE_CODE_THINKING=1).' }}
        </span>
      </label>
      <button class="mini primary" :disabled="busy" @click="save">Save</button>
      <button class="mini" :disabled="busy" @click="editing = false">Cancel</button>
      <span v-if="error" class="err">{{ error }}</span>
    </div>
  </div>
</template>

<style scoped>
.selection-panel {
  background: var(--bg-surface0);
  border: 1px solid var(--bg-surface1);
  border-radius: 4px;
  padding: 6px 10px;
  margin-bottom: 10px;
  font-size: 11px;
}
.selection-panel.bad { border-color: var(--red, #f38ba8); }
.row { display: flex; align-items: center; gap: 8px; }
.label {
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  min-width: 58px;
}
.pair { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.pair code {
  font-family: var(--mono);
  color: var(--text);
  background: var(--bg-mantle);
  padding: 1px 5px;
  border-radius: 3px;
}
.origin { color: var(--text-muted); font-style: italic; }
.sep { color: var(--text-muted); }
.batch-row { margin-top: 6px; }
.batch-copy {
  margin-top: 2px;
  font-size: 10px;
  color: var(--text-muted);
  font-style: italic;
}
.degraded-notice {
  margin-top: 6px;
  padding: 5px 8px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--peach, #f9b874) 14%, transparent);
  color: var(--text);
  line-height: 1.5;
}
.refusal {
  margin-top: 6px;
  padding: 6px 8px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--red, #f38ba8) 12%, transparent);
  color: var(--text);
  line-height: 1.5;
}
.refusal-actions { margin-top: 6px; display: flex; gap: 6px; }
.editor {
  margin-top: 8px;
  display: flex;
  align-items: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
.editor label { display: flex; flex-direction: column; gap: 2px; color: var(--text-muted); }
.editor input, .editor select {
  font-family: var(--mono);
  font-size: 11px;
  padding: 3px 6px;
  background: var(--bg-mantle);
  color: var(--text);
  border: 1px solid var(--bg-surface1);
  border-radius: 3px;
  min-width: 190px;
}
.mini {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 3px;
  border: 1px solid var(--bg-surface1);
  background: var(--bg-mantle);
  color: var(--text-muted);
  cursor: pointer;
}
.mini:hover { background: var(--bg-surface1); color: var(--text); }
.mini.primary { border-color: var(--green, #a6e3a1); color: var(--green, #a6e3a1); }
.err { color: var(--red, #f38ba8); }
</style>
