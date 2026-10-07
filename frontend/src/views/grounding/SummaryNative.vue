<script setup lang="ts">
import { ref, computed, watch, onMounted, type Ref } from 'vue'
import { apiFetch } from '../../api/client'
import { useConfigStore } from '../../stores/config'
import { useGroundingRun } from '../../composables/useGroundingRun'
import PathField from '../../components/shared/PathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

// summary_native (feature 031): grounding-doc drafts built straight from
// reviewed session summaries. This page invokes the `summary_native` CLI and
// reimplements none of it (FR-029). There is no promote button and no rulings
// editor: a draft is reviewed and promoted by hand, and the CLI-only paths
// (registry, canon, out-root) are set once in grounding.yaml, not per run.

const BASE = '/api/grounding/summary-native'
const SYNTH_ENDPOINT = '/api/grounding/summary-native/run/synth'
const DOCS = ['world_state', 'campaign_state', 'party', 'planning'] as const
type Doc = (typeof DOCS)[number]
// world_state and campaign_state are built from the checked notes (spec 033): Extract first, one prose
// call per section, no --parts and no --audit. party and planning keep the one-shot path.
const CHUNKED: readonly Doc[] = ['world_state', 'campaign_state']

const config = useConfigStore()

// ── Persisted fields (grounding.yaml summary_native) ────────────────────────
// Numeric inputs hold '' while a field is being retyped; that must not reach
// the strict schema, so the persisted view of a blank is `undefined` (dropped
// by JSON, leaving the stored value alone) or, for the range, an explicit null.
type Num = number | '' | null

const summariesDir = ref('')
const rangeSince = ref<Num>(null)
const rangeUntil = ref<Num>(null)
const dupThreshold = ref<Num>('')
const recentChapters = ref<Num>('')
const recurringMin = ref<Num>('')
const parts = ref<Num>('')

function persisted(r: Ref<Num>, nullable: boolean) {
  return computed<number | null | undefined>({
    get: () => (typeof r.value === 'number' ? r.value : nullable ? null : undefined),
    set: v => { r.value = v === undefined ? '' : v },
  })
}

useGroundingRun('summary_native', {
  summaries_dir: summariesDir,
  range_since: persisted(rangeSince, true),
  range_until: persisted(rangeUntil, true),
  dup_threshold: persisted(dupThreshold, false),
  recent_chapters: persisted(recentChapters, false),
  recurring_min: persisted(recurringMin, false),
  parts: persisted(parts, false),
})

// ── Per-run fields (not stored) ─────────────────────────────────────────────
const doc = ref<Doc>('world_state')
const worldStatePath = ref('')
const campaignStatePath = ref('')
const partyConfigPath = ref('')
const planningConfigPath = ref('')
const auditText = ref('')
const namesText = ref('')
const maxTokens = ref<Num>('')
const dumpOnly = ref(false)
const forceBuild = ref(false)
// Per-run, never persisted: replacing a reviewed draft must be a deliberate act each time.
const forceSynth = ref(false)
// Per run, never persisted and unchecked on every load (spec 033 FR-018b): write a code-built Key NPCs line
// for an NPC with no published dossier instead of refusing. world_state only.
const fallbackNpcLines = ref(false)
// Extract (per run, never persisted): a blank chunk size uses grounding.yaml summary_native.extract.chunk_chars.
const extractChunkChars = ref<Num>('')
const extractMaxTokens = ref<Num>('')
const extractDumpOnly = ref(false)
const forceExtract = ref(false)

const lines = (t: string) => t.split('\n').map(l => l.trim()).filter(Boolean)
const num = (n: Num) => (typeof n === 'number' ? n : undefined)

// ── Chapters / range picker ─────────────────────────────────────────────────
interface Chapters {
  present: number[]
  files: { chapter: number; path: string }[]
  duplicate_chapters: number[]
}
const chapters = ref<Chapters | null>(null)
const chaptersError = ref('')
let chaptersTimer: ReturnType<typeof setTimeout> | null = null

