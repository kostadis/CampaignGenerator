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
  context: string
  // ── Stage knobs ───────────────────────────────────────────
  backend: 'anthropic' | 'dgx' | 'openrouter' | 'claude-code'
  dgxEndpoint: string
  dgxModel: string
  openrouterModel: string
  narrateTokens: number
  proseMode: boolean
  reflections: boolean
  // The genre rulebook is a FILE now (#276 fix 2): this is a path, and
  // `genreInfo` is the server's read-only summary of what it resolved to.
  genreFile: string
  genreInfo?: {
    path: string | null
    exists: boolean
    lines: number
    chars: number
    preview: string
    sha256: string
    error: string | null
  } | null
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
  'update:context': [value: string]
  'update:backend': [value: 'anthropic' | 'dgx' | 'openrouter' | 'claude-code']
  'update:dgxEndpoint': [value: string]
  'update:dgxModel': [value: string]
  'update:openrouterModel': [value: string]
  'update:narrateTokens': [value: number]
  'update:proseMode': [value: boolean]
  'update:reflections': [value: boolean]
  'update:genreFile': [value: string]
}>()

const ready = computed(() => !!(props.session?.trim() && props.sceneExtractionsDir?.trim()))

// Three display states, all of which the GM needs to tell apart at a glance:
// no rulebook configured, one configured but not found on disk, and one
// resolved. The middle state is the dangerous one — Pass 5 runs with NO genre
// directive at all, silently, because the rulebook is no longer mirrored into
// session_doc.yaml as a fallback.
const genreState = computed<'unset' | 'missing' | 'ok'>(() => {
  if (!props.genreFile?.trim()) return 'unset'
  return props.genreInfo?.exists ? 'ok' : 'missing'
})
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
          <div class="field-help">
            The narrating cast comes from <code>party.yaml</code>, and each
            character names its own voice and example files there. Typing the
            roster a second time here is what let it go stale against itself.
          </div>
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
        <!-- 005-ui-batch-selection, FR-011: the bespoke batch checkbox that
             used to live here is retired — batch (Anthropic Message
             Batches: 50% off list price; replaces streaming with
             poll-progress) is now set app-wide from the sidebar and
             inherited here, same as every other service. -->
        <div class="field">
          <label class="field-label">Backend (also applies to Stage 2, Narrate)</label>
          <div class="seg-toggle">
            <button
              class="seg-btn"
              :class="{ active: backend === 'anthropic' }"
              @click="emit('update:backend', 'anthropic')"
            >Anthropic</button>
            <button
              class="seg-btn"
              :class="{ active: backend === 'claude-code' }"
              @click="emit('update:backend', 'claude-code')"
              title="Route generation through the Claude Code CLI — bills your Pro/Max subscription, not the metered API"
            >Subscription</button>
            <button
              class="seg-btn"
              :class="{ active: backend === 'dgx' }"
              @click="emit('update:backend', 'dgx')"
            >DGX</button>
            <button
              class="seg-btn"
              :class="{ active: backend === 'openrouter' }"
              @click="emit('update:backend', 'openrouter')"
            >OpenRouter</button>
          </div>
          <div class="field-help">Stage 3 (Plan &amp; Check) honors Anthropic or Subscription; DGX falls back to the Anthropic API.</div>
        </div>
        <div v-if="backend === 'dgx'" class="field">
          <label class="field-label">DGX endpoint</label>
          <input
            type="text"
            class="field-input"
            :value="dgxEndpoint"
            placeholder="http://192.168.1.147:8001/v1"
            @input="emit('update:dgxEndpoint', ($event.target as HTMLInputElement).value)"
          />
          <div class="field-help">OpenAI-compatible URL. Use the Spark's IP, not a hostname — WSL2 can't resolve <code>spark</code>. Blank → <code>http://localhost:8000</code>.</div>
        </div>
        <div v-if="backend === 'dgx'" class="field">
          <label class="field-label">DGX model</label>
          <input
            type="text"
            class="field-input"
            :value="dgxModel"
            placeholder="Qwen/Qwen2.5-14B-Instruct-AWQ"
            @input="emit('update:dgxModel', ($event.target as HTMLInputElement).value)"
          />
          <div class="field-help">Model name the endpoint serves. Blank → the runtime default.</div>
        </div>
        <div v-if="backend === 'openrouter'" class="field">
          <label class="field-label">OpenRouter model</label>
          <input
            type="text"
            class="field-input"
            :value="openrouterModel"
            placeholder="anthropic/claude-sonnet-4"
            @input="emit('update:openrouterModel', ($event.target as HTMLInputElement).value)"
          />
          <div class="field-help">OpenRouter model id. Blank → the runtime default. Uses OpenRouter's fixed base URL — no endpoint to configure.</div>
        </div>
      </section>

      <!-- Stage 2 — Extract -->
      <section class="drawer-section">
        <h3>② Extract</h3>
        <div class="field-help muted-block">
          Batch (set app-wide via the sidebar) and Backend apply here. The Re-Extract button always forwards
          <code>--force</code> so prior per-scene files are snapshotted to <code>.prev</code> and
          rewritten.
        </div>
      </section>

      <!-- Stage 4 — Narrate -->
      <section class="drawer-section">
        <h3>④ Narrate</h3>
        <!-- 005-ui-batch-selection, FR-010: narrate's handoff-threaded scenes
             can only submit as sequential one-item batches — same 50%
             discount as any other stage, but not the parallel speedup batch
             usually gives (data-model.md's "Batch capability map" classifies
             session_doc as `degraded`). Stated unconditionally rather than
             gated on a live toggle: T029 retired the bespoke Enhance
             checkbox this used to key off of, and batch here is now
             inherited from the resolved selection (app-wide, or this
             editor's own per-backend override) rather than a value this
             page holds locally. -->
        <div class="degraded-note">
          If batch is enabled — app-wide, or for this editor's active
          backend — narration runs one scene at a time: same discount,
          slower than a normal run.
        </div>
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
          <label class="field-label">Narration genre file</label>
          <input
            class="field-input"
            type="text"
            :value="genreFile"
            placeholder="voice/_genre.md"
            @input="emit('update:genreFile', ($event.target as HTMLInputElement).value)"
          />
          <div v-if="genreState === 'ok'" class="genre-status ok">
            ✓ resolved · {{ genreInfo?.lines }} lines · {{ genreInfo?.chars?.toLocaleString() }} chars
          </div>
          <div v-else-if="genreState === 'missing'" class="genre-status bad">
            ✗ {{ genreInfo?.error || 'not found' }}
          </div>
          <div v-else class="genre-status muted">
            No genre file — Pass 5 runs with no genre directive.
          </div>
          <pre v-if="genreState === 'ok' && genreInfo?.preview" class="genre-preview">{{ genreInfo.preview }}</pre>
          <div class="field-help">
            The genre/register rulebook injected into the Pass-5 prompt, read from
            this file at render time. It is the single source of truth — edit the
            file itself to change it; this drawer only points at it.
          </div>
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
.degraded-note {
  padding: 6px 8px;
  margin-bottom: 10px;
  border-radius: 3px;
  font-size: 11px;
  line-height: 1.4;
  color: var(--text);
  background: color-mix(in srgb, var(--peach, #f9b874) 14%, transparent);
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
.field-textarea {
  resize: vertical;
  line-height: 1.5;
}
.field-help {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
  line-height: 1.4;
}
.genre-status {
  font-size: 10px;
  margin-top: 3px;
  line-height: 1.4;
}
.genre-status.ok { color: var(--green, #a6e3a1); }
.genre-status.bad { color: var(--red, #f38ba8); }
.genre-status.muted { color: var(--text-muted); }
.genre-preview {
  margin: 4px 0 0;
  padding: 6px 8px;
  max-height: 140px;
  overflow: auto;
  border-radius: 4px;
  border: 1px solid var(--bg-surface1);
  background: var(--bg-base);
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
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
