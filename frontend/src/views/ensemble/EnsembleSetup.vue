<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import { readEnsembleConfig, type EnsembleConfig } from './useEnsembleRun'
import ChapterPicker from './ChapterPicker.vue'

const config = useConfigStore()
const cfg = ref<EnsembleConfig>(readEnsembleConfig({}))
const knownNamesText = ref('')
const saved = ref(false)

onMounted(async () => {
  await config.load()
  cfg.value = readEnsembleConfig(config.resolved)
  knownNamesText.value = cfg.value.known_names.join('\n')
})

async function save() {
  cfg.value.known_names = knownNamesText.value.split('\n').map(s => s.trim()).filter(Boolean)
  await config.updateSection('ensemble', {
    campaign_dir: cfg.value.campaign_dir,
    chapters_glob: cfg.value.chapters_glob,
    chapters_selected: cfg.value.chapters_selected,
    extract: cfg.value.extract,
    synthesize: cfg.value.synthesize,
    known_names: cfg.value.known_names,
    aliases_path: cfg.value.aliases_path,
  })
  saved.value = true
  setTimeout(() => (saved.value = false), 1500)
}
</script>

<template>
  <div class="step">
    <h2>Ensemble Setup</h2>
    <p class="hint">
      Point at your inputs and pick a backend for each LLM-bearing stage. Extraction
      and synthesis are chosen independently. Files on disk are the source of truth —
      this only records your selections.
    </p>

    <div class="fld">
      <span>Chapters</span>
      <ChapterPicker
        v-model:glob="cfg.chapters_glob"
        v-model:selected="cfg.chapters_selected" />
    </div>

    <label class="fld">
      <span>Known-names sources (one path per line — module inventory, <code>.dedup_state.json</code>)</span>
      <textarea v-model="knownNamesText" rows="3"
                placeholder="docs/background/module-inventory.md&#10;docs/npcs/.dedup_state.json"></textarea>
    </label>

    <label class="fld">
      <span>Aliases file (the alias-correction gate edits this)</span>
      <input v-model="cfg.aliases_path" type="text" placeholder="docs/ensemble/aliases.json" />
    </label>

    <div class="profiles">
      <fieldset v-for="stage in (['extract','synthesize'] as const)" :key="stage">
        <legend>{{ stage === 'extract' ? 'Extraction backend' : 'Synthesis backend' }}</legend>
        <label class="fld">
          <span>Backend</span>
          <select v-model="cfg[stage].backend"
                  @change="cfg[stage].endpoint = ''; cfg[stage].model = ''">
            <option value="anthropic">Anthropic (Claude API)</option>
            <option value="dgx">DGX / Spark (local)</option>
            <option value="openrouter">OpenRouter</option>
            <option value="claude-code">Subscription (Claude Code)</option>
          </select>
        </label>
        <label class="fld" v-if="cfg[stage].backend === 'dgx'">
          <span>Endpoint</span>
          <input v-model="cfg[stage].endpoint" type="text" placeholder="http://192.168.1.147:8001/v1" />
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
