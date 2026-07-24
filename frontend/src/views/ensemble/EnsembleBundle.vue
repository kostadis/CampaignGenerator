<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { apiFetch, apiPut } from '../../api/client'
import { useEnsembleRun, fetchEnsembleConfig, type EnsembleConfig } from './useEnsembleRun'
import StreamOutput from '../../components/shared/StreamOutput.vue'

const emit = defineEmits<{ changed: [] }>()
const cfg = ref<EnsembleConfig | null>(null)
const listRun = useEnsembleRun()
const aggRun = useEnsembleRun()
const threadsRun = useEnsembleRun()

function statusLabel(s: string, rc: number | null): string {
  if (s === 'done') return 'Done'
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

// Gate state — aggregation is blocked until the operator confirms they reviewed
// scope + aliases (Principle II: no precision decision auto-fed downstream).
const gateConfirmed = ref(false)
const aliasContent = ref('')
const aliasLoaded = ref(false)

onMounted(async () => {
  cfg.value = await fetchEnsembleConfig()
  await loadAliases()
})

// Empty on purpose: corpus, aliases, known_names and min_facts are all
// resolved server-side from ensemble.yaml (Phase 3). Kept as a function so
// the two call sites still read as "the shared bundle arguments".
function commonParams(): Record<string, unknown> {
  return {}
}

function runList() {
  listRun.run('/api/ensemble/run/bundle', { ...commonParams(), list: true })
}

async function loadAliases() {
  if (!cfg.value?.aliases_path) { aliasLoaded.value = false; return }
  try {
    const r = await apiFetch(`/api/ensemble/file?path=${encodeURIComponent(cfg.value.aliases_path)}`)
    aliasContent.value = r.content ?? ''
    aliasLoaded.value = true
  } catch {
    aliasContent.value = ''
    aliasLoaded.value = false
  }
}

async function saveAliases() {
  if (!cfg.value?.aliases_path) return
  await apiPut(`/api/ensemble/file?path=${encodeURIComponent(cfg.value.aliases_path)}`,
              { content: aliasContent.value })
}

function runAggregate() {
  if (!gateConfirmed.value) return
  aggRun.run('/api/ensemble/run/bundle', {
    ...commonParams(),
    known_only: true,
  }, (rc) => { if (rc === 0) emit('changed') })
}

function runThreads() {
  threadsRun.run('/api/ensemble/run/threads', {})
}
</script>

<template>
  <div class="step" v-if="cfg">
    <h2>Stage 2 — Fact bundling</h2>

    <!-- Gate 1: scope review (--list, no model) -->
    <section class="gate">
      <h3>① Scope review <span class="tag">human checkpoint</span></h3>
      <p class="hint">
        List the entity universe and the known/location split before spending model
        time. No model call. Review which names are <code>[known]</code> vs
        <code>[location]</code>-scoped — this is a precision decision; you may also
        run <code>facts_to_state.py --list</code> at the CLI.
      </p>
      <div class="controls">
        <button class="btn-neutral" :disabled="listRun.status.value === 'running'" @click="runList">
          {{ listRun.status.value === 'running' ? 'Listing…' : 'Run scope list' }}
        </button>
        <button v-if="listRun.status.value === 'running'" class="btn-warn btn-sm" @click="listRun.abort()">Abort</button>
        <span v-if="statusLabel(listRun.status.value, listRun.returnCode.value)"
              :class="statusClass(listRun.status.value)">
          {{ statusLabel(listRun.status.value, listRun.returnCode.value) }}
        </span>
      </div>
      <StreamOutput v-if="listRun.output.value" :text="listRun.output.value" />
    </section>

    <!-- Gate 2: alias correction -->
    <section class="gate">
      <h3>② Alias correction <span class="tag">human checkpoint</span></h3>
      <p class="hint" v-if="cfg.aliases_path">
        Edit <code>{{ cfg.aliases_path }}</code> here, or in the CLI/chat and click
        Reload — changes are reflected without re-running any LLM step.
      </p>
      <p class="hint warn" v-else>Set an aliases path on the Setup step to use this gate.</p>
      <template v-if="cfg.aliases_path">
        <textarea v-model="aliasContent" rows="6" class="alias-box"
                  placeholder='{ "Canonical Name": ["variant1", "variant2"] }'></textarea>
        <div class="controls">
          <button class="btn-neutral btn-sm" @click="loadAliases">↻ Reload from disk</button>
          <button class="btn-success btn-sm" @click="saveAliases">Save aliases</button>
        </div>
      </template>
    </section>

    <!-- Gate confirm + aggregate -->
    <section class="gate">
      <h3>③ Aggregate dossiers</h3>
      <label class="confirm">
        <input type="checkbox" v-model="gateConfirmed" />
        I reviewed the scope list and corrected aliases.
      </label>
      <p class="hint">
        Runs <code>facts_to_state.py --known-only</code> → <code>state_dossiers/*.md</code>.
        Backend: <strong>{{ cfg.extract.backend }}</strong>. Resumable.
      </p>
      <div class="controls">
        <button class="btn-success" :disabled="!gateConfirmed || aggRun.status.value === 'running'"
                @click="runAggregate">
          {{ aggRun.status.value === 'running' ? 'Aggregating…' : '▶ Aggregate' }}
        </button>
        <button v-if="aggRun.status.value === 'running'" class="btn-warn btn-sm" @click="aggRun.abort()">Abort</button>
        <span v-if="statusLabel(aggRun.status.value, aggRun.returnCode.value)"
              :class="statusClass(aggRun.status.value)">
          {{ statusLabel(aggRun.status.value, aggRun.returnCode.value) }}
        </span>
        <button class="btn-neutral btn-sm"
                :disabled="threadsRun.status.value === 'running'"
                @click="runThreads">
          {{ threadsRun.status.value === 'running' ? 'Rendering…' : 'Render threads.md' }}
        </button>
      </div>
      <StreamOutput v-if="aggRun.output.value" :text="aggRun.output.value" />
      <StreamOutput v-if="threadsRun.output.value" :text="threadsRun.output.value" />
    </section>
  </div>
</template>

<style scoped>
.step { padding: 16px 20px; overflow-y: auto; }
h2 { font-size: 16px; margin-bottom: 10px; }
h3 { font-size: 13px; margin-bottom: 4px; }
.gate { border: 1px solid var(--bg-surface1); border-radius: 6px; padding: 12px 14px; margin-bottom: 14px; }
.tag { font-size: 9px; background: var(--peach); color: var(--bg-mantle); border-radius: 8px; padding: 1px 7px; margin-left: 6px; font-weight: 700; vertical-align: middle; }
.hint { font-size: 12px; color: var(--text-muted); margin: 4px 0 8px; max-width: 64ch; }
.hint.warn { color: var(--peach); }
.alias-box { width: 100%; max-width: 640px; font-family: var(--mono); font-size: 12px; padding: 6px 8px; background: var(--bg-surface0); color: var(--text); border: 1px solid var(--bg-surface1); border-radius: 4px; }
.controls { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
.confirm { display: flex; align-items: center; gap: 6px; font-size: 12px; margin-bottom: 6px; }
.ok { color: var(--green); font-size: 12px; font-weight: 600; }
.err { color: var(--red); font-size: 12px; font-weight: 600; }
.aborted { color: var(--peach); font-size: 12px; font-weight: 600; }
</style>
