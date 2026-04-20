<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import ExtractSynthesizePanel from '../../components/shared/ExtractSynthesizePanel.vue'

const config = useConfigStore()

// Mode: 'synthesize' or 'dossiers'
const mode = ref<'synthesize' | 'dossiers'>('synthesize')

// ── Synthesize mode ──
const npcFiles = ref('')
const arcScores = ref('')
const summaries = ref('')
const context = ref('')
const output = ref('')
const extractDir = ref('')
const chunkSize = ref(60000)
const splitChapters = ref('')
const noLog = ref(false)
const showAdvanced = ref(false)

// ── Build dossiers mode ──
const dossierSummaries = ref('')
const dossierDir = ref('')
const dossierExtractDir = ref('')
const dossierChunkSize = ref(60000)
const dossierSplitChapters = ref('')
const dossierSince = ref(0)

function loadFromConfig() {
  const v = config.values
  npcFiles.value = v.plan_npc || ''
  arcScores.value = v.plan_arc_scores || ''
  summaries.value = v.plan_summaries || v.summaries || ''
  context.value = v.plan_context || ''
  output.value = v.plan_output || v.planning_output || v.planning || ''
  extractDir.value = v.plan_extract_dir || ''
  chunkSize.value = v.plan_chunk_size || 60000
  splitChapters.value = v.plan_split_chapters || ''

  dossierSummaries.value = v.plan_build_summaries || v.summaries || ''
  dossierDir.value = v.plan_dossier_dir || 'docs/npcs/'
  dossierExtractDir.value = v.plan_build_extract_dir || ''
  dossierChunkSize.value = v.plan_build_chunk_size || 60000
  dossierSplitChapters.value = v.plan_build_split_chapters || ''
}

const npcList = computed(() =>
  npcFiles.value.split('\n').map(l => l.trim()).filter(Boolean)
)
const arcScoreList = computed(() =>
  arcScores.value.split('\n').map(l => l.trim()).filter(Boolean)
)
const contextList = computed(() =>
  context.value.split('\n').map(l => l.trim()).filter(Boolean)
)

const synthReady = computed(() =>
  !!(npcList.value.length && output.value.trim())
)

const dossierReady = computed(() =>
  !!(dossierSummaries.value.trim() && dossierDir.value.trim())
)

const synthParams = computed(() => ({
  npc: npcList.value,
  arc_scores: arcScoreList.value,
  summaries: summaries.value,
  context: contextList.value,
  output: output.value,
  extract_dir: extractDir.value,
  chunk_size: chunkSize.value,
  split_chapters: splitChapters.value,
  no_log: noLog.value,
  model: config.model,
}))

const synthHasSummaries = computed(() => !!summaries.value.trim())

const dossierParams = computed(() => ({
  summaries: dossierSummaries.value,
  dossier_dir: dossierDir.value,
  extract_dir: dossierExtractDir.value,
  chunk_size: dossierChunkSize.value,
  split_chapters: dossierSplitChapters.value,
  since: dossierSince.value,
  no_log: noLog.value,
  model: config.model,
}))

