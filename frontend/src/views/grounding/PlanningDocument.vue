<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import ExtractSynthesizePanel from '../../components/shared/ExtractSynthesizePanel.vue'
import PlanningConfigEditor from '../../components/shared/PlanningConfigEditor.vue'
import { resolvePathWithBase } from '../../utils/paths'

const config = useConfigStore()

// Mode: 'synthesize' or 'dossiers'
const mode = ref<'synthesize' | 'dossiers'>('synthesize')

// Synthesize input mode: 'config' (planning.yaml) or 'flat' (legacy flag lists).
type SynthMode = 'config' | 'flat'
const synthMode = ref<SynthMode>('flat')
const planningConfigPath = ref('')

// ── Synthesize mode ──
const npcFiles = ref('')
const arcScores = ref('')
const summaries = ref('')
const context = ref('')
const output = ref('')
const extractDir = ref('')
const splitChapters = ref('# Chapter')
const noLog = ref(false)
const showAdvanced = ref(false)

// ── Build dossiers mode ──
const dossierSummaries = ref('')
const dossierDir = ref('')
const dossierExtractDir = ref('')
const dossierSplitChapters = ref('# Chapter')
const dossierSince = ref(0)

function loadFromConfig() {
  const v = config.values
  npcFiles.value = v.plan_npc || ''
  arcScores.value = v.plan_arc_scores || ''
  summaries.value = v.plan_summaries || v.summaries || ''
  context.value = v.plan_context || ''
  output.value = v.plan_output || v.planning_output || v.planning || ''
  extractDir.value = v.plan_extract_dir || ''
  splitChapters.value = v.plan_split_chapters || '# Chapter'

  dossierSummaries.value = v.plan_build_summaries || v.summaries || ''
  dossierDir.value = v.plan_dossier_dir || 'docs/npcs/'
  dossierExtractDir.value = v.plan_build_extract_dir || ''
  dossierSplitChapters.value = v.plan_build_split_chapters || '# Chapter'

  planningConfigPath.value = v.plan_config_path || ''
  // Persisted mode wins; default to 'config' if a yaml path is set,
  // else stay on 'flat' so legacy workspaces are unaffected.
  if (v.plan_synth_mode === 'config' || v.plan_synth_mode === 'flat') {
    synthMode.value = v.plan_synth_mode
  } else {
    synthMode.value = planningConfigPath.value ? 'config' : 'flat'
  }
}

// Persist synth-mode + planning-config path through the typed planning
// section so the choice survives a reload (mirrors PartyDocument).
let planPersistTimer: ReturnType<typeof setTimeout> | null = null
function schedulePlanPersist() {
  if (planPersistTimer) clearTimeout(planPersistTimer)
  planPersistTimer = setTimeout(() => {
    config.updateSection('planning', {
      synth_mode: synthMode.value,
      config_path: planningConfigPath.value,
    }).catch(() => { /* non-fatal — overlay still has the values */ })
  }, 500)
}
watch(synthMode, (m) => {
  config.values.plan_synth_mode = m
  schedulePlanPersist()
})
watch(planningConfigPath, (p) => {
  config.values.plan_config_path = p
  schedulePlanPersist()
})

const npcList = computed(() =>
  npcFiles.value.split('\n').map(l => l.trim()).filter(Boolean)
)
const arcScoreList = computed(() =>
  arcScores.value.split('\n').map(l => l.trim()).filter(Boolean)
)
const contextList = computed(() =>
  context.value.split('\n').map(l => l.trim()).filter(Boolean)
)

const synthReady = computed(() => {
  if (!output.value.trim()) return false
  return synthMode.value === 'config'
    ? !!planningConfigPath.value.trim()
    : npcList.value.length > 0
})

const dossierReady = computed(() =>
  !!(dossierSummaries.value.trim() && dossierDir.value.trim())
)

const synthParams = computed(() => {
  const base: Record<string, unknown> = {
    summaries: summaries.value,
    context: contextList.value,
    output: output.value,
    extract_dir: extractDir.value,
    split_chapters: splitChapters.value,
    no_log: noLog.value,
    model: config.model,
  }
  if (synthMode.value === 'config') {
    base.planning_config = planningConfigPath.value
    // Pass-through extras: NPCs with no arc score that aren't in the yaml.
    // planning.py rejects --planning-config + --arc-scores, so we drop those.
    base.npc = npcList.value
  } else {
    base.npc = npcList.value
    base.arc_scores = arcScoreList.value
  }
  return base
})

const synthHasSummaries = computed(() => !!summaries.value.trim())

