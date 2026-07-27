<script setup lang="ts">
import { ref, onMounted, reactive, watch } from 'vue'
import { useConfigStore } from '../../stores/config'
import { apiFetch, apiPost } from '../../api/client'
import {
  useEnsembleRun, fetchEnsembleConfig, saveEnsembleConfig, fetchRegistrySummary,
  type EnsembleConfig, type RegistrySummary,
} from './useEnsembleRun'
import StreamOutput from '../../components/shared/StreamOutput.vue'
import EnsemblePlanningFields from '../../components/ensemble/EnsemblePlanningFields.vue'
import PathField from '../../components/shared/PathField.vue'

const emit = defineEmits<{ changed: [] }>()
const config = useConfigStore()
const cfg = ref<EnsembleConfig | null>(null)
const run = useEnsembleRun()

function statusLabel(s: string, rc: number | null): string {
  if (s === 'done') return 'Draft written'
  if (s === 'error') return `Exit ${rc}`
  if (s === 'aborted') return 'Aborted'
  return ''
}
function statusClass(s: string): string {
  if (s === 'done') return 'ok'
  if (s === 'error') return 'err'
  if (s === 'aborted') return 'aborted'
  return ''
}

const DOCS = [
  { id: 'world_state', label: 'World State' },
  { id: 'campaign_state', label: 'Campaign State' },
  { id: 'party', label: 'Party' },
  { id: 'planning', label: 'Planning' },
] as const

const selectedDoc = ref<typeof DOCS[number]['id']>('world_state')
const diffs = reactive<Record<string, string>>({})
// Party config path set via the Party Document page — read from
// grounding.yaml's `party.config_path`. Passed through as-is; the server
// falls back to config/party.yaml when this is blank.
const partyConfigPath = ref('')
// Planning config path set via the Planning Document page — grounding.yaml's
// `planning.config_path`. Same fallback pattern as party. Shared with the
// standalone Planning Document page on purpose: both should point at the
// same campaign planning.yaml.
const planningConfigPath = ref('')
const planningSynthMode = ref<'config' | 'flat'>('config')
const planningNpcFiles = ref('')
const planningArcScores = ref('')
const planningContextFiles = ref('')
// Overrides on top of the model's own scene-relevance curation — 'scene' is
// planning.py --depth's default (exact no-op), so leaving these untouched
// reproduces prior behavior. See EnsemblePlanningFields.vue.
const planningDepth = ref<'scene' | 'full'>('scene')
const planningForceInclude = ref('')
// Module inventory — authoritative module-canon spellings, passed as
// synthesise_world_state's --inventory. Separate from the entity registry
// (which supplies aliases only); lives in ensemble.yaml's `paths.inventory`.
const inventoryPath = ref('')
// Entity registry status — world_state's run is gated server-side on this
// existing (see /run/synthesize's registry requirement); surfaced here so the
// operator sees the problem before clicking Run rather than from a failed SSE.
const registry = ref<RegistrySummary | null>(null)

onMounted(async () => {
  await config.load()
  const loaded = await fetchEnsembleConfig()
  cfg.value = loaded
  // These read grounding.yaml, not ui_state.yaml. They used to read
  // `config.resolved.ui.party/planning.config_path`; Phase 10 of
  // docs/config/grounding-isolation.md deleted both sections, so from that
  // point on both prefills were permanently blank and the two warn-hints
  // below always fired. GroundingConfigService owns these values now, and
  // the store boot-loads the document alongside the editor config.
  partyConfigPath.value = config.groundingConfig?.party?.config_path || ''
  planningConfigPath.value = config.groundingConfig?.planning?.config_path || ''
  // Phase 3: these come from ensemble.yaml's typed `planning` group. They
  // used to be six undeclared keys riding on ui.ensemble's extra="allow".
  const pl = loaded.planning
  planningSynthMode.value = pl.synth_mode
  planningNpcFiles.value = pl.npc.join('\n')
  planningArcScores.value = pl.arc_scores.join('\n')
  planningContextFiles.value = pl.context.join('\n')
  planningDepth.value = pl.depth
  planningForceInclude.value = pl.force_include.join('\n')
  inventoryPath.value = loaded.paths.inventory
  registry.value = await fetchRegistrySummary()
})

const lines = (t: string): string[] =>
  t.split('\n').map(l => l.trim()).filter(Boolean)