async function loadChapters() {
  chaptersError.value = ''
  chapters.value = null
  const dir = summariesDir.value.trim()
  if (!dir) return
  try {
    chapters.value = await apiFetch<Chapters>(
      `${BASE}/chapters?summaries_dir=${encodeURIComponent(dir)}`,
    )
  } catch (e) {
    chaptersError.value = e instanceof Error ? e.message : String(e)
  }
}

watch(summariesDir, () => {
  if (chaptersTimer) clearTimeout(chaptersTimer)
  chaptersTimer = setTimeout(loadChapters, 400)
})

// "All chapters" is a deliberate choice: it writes the first and last chapter
// into the range explicitly, so the run (and the stored config) names them.
function selectAll() {
  const present = chapters.value?.present ?? []
  if (!present.length) return
  rangeSince.value = present[0]
  rangeUntil.value = present[present.length - 1]
}

const rangeChosen = computed(
  () => typeof rangeSince.value === 'number' && typeof rangeUntil.value === 'number',
)
const rangeInverted = computed(
  () => rangeChosen.value && (rangeSince.value as number) > (rangeUntil.value as number),
)
const ready = computed(() => !!summariesDir.value.trim() && rangeChosen.value && !rangeInverted.value)

// ── Run params ──────────────────────────────────────────────────────────────
const baseParams = computed(() => ({
  summaries_dir: summariesDir.value.trim(),
  since: num(rangeSince.value),
  until: num(rangeUntil.value),
}))
const validateParams = computed(() => ({
  ...baseParams.value, dup_threshold: num(dupThreshold.value),
}))
const buildParams = computed(() => ({
  ...baseParams.value, dup_threshold: num(dupThreshold.value), force: forceBuild.value,
}))
const isChunked = computed(() => CHUNKED.includes(doc.value))
const extractParams = computed(() => ({
  ...baseParams.value,
  chunk_chars: num(extractChunkChars.value),
  max_tokens: num(extractMaxTokens.value),
  dump_only: extractDumpOnly.value,
  force: forceExtract.value,
}))
const synthParams = computed(() => isChunked.value
  ? {
      // The prose step takes its backend and model from grounding.yaml summary_native.prose, so the
      // page does not send the app-wide model for these two documents.
      ...baseParams.value,
      // world_state's Key NPCs selection (campaign_state has no such section and the server refuses these)
      ...(doc.value === 'world_state'
        ? {
            name: lines(namesText.value),
            recent_chapters: num(recentChapters.value),
            recurring_min: num(recurringMin.value),
            fallback_npc_lines: fallbackNpcLines.value,
          }
        : {}),
      max_tokens: num(maxTokens.value),
      dump_only: dumpOnly.value,
      force: forceSynth.value,
    }
  : {
      ...baseParams.value,
      world_state: worldStatePath.value.trim(),
      campaign_state: campaignStatePath.value.trim(),
      party_config: doc.value === 'party' ? partyConfigPath.value.trim() : '',
      planning_config: doc.value === 'planning' ? planningConfigPath.value.trim() : '',
      audit: lines(auditText.value),
      name: lines(namesText.value),
      recent_chapters: num(recentChapters.value),
      recurring_min: num(recurringMin.value),
      parts: num(parts.value),
      max_tokens: num(maxTokens.value),
      dump_only: dumpOnly.value,
      force: forceSynth.value,
      model: config.model || undefined,
    })

// ── Report and drafts ───────────────────────────────────────────────────────
interface Finding {
  file: string; line: number | null; code: string; message: string
  expected: string | null; found: string | null; blocking: boolean; in_range: boolean
}
interface Report {
  range: { since: number; until: number; present: number[]; gaps: number[] }
  files_scanned: number; files_in_range: number
  blocking_count: number; files_failing: number; non_blocking_count: number
  findings: Finding[]
  existing_corpus?: { state: string; [k: string]: unknown }
}
interface DraftRow { doc: string; path: string; status: 'draft' | 'incomplete' | 'report'; bytes: number }
interface ExtractChunk { index: number; chapters: string; status: string; kept: number; dropped: number; outlier: boolean }
interface ExtractState {
  present: boolean; complete: boolean; stale: boolean; stale_reason: string | null
  backend?: string; model?: string; chunk_chars?: number; absent_chapters?: number[]
  chunks: ExtractChunk[]
  totals: { chunks: number; checked: number; kept: number; dropped: number }
  outliers: string[]; drops_file: string | null
}

