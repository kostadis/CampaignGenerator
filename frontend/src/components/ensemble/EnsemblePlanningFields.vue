<script setup lang="ts">
import { computed } from 'vue'
import PathField from '../shared/PathField.vue'
import MultiPathField from '../shared/MultiPathField.vue'
import PlanningConfigEditor from '../shared/PlanningConfigEditor.vue'
import { resolvePathWithBase } from '../../utils/paths'

// Mirrors PlanningDocument.vue's synthMode toggle, minus the parts that
// don't apply to ensemble (no --summaries extract pass, no build-dossiers
// mode — see the plan for why). Both modes' file lists are optional
// *overrides*: left blank, the server auto-detects config/planning.yaml and
// auto-globs docs/ensemble/merged_dossiers/npc_*.md, exactly as it does
// today; filling one in takes precedence (same npc or _planning_npc_passthrough(...)
// logic already in server/routers/ensemble.py).
type SynthMode = 'config' | 'flat'

const synthMode = defineModel<SynthMode>('synthMode', { required: true })
const configPath = defineModel<string>('configPath', { required: true })
const npcFiles = defineModel<string>('npcFiles', { required: true })
const arcScores = defineModel<string>('arcScores', { required: true })
const contextFiles = defineModel<string>('contextFiles', { required: true })

const resolvedConfigPath = computed(() => resolvePathWithBase(configPath.value, 'campaign'))
</script>

<template>
  <div class="planning-fields">
    <div class="mode-toggle-radio">
      <label class="radio-label">
        <input type="radio" value="config" v-model="synthMode" />
        Planning config YAML
        <span class="mode-hint">— tracked (arc-scored) NPCs/factions; a human-curated subset</span>
      </label>
      <label class="radio-label">
        <input type="radio" value="flat" v-model="synthMode" />
        Explicit dossier list
        <span class="mode-hint">— override the auto-detected NPC/arc-score files directly</span>
      </label>
    </div>

    <div v-if="synthMode === 'config'">
      <PathField v-model="configPath" label="Planning config file" resolve-base="campaign"
        help="Path to planning.yaml. Blank = auto-detect config/planning.yaml or planning.yaml at the campaign root." />
      <PlanningConfigEditor v-if="configPath.trim()" :config-path="resolvedConfigPath" />
      <MultiPathField v-model="npcFiles" label="Extra unbound NPC dossiers (optional override)" resolve-base="campaign"
        help="One per line. Leave blank to auto-include every docs/ensemble/merged_dossiers/npc_*.md not already bound above — names must not overlap with planning.yaml entries." />
    </div>

    <div v-else>
      <p class="warn-hint">
        ⚠ The server still auto-detects <code>config/planning.yaml</code> /
        <code>planning.yaml</code> if either exists on disk, even with this
        mode selected — there's currently no way to force-skip it. Arc
        scores entered here are only used when no such file is found. This
        mode is really for campaigns with no planning.yaml yet.
      </p>
      <MultiPathField v-model="npcFiles" label="NPC dossier files (optional override)" resolve-base="campaign"
        help="One per line. Leave blank to auto-include every docs/ensemble/merged_dossiers/npc_*.md." />
      <MultiPathField v-model="arcScores" label="Arc score files" resolve-base="campaign"
        help="One per line. Threat arc-score mechanic files for villains/factions. Not for PC arc scores — those belong in Party Document." />
    </div>

    <MultiPathField v-model="contextFiles" label="Context files" resolve-base="campaign"
      help="Optional world context (factions, locations, etc.)." />
  </div>
</template>

<style scoped>
.planning-fields {
  margin: 4px 0 12px;
  padding: 10px 12px;
  background: var(--bg-mantle);
  border-radius: 4px;
  border: 1px solid var(--bg-surface0);
}
.mode-toggle-radio { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.radio-label {
  font-size: 11px; color: var(--text-sub);
  display: flex; align-items: center; gap: 6px; cursor: pointer;
}
.radio-label input { accent-color: var(--mauve); }
.mode-hint { color: var(--text-muted); font-weight: 400; }
.warn-hint { font-size: 11px; color: var(--peach); margin-bottom: 8px; max-width: 64ch; }
</style>