// Auto-persist planning field edits — mirrors PlanningDocument.vue's own
// debounced persist. These are ensemble-specific overrides and live in
// ensemble.yaml's own `planning` group so they don't collide with the
// standalone page's npc/arc-score/context lists. `planningConfigPath` is
// read-only here: grounding.yaml owns it and the standalone Planning
// Document page is its writer.
let planPersistTimer: ReturnType<typeof setTimeout> | null = null
function schedulePlanPersist() {
  if (planPersistTimer) clearTimeout(planPersistTimer)
  planPersistTimer = setTimeout(() => {
    // config_path used to be mirrored into ui.planning as well; that section
    // is retired (grounding.yaml owns the standalone page's copy) and the
    // ensemble's own override is written to ensemble.yaml just below.
    saveEnsembleConfig({
      planning: {
        synth_mode: planningSynthMode.value,
        npc: lines(planningNpcFiles.value),
        arc_scores: lines(planningArcScores.value),
        context: lines(planningContextFiles.value),
        depth: planningDepth.value,
        force_include: lines(planningForceInclude.value),
      },
    }).then(c => { cfg.value = c }).catch(() => {})
  }, 500)
}
watch([planningConfigPath, planningSynthMode, planningNpcFiles, planningArcScores, planningContextFiles,
       planningDepth, planningForceInclude],
  schedulePlanPersist)

// Same debounced-persist shape as the planning fields above, but for
// `paths.inventory` — a sibling field of `paths.chapters_glob`, which
// EnsembleSetup.vue already persists as a lone key inside `paths` (the
// service's update_config does a recursive deep-merge, so sending only
// `{ paths: { inventory } }` updates that one key and leaves the rest of
// `paths` — chapters_glob, dossiers_glob, etc. — untouched).
let inventoryPersistTimer: ReturnType<typeof setTimeout> | null = null
function scheduleInventoryPersist() {
  if (inventoryPersistTimer) clearTimeout(inventoryPersistTimer)
  inventoryPersistTimer = setTimeout(() => {
    saveEnsembleConfig({ paths: { inventory: inventoryPath.value } })
      .then(c => { cfg.value = c }).catch(() => {})
  }, 500)
}
watch(inventoryPath, scheduleInventoryPersist)

function synthesize() {
  // backend/endpoint/model come from ensemble.yaml's `synthesize` group, which
  // the server reads itself (Phase 3). Only what this page actually chooses is
  // sent. The planning fields below are still passed explicitly: the debounced
  // persist may not have landed yet when Run is clicked, so the request — not
  // the stored config — is the authority on this run's planning scope.
  const params: Record<string, unknown> = {
    doc: selectedDoc.value,
    party: partyConfigPath.value,
  }
  if (selectedDoc.value === 'world_state') {
    // Same request-is-the-authority rationale as the planning params below —
    // the debounced persist for `paths.inventory` may not have landed yet.
    params.inventory = inventoryPath.value
  }
  if (selectedDoc.value === 'planning') {
    // planning_mode tells the server which branch to run. In 'flat' mode
    // (Explicit dossier list) the server skips planning.yaml auto-detection
    // entirely, even if one exists on disk — so planning_config is only
    // meaningful, and only sent, in 'config' mode.
    params.planning_mode = planningSynthMode.value
    if (planningSynthMode.value === 'config') {
      params.planning_config = planningConfigPath.value
    }
    params.npc = planningNpcFiles.value.split('\n').map(l => l.trim()).filter(Boolean)
    params.context = planningContextFiles.value.split('\n').map(l => l.trim()).filter(Boolean)
    if (planningSynthMode.value === 'flat') {
      params.arc_scores = planningArcScores.value.split('\n').map(l => l.trim()).filter(Boolean)
    }
    // 'scene' is the server-side default (exact no-op) — only send when overridden.
    if (planningDepth.value === 'full') {
      params.depth = 'full'
    }
    const forceInclude = planningForceInclude.value.split('\n').map(l => l.trim()).filter(Boolean)
    if (forceInclude.length) {
      params.force_include = forceInclude
    }
  } else {
    params.planning_config = planningConfigPath.value
  }
  run.run('/api/ensemble/run/synthesize', params, (rc) => { if (rc === 0) emit('changed') })
}

async function showDiff(doc: string) {
  const r = await apiFetch(
    `/api/ensemble/diff?draft=docs/${doc}_draft.md&live=docs/${doc}.md`)
  diffs[doc] = r.diff || '(no differences — or live doc does not exist yet)'
}

async function promote(doc: string) {
  if (!confirm(`Promote ${doc}_draft.md over the live docs/${doc}.md?`)) return
  await apiPost('/api/ensemble/promote',
                { draft: `docs/${doc}_draft.md`, live: `docs/${doc}.md` })
  delete diffs[doc]
  emit('changed')
}
</script>

