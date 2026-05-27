<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiFetch, apiPost } from '../../api/client'

const router = useRouter()

interface StageStatus {
  status: 'ok' | 'warn' | 'bad' | 'cold'
  ago: string | null
  mtime: number | null
  count?: number
  count_done?: number
  count_total?: number
}

interface PipelineState {
  enhance: StageStatus
  extract: StageStatus
  plan: StageStatus
  narrate: StageStatus
}

interface Knobs {
  narrate_tokens?: number
  prose_mode?: boolean
  reflections?: boolean
  narration_genre?: string | null
  backend?: 'anthropic' | 'dgx'
}

interface RosterRow {
  index: number
  narrator: string
  scene: string
  tokens: number | null
  lifecycle: { extract: boolean; reviewed: boolean; narrate: boolean; scrub: boolean }
  applied_knobs: Knobs | null
  preview: string
}

interface ActivityEntry {
  ts: string
  stage: string
  rc: number | null
  scene?: number
  knobs?: Record<string, unknown>
  outputs?: string[]
}

const pipeline = ref<PipelineState | null>(null)
const roster = ref<RosterRow[]>([])
const activity = ref<ActivityEntry[]>([])
const loading = ref(true)
const assembling = ref(false)
const assembleResult = ref<{ ok: boolean; filename?: string; error?: string; scenes_included?: number } | null>(null)

async function loadAll() {
  loading.value = true
  try {
    const [p, r, a] = await Promise.all([
      apiFetch('/api/editor/pipeline-status'),
      apiFetch('/api/editor/scene-roster'),
      apiFetch('/api/editor/activity?limit=100'),
    ])
    pipeline.value = p
    roster.value = r.scenes ?? []
    activity.value = (a.entries ?? []).slice().reverse()  // newest first
  } catch (e) {
    console.error('Review load failed', e)
  } finally {
    loading.value = false
  }
}

// ── Blocking logic ────────────────────────────────────────────────
// A scene blocks assembly if it isn't narrated, or if its extraction
// is newer than its narration (the recorded knob sidecar lets us
// detect this without re-statting). We only check narration presence
// today; the "extraction newer" case would need a per-scene mtime
// fetch and is handled by the pipeline strip's overall warn state.
const blockingScenes = computed(() =>
  roster.value.filter(r => !r.lifecycle.narrate),
)
const blocked = computed(() => blockingScenes.value.length > 0)
const blockReason = computed(() => {
  if (!blocked.value) return ''
  const first = blockingScenes.value[0]
  if (blockingScenes.value.length === 1) {
    return `blocked: scene ${first.index} not narrated`
  }
  return `blocked: ${blockingScenes.value.length} scenes not narrated`
})

// ── Knobs rollup (footer) ─────────────────────────────────────────
const knobsRollup = computed(() => {
  const counts: Record<string, Record<string, number>> = {
    prose_mode: { on: 0, off: 0 },
    reflections: { on: 0, off: 0 },
    backend: {},
  }
  const genres = new Set<string>()
  for (const r of roster.value) {
    const k = r.applied_knobs
    if (!k) continue
    counts.prose_mode[k.prose_mode ? 'on' : 'off']++
    counts.reflections[k.reflections ? 'on' : 'off']++
    const b = k.backend ?? 'anthropic'
    counts.backend[b] = (counts.backend[b] ?? 0) + 1
    if (k.narration_genre) genres.add(k.narration_genre)
  }
  return { counts, genres: Array.from(genres) }
})

// ── Assemble ──────────────────────────────────────────────────────
async function doAssemble() {
  if (assembling.value || blocked.value) return
  assembling.value = true
  assembleResult.value = null
  try {
    const data = await apiPost('/api/editor/assemble')
    assembleResult.value = data
    if (data?.ok) await loadAll()
  } catch (e: any) {
    assembleResult.value = { ok: false, error: e?.message ?? 'assemble error' }
  } finally {
    assembling.value = false
  }
}

async function openAssembled() {
  try {
    await apiPost('/api/editor/open/assembled/0')
  } catch {
    /* ignored */
  }
}

function backToEditor() {
  router.push('/workflow/editor')
}

