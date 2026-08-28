<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import ExtractSynthesizePanel from '../../components/shared/ExtractSynthesizePanel.vue'
import PartyConfigEditor from '../../components/shared/PartyConfigEditor.vue'
import { useGroundingRun } from '../../composables/useGroundingRun'

const config = useConfigStore()

type Mode = 'config' | 'flat'
const mode = ref<Mode>('config')

const partyConfigPath = ref('')
const characters = ref('')
const summaries = ref('')
const backstory = ref('')
const arcScores = ref('')
const context = ref('')
const output = ref('')
const extractDir = ref('')
const splitChapters = ref('# Chapter')
const noLog = ref(false)
const showAdvanced = ref(false)

// Newline textareas <-> the config's string lists.
function linesOf(r: typeof characters) {
  return computed<string[]>({
    get: () => r.value.split('\n').map(l => l.trim()).filter(Boolean),
    set: (v: string[]) => { r.value = v.join('\n') },
  })
}
const charFiles = linesOf(characters)
const backstoryFiles = linesOf(backstory)
const arcScoreFiles = linesOf(arcScores)
const contextFiles = linesOf(context)

// This page previously persisted 2 of the 9 fields it read (mode and
// config_path); `chars`, `summaries`, `backstory`, `arc_scores`, `context`,
// `output`, `extract_dir` and `split_chapters` were dead reads against keys
// nothing ever wrote. All nine persist now.
const { sharedSummaries } = useGroundingRun('party', {
  mode, config_path: partyConfigPath, input: summaries, output,
  extract_dir: extractDir, split_chapters: splitChapters, no_log: noLog,
  characters: charFiles, backstory: backstoryFiles,
  arc_scores: arcScoreFiles, context: contextFiles,
})

const effectiveSummaries = computed(() => summaries.value.trim() || sharedSummaries.value)

const ready = computed(() => {
  if (!output.value.trim()) return false
  return mode.value === 'config'
    ? !!partyConfigPath.value.trim()
    : charFiles.value.length > 0
})

// Extract phase needs summaries; the two-phase panel appends extract_only=true.
// When the user hits Synthesize, the panel auto-adds synthesize_only=true so
// the CLI skips the extract pass and just reads the cached files.
const runParams = computed(() => {
  const base: Record<string, unknown> = {
    summaries: summaries.value,
    context: contextFiles.value,
    output: output.value,
    extract_dir: extractDir.value,
    split_chapters: splitChapters.value,
    no_log: noLog.value,
    model: config.model || undefined,
  }
  if (mode.value === 'config') {
    base.party_config = partyConfigPath.value
  } else {
    base.character = charFiles.value
    base.backstory = backstoryFiles.value
    base.arc_scores = arcScoreFiles.value
  }
  return base
})

// Extract needs a timeline; an empty local field inherits the shared one.
const hasSummaries = computed(() => !!effectiveSummaries.value)

watch(output, (newOutput) => {
  if (!extractDir.value && newOutput) {
    const idx = newOutput.lastIndexOf('/')
    const parent = idx >= 0 ? newOutput.slice(0, idx) : ''
    extractDir.value = parent ? `${parent}/party_extractions` : 'party_extractions'
  }
})

