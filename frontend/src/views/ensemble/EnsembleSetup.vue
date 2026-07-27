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

async function save() {
  if (!cfg.value) return
  cfg.value.extract.endpoints = extractEndpointsText.value.split('\n').map(s => s.trim()).filter(Boolean)
  // Send only what this page owns — chapters_glob now lives under `paths`,
  // and the untouched groups (tuning, planning) are left to merge server-side.
  cfg.value = await saveEnsembleConfig({
    chapters_selected: cfg.value.chapters_selected,
    extract: cfg.value.extract,
    synthesize: cfg.value.synthesize,
    paths: { chapters_glob: cfg.value.paths.chapters_glob },
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
      </fieldset>
    </div>

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
.profiles { display: flex; gap: 16px; flex-wrap: wrap; margin: 10px 0; }
fieldset { border: 1px solid var(--bg-surface1); border-radius: 6px; padding: 10px 12px; min-width: 280px; }
legend { font-size: 11px; font-weight: 700; color: var(--mauve); padding: 0 6px; }
.warn-note { font-size: 11px; color: var(--peach); max-width: 40ch; margin-top: 4px; }
.actions { margin-top: 12px; display: flex; align-items: center; gap: 10px; }
.ok { color: var(--green); font-size: 12px; font-weight: 600; }
</style>