function fmtTs(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function stageLabel(stage: string): string {
  switch (stage) {
    case 'enhance': return '① Enhance'
    case 'extract': return '② Extract'
    case 'plan':    return '③ Plan'
    case 'narrate': return '④ Narrate'
    case 'scrub':   return '④½ Scrub'
    case 'scrub_all': return '④½ Scrub all'
    default: return stage
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="review-page">
    <header class="review-header">
      <button class="back-btn" @click="backToEditor" title="Back to editor">← Editor</button>
      <h1>Review &amp; Assemble</h1>
      <button class="reload-btn" @click="loadAll" :disabled="loading">{{ loading ? 'Loading…' : 'Reload' }}</button>
    </header>

    <!-- Pipeline readiness strip -->
    <section v-if="pipeline" class="ready-strip">
      <div class="ready-stage">
        <span class="ready-glyph">①</span>
        <span class="ready-name">Enhance</span>
        <span class="ready-dot" :class="pipeline.enhance.status"></span>
        <span class="ready-meta">{{ pipeline.enhance.ago ?? 'never' }}</span>
      </div>
      <div class="ready-stage">
        <span class="ready-glyph">②</span>
        <span class="ready-name">Extract</span>
        <span class="ready-dot" :class="pipeline.extract.status"></span>
        <span class="ready-meta">{{ pipeline.extract.count ?? 0 }} scenes · {{ pipeline.extract.ago ?? 'never' }}</span>
      </div>
      <div class="ready-stage">
        <span class="ready-glyph">③</span>
        <span class="ready-name">Plan</span>
        <span class="ready-dot" :class="pipeline.plan.status"></span>
        <span class="ready-meta">{{ pipeline.plan.ago ?? 'never' }}</span>
      </div>
      <div class="ready-stage">
        <span class="ready-glyph">④</span>
        <span class="ready-name">Narrate</span>
        <span class="ready-dot" :class="pipeline.narrate.status"></span>
        <span class="ready-meta">
          {{ pipeline.narrate.count_done ?? 0 }}/{{ pipeline.narrate.count_total ?? 0 }}
          · {{ pipeline.narrate.ago ?? 'never' }}
        </span>
      </div>
    </section>

    <!-- Two columns: activity + roster -->
    <div class="review-cols">
      <!-- Activity timeline -->
      <section class="col activity-col">
        <h2>Activity</h2>
        <div v-if="activity.length === 0" class="empty">No pipeline runs recorded yet.</div>
        <ul v-else class="activity-list">
          <li
            v-for="(a, i) in activity"
            :key="i"
            class="activity-item"
            :class="{ failed: a.rc !== 0 && a.rc !== null }"
          >
            <span class="activity-ts">{{ fmtTs(a.ts) }}</span>
            <span class="activity-stage">{{ stageLabel(a.stage) }}</span>
            <span v-if="a.scene !== undefined" class="activity-scene">scene {{ a.scene }}</span>
            <span class="activity-rc" :class="(a.rc === 0 ? 'ok' : 'bad')">
              rc {{ a.rc ?? '?' }}
            </span>
          </li>
        </ul>
      </section>

      <!-- Per-scene roster -->
      <section class="col roster-col">
        <h2>Scenes</h2>
        <div v-if="roster.length === 0" class="empty">No scenes loaded.</div>
        <div v-else class="roster-list">
          <div
            v-for="r in roster"
            :key="r.index"
            class="roster-row"
            :class="{ blocked: !r.lifecycle.narrate }"
          >
            <div class="roster-head">
              <span class="r-idx">Scene {{ r.index }}</span>
              <span class="r-narrator">{{ r.narrator || '—' }}</span>
              <span class="r-scene">{{ r.scene || '—' }}</span>
              <span v-if="r.tokens" class="r-tokens">~{{ r.tokens }} tok</span>
            </div>
            <div class="r-dots">
              <span class="dot" :class="{ ok: r.lifecycle.extract }">E</span>
              <span class="dot" :class="{ ok: r.lifecycle.reviewed }">R</span>
              <span class="dot" :class="{ ok: r.lifecycle.narrate }">N</span>
              <span class="dot" :class="{ ok: r.lifecycle.scrub }">S</span>
            </div>
            <div v-if="r.applied_knobs" class="r-chips">
              <span v-if="r.applied_knobs.prose_mode" class="chip">prose</span>
              <span v-if="r.applied_knobs.reflections" class="chip">reflections</span>
              <span v-if="r.applied_knobs.backend" class="chip">{{ r.applied_knobs.backend }}</span>
              <span v-if="r.applied_knobs.narration_genre" class="chip wide" :title="r.applied_knobs.narration_genre">
                genre
              </span>
            </div>
            <div v-if="r.preview" class="r-preview">{{ r.preview }}</div>
            <div v-if="!r.lifecycle.narrate" class="r-callout">Not narrated yet — Assemble is blocked.</div>
          </div>
        </div>
      </section>
    </div>

    <!-- Footer: knob rollup + Assemble action -->
    <footer class="review-footer">
      <div class="rollup">
        <span>prose: {{ knobsRollup.counts.prose_mode.on }}/{{ knobsRollup.counts.prose_mode.on + knobsRollup.counts.prose_mode.off }}</span>
        <span>reflections: {{ knobsRollup.counts.reflections.on }}/{{ knobsRollup.counts.reflections.on + knobsRollup.counts.reflections.off }}</span>
        <span>backends:
          <template v-for="(n, k) in knobsRollup.counts.backend" :key="k">{{ k }}={{ n }} </template>
          <template v-if="Object.keys(knobsRollup.counts.backend).length === 0">—</template>
        </span>
        <span v-if="knobsRollup.genres.length === 1">genre: {{ knobsRollup.genres[0] }}</span>
        <span v-else-if="knobsRollup.genres.length > 1">{{ knobsRollup.genres.length }} different genres ⚠</span>
      </div>

      <div class="footer-actions">
        <span v-if="blocked" class="block-reason">{{ blockReason }}</span>
        <span v-if="assembleResult && assembleResult.ok" class="ok-msg">Saved → {{ assembleResult.filename }} ({{ assembleResult.scenes_included }} scenes)</span>
        <span v-if="assembleResult && !assembleResult.ok" class="bad-msg">{{ assembleResult.error }}</span>
        <button
          class="btn-primary"
          :disabled="blocked || assembling"
          @click="doAssemble"
        >{{ assembling ? 'Assembling…' : 'Assemble Doc' }}</button>
        <button
          v-if="assembleResult && assembleResult.ok"
          class="btn-neutral btn-sm"
          @click="openAssembled"
        >Open in Typora</button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.review-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-base);
}

.review-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
}
.review-header h1 {
  font-size: 14px;
  font-weight: 700;
  color: var(--mauve);
}
.back-btn, .reload-btn {
  background: transparent;
  border: 1px solid var(--bg-surface1);
  color: var(--text-sub);
  padding: 4px 10px;
  border-radius: 3px;
  font-size: 11px;
  cursor: pointer;
}
.back-btn:hover, .reload-btn:hover { background: var(--bg-surface0); color: var(--text); }
.reload-btn { margin-left: auto; }