</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Party Document</h2>
      <p class="subtitle">
        Generate party.md from character sheets, session summaries, backstories, and arc score mechanics.
      </p>
    </div>

    <div class="form-grid">
      <!-- Input mode toggle -->
      <div class="form-section mode-section">
        <label class="field-label">Input mode</label>
        <div class="mode-toggle">
          <label class="radio-label">
            <input type="radio" value="config" v-model="mode" />
            Party config YAML
            <span class="mode-hint">— preferred; explicit per-PC mapping with first-class trackless support</span>
          </label>
          <label class="radio-label">
            <input type="radio" value="flat" v-model="mode" />
            Flat file lists
            <span class="mode-hint">— legacy; one file per line for sheets / backstories / arc scores</span>
          </label>
        </div>
      </div>

      <!-- Party config YAML (mode = config) -->
      <div v-if="mode === 'config'" class="form-section">
        <PathField v-model="partyConfigPath" label="Party config file" required resolve-base="campaign"
          help="Path to party.yaml. Maps each PC to their sheet, backstory, and arc_score (use null for trackless). See config/party.example.yaml." />
        <PartyConfigEditor />
      </div>

      <!-- Required: character sheets (mode = flat) -->
      <div v-else class="form-section">
        <MultiPathField v-model="characters" label="Character sheet files" required resolve-base="campaign"
          help="One character sheet per line (e.g. docs/characters/soma.md). Required." />
      </div>

      <!-- Summaries (both modes) -->
      <div class="form-section">
        <PathField v-model="summaries" label="Canonical timeline" resolve-base="campaign"
          help="The master narrative bible. Optional — omit to skip the Extract pass (characters-only mode)." />
      </div>

      <div class="form-section">
        <PathField v-model="extractDir" label="Extractions directory" resolve-base="campaign"
          help="Where intermediate party_extractions/ files live. Review these between Extract and Synthesize." />
      </div>

      <!-- Output -->
      <div class="form-section">
        <PathField v-model="output" label="Output file" required is-output resolve-base="campaign"
          help="party.md — roster, arc scores, relationships." />
      </div>

      <!-- Optional inputs (flat mode only) -->
      <div v-if="mode === 'flat'" class="form-section">
        <MultiPathField v-model="backstory" label="Backstory files" resolve-base="campaign"
          help="One per line. Optional backstory documents for each character." />
        <MultiPathField v-model="arcScores" label="PC arc score mechanic files" resolve-base="campaign"
          help="One per line. Arc score mechanic files for player characters, one per PC (e.g. soma-score.md). Defines score triggers for character arcs. Not for NPC/faction arc scores — those belong in Planning Document." />
      </div>

      <!-- Context (both modes) -->
      <div class="form-section">
        <MultiPathField v-model="context" label="Additional context files" resolve-base="campaign"
          help="e.g. campaign_state.md — optional extra context for synthesis." />
      </div>

      <!-- Advanced -->
      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </button>

        <div v-if="showAdvanced" class="advanced-panel">
          <div class="field">
            <label class="field-label">Split by session prefix</label>
            <input type="text" class="field-input" v-model="splitChapters"
              placeholder="e.g. # Session — splits at each session heading" />
            <span class="field-help">When set, each session becomes one extract chunk.</span>
          </div>
          <div class="field">
            <label class="checkbox-label">
              <input type="checkbox" v-model="noLog" />
              Skip log file
            </label>
          </div>
        </div>
      </div>

      <ExtractSynthesizePanel
        endpoint="/api/grounding/run/party"
        selection-service="party"
        :selection-can-override="true"
        :params="runParams"
        :extract-dir="extractDir"
        :disabled="!ready"
        :extract-disabled="!hasSummaries"
        extract-label="1. Extract character info from summaries"
        synth-label="2. Synthesize party.md"
      />
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface0);
}
.form-section:last-child { border-bottom: none; }

.mode-section { display: flex; flex-direction: column; gap: 6px; }
.mode-toggle { display: flex; flex-direction: column; gap: 4px; }
.radio-label {
  font-size: 11px; color: var(--text-sub);
  display: flex; align-items: center; gap: 6px; cursor: pointer;
}
.radio-label input { accent-color: var(--mauve); }
.mode-hint { color: var(--text-muted); font-weight: 400; }

.field { margin-bottom: 10px; }
.field-label {
  display: block; font-size: 11px; font-weight: 600;
  color: var(--text-sub); margin-bottom: 3px;
}
.field-input {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box;
}
.field-input:focus { border-color: var(--mauve); }

.checkbox-label {
  font-size: 11px; color: var(--text-sub); display: flex;
  align-items: center; gap: 6px; cursor: pointer;
}
.checkbox-label input { accent-color: var(--mauve); }

.field-help { display: block; font-size: 10px; color: var(--text-muted); margin-top: 3px; }
.field-input:disabled { opacity: 0.4; cursor: not-allowed; }

.advanced-panel {
  margin-top: 10px; padding: 10px;
  background: var(--bg-mantle); border-radius: 4px;
}
</style>