const resolvedPlanningConfigPath = computed(() =>
  resolvePathWithBase(planningConfigPath.value, 'campaign')
)

const dossierParams = computed(() => ({
  summaries: dossierSummaries.value,
  dossier_dir: dossierDir.value,
  extract_dir: dossierExtractDir.value,
  split_chapters: dossierSplitChapters.value,
  since: dossierSince.value,
  no_log: noLog.value,
  model: config.model,
}))

watch(output, (newOutput) => {
  if (!extractDir.value && newOutput) {
    const idx = newOutput.lastIndexOf('/')
    const parent = idx >= 0 ? newOutput.slice(0, idx) : ''
    extractDir.value = parent ? `${parent}/planning_extractions` : 'planning_extractions'
  }
})

watch(dossierDir, (newDir) => {
  if (!dossierExtractDir.value && newDir) {
    const trimmed = newDir.replace(/\/$/, '')
    const idx = trimmed.lastIndexOf('/')
    const parent = idx >= 0 ? trimmed.slice(0, idx) : ''
    dossierExtractDir.value = parent ? `${parent}/planning_extractions` : 'planning_extractions'
  }
})

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
      <!-- Input mode toggle -->
      <div class="form-section mode-section">
        <label class="field-label">Input mode</label>
        <div class="mode-toggle-radio">
          <label class="radio-label">
            <input type="radio" value="config" v-model="synthMode" />
            Planning config YAML
            <span class="mode-hint">— preferred; binds each NPC/faction to its dossier + arc score with first-class trackless support</span>
          </label>
          <label class="radio-label">
            <input type="radio" value="flat" v-model="synthMode" />
            Flat file lists
            <span class="mode-hint">— legacy; one file per line for dossiers / arc scores</span>
          </label>
        </div>
      </div>

      <!-- Config mode: planning.yaml path + inline editor -->
      <div v-if="synthMode === 'config'" class="form-section">
        <PathField v-model="planningConfigPath" label="Planning config file" required resolve-base="campaign"
          help="Path to planning.yaml. Maps each NPC/faction to dossier + arc_score (use null for trackless)." />
        <PlanningConfigEditor :config-path="resolvedPlanningConfigPath" />
      </div>

      <!-- Flat mode: required NPC dossiers + optional arc scores -->
      <div v-if="synthMode === 'flat'" class="form-section">
        <MultiPathField v-model="npcFiles" label="NPC dossier files" required resolve-base="campaign"
          help="One per line. Per-NPC dossier files (docs/npcs/*.md)." />
      </div>

      <div v-if="synthMode === 'flat'" class="form-section">
        <MultiPathField v-model="arcScores" label="NPC/faction arc score files" resolve-base="campaign"
          help="One per line. Arc score mechanic files for villains and factions (e.g. grundar_score.md, kraken_echoes.md). Defines triggers and thresholds for threat arcs. Not for PC arc scores — those belong in Party Document." />
      </div>

      <!-- Config mode: optional pass-through NPC dossiers (no arc score, not in yaml) -->
      <div v-if="synthMode === 'config'" class="form-section">
        <MultiPathField v-model="npcFiles" label="Extra unbound NPC dossiers" resolve-base="campaign"
          help="One per line. Optional — pass-through dossiers for NPCs with no arc score that aren't in planning.yaml. Names must not overlap with yaml entries." />
      </div>

      <div class="form-section">
        <PathField v-model="summaries" label="Canonical timeline" resolve-base="campaign"
          help="The master narrative bible. Optional — omit to skip the Extract pass (synthesize from dossiers only)." />
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
        endpoint="/api/grounding/run/planning"
        :params="synthParams"
        :extract-dir="extractDir"
        :disabled="!synthReady"
        :extract-disabled="!synthHasSummaries"
        extract-label="1. Extract NPC info from summaries"
        synth-label="2. Synthesize planning.md"
      />
    </div>

    <!-- Build dossiers mode -->
    <div v-if="mode === 'dossiers'" class="form-grid">
      <div class="form-section">
        <PathField v-model="dossierSummaries" label="Canonical timeline" required resolve-base="campaign"
          help="The master narrative bible — per-NPC info is extracted from this." />
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
            <span class="field-help">When set, each session becomes one extract chunk.</span>
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
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
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

.mode-section { display: flex; flex-direction: column; gap: 6px; }
.mode-toggle-radio { display: flex; flex-direction: column; gap: 4px; }
.radio-label {
  font-size: 11px; color: var(--text-sub);
  display: flex; align-items: center; gap: 6px; cursor: pointer;
}
.radio-label input { accent-color: var(--mauve); }
.mode-hint { color: var(--text-muted); font-weight: 400; }

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