.ready-strip {
  display: flex;
  gap: 18px;
  padding: 10px 16px;
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
}
.ready-stage {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-sub);
}
.ready-glyph { font-weight: 700; color: var(--text-sub); }
.ready-name { font-weight: 600; }
.ready-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--bg-surface1);
}
.ready-dot.ok   { background: var(--green, #a6d189); }
.ready-dot.warn { background: var(--yellow, #e5c890); }
.ready-dot.bad  { background: var(--red, #e78284); }
.ready-meta { color: var(--text-muted); font-family: var(--mono); font-size: 10px; }

.review-cols {
  flex: 1;
  display: grid;
  grid-template-columns: 320px 1fr;
  overflow: hidden;
}
.col {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--bg-surface0);
}
.col:last-child { border-right: none; }
.col h2 {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  padding: 10px 14px;
  flex-shrink: 0;
}
.empty {
  padding: 14px;
  color: var(--text-muted);
  font-size: 11px;
}

/* Activity */
.activity-list {
  list-style: none;
  padding: 0 0 16px;
  margin: 0;
  overflow-y: auto;
}
.activity-item {
  display: grid;
  grid-template-columns: 90px 1fr auto auto;
  gap: 6px;
  padding: 5px 14px;
  font-size: 11px;
  border-top: 1px solid var(--bg-surface0);
  color: var(--text-sub);
}
.activity-item.failed { background: rgba(231, 130, 132, 0.08); }
.activity-ts { color: var(--text-muted); font-family: var(--mono); font-size: 10px; }
.activity-stage { font-weight: 600; }
.activity-scene { font-size: 10px; color: var(--text-muted); }
.activity-rc { font-size: 9px; font-family: var(--mono); padding: 1px 4px; border-radius: 2px; }
.activity-rc.ok  { background: #1e3a2a; color: var(--green); }
.activity-rc.bad { background: #3a1e1e; color: var(--red); }

/* Roster */
.roster-list {
  overflow-y: auto;
  padding: 0 14px 16px;
}
.roster-row {
  padding: 8px 0;
  border-top: 1px solid var(--bg-surface0);
}
.roster-row.blocked {
  background: rgba(231, 130, 132, 0.04);
  border-left: 3px solid var(--red, #e78284);
  padding-left: 8px;
}
.roster-head {
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
  font-size: 11px;
}
.r-idx { font-weight: 700; color: var(--text-muted); width: 56px; }
.r-narrator { font-weight: 700; }
.r-scene { color: var(--text-sub); }
.r-tokens { font-size: 10px; color: var(--text-muted); font-family: var(--mono); margin-left: auto; }
.r-dots {
  display: flex;
  gap: 3px;
  margin: 4px 0;
}
.r-dots .dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--bg-surface0);
  color: var(--text-muted);
  text-align: center;
  font-size: 8px;
  line-height: 14px;
  font-weight: 700;
}
.r-dots .dot.ok { background: var(--green, #a6d189); color: #0e1018; }

.r-chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin: 4px 0;
}
.chip {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .04em;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--bg-surface0);
  color: var(--text-sub);
}
.chip.wide { background: #2a2540; color: var(--mauve); }

.r-preview {
  font-size: 11px;
  color: var(--text-sub);
  margin-top: 4px;
  line-height: 1.4;
  opacity: 0.75;
}
.r-callout {
  font-size: 10px;
  color: var(--red);
  margin-top: 4px;
  font-weight: 600;
}

/* Footer */
.review-footer {
  background: var(--bg-mantle);
  border-top: 1px solid var(--bg-surface0);
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.rollup {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 10px;
  color: var(--text-muted);
}
.footer-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}
.block-reason {
  font-size: 11px;
  color: var(--red);
}
.ok-msg { font-size: 11px; color: var(--green); }
.bad-msg { font-size: 11px; color: var(--red); }
</style>
