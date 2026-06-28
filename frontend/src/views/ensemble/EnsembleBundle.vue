<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import { apiFetch, apiPut } from '../../api/client'
import { useEnsembleRun, readEnsembleConfig, type EnsembleConfig } from './useEnsembleRun'
import StreamOutput from '../../components/shared/StreamOutput.vue'

const emit = defineEmits<{ changed: [] }>()
const config = useConfigStore()
const cfg = ref<EnsembleConfig>(readEnsembleConfig({}))
const listRun = useEnsembleRun()
const aggRun = useEnsembleRun()
const threadsRun = useEnsembleRun()

// Gate state — aggregation is blocked until the operator confirms they reviewed
// scope + aliases (Principle II: no precision decision auto-fed downstream).
const gateConfirmed = ref(false)
const aliasContent = ref('')
const aliasLoaded = ref(false)

onMounted(async () => {
  await config.load()
  cfg.value = readEnsembleConfig(config.resolved)
  await loadAliases()
})

function commonParams() {
  return {
    corpus: 'docs/ensemble/per_chapter/*/merged.json',
    aliases: cfg.value.aliases_path,
    known_names: cfg.value.known_names,
    min_facts: 3,
  }
}

function runList() {
  listRun.run('/api/ensemble/run/bundle', { ...commonParams(), list: true })
}

async function loadAliases() {
  if (!cfg.value.aliases_path) { aliasLoaded.value = false; return }
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
  await apiPut(`/api/ensemble/file?path=${encodeURIComponent(cfg.value.aliases_path)}`,
              { content: aliasContent.value })
}

function runAggregate() {
  if (!gateConfirmed.value) return
  aggRun.run('/api/ensemble/run/bundle', {
    ...commonParams(),
    known_only: true,
    out_dir: 'docs/ensemble/state_dossiers',
    backend: cfg.value.extract.backend,
    endpoint: cfg.value.extract.endpoint,
    model: cfg.value.extract.model,
  }, (rc) => { if (rc === 0) emit('changed') })
}

function runThreads() {
  threadsRun.run('/api/ensemble/run/threads', {
    corpus: 'docs/ensemble/per_chapter/*/merged.json',
    aliases: cfg.value.aliases_path,
    output: 'docs/ensemble/threads.md',
  })
}
</script>

<template>
  <div class="step">
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
      <button class="btn-neutral" :disabled="listRun.status.value === 'running'" @click="runList">
        {{ listRun.status.value === 'running' ? 'Listing…' : 'Run scope list' }}
      </button>
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
        <span v-if="aggRun.returnCode.value !== null"
              :class="aggRun.returnCode.value === 0 ? 'ok' : 'err'">
          {{ aggRun.returnCode.value === 0 ? 'Done' : `Exit ${aggRun.returnCode.value}` }}
        </span>
        <button class="btn-neutral btn-sm" @click="runThreads">Render threads.md</button>
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
</style>
