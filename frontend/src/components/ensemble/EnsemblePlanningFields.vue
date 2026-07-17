<script setup lang="ts">
import { computed } from 'vue'
import PathField from '../shared/PathField.vue'
import MultiPathField from '../shared/MultiPathField.vue'
import PlanningConfigEditor from '../shared/PlanningConfigEditor.vue'
import { resolvePathWithBase } from '../../utils/paths'

// Mirrors PlanningDocument.vue's synthMode toggle, minus the parts that
// don't apply to ensemble (no --summaries extract pass, no build-dossiers
// mode — see the plan for why). Both modes' file lists are optional
// *overrides*; filling one in takes precedence over auto-detection. Left
// blank: 'config' mode auto-detects config/planning.yaml and passes through
// every NPC dossier not already bound in it (npc or _planning_npc_passthrough(...)
// in server/routers/ensemble.py); 'flat' mode skips planning.yaml entirely
// and auto-globs docs/ensemble/merged_dossiers/npc_*.md instead
// (_all_planning_npc_files(...), same file).
type SynthMode = 'config' | 'flat'

const synthMode = defineModel<SynthMode>('synthMode', { required: true })
const configPath = defineModel<string>('configPath', { required: true })
const npcFiles = defineModel<string>('npcFiles', { required: true })
const arcScores = defineModel<string>('arcScores', { required: true })
const contextFiles = defineModel<string>('contextFiles', { required: true })
// depth/forceInclude are overrides on top of the model's own scene-relevance
// curation (planning.py --depth / --force-include) — 'scene' (default) is an
// exact no-op server-side, so leaving these alone reproduces prior behavior.
const depth = defineModel<'scene' | 'full'>('depth', { required: true })
const forceInclude = defineModel<string>('forceInclude', { required: true })

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
      <p class="mode-hint">
        Skips <code>config/planning.yaml</code> / <code>planning.yaml</code>
        entirely, even if one exists on disk — use this to synthesize from a
        raw dossier list without a planning-config binding.
      </p>
      <MultiPathField v-model="npcFiles" label="NPC dossier files (optional override)" resolve-base="campaign"
        help="One per line. Leave blank to auto-include every docs/ensemble/merged_dossiers/npc_*.md." />
      <MultiPathField v-model="arcScores" label="Arc score files" resolve-base="campaign"
        help="One per line. Threat arc-score mechanic files for villains/factions. Not for PC arc scores — those belong in Party Document." />
    </div>

    <MultiPathField v-model="contextFiles" label="Context files" resolve-base="campaign"
      help="Optional world context (factions, locations, etc.)." />

    <div class="mode-toggle-radio">
      <label class="radio-label">
        <input type="radio" value="scene" v-model="depth" />
        Scene-focused (default)
        <span class="mode-hint">— the model curates NPC/faction coverage down to what's relevant right now</span>
      </label>
      <label class="radio-label">
        <input type="radio" value="full" v-model="depth" />
        Comprehensive
        <span class="mode-hint">— render every NPC/faction you supplied, not just the scene-relevant ones</span>
      </label>
    </div>

    <div class="force-include-field">
      <label class="field-label">Force-include NPCs</label>
      <textarea
        class="field-textarea"
        v-model="forceInclude"
        rows="2"
        placeholder="One NPC name per line"
        spellcheck="false"
      />
      <div class="field-help">
        Guarantees a subsection for specific NPCs the model might otherwise drop under
        scene-focused curation — for the occasional one you know matters. Names, not file paths.
      </div>
    </div>
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

.force-include-field { margin-top: 10px; }
.field-label { display: block; font-size: 11px; font-weight: 600; color: var(--text-sub); margin-bottom: 3px; }
.field-textarea {
  width: 100%;
  padding: 6px 8px;
  border-radius: 4px;
  border: 1px solid var(--bg-surface1);
  background: var(--bg-base);
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  outline: none;
  resize: vertical;
  line-height: 1.6;
  transition: border-color .1s;
}
.field-textarea:focus { border-color: var(--mauve); }
.field-help { font-size: 10px; color: var(--text-muted); margin-top: 2px; line-height: 1.4; }
</style>