const report = ref<Report | null>(null)
const reportNote = ref('')
const drafts = ref<DraftRow[]>([])
const draftsNote = ref('')
const extractState = ref<ExtractState | null>(null)
// world_state's last build: words written against each prose section's budget.
interface BudgetRow { budget: number; words: number; over: boolean }
const worldBudgets = ref<Record<string, BudgetRow> | null>(null)
// Each chunked document's last annotate step (written by synth, and again by Annotate).
interface AnnotationCounts { later: number; since: number; unverified: number; removed: number; lines: number }
const annotations = ref<Record<string, AnnotationCounts>>({})
const docAnnotations = computed(() => annotations.value[doc.value] ?? null)
const budgetRows = computed(() => Object.entries(worldBudgets.value ?? {}))
const overBudget = computed(() => budgetRows.value.filter(([, r]) => r.over).length)

const duplicates = computed(() => report.value?.findings.filter(f => f.code === 'possible-duplicate') ?? [])
const otherFindings = computed(() => report.value?.findings.filter(f => f.code !== 'possible-duplicate') ?? [])

async function refreshOutputs() {
  report.value = null; reportNote.value = ''
  drafts.value = []; draftsNote.value = ''
  extractState.value = null
  worldBudgets.value = null
  annotations.value = {}
  if (!rangeChosen.value) return
  const q = `since=${rangeSince.value}&until=${rangeUntil.value}`
  try {
    const state = await apiFetch<{
      extract: ExtractState; world_budgets: Record<string, BudgetRow> | null
      annotations: Record<string, AnnotationCounts>
      missing_dossiers: MissingNpc[] | null; missing_dossiers_refused: boolean
    }>(`${BASE}/state?${q}`)
    extractState.value = state.extract
    worldBudgets.value = state.world_budgets
    annotations.value = state.annotations ?? {}
    // The latest world_state attempt's list, so a refusal is still shown after a reload.
    missingNpcs.value = state.missing_dossiers_refused ? (state.missing_dossiers ?? []) : []
  } catch {
    extractState.value = null // the Extract panel simply stays empty; the other outputs still load
  }
  try {
    report.value = await apiFetch<Report>(`${BASE}/report?${q}`)
  } catch (e) {
    reportNote.value = e instanceof Error && e.message.startsWith('API 404')
      ? 'No validation report for this range yet. Run Validate.'
      : (e instanceof Error ? e.message : String(e))
  }
  try {
    drafts.value = await apiFetch<DraftRow[]>(`${BASE}/drafts?${q}`)
    if (!drafts.value.length) draftsNote.value = 'No drafts for this range yet.'
  } catch (e) {
    draftsNote.value = e instanceof Error && e.message.startsWith('API 404')
      ? 'Nothing built for this range yet. Run Build.'
      : (e instanceof Error ? e.message : String(e))
  }
}

// The NPCs a refused world_state build named, parsed from the CLI's own message (one `  Name: state` line each).
interface MissingNpc { name: string; state: string }
const missingNpcs = ref<MissingNpc[]>([])
const MISSING_HEADER = /need a published, verified dossier/
const MISSING_LINE = /^ {2}(?!summary_native )(.+?): (not drafted|drafted, not verified|drafted, not published|failed verification.*|published for .+)$/
function parseMissingNpcs(output: string): MissingNpc[] {
  if (!MISSING_HEADER.test(output)) return []
  const out: MissingNpc[] = []
  for (const raw of output.split('\n')) {
    const m = MISSING_LINE.exec(raw.trimEnd())
    if (m) out.push({ name: m[1], state: m[2] })
  }
  return out
}

