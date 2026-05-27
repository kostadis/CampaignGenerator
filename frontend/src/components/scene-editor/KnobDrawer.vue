<script setup lang="ts">
import { computed } from 'vue'
import PathField from '../shared/PathField.vue'
import MultiPathField from '../shared/MultiPathField.vue'

const props = defineProps<{
  open: boolean
  // ── Paths ─────────────────────────────────────────────────
  session: string
  sessionSummary: string
  sceneExtractionsDir: string
  narrationDir: string
  outputDir: string
  party: string
  voiceDir: string
  examplesDir: string
  characters: string
  context: string
  // ── Stage knobs ───────────────────────────────────────────
  useBatch: boolean
  backend: 'anthropic' | 'dgx'
  narrateTokens: number
  proseMode: boolean
  reflections: boolean
  narrationGenre: string
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'update:session': [value: string]
  'update:sessionSummary': [value: string]
  'update:sceneExtractionsDir': [value: string]
  'update:narrationDir': [value: string]
  'update:outputDir': [value: string]
  'update:party': [value: string]
  'update:voiceDir': [value: string]
  'update:examplesDir': [value: string]
  'update:characters': [value: string]
  'update:context': [value: string]
  'update:useBatch': [value: boolean]
  'update:backend': [value: 'anthropic' | 'dgx']
  'update:narrateTokens': [value: number]
  'update:proseMode': [value: boolean]
  'update:reflections': [value: boolean]
  'update:narrationGenre': [value: string]
}>()

const ready = computed(() => !!(props.session?.trim() && props.sceneExtractionsDir?.trim()))
</script>

<template>
  <aside class="knob-drawer" :class="{ open }">
    <header class="drawer-header">
      <h2>Config</h2>
      <span class="ready-pill" :class="{ ok: ready }">
        {{ ready ? 'Ready' : 'Set required fields' }}
      </span>
      <button class="close-btn" @click="emit('update:open', false)" title="Close drawer">×</button>
    </header>

    <div class="drawer-body">
      <!-- Paths -->
      <section class="drawer-section">
        <h3>Paths</h3>
        <PathField
          :model-value="session"
          @update:model-value="emit('update:session', $event)"
          label="GMassistant recap file"
          required
          help="Stage 1 input (gm-assist.md)."
        />
        <PathField
          :model-value="sessionSummary"
          @update:model-value="emit('update:sessionSummary', $event)"
          label="Session summary file"
          help="Stage 1 output (session-summary.md)."
        />
        <PathField
          :model-value="sceneExtractionsDir"
          @update:model-value="emit('update:sceneExtractionsDir', $event)"
          label="Scene extractions dir"
          required
          help="Stage 2 output — NN_<slug>.md files."
        />
        <PathField
          :model-value="narrationDir"
          @update:model-value="emit('update:narrationDir', $event)"
          label="Narration dir"
          help="Stage 4 output — session_doc_scene_NN_*.md files."
        />
        <PathField
          :model-value="outputDir"
          @update:model-value="emit('update:outputDir', $event)"
          label="Output dir"
          help="Where the assembled doc is saved."
        />
        <PathField
          :model-value="party"
          @update:model-value="emit('update:party', $event)"
          label="Party document"
          help="party.md — backstory, personality, relationships."
        />
        <PathField
          :model-value="voiceDir"
          @update:model-value="emit('update:voiceDir', $event)"
          label="Voice files dir"
          help="Directory of {name}_voice.md files."
        />
        <PathField
          :model-value="examplesDir"
          @update:model-value="emit('update:examplesDir', $event)"
          label="Examples dir"
          help="Handcrafted .md style references for narration."
        />
        <div class="field">
          <label class="field-label">Characters</label>
          <input
            type="text"
            class="field-input"
            :value="characters"
            placeholder="Zalthir, Grygum, Daz, Thorin"
            @input="emit('update:characters', ($event.target as HTMLInputElement).value)"
          />
          <div class="field-help">Comma-separated narrator roster (used by Extract).</div>
        </div>
        <MultiPathField
          :model-value="context"
          @update:model-value="emit('update:context', $event)"
          label="Campaign context files"
          help="campaign_state.md, world_state.md — injected as campaign context."
        />
      </section>

      <!-- Stage 1 — Enhance -->
      <section class="drawer-section">
        <h3>① Enhance</h3>
        <label class="checkbox-row">
          <input
            type="checkbox"
            :checked="useBatch"
            @change="emit('update:useBatch', ($event.target as HTMLInputElement).checked)"
          />
          Use Anthropic Message Batches (50% off list price; replaces streaming with poll-progress)
        </label>
        <div class="field">
          <label class="field-label">Backend (also applies to Stage 2, Narrate, Scrub)</label>
          <div class="seg-toggle">
            <button
              class="seg-btn"
              :class="{ active: backend === 'anthropic' }"
              @click="emit('update:backend', 'anthropic')"
            >Anthropic</button>
            <button
              class="seg-btn"
              :class="{ active: backend === 'dgx' }"
              @click="emit('update:backend', 'dgx')"
            >DGX</button>
          </div>
          <div class="field-help">Stage 3 (Plan &amp; Check) always uses Anthropic — tool-use path.</div>
        </div>
      </section>

      <!-- Stage 2 — Extract -->
      <section class="drawer-section">
        <h3>② Extract</h3>
        <div class="field-help muted-block">
          Batch mode (toggle above) and Backend apply here. The Re-Extract button always forwards
          <code>--force</code> so prior per-scene files are snapshotted to <code>.prev</code> and
          rewritten.
        </div>
      </section>

      <!-- Stage 4 — Narrate -->
      <section class="drawer-section">
        <h3>④ Narrate</h3>
        <div class="field">
          <label class="field-label">Token limit</label>
          <input
            type="number"
            class="field-input"
            :value="narrateTokens"
            min="1000"
            step="500"
            @input="emit('update:narrateTokens', Number(($event.target as HTMLInputElement).value) || 0)"
          />
          <div class="field-help">Per-scene output cap. Override per-scene with <code>tokens: N</code> in the extraction file.</div>
        </div>
        <label class="checkbox-row">
          <input
            type="checkbox"
            :checked="proseMode"
            @change="emit('update:proseMode', ($event.target as HTMLInputElement).checked)"
          />
          Prose mode (strip mechanical language, GM framing)
        </label>
        <label class="checkbox-row">
          <input
            type="checkbox"
            :checked="reflections"
            @change="emit('update:reflections', ($event.target as HTMLInputElement).checked)"
          />
          Reflections (inject campaign history as memories)
        </label>
        <div class="field">
          <label class="field-label">Narration genre</label>
          <input
            type="text"
            class="field-input"
            :value="narrationGenre"
            placeholder='e.g. First-person comic-noir fantasy memoir'
            @input="emit('update:narrationGenre', ($event.target as HTMLInputElement).value)"
          />
          <div class="field-help">One-line genre directive injected into the Pass-5 prompt.</div>
        </div>
      </section>

      <!-- Stage 5 — Assemble -->
      <section class="drawer-section muted">
        <h3>⑤ Assemble</h3>
        <div class="field-help">No tunable knobs today. Polish toggle lands when the optional polish pass is wired in.</div>
      </section>
    </div>
  </aside>

  <div v-if="open" class="drawer-scrim" @click="emit('update:open', false)" />
