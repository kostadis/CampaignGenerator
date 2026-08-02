<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  fetchEnsembleConfig, saveEnsembleConfig, fetchRegistrySummary,
  type EnsembleConfig, type RegistrySummary,
} from './useEnsembleRun'
import ChapterPicker from './ChapterPicker.vue'

// Populated by the GET below; the server owns every default.
const cfg = ref<EnsembleConfig | null>(null)
const extractEndpointsText = ref('')
const saved = ref(false)
// Read-only — the entity registry (docs/entity_registry.yaml) replaced the
// known-names/aliases inputs this page used to own. Curated via the
// `registry` CLI / /entity-triage / /ensemble-alias-review, never here.
const registry = ref<RegistrySummary | null>(null)

// Synthesis is a single non-parallelized call, so it keeps one endpoint —
// bind the array's first slot as if it were a plain string field.
const synthEndpoint = computed({
  get: () => cfg.value?.synthesize.endpoints[0] ?? '',
  set: (v: string) => { if (cfg.value) cfg.value.synthesize.endpoints = v ? [v] : [] },
})

onMounted(async () => {
  const loaded = await fetchEnsembleConfig()
  cfg.value = loaded
  extractEndpointsText.value = loaded.extract.endpoints.join('\n')
  registry.value = await fetchRegistrySummary()
})

// Plain-language readout of what the two scope knobs currently mean together.
// They only make sense as a pair — a floor without a window is what deleted the
// newest chapter's entities every run (issue #194) — so the page states the
// combined effect rather than leaving the operator to compose it.
const scopeSummary = computed(() => {
  const w = cfg.value?.tuning.dossier_recent_window ?? 0
  const m = cfg.value?.tuning.background_min_facts ?? 0
  if (w === 0) {
    return `Every entity counts as current, so the ${m}-fact floor is not applied `
      + `— nothing is dropped, and the payload is every dossier on disk.`
  }
  return `Entities touched in the last ${w} chapter${w === 1 ? '' : 's'} are always `
    + `included, however few facts they have. Entities last seen earlier need at `
    + `least ${m} fact${m === 1 ? '' : 's'}.`
})

// States which merge algorithm the endpoint field actually selects, and what the
// weaker one cannot do. Blank is a legitimate state (no embed server), but it is
// a real downgrade and the page says so rather than letting it read as neutral —
// the whole of issue #197 is a degradation that looked like a decision.
const mergeSummary = computed(() => {
  const ep = (cfg.value?.merge.embed_endpoint ?? '').trim()
  return ep
    ? `Embedding merge: facts cluster by meaning across subjects, so the same `
      + `event described under two different subjects collapses into one.`
    : `No endpoint — falls back to the subject merge, which groups on `
      + `(type, subject) and therefore never compares facts filed under `
      + `different subjects. Cross-subject duplicates and contradictions `
      + `survive it by construction.`
})

async function save() {
  if (!cfg.value) return
  cfg.value.extract.endpoints = extractEndpointsText.value.split('\n').map(s => s.trim()).filter(Boolean)
  // Send only what this page owns — chapters_glob now lives under `paths`, and
  // `tuning` carries just the two world_state scope knobs. The service
  // deep-merges, so the other four tuning fields (chapter_parallel,
  // chunk_parallel, bundle/threads_min_facts, entity_parallel) stay
  // YAML-only and survive untouched.
  cfg.value = await saveEnsembleConfig({
    chapters_selected: cfg.value.chapters_selected,
    extract: cfg.value.extract,
    synthesize: cfg.value.synthesize,
    paths: { chapters_glob: cfg.value.paths.chapters_glob },
    tuning: {
      dossier_recent_window: cfg.value.tuning.dossier_recent_window,
      background_min_facts: cfg.value.tuning.background_min_facts,
    },
    // The endpoint decides WHICH merge algorithm runs; the model decides
    // whether it can run at all, so they are saved as a pair. Splitting them
    // is what broke the 2026-07-29 Phandalin run: the UI could point at an
    // Ollama endpoint but not name an Ollama model, so the merge inherited a
    // stale vLLM default and 404'd after extraction had finished.
    // method/embed_threshold/similarity stay YAML-only — 0.94 is a measured
    // threshold, not a dial (issue #197; calibrated on qwen3-embedding:0.6b
    // via calibrate_embed).
    merge: {
      embed_endpoint: cfg.value.merge.embed_endpoint,
      embed_model: cfg.value.merge.embed_model,
    },
  })
  saved.value = true
  setTimeout(() => (saved.value = false), 1500)
}

function resetBackend(stage: 'extract' | 'synthesize') {
  if (!cfg.value) return
  cfg.value[stage].endpoints = []
  cfg.value[stage].model = ''
  if (stage === 'extract') extractEndpointsText.value = ''
}