onMounted(() => { loadFromConfig() })
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Planning Document</h2>
      <p class="subtitle">
        Build NPC dossier files from summaries, then synthesize planning.md from dossiers + arc scores.
      </p>
    </div>

    <!-- Mode toggle -->
    <div class="mode-toggle">
      <button
        class="mode-btn"
        :class="{ active: mode === 'synthesize' }"
        @click="mode = 'synthesize'"
      >
        Synthesize planning.md
      </button>
      <button
        class="mode-btn"
        :class="{ active: mode === 'dossiers' }"
        @click="mode = 'dossiers'"
      >
        Build dossier files
      </button>
    </div>

    <!-- Synthesize mode -->
    <div v-if="mode === 'synthesize'" class="form-grid">
      <div class="form-section">
        <MultiPathField v-model="npcFiles" label="NPC dossier files" required resolve-base="campaign"
          help="One per line. Per-NPC dossier files (docs/npcs/*.md)." />
      </div>

      <div class="form-section">
        <MultiPathField v-model="arcScores" label="Threat arc score files" resolve-base="campaign"
          help="One per line. Arc score documents for threat factions." />
      </div>

      <div class="form-section">
        <PathField v-model="summaries" label="Session summaries file" resolve-base="campaign"
          help="Optional. Omit to skip the Extract pass (synthesize from dossiers only)." />
      </div>

      <div class="form-section">
        <MultiPathField v-model="context" label="Context files" resolve-base="campaign"
          help="Optional world context (factions, locations, etc.)." />
      </div>

      <div class="form-section">
        <PathField v-model="output" label="Output file" required is-output resolve-base="campaign"
          help="planning.md — enemy dossiers and strategic planning." />
      </div>

      <div class="form-section">
        <PathField v-model="extractDir" label="Extractions directory" resolve-base="campaign"
          help="Where planning_extractions/ files live. Review between Extract and Synthesize." />
      </div>

      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </button>

        <div v-if="showAdvanced" class="advanced-panel">
          <div class="field">
            <label class="field-label">Split by session prefix</label>
            <input type="text" class="field-input" v-model="splitChapters"
              placeholder="e.g. # Session — splits at each session heading" />
            <span class="field-help">When set, each session becomes one extract chunk. Overrides chunk size.</span>
          </div>
          <div class="field">
            <label class="field-label">Chunk size (chars)</label>
            <input type="number" class="field-input" v-model.number="chunkSize" min="10000" step="5000"
              :disabled="!!splitChapters" />
            <span class="field-help">Ignored when split-by-prefix is set. Default 60,000.</span>
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
        endpoint="/api/grounding/run/planning"
        :params="synthParams"
        :extract-dir="extractDir"
        :disabled="!synthReady"
        :extract-disabled="!synthHasSummaries"
        extract-label="1. Extract per-NPC"
        synth-label="2. Synthesize planning.md"
      />
    </div>

    <!-- Build dossiers mode -->
    <div v-if="mode === 'dossiers'" class="form-grid">
      <div class="form-section">
        <PathField v-model="dossierSummaries" label="Session summaries file" required resolve-base="campaign"
          help="The large summaries.md — per-NPC info is extracted from this." />
      </div>

      <div class="form-section">
        <PathField v-model="dossierDir" label="Dossier output directory" required is-output resolve-base="campaign"
          help="Where per-NPC dossier files are saved (e.g. docs/npcs/)." />
      </div>

      <div class="form-section">
        <PathField v-model="dossierExtractDir" label="Extractions directory" resolve-base="campaign"
          help="Where dossier_extract_*.md files live. Review between Extract and per-NPC synthesis." />
      </div>

      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </button>

        <div v-if="showAdvanced" class="advanced-panel">
          <div class="field">
            <label class="field-label">Split by session prefix</label>
            <input type="text" class="field-input" v-model="dossierSplitChapters"
              placeholder="e.g. # Session — splits at each session heading" />
            <span class="field-help">When set, each session becomes one extract chunk. Overrides chunk size.</span>
          </div>
          <div class="field">
            <label class="field-label">Chunk size (chars)</label>
            <input type="number" class="field-input" v-model.number="dossierChunkSize" min="10000" step="5000"
              :disabled="!!dossierSplitChapters" />
            <span class="field-help">Ignored when split-by-prefix is set. Default 60,000.</span>
          </div>
          <div class="field">
            <label class="field-label">Since chunk N (incremental)</label>
            <input type="number" class="field-input" v-model.number="dossierSince" min="0" step="1" />
            <span class="field-help">
              Aggregate and synthesize only from extracts numbered ≥ N. Use after a new session
              (e.g. 11 when dossier_extract_011.md is the new chunk) to skip historical chunks
              already rolled into dossiers. 0 = disabled (full rebuild).
            </span>
          </div>
        </div>
      </div>

      <ExtractSynthesizePanel
        endpoint="/api/grounding/run/build-dossiers"
        :params="dossierParams"
        :extract-dir="dossierExtractDir"
        :disabled="!dossierReady"
        extract-label="1. Extract per-chunk NPCs"
        synth-label="2. Aggregate & build dossiers"
      />
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 700px; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.mode-toggle {
  display: flex; gap: 0; margin-bottom: 16px;
  border: 1px solid var(--bg-surface1); border-radius: 4px; overflow: hidden;
}
.mode-btn {
  flex: 1; padding: 7px 12px; font-size: 11px; font-weight: 600;
  background: var(--bg-base); color: var(--text-sub); border: none;
  cursor: pointer; transition: background .1s;
}
.mode-btn:not(:last-child) { border-right: 1px solid var(--bg-surface1); }
.mode-btn:hover { background: var(--bg-surface0); }
.mode-btn.active {
  background: var(--bg-surface0); color: var(--mauve); font-weight: 700;
}

.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface0);
}
.form-section:last-child { border-bottom: none; }

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