</template>

<style scoped>
.knob-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 360px;
  background: var(--bg-mantle);
  border-left: 1px solid var(--bg-surface0);
  transform: translateX(100%);
  transition: transform .18s ease-out;
  z-index: 90;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.knob-drawer.open {
  transform: translateX(0);
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.35);
}

.drawer-scrim {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.18);
  z-index: 80;
}

.drawer-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--bg-surface0);
  flex-shrink: 0;
}
.drawer-header h2 {
  font-size: 13px;
  font-weight: 700;
  color: var(--mauve);
}
.ready-pill {
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .05em;
  padding: 2px 6px;
  border-radius: 3px;
  background: var(--bg-surface0);
  color: var(--text-muted);
  margin-left: auto;
}
.ready-pill.ok {
  background: #1e3a2a;
  color: var(--green);
}
.close-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
}
.close-btn:hover { color: var(--text); }

.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px 24px;
}

.drawer-section {
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface0);
}
.drawer-section:last-child {
  border-bottom: none;
}
.drawer-section h3 {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.drawer-section.muted h3 { color: var(--text-muted); opacity: 0.6; }
.muted-block {
  padding: 6px 8px;
  background: var(--bg-base);
  border-radius: 3px;
}

.field { margin-bottom: 10px; }
.field-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-sub);
  margin-bottom: 3px;
}
.field-input {
  width: 100%;
  padding: 6px 8px;
  border-radius: 4px;
  border: 1px solid var(--bg-surface1);
  background: var(--bg-base);
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  outline: none;
  box-sizing: border-box;
}
.field-input:focus { border-color: var(--mauve); }
.field-help {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
  line-height: 1.4;
}

.checkbox-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 11px;
  color: var(--text-sub);
  cursor: pointer;
  margin-bottom: 8px;
  line-height: 1.4;
}
.checkbox-row input { accent-color: var(--mauve); margin-top: 2px; }

.seg-toggle {
  display: inline-flex;
  border: 1px solid var(--bg-surface1);
  border-radius: 4px;
  overflow: hidden;
}
.seg-btn {
  padding: 4px 12px;
  font-size: 11px;
  font-weight: 600;
  background: var(--bg-base);
  color: var(--text-sub);
  border: none;
  cursor: pointer;
}
.seg-btn:not(:last-child) { border-right: 1px solid var(--bg-surface1); }
.seg-btn.active {
  background: var(--bg-surface0);
  color: var(--mauve);
}
</style>
