<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import {
  useEnsembleRun, fetchEnsembleConfig, fetchRegistrySummary,
  type EnsembleConfig, type RegistrySummary,
} from './useEnsembleRun'
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
// scope + the registry checkpoint (Principle II: no precision decision auto-fed
// downstream). `registry` also directly disables the checkbox: an invalid/
// missing registry can't be armed at all, not just unchecked-by-default.
const gateConfirmed = ref(false)
const registry = ref<RegistrySummary | null>(null)

onMounted(async () => {
  cfg.value = await fetchEnsembleConfig()
  await loadRegistry()
})

async function loadRegistry() {
  registry.value = await fetchRegistrySummary()
}

// If the registry becomes invalid/missing after the operator already checked
// the confirm box (e.g. a re-check after editing the registry on disk),
// un-arm it rather than leaving a stale confirmation in place.
watch(registry, (r) => {
  if (!r?.found || r?.error) gateConfirmed.value = false
})

// Empty on purpose: corpus, the registry path, and min_facts are all resolved
// server-side from ensemble.yaml / docs/entity_registry.yaml (Phase 3). Kept
// as a function so the two call sites still read as "the shared bundle
// arguments".
function commonParams(): Record<string, unknown> {
  return {}
}

function runList() {
  listRun.run('/api/ensemble/run/bundle', { ...commonParams(), list: true })
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

    <!-- Gate 2: entity registry checkpoint -->
    <section class="gate">
      <h3>② Entity registry <span class="tag">human checkpoint</span></h3>
      <template v-if="registry?.found && !registry.error">
        <p class="hint">
          <code>{{ registry.path }}</code> — {{ registry.entity_count }} entities, {{ registry.alias_count }} aliases
        </p>
        <template v-if="registry.check">
          <p v-if="registry.check.grouping.length" class="hint warn">
            Grouping drift ({{ registry.check.grouping.length }}) — review before aggregating:
          </p>
          <ul v-if="registry.check.grouping.length" class="findings">
            <li v-for="(f, i) in registry.check.grouping" :key="i">{{ f }}</li>
          </ul>
          <p v-if="registry.check.clean" class="hint ok-note">✓ No drift against legacy stores.</p>

          <details v-if="registry.check.fuzzy.length">
            <summary>Fuzzy near-dups ({{ registry.check.fuzzy.length }}) — review material, not errors</summary>
            <ul class="findings"><li v-for="(f, i) in registry.check.fuzzy" :key="i">{{ f }}</li></ul>
          </details>
          <details v-if="registry.check.missing_from_registry.length">
            <summary>Missing from registry ({{ registry.check.missing_from_registry.length }})</summary>
            <ul class="findings"><li v-for="(f, i) in registry.check.missing_from_registry" :key="i">{{ f }}</li></ul>
          </details>
          <details v-if="registry.check.missing_from_legacy.length">
            <summary>Missing from legacy stores ({{ registry.check.missing_from_legacy.length }})</summary>
            <ul class="findings"><li v-for="(f, i) in registry.check.missing_from_legacy" :key="i">{{ f }}</li></ul>
          </details>
        </template>
      </template>
      <p v-else class="hint warn">{{ registry?.error || 'no entity registry found' }}</p>
      <p class="hint">
        Curate via the <code>registry</code> CLI, <code>/entity-triage</code>, or
        <code>/ensemble-alias-review</code> — not from this page.
      </p>
      <div class="controls">
        <button class="btn-neutral btn-sm" @click="loadRegistry">↻ Re-check</button>
      </div>
    </section>

    <!-- Gate confirm + aggregate -->
    <section class="gate">
      <h3>③ Aggregate dossiers</h3>
      <label class="confirm">
        <input type="checkbox" v-model="gateConfirmed" :disabled="!registry?.found || !!registry?.error" />
        I reviewed the scope list and the registry checkpoint.
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
.hint.ok-note { color: var(--green); }
.findings { margin: 0 0 8px; padding-left: 18px; font-size: 12px; color: var(--text); max-width: 64ch; }
.findings li { margin-bottom: 2px; }
details { margin-bottom: 8px; }
details summary { font-size: 12px; color: var(--text-sub); cursor: pointer; }
details .findings { margin-top: 6px; }
.controls { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
.confirm { display: flex; align-items: center; gap: 6px; font-size: 12px; margin-bottom: 6px; }
.ok { color: var(--green); font-size: 12px; font-weight: 600; }
.err { color: var(--red); font-size: 12px; font-weight: 600; }
.aborted { color: var(--peach); font-size: 12px; font-weight: 600; }
</style>