<template>
  <div class="step">
    <h2>Stage 3 — Synthesis &amp; promotion</h2>
    <p class="hint">
      Synthesis writes <code>*_draft.md</code> only — never a live doc. Backend:
      <strong>{{ cfg?.synthesize.backend ?? '' }}</strong>. Review the diff, then promote by hand.
    </p>
    <template v-if="selectedDoc === 'world_state'">
      <p v-if="registry?.found && !registry.error" class="hint">
        Registry: <code>{{ registry.path }}</code> ({{ registry.entity_count }} entities)
      </p>
      <p v-else class="hint warn-hint">
        ⚠ {{ registry?.error || 'no entity registry found' }} — world_state synthesis
        requires one (see the Bundle step's ② checkpoint).
      </p>
      <PathField v-model="inventoryPath" label="Module inventory (optional)" resolve-base="campaign"
        placeholder="docs/background/module-inventory.md"
        help="Authoritative module-canon spellings — separate from the registry, which supplies aliases only." />
    </template>
    <p v-if="selectedDoc === 'party'" class="hint">
      Uses <code>{{ partyConfigPath || 'config/party.yaml (auto-detected if present)' }}</code>
      — the human-maintained PC roster (see the Party Document page to create or edit
      one). No pre-staged extracts needed once it exists. Also auto-includes
      <code>world_state</code>/<code>campaign_state</code> (draft, or live if no draft
      yet) as context, so current location/quests/reputation aren't reported as missing.
    </p>
    <p v-if="selectedDoc === 'party' && !partyConfigPath" class="hint warn-hint">
      ⚠ If no <code>config/party.yaml</code> exists yet on disk, this will fall back to
      the old staged-extracts path and error without <code>--extract-dir</code> — see
      <code>docs/cli/ensemble_workflow.md</code> §3d, or create a party.yaml first.
    </p>
    <template v-if="selectedDoc === 'planning'">
      <p class="hint">
        The config-mode NPC/faction list is the tracked (arc-scored) subset —
        a human-curated choice. Every other NPC dossier in
        <code>docs/ensemble/merged_dossiers/</code> is auto-included as
        pass-through context alongside it unless overridden below.
      </p>
      <p v-if="!planningConfigPath && !planningNpcFiles" class="hint warn-hint">
        ⚠ No planning config path set and no NPC dossiers listed below — if
        neither <code>config/planning.yaml</code> nor <code>planning.yaml</code>
        exists on disk either, this will error with no source material.
      </p>
      <EnsemblePlanningFields
        v-model:synth-mode="planningSynthMode"
        v-model:config-path="planningConfigPath"
        v-model:npc-files="planningNpcFiles"
        v-model:arc-scores="planningArcScores"
        v-model:context-files="planningContextFiles"
        v-model:depth="planningDepth"
        v-model:force-include="planningForceInclude"
      />
    </template>

    <div class="controls">
      <select v-model="selectedDoc">
        <option v-for="d in DOCS" :key="d.id" :value="d.id">{{ d.label }}</option>
      </select>
      <button class="btn-success" :disabled="run.status.value === 'running'" @click="synthesize">
        {{ run.status.value === 'running' ? 'Synthesizing…' : '▶ Synthesize draft' }}
      </button>
      <button v-if="run.status.value === 'running'" class="btn-warn btn-sm" @click="run.abort()">Abort</button>
      <span v-if="statusLabel(run.status.value, run.returnCode.value)"
            :class="statusClass(run.status.value)">
        {{ statusLabel(run.status.value, run.returnCode.value) }}
      </span>
    </div>
    <StreamOutput v-if="run.output.value" :text="run.output.value" />

    <h3>Diff &amp; promote <span class="tag">human checkpoint</span></h3>
    <table class="promote-tbl">
      <tr v-for="d in DOCS" :key="d.id">
        <td>{{ d.label }}</td>
        <td><button class="btn-neutral btn-sm" @click="showDiff(d.id)">Diff vs live</button></td>
        <td><button class="btn-warn btn-sm" @click="promote(d.id)">Promote →</button></td>
      </tr>
    </table>
    <pre v-for="(d, k) in diffs" :key="k" class="diff"><strong>{{ k }}</strong>
{{ d }}</pre>
  </div>
</template>

<style scoped>
.step { padding: 16px 20px; overflow-y: auto; }
h2 { font-size: 16px; margin-bottom: 6px; }
h3 { font-size: 13px; margin: 16px 0 6px; }
.tag { font-size: 9px; background: var(--peach); color: var(--bg-mantle); border-radius: 8px; padding: 1px 7px; margin-left: 6px; font-weight: 700; }
.hint { font-size: 12px; color: var(--text-muted); margin-bottom: 12px; max-width: 64ch; }
.warn-hint { color: var(--peach); }
.controls { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
select { font-size: 12px; padding: 5px 7px; background: var(--bg-surface0); color: var(--text); border: 1px solid var(--bg-surface1); border-radius: 4px; }
.ok { color: var(--green); font-size: 12px; font-weight: 600; }
.err { color: var(--red); font-size: 12px; font-weight: 600; }
.aborted { color: var(--peach); font-size: 12px; font-weight: 600; }
.promote-tbl td { padding: 4px 10px 4px 0; font-size: 12px; }
.diff { background: #141420; border: 1px solid var(--bg-surface0); border-radius: 4px; padding: 8px 10px; font-family: var(--mono); font-size: 11px; white-space: pre-wrap; max-height: 300px; overflow-y: auto; }
</style>