function onSynthDone(rc: number, output = '') {
  forceSynth.value = false
  missingNpcs.value = rc === 2 && doc.value === 'world_state' ? parseMissingNpcs(output) : []
  refreshOutputs()
}

watch(doc, () => { fallbackNpcLines.value = false })

const annotateDryParams = computed(() => ({ ...baseParams.value, dry_run: true }))
function onAnnotateDone() { refreshOutputs() }

function onExtractDone() {
  forceExtract.value = false
  refreshOutputs()
}

watch([rangeSince, rangeUntil], refreshOutputs)

onMounted(async () => {
  // useGroundingRun hydrates the refs on mount; give it a tick before reading.
  await (config.groundingConfig ?? config.refreshGrounding())
  setTimeout(() => { loadChapters(); refreshOutputs() }, 50)
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Summary-native</h2>
      <p class="subtitle">
        Build grounding-document drafts directly from reviewed session summaries &mdash; no extraction pass.
        Drafts are written for review; nothing here promotes one to the live document.
      </p>
    </div>

    <div class="form-grid">
      <!-- Input -->
      <div class="form-section">
        <PathField v-model="summariesDir" label="Summaries directory" required resolve-base="campaign"
          help="A directory of structured session summaries (*.md) whose filenames start with the chapter number." />
        <span v-if="chaptersError" class="field-error">{{ chaptersError }}</span>
      </div>

      <!-- Range -->
      <div class="form-section">
        <label class="field-label">Chapter range</label>
        <div v-if="chapters && chapters.present.length" class="range-row">
          <select class="field-input narrow" v-model="rangeSince" aria-label="First chapter">
            <option :value="null" disabled>first&hellip;</option>
            <option v-for="c in chapters.present" :key="c" :value="c">{{ c }}</option>
          </select>
          <span class="range-sep">to</span>
          <select class="field-input narrow" v-model="rangeUntil" aria-label="Last chapter">
            <option :value="null" disabled>last&hellip;</option>
            <option v-for="c in chapters.present" :key="c" :value="c">{{ c }}</option>
          </select>
          <button class="btn-neutral btn-sm" @click="selectAll">All chapters</button>
        </div>
        <span v-else class="field-help">
          {{ summariesDir.trim() ? 'No numbered summaries found in that directory.' : 'Set the summaries directory to list its chapters.' }}
        </span>
        <span v-if="chapters && chapters.duplicate_chapters.length" class="field-error">
          More than one file for chapter {{ chapters.duplicate_chapters.join(', ') }} &mdash; Validate will block until one is removed.
        </span>
        <span v-if="rangeInverted" class="field-error">The first chapter is after the last.</span>
        <span v-else-if="!rangeChosen" class="field-help">
          Choose a range explicitly. &ldquo;All chapters&rdquo; fills in the first and last chapter for you.
        </span>
      </div>

      <!-- 1. Validate -->
      <div class="form-section">
        <h3 class="step">1. Validate</h3>
        <div class="field">
          <label class="field-label">Possible-duplicate threshold</label>
          <input type="number" step="0.01" min="0" max="1" class="field-input narrow" v-model.number="dupThreshold" />
          <span class="field-help">Similarity ratio above which two entries are reported as possible duplicates. Blank uses the stored default.</span>
        </div>
        <RunPanel :endpoint="`${BASE}/run/validate`" :params="validateParams" :disabled="!ready"
          label="Validate" @done="refreshOutputs" />
      </div>

      <!-- 2. Build -->
      <div class="form-section">
        <h3 class="step">2. Build corpus</h3>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceBuild" /> Rebuild existing corpus (--force)
        </label>
        <RunPanel :endpoint="`${BASE}/run/build`" :params="buildParams" :disabled="!ready"
          label="Build" @done="refreshOutputs" />
      </div>

      <!-- 3. Extract -->
      <div class="form-section">
        <h3 class="step">3. Extract notes</h3>
        <span class="field-help">
          Reads the full summaries a few chapters at a time and writes notes, which code then checks:
          every citation must resolve inside its chunk, every quotation must be verbatim, every note must carry its tag.
          world_state and campaign_state are built from these notes. Notes that fail are dropped and listed in drops.md.
        </span>
        <div class="num-grid">
          <div class="field">
            <label class="field-label">Chunk size (characters)</label>
            <input type="number" min="1" class="field-input" v-model.number="extractChunkChars" />
            <span class="field-help">Whole chapters per call, up to this size. Blank uses the stored default.</span>
          </div>
          <div class="field">
            <label class="field-label">Max tokens</label>
            <input type="number" min="1" class="field-input" v-model.number="extractMaxTokens" />
            <span class="field-help">Per call. Blank uses the CLI default.</span>
          </div>
        </div>
        <label class="checkbox-label">
          <input type="checkbox" v-model="extractDumpOnly" /> Dump only &mdash; write the prompts and the manifest, make no model call
        </label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceExtract" /> Re-extract every chunk (--force)
        </label>
        <RunPanel :endpoint="`${BASE}/run/extract`" :params="extractParams" :disabled="!ready"
          label="Extract notes" @done="onExtractDone" />
        <div v-if="extractState && extractState.present" class="panel extract-state">
          <div class="counts">
            <span :class="extractState.complete ? 'ok' : 'bad'">
              {{ extractState.complete ? 'complete' : 'incomplete' }}
              ({{ extractState.totals.checked }} of {{ extractState.totals.chunks }} chunks checked)
            </span>
            <span>{{ extractState.totals.kept }} notes kept</span>
            <span>{{ extractState.totals.dropped }} dropped</span>
            <span v-if="extractState.model">{{ extractState.backend }} / {{ extractState.model }}</span>
            <span v-if="extractState.absent_chapters?.length">absent chapters: {{ extractState.absent_chapters.join(', ') }}</span>
          </div>
          <p v-if="extractState.stale" class="field-error">
            The notes are stale: {{ extractState.stale_reason }}
          </p>
          <p v-if="!extractState.complete" class="field-error">
            Some chunks have no checked notes. Run Extract again: only the missing chunks are extracted.
          </p>
          <table class="drafts chunks">
            <thead><tr><th>Chunk</th><th>Chapters</th><th>Status</th><th>Kept</th><th>Dropped</th><th></th></tr></thead>
            <tbody>
              <tr v-for="c in extractState.chunks" :key="c.index" :class="{ outlier: c.outlier }">
                <td>{{ c.index }}</td>
                <td>{{ c.chapters }}</td>
                <td :class="c.status === 'checked' ? 'ok' : 'bad'">{{ c.status }}</td>
                <td>{{ c.kept }}</td>
                <td>{{ c.dropped }}</td>
                <td><span v-if="c.outlier" class="bad">outlier: possible runaway call</span></td>
              </tr>
            </tbody>
          </table>
          <span v-if="extractState.drops_file" class="field-help">
            Every dropped note and its reason: <code>{{ extractState.drops_file }}</code>
          </span>
        </div>
      </div>

      <!-- 4. Synth -->
      <div class="form-section">
        <h3 class="step">4. Synthesize a draft</h3>
        <div class="field">
          <label class="field-label">Document</label>
          <select class="field-input narrow" v-model="doc">
            <option v-for="d in DOCS" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <span v-if="isChunked" class="field-help">
          Built from the checked notes: run Extract first. Code builds the timeline, completed list and NPC status table;
          the model writes each remaining section from the notes routed to it. The tracking audit is its own step.
          <template v-if="doc === 'world_state'">
            Key NPCs are rendered from the published NPC dossiers: the build refuses when a selected NPC has none.
          </template>
        </span>
        <PathField v-if="!isChunked" v-model="worldStatePath" label="World-state draft (context)" resolve-base="campaign"
          help="A GM-reviewed world_state draft to use as upstream context. Optional." />
        <PathField v-if="!isChunked" v-model="campaignStatePath" label="Campaign-state draft (context)" resolve-base="campaign"
          help="A GM-reviewed campaign_state draft to use as upstream context. Optional." />
        <PathField v-if="doc === 'party'" v-model="partyConfigPath" label="Party config" resolve-base="campaign"
          help="The party roster (sheets and backstories). Blank uses config/party.yaml." />
        <PathField v-if="doc === 'planning'" v-model="planningConfigPath" label="Planning config" resolve-base="campaign"
          help="Tracked NPCs, factions and arc scores. Blank uses config/planning.yaml; none means no arc scores." />
        <div v-if="!isChunked" class="field">
          <label class="field-label">Audit files</label>
          <textarea class="field-textarea" v-model="auditText" rows="3"
            placeholder="One path per line. Blank uses the Campaign State page's tracking lists." />
          <span class="field-help">Tracking, planning or module files treated as questions to answer from the summaries.</span>
        </div>
        <div v-if="!isChunked || doc === 'world_state'" class="field">
          <label class="field-label">Named subjects</label>
          <textarea class="field-textarea" v-model="namesText" rows="2"
            placeholder="One subject per line &mdash; force-includes these dossiers" />
          <span v-if="doc === 'world_state'" class="field-help">Force-includes these global NPCs in Key NPCs.</span>
        </div>
        <div class="num-grid">
          <div v-if="!isChunked || doc === 'world_state'" class="field">
            <label class="field-label">Recent chapters</label>
            <input type="number" min="0" class="field-input" v-model.number="recentChapters" />
            <span class="field-help">Counted back from the range end; 0 = all.<template v-if="doc === 'world_state'"> Picks the Key NPCs.</template></span>
          </div>
          <div v-if="!isChunked || doc === 'world_state'" class="field">
            <label class="field-label">Recurring minimum</label>
            <input type="number" min="0" class="field-input" v-model.number="recurringMin" />
            <span class="field-help">Observations that make an entity recurring.</span>
          </div>
          <div v-if="!isChunked" class="field">
            <label class="field-label">Parts</label>
            <input type="number" min="0" class="field-input" v-model.number="parts" />
            <span class="field-help">Split the outline into N calls; 0 = one call.</span>
          </div>
          <div class="field">
            <label class="field-label">Max tokens</label>
            <input type="number" min="1" class="field-input" v-model.number="maxTokens" />
            <span class="field-help">Per call. Blank uses the CLI default.</span>
          </div>
        </div>
        <label class="checkbox-label">
          <input type="checkbox" v-model="dumpOnly" /> Dump only &mdash; write the prompts and run record, make no model call
        </label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceSynth" /> Replace existing reviewed draft (--force)
        </label>
        <label v-if="doc === 'world_state'" class="checkbox-label">
          <input type="checkbox" v-model="fallbackNpcLines" /> Write fallback lines for NPCs without a published dossier
        </label>
        <span v-if="doc === 'world_state' && fallbackNpcLines" class="field-help">
          This run only. Each such NPC gets a line built by code from its checked notes and marked
          &ldquo;(no published dossier &mdash; from checked notes)&rdquo;. Not saved.
        </span>
        <RunPanel :endpoint="`${SYNTH_ENDPOINT}/${doc}`" :params="synthParams" :disabled="!ready"
          :label="`Synthesize ${doc}`" :selection-service="isChunked ? undefined : 'grounding'"
          selection-doc="summary_native" :selection-can-override="true" @done="onSynthDone" />
        <div v-if="doc === 'world_state' && missingNpcs.length" class="panel missing-npcs">
          <div class="counts">
            <span class="bad">Build refused: {{ missingNpcs.length }} selected NPC(s) have no published, verified dossier</span>
          </div>
          <table class="drafts">
            <thead><tr><th>NPC</th><th>Dossier state</th></tr></thead>
            <tbody>
              <tr v-for="n in missingNpcs" :key="n.name">
                <td>{{ n.name }}</td>
                <td class="bad">{{ n.state }}</td>
              </tr>
            </tbody>
          </table>
          <span class="field-help">
            Draft, verify and publish them on the <RouterLink to="/npcs/dossiers">NPC dossiers page</RouterLink>,
            then build again &mdash; or tick &ldquo;Write fallback lines&rdquo; above for this run.
          </span>
        </div>
        <div v-if="doc === 'world_state' && budgetRows.length" class="panel budgets">
          <div class="counts">
            <span>Word budgets (last world_state build; citations not counted)</span>
            <span :class="overBudget ? 'bad' : 'ok'">
              {{ overBudget ? `${overBudget} over budget` : 'all within budget' }}
            </span>
          </div>
          <table class="drafts">
            <thead><tr><th>Section</th><th>Words</th><th>Budget</th><th></th></tr></thead>
            <tbody>
              <tr v-for="[name, r] in budgetRows" :key="name">
                <td>{{ name }}</td>
                <td>{{ r.words }}</td>
                <td>{{ r.budget }}</td>
                <td :class="r.over ? 'bad' : 'ok'">{{ r.over ? 'OVER (kept whole, not truncated)' : 'ok' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 5. Annotate -->
      <div v-if="isChunked" class="form-section">
        <h3 class="step">5. Annotate the {{ doc }} draft</h3>
        <span class="field-help">
          Deterministic: no model is called and no line is reworded. Where a newer checked note, a mentioned NPC's later status,
          another section, a non-verbatim quotation or an unresolved citation bears on a line, the evidence is appended under it
          (<code>&#9888; later:</code>, <code>&#8505; since:</code>, <code>&#9888; unverified:</code>); a player character listed as a
          companion is removed. Synthesize already does this; run it again after publishing a dossier or editing a summary.
          Key NPCs and the code-built sections are never annotated.
        </span>
        <div v-if="docAnnotations" class="panel annotations">
          <div class="counts">
            <span>Last annotate step:</span>
            <span>{{ docAnnotations.later }} later</span>
            <span>{{ docAnnotations.since }} since</span>
            <span :class="docAnnotations.unverified ? 'bad' : ''">{{ docAnnotations.unverified }} unverified</span>
            <span>{{ docAnnotations.removed }} removed</span>
            <span>on {{ docAnnotations.lines }} lines</span>
          </div>
          <span class="field-help">Every hit: <code>annotations.md</code> (listed under Drafts).</span>
        </div>
        <RunPanel :endpoint="`${BASE}/run/annotate/${doc}`" :params="annotateDryParams" :disabled="!ready"
          :label="`Preview annotations for ${doc} (dry run)`" />
        <RunPanel :endpoint="`${BASE}/run/annotate/${doc}`" :params="baseParams" :disabled="!ready"
          :label="`Annotate ${doc}`" @done="onAnnotateDone" />
      </div>

      <!-- 6. Compare -->
      <div class="form-section">
        <h3 class="step">6. Compare with the live document</h3>
        <span class="field-help">Diffs the {{ doc }} draft against docs/{{ doc }}.md. Read-only.</span>
        <RunPanel :endpoint="`${BASE}/run/compare/${doc}`" :params="baseParams" :disabled="!ready"
          :label="`Compare ${doc}`" />
      </div>

      <!-- Report -->
      <div class="form-section">
        <h3 class="step">Validation report</h3>
        <span v-if="reportNote" class="field-help">{{ reportNote }}</span>
        <div v-if="report" class="panel">
          <div class="counts">
            <span>{{ report.files_in_range }} of {{ report.files_scanned }} files in range</span>
            <span :class="report.blocking_count ? 'bad' : 'ok'">{{ report.blocking_count }} blocking</span>
            <span>{{ report.non_blocking_count }} advisory</span>
            <span v-if="report.range.gaps.length">gaps: {{ report.range.gaps.join(', ') }}</span>
            <span v-if="report.existing_corpus">corpus: {{ report.existing_corpus.state }}</span>
          </div>
          <div v-if="duplicates.length" class="findings">
            <h4>Possible duplicates ({{ duplicates.length }})</h4>
            <p class="field-help">Review only. Rule on a pair in canon.yaml to silence it; nothing is merged for you.</p>
            <ul>
              <li v-for="(f, i) in duplicates" :key="'d' + i">
                <code>{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></code> {{ f.message }}
              </li>
            </ul>
          </div>
          <div v-if="otherFindings.length" class="findings">
            <h4>Findings ({{ otherFindings.length }})</h4>
            <ul>
              <li v-for="(f, i) in otherFindings" :key="'f' + i" :class="{ bad: f.blocking }">
                <strong>{{ f.blocking ? 'BLOCK' : 'note' }}</strong>
                <code>{{ f.code }}</code>
                <code>{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></code>
                {{ f.message }}
              </li>
            </ul>
          </div>
        </div>
      </div>

      <!-- Drafts -->
      <div class="form-section">
        <h3 class="step">Drafts</h3>
        <span v-if="draftsNote" class="field-help">{{ draftsNote }}</span>
        <table v-if="drafts.length" class="drafts">
          <thead><tr><th>Document</th><th>Status</th><th>Size</th><th>Path</th></tr></thead>
          <tbody>
            <tr v-for="d in drafts" :key="d.path">
              <td>{{ d.doc }}</td>
              <td :class="d.status === 'incomplete' ? 'bad' : d.status === 'draft' ? 'ok' : ''">{{ d.status }}</td>
              <td>{{ d.bytes }} B</td>
              <td><code>{{ d.path }}</code></td>
            </tr>
          </tbody>
        </table>
        <span v-if="drafts.length" class="field-help">
          An incomplete draft failed its outline check and is not promotable. A report is read-only evidence
          (drops.md lists every dropped note; npc_status_report.md the merged, unresolved and player-character names;
          canon_events_timeline.md every event in order; annotations.md every annotation and removal; key_npcs_report.md
          who was selected for Key NPCs and what code replaced; reference/*.md every checked note by subject, which each
          world_state section and campaign_state's thread sections point to).
          Review a draft in your editor; promotion is manual.
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section { padding-bottom: 12px; border-bottom: 1px solid var(--bg-surface0); }
.form-section:last-child { border-bottom: none; }
.step { font-size: 12px; font-weight: 700; color: var(--text); margin-bottom: 8px; }

.field { margin-bottom: 10px; }
.field-label { display: block; font-size: 11px; font-weight: 600; color: var(--text-sub); margin-bottom: 3px; }
.field-input, .field-textarea {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box;
}
.field-input.narrow { width: 160px; }
.field-textarea { resize: vertical; }
.field-input:focus, .field-textarea:focus { border-color: var(--mauve); }
.field-help { display: block; font-size: 10px; color: var(--text-muted); margin-top: 3px; }
.field-error { display: block; font-size: 11px; color: var(--red); margin-top: 4px; }

.range-row { display: flex; align-items: center; gap: 8px; }
.range-sep { font-size: 11px; color: var(--text-muted); }
.num-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 0 16px; }

.checkbox-label { font-size: 11px; color: var(--text-sub); display: flex; align-items: center; gap: 6px; cursor: pointer; margin-bottom: 8px; }
.checkbox-label input { accent-color: var(--mauve); }

.panel { padding: 10px; background: var(--bg-mantle); border-radius: 4px; font-size: 11px; color: var(--text-sub); }
.counts { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 8px; }
.findings h4 { font-size: 11px; font-weight: 700; color: var(--text); margin: 8px 0 4px; }
.findings ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 3px; }
.findings code, .drafts code { font-family: var(--mono); font-size: 10px; margin-right: 6px; }
.ok { color: var(--green); }
.bad { color: var(--red); }

.drafts { border-collapse: collapse; font-size: 11px; color: var(--text-sub); margin-top: 6px; }
.drafts th, .drafts td { text-align: left; padding: 3px 14px 3px 0; }
.drafts th { font-weight: 600; color: var(--text); }
.extract-state, .budgets, .missing-npcs, .annotations { margin-top: 10px; }
.chunks tr.outlier td { background: color-mix(in srgb, var(--red) 14%, transparent); }
</style>
