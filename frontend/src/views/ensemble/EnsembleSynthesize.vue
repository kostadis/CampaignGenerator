<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { useConfigStore } from '../../stores/config'
import { apiFetch, apiPost } from '../../api/client'
import { useEnsembleRun, readEnsembleConfig, type EnsembleConfig } from './useEnsembleRun'
import StreamOutput from '../../components/shared/StreamOutput.vue'

const emit = defineEmits<{ changed: [] }>()
const config = useConfigStore()
const cfg = ref<EnsembleConfig>(readEnsembleConfig({}))
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
// Party config path set via the Party Document page (ui.party.config_path).
// Passed through as-is — the server falls back to config/party.yaml or
// party.yaml at the campaign root when this is blank.
const partyConfigPath = ref('')

onMounted(async () => {
  await config.load()
  cfg.value = readEnsembleConfig(config.resolved)
  partyConfigPath.value = config.resolved?.ui?.party?.config_path || ''
})

function synthesize() {
  run.run('/api/ensemble/run/synthesize', {
    doc: selectedDoc.value,
    backend: cfg.value.synthesize.backend,
    endpoint: cfg.value.synthesize.endpoints[0] ?? '',
    model: cfg.value.synthesize.model,
    party: partyConfigPath.value,
  }, (rc) => { if (rc === 0) emit('changed') })
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
      <strong>{{ cfg.synthesize.backend }}</strong>. Review the diff, then promote by hand.
    </p>
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