// Batch is a per-stage `bool | null` (005-ui-batch-selection — see the
// `batch` field doc on BackendProfile in useEnsembleRun.ts): `null` defers
// to the platform's app-wide batch flag, `false` is a sticky per-stage off
// that does NOT follow an app-wide change. A plain checkbox can't express
// "defer" separately from "explicitly off", so this stage control is a
// three-option select instead — same treatment as SelectionPanel.vue's
// per-service batch override, one level down at the ensemble-stage tier.
function batchSelectValue(stage: 'extract' | 'synthesize'): '' | 'on' | 'off' {
  const b = cfg.value?.[stage].batch
  return b === true ? 'on' : b === false ? 'off' : ''
}
function setBatchSelect(stage: 'extract' | 'synthesize', value: string) {
  if (!cfg.value) return
  cfg.value[stage].batch = value === 'on' ? true : value === 'off' ? false : null
}
</script>

<template>
  <div class="step" v-if="cfg">
    <h2>Ensemble Setup</h2>
    <p class="hint">
      Point at your inputs and pick a backend for each LLM-bearing stage. Extraction
      and synthesis are chosen independently. Files on disk are the source of truth —
      this only records your selections.
    </p>

    <div class="fld">
      <span>Chapters</span>
      <ChapterPicker
        v-model:glob="cfg.paths.chapters_glob"
        v-model:selected="cfg.chapters_selected" />
    </div>

    <div class="fld">
      <span>Entity registry</span>
      <p v-if="registry?.found && !registry.error" class="hint">
        <code>{{ registry.path }}</code> — {{ registry.entity_count }} entities, {{ registry.alias_count }} aliases
      </p>
      <p v-else-if="registry" class="warn-note">{{ registry.error }}</p>
    </div>

    <div class="profiles">
      <fieldset v-for="stage in (['extract','synthesize'] as const)" :key="stage">
        <legend>{{ stage === 'extract' ? 'Extraction backend' : 'Synthesis backend' }}</legend>
        <label class="fld">
          <span>Backend</span>
          <select v-model="cfg[stage].backend" @change="resetBackend(stage)">
            <option value="anthropic">Anthropic (Claude API)</option>
            <option value="dgx">DGX / Spark (local)</option>
            <option value="openrouter">OpenRouter</option>
            <option value="claude-code">Subscription (Claude Code)</option>
          </select>
        </label>
        <label class="fld" v-if="cfg[stage].backend === 'dgx' && stage === 'extract'">
          <span>DGX endpoints (one per line — fanned out round-robin across chapters/entities)</span>
          <textarea v-model="extractEndpointsText" rows="3"
                    placeholder="http://spark1:8001/v1&#10;http://spark2:8001/v1"></textarea>
        </label>
        <label class="fld" v-if="cfg[stage].backend === 'dgx' && stage === 'synthesize'">
          <span>Endpoint</span>
          <input v-model="synthEndpoint" type="text" placeholder="http://192.168.1.147:8001/v1" />
        </label>
        <label class="fld" v-if="cfg[stage].backend !== 'anthropic' && cfg[stage].backend !== 'claude-code'">
          <span>Model id</span>
          <input v-model="cfg[stage].model" type="text"
                 :placeholder="cfg[stage].backend === 'openrouter' ? 'anthropic/claude-sonnet-4' : 'Qwen/Qwen3-Next-80B-A3B-Instruct-FP8'" />
        </label>
        <label class="fld" v-if="cfg[stage].backend === 'claude-code'">
          <span>Model id (optional — defaults to the subscription's own default)</span>
          <input v-model="cfg[stage].model" type="text" placeholder="claude-opus-4-8" />
        </label>
        <p v-if="stage === 'synthesize' && cfg.synthesize.backend !== 'anthropic'" class="warn-note">
          Synthesis assumes a model at least as capable as Sonnet; a weak or
          local model underperforms here (you'll get a warning at run time, not a block).
        </p>
        <label class="fld batch-fld">
          <span>Batch</span>
          <select
            :value="batchSelectValue(stage)"
            @change="setBatchSelect(stage, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">(inherit platform)</option>
            <option value="on">On</option>
            <option value="off">Off</option>
          </select>
          <div class="field-help">
            Use Anthropic Message Batches (50% off list price; replaces streaming with poll-progress)
          </div>
        </label>
        <p v-if="batchSelectValue(stage) === 'on' && cfg[stage].backend !== 'anthropic'" class="warn-note">
          Batch is a Claude API option — this stage is set to the
          {{ cfg[stage].backend }} backend, so the run will refuse rather
          than run at full price. Switch this stage to Anthropic, or turn
          batch off.
        </p>
      </fieldset>
    </div>

    <fieldset class="scope">
      <legend>Synthesis scope (world_state dossiers)</legend>
      <p class="hint">
        Which entity dossiers reach the world_state synthesis call. Recency
        decides, not how often an entity is mentioned — a character introduced
        last session has the fewest facts precisely because it is new.
      </p>
      <div class="scope-row">
        <label class="fld">
          <span>Recent window (chapters)</span>
          <input v-model.number="cfg.tuning.dossier_recent_window" type="number" min="0" step="1" />
          <div class="field-help">
            Chapters counted as “current”. Everything touched in them is included
            whatever its fact count. 0 = all chapters are recent, so no floor applies.
          </div>
        </label>
        <label class="fld">
          <span>Background floor (facts)</span>
          <input v-model.number="cfg.tuning.background_min_facts" type="number" min="0" step="1" />
          <div class="field-help">
            Minimum facts for an entity last seen <em>before</em> the window.
            Filters one-scene noise out of the deep past.
          </div>
        </label>
      </div>
      <p class="scope-summary">{{ scopeSummary }}</p>
    </fieldset>

    <fieldset class="scope">
      <legend>Fact merge (extraction)</legend>
      <p class="hint">
        How the five extraction lenses' facts are collapsed into
        <code>merged.json</code>. This runs per chapter during extraction.
      </p>
      <label class="fld">
        <span>Embedding endpoint</span>
        <input v-model="cfg.merge.embed_endpoint" type="text"
               placeholder="http://192.168.1.147:11434/v1" />
        <div class="field-help">
          An OpenAI-compatible <code>/v1/embeddings</code> server. Leave
          blank if you have none.
        </div>
      </label>
      <label class="fld">
        <span>Embedding model</span>
        <input v-model="cfg.merge.embed_model" type="text"
               placeholder="qwen3-embedding:0.6b" />
        <div class="field-help">
          The model id <em>as that server names it</em> — an Ollama endpoint
          wants <code>qwen3-embedding:0.6b</code>, a vLLM one wants the full
          <code>org/model</code> id. A mismatch fails the merge with
          <code>model … not found</code> <em>after</em> extraction has run, so
          it is worth getting right before a long batch. Changing it away from
          <code>qwen3-embedding:0.6b</code> also invalidates the calibrated
          <code>embed_threshold</code> (0.94) — re-run
          <code>calibrate_embed</code> for the new model.
        </div>
      </label>
      <p class="scope-summary">{{ mergeSummary }}</p>
    </fieldset>

    <div class="actions">
      <button class="btn-success" @click="save">Save selections</button>
      <span v-if="saved" class="ok">Saved</span>
    </div>
  </div>
</template>

<style scoped>
.step { padding: 16px 20px; overflow-y: auto; }
h2 { font-size: 16px; margin-bottom: 6px; }
.hint { font-size: 12px; color: var(--text-muted); margin-bottom: 14px; max-width: 60ch; }
.fld { display: block; margin-bottom: 10px; font-size: 12px; }
.fld > span { display: block; margin-bottom: 3px; color: var(--text-sub); }
.fld input, .fld textarea, .fld select {
  width: 100%; max-width: 560px; font-size: 12px; padding: 5px 7px;
  background: var(--bg-surface0); color: var(--text);
  border: 1px solid var(--bg-surface1); border-radius: 4px; font-family: var(--mono);
}
.batch-fld { margin-top: 8px; }
.batch-fld .field-help {
  font-size: 10px; color: var(--text-muted); font-style: italic;
  margin-top: 3px; line-height: 1.4; max-width: 40ch;
}
.profiles { display: flex; gap: 16px; flex-wrap: wrap; margin: 10px 0; }
.scope { margin: 10px 0; max-width: 600px; }
.scope .hint { margin-bottom: 10px; }
.scope-row { display: flex; gap: 16px; flex-wrap: wrap; }
.scope-row .fld { flex: 1 1 200px; margin-bottom: 6px; }
.scope-row .fld input { max-width: 110px; }
.scope .field-help {
  font-size: 10px; color: var(--text-muted); font-style: italic;
  margin-top: 3px; line-height: 1.4;
}
.scope-summary {
  font-size: 11px; color: var(--text-sub); margin-top: 8px;
  padding: 6px 8px; border-left: 2px solid var(--mauve);
  background: var(--bg-surface0); border-radius: 0 4px 4px 0; line-height: 1.5;
}
fieldset { border: 1px solid var(--bg-surface1); border-radius: 6px; padding: 10px 12px; min-width: 280px; }
legend { font-size: 11px; font-weight: 700; color: var(--mauve); padding: 0 6px; }
.warn-note { font-size: 11px; color: var(--peach); max-width: 40ch; margin-top: 4px; }
.actions { margin-top: 12px; display: flex; align-items: center; gap: 10px; }
.ok { color: var(--green); font-size: 12px; font-weight: 600; }
</style>
