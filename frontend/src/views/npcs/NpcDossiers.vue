<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { apiFetch } from '../../api/client'
import { useConfigStore } from '../../stores/config'
import { useGroundingRun } from '../../composables/useGroundingRun'
import PathField from '../../components/shared/PathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'
import ReviewLauncher from '../../components/ReviewLauncher.vue'

// NPC dossiers (spec 032, US5). This page only mechanises `summary_native npc-*`
// runs with explicit arguments (Principle IX): every file it shows is read-only,
// and nothing here edits an authored file, a draft or a ruling. Draft and publish
// need a deliberately chosen selection (Principle X), so neither radio group
// starts selected. The corpus paths and the chapter range are the ones the
// Summary-native page uses (grounding.yaml summary_native); this page's own knobs
// live in <config>/npc_dossiers.yaml.

const BASE = '/api/npc-dossiers'
const BACKENDS = ['anthropic', 'dgx', 'openrouter', 'claude-code', 'codex-cli'] as const
const MODES = ['chunked', 'one-shot'] as const
const SOURCES = ['summary_native', 'hand-built'] as const

const config = useConfigStore()

type Num = number | '' | null

// ── Shared input (grounding.yaml summary_native) ────────────────────────────
const summariesDir = ref('')
const rangeSince = ref<Num>(null)
const rangeUntil = ref<Num>(null)

useGroundingRun('summary_native', {
  summaries_dir: summariesDir,
  range_since: computed<number | null>({
    get: () => (typeof rangeSince.value === 'number' ? rangeSince.value : null),
    set: v => { rangeSince.value = v },
  }),
  range_until: computed<number | null>({
    get: () => (typeof rangeUntil.value === 'number' ? rangeUntil.value : null),
    set: v => { rangeUntil.value = v },
  }),
})

const num = (n: Num) => (typeof n === 'number' ? n : undefined)
const lines = (t: string) => t.split('\n').map(l => l.trim()).filter(Boolean)

// ── Chapters / range picker ─────────────────────────────────────────────────
interface Chapters { present: number[]; files: { chapter: number; path: string }[]; duplicate_chapters: number[] }
const chapters = ref<Chapters | null>(null)
const chaptersError = ref('')
let chaptersTimer: ReturnType<typeof setTimeout> | null = null

async function loadChapters() {
  chaptersError.value = ''
  chapters.value = null
  const dir = summariesDir.value.trim()
  if (!dir) return
  try {
    const c = await apiFetch<Chapters>(`${BASE}/chapters?summaries_dir=${encodeURIComponent(dir)}`)
    chapters.value = Array.isArray(c?.present) ? c : null
  } catch (e) {
    chaptersError.value = e instanceof Error ? e.message : String(e)
  }
}
watch(summariesDir, () => {
  if (chaptersTimer) clearTimeout(chaptersTimer)
  chaptersTimer = setTimeout(loadChapters, 400)
})

// "All chapters" is a deliberate choice: it writes the first and last chapter in.
function selectAll() {
  const present = chapters.value?.present ?? []
  if (!present.length) return
  rangeSince.value = present[0]
  rangeUntil.value = present[present.length - 1]
}
const rangeChosen = computed(() => typeof rangeSince.value === 'number' && typeof rangeUntil.value === 'number')
const rangeInverted = computed(() => rangeChosen.value && (rangeSince.value as number) > (rangeUntil.value as number))
const ready = computed(() => !!summariesDir.value.trim() && rangeChosen.value && !rangeInverted.value)

const baseParams = computed(() => ({
  summaries_dir: summariesDir.value.trim(),
  since: num(rangeSince.value),
  until: num(rangeUntil.value),
}))

// ── This service's config (npc_dossiers.yaml) ───────────────────────────────
interface DraftBlock { backend: string; model: string; mode: string; chunk_chars: number }
interface NpcConfig {
  npc_root: string; recent_chapters: number; recurring_min: number; max_tokens: number
  selection: Record<string, unknown>; draft: DraftBlock
}
const npcConfig = ref<NpcConfig | null>(null)
const configNote = ref('')

const backend = ref('')
const model = ref('')
const mode = ref('')
const chunkChars = ref<Num>('')
const maxTokens = ref<Num>('')
const recentChapters = ref<Num>('')
const recurringMin = ref<Num>('')

async function loadConfig() {
  configNote.value = ''
  try {
    const c = await apiFetch<NpcConfig>(`${BASE}/config`)
    if (!c || !c.draft) return
    npcConfig.value = c
    // The selection override, when set, beats the draft block on the server.
    const sel = (c.selection ?? {}) as { backend?: string; model?: string }
    backend.value = sel.backend || c.draft.backend
    model.value = sel.model || c.draft.model
    mode.value = c.draft.mode
    chunkChars.value = c.draft.chunk_chars
    maxTokens.value = c.max_tokens
    recentChapters.value = c.recent_chapters
    recurringMin.value = c.recurring_min
  } catch (e) {
    configNote.value = e instanceof Error ? e.message : String(e)
  }
}

// ── State (read from disk only) ─────────────────────────────────────────────
interface NpcRow {
  stem: string; subject: string; global: boolean; exclusion: string | null
  n_entries: number; n_scenes: number; n_moments: number; first_seen: number; last_seen: number
  draft: 'none' | 'drafted' | 'incomplete' | 'stale'
  published: boolean; verify: 'none' | 'pass' | 'fail'
  authored: boolean; composed: boolean
  manual_dropped: { n: number; text: string }[]
}
interface State {
  range: string; linked: boolean; link_stale: boolean
  warnings: { ambiguous: number; generic_unruled: number }; npcs: NpcRow[]
}
interface Finding { code: string; form?: string; subject?: string; ruling?: string | null; message: string; locations?: string[] }

const state = ref<State | null>(null)
const stateNote = ref('')
const findings = ref<Finding[]>([])
const reportNote = ref('')
const picked = ref<string[]>([])

const npcs = computed(() => state.value?.npcs ?? [])
const pickedSubjects = computed(() =>
  npcs.value.filter(n => picked.value.includes(n.stem)).map(n => n.subject))
const warningCount = computed(() =>
  (state.value?.warnings.ambiguous ?? 0) + (state.value?.warnings.generic_unruled ?? 0))
interface SchedulerStatus { present: boolean; run_id?: string; status: string
  counts: { cached: number; completed: number; unfinished: number; failed: number }
  endpoints?: Array<{ id: string; state: string; active?: number; limit?: number; reason?: string }>
  outcomes?: Record<string, { category?: string; code?: string; message?: string }> }
const draftScheduler = ref<SchedulerStatus | null>(null)
const verifyScheduler = ref<SchedulerStatus | null>(null)

async function refresh() {
  state.value = null; stateNote.value = ''
  findings.value = []; reportNote.value = ''
  if (!rangeChosen.value) return
  const q = `since=${rangeSince.value}&until=${rangeUntil.value}`
  try {
    const s = await apiFetch<State>(`${BASE}/state?${q}`)
    state.value = s && Array.isArray(s.npcs) ? s : null
    if (state.value && !state.value.linked) stateNote.value = 'Not linked for this range yet. Run Link.'
  } catch (e) {
    stateNote.value = e instanceof Error ? e.message : String(e)
  }
  if (!state.value?.linked) return
  try {
    const r = await apiFetch<{ findings: Finding[] }>(`${BASE}/report/link?${q}`)
    findings.value = r?.findings ?? []
  } catch (e) {
    reportNote.value = e instanceof Error ? e.message : String(e)
  }
  picked.value = picked.value.filter(s => npcs.value.some(n => n.stem === s))
  try { draftScheduler.value = await apiFetch<SchedulerStatus>(`${BASE}/status/draft?${q}`) } catch { draftScheduler.value = null }
  try { verifyScheduler.value = await apiFetch<SchedulerStatus>(`${BASE}/status/verify?${q}`) } catch { verifyScheduler.value = null }
}
watch([rangeSince, rangeUntil], refresh)

// ── 2. Link ─────────────────────────────────────────────────────────────────
const forceLink = ref(false)
const linkParams = computed(() => ({ ...baseParams.value, force: forceLink.value }))
function onLinkDone() { forceLink.value = false; refresh() }

// ── 3. Draft ────────────────────────────────────────────────────────────────
// '' = nothing chosen yet, and the Draft button stays disabled until it is.
const draftSelect = ref<'' | 'all' | 'narrowed'>('')
const draftNames = ref('')
const dumpOnly = ref(false)
const forceDraft = ref(false)
const draftEndpointsText = ref('')
const draftParallel = ref<Num>('')
const draftResume = ref(false)
const draftResumeId = ref('')
const draftReady = computed(() => ready.value && draftSelect.value !== '')
const narrowedByName = computed(() => lines(draftNames.value).length > 0)
// With names, thresholds are sent only when asked for: the CLI drafts the union of both.
const alsoByThreshold = ref(false)
const sendThresholds = computed(() =>
  draftSelect.value === 'narrowed' && (!narrowedByName.value || alsoByThreshold.value))
const draftParams = computed(() => ({
  ...baseParams.value,
  select: draftSelect.value,
  name: draftSelect.value === 'narrowed' ? lines(draftNames.value) : [],
  recent_chapters: sendThresholds.value ? num(recentChapters.value) : undefined,
  recurring_min: sendThresholds.value ? num(recurringMin.value) : undefined,
  backend: backend.value || undefined,
  model: model.value.trim() || undefined,
  mode: mode.value || undefined,
  chunk_chars: num(chunkChars.value),
  max_tokens: num(maxTokens.value),
  dump_only: dumpOnly.value,
  force: forceDraft.value,
  endpoints: lines(draftEndpointsText.value),
  parallel: num(draftParallel.value),
  ...(draftResume.value ? { resume: draftResumeId.value.trim() } : {}),
}))
function onDraftDone() { forceDraft.value = false; refresh() }

// ── 5. Verify ───────────────────────────────────────────────────────────────
const verifyParallel = ref<Num>('')
const verifyResume = ref(false)
const verifyResumeId = ref('')
const verifyParams = computed(() => ({ ...baseParams.value, name: pickedSubjects.value, parallel: num(verifyParallel.value),
  ...(verifyResume.value ? { resume: verifyResumeId.value.trim() } : {}) }))

// ── 6. Compose ──────────────────────────────────────────────────────────────
const composeParams = computed(() => ({ ...baseParams.value, name: pickedSubjects.value }))
const initParams = computed(() => ({ ...baseParams.value, init: pickedSubjects.value }))

// ── 7. Publish ──────────────────────────────────────────────────────────────
const publishSelect = ref<'' | 'named' | 'all' | 'authored_all'>('')
const publishSource = ref('')
// Per-run, never persisted: publishing over a failed check must be deliberate each time.
const forcePublish = ref(false)
const publishReady = computed(() =>
  ready.value && (publishSelect.value === 'all' || publishSelect.value === 'authored_all'
    || (publishSelect.value === 'named' && pickedSubjects.value.length > 0)))
const publishParams = computed(() => ({
  ...baseParams.value,
  select: publishSelect.value,
  name: publishSelect.value === 'named' ? pickedSubjects.value : [],
  source: publishSource.value,
  force: forcePublish.value,
}))
function onPublishDone() { forcePublish.value = false; refresh() }

// ── Read-only file viewer ───────────────────────────────────────────────────
const viewer = ref<{ title: string; text: string } | null>(null)
const viewerNote = ref('')
const VIEW_KINDS = [
  ['evidence', 'Evidence'], ['draft', 'Draft'], ['gm', 'GM'], ['published', 'Published'],
] as const

async function view(row: NpcRow, kind: string, label: string) {
  viewerNote.value = ''
  viewer.value = null
  const q = `since=${rangeSince.value}&until=${rangeUntil.value}&kind=${kind}&stem=${encodeURIComponent(row.stem)}`
  try {
    const f = await apiFetch<{ path: string; text: string }>(`${BASE}/file?${q}`)
    viewer.value = { title: `${row.subject} — ${label} (${f.path})`, text: f.text }
  } catch (e) {
    viewerNote.value = e instanceof Error ? e.message : String(e)
  }
}
async function viewVerify(row: NpcRow) {
  viewerNote.value = ''
  viewer.value = null
  try {
    const r = await apiFetch<{ markdown: string }>(
      `${BASE}/report/verify/${encodeURIComponent(row.stem)}?since=${rangeSince.value}&until=${rangeUntil.value}`)
    viewer.value = { title: `${row.subject} — verification`, text: r.markdown }
  } catch (e) {
    viewerNote.value = e instanceof Error ? e.message : String(e)
  }
}

function togglePickAll(on: boolean) {
  picked.value = on ? npcs.value.map(n => n.stem) : []
}

onMounted(async () => {
  await (config.groundingConfig ?? config.refreshGrounding())
  await loadConfig()
  setTimeout(() => { loadChapters(); refresh() }, 50)
})
</script>

<template>
  <ReviewLauncher context="npc" :selected="pickedSubjects" />
  <div class="page">
    <div class="page-header">
      <h2>NPC dossiers</h2>
      <p class="subtitle">
        Per-NPC dossiers built from reviewed session summaries: link the evidence, draft, verify, compose the GM
        edition, then publish. This page runs the <code>summary_native npc-*</code> commands; it shows files
        read-only and never edits an authored file, a draft or a ruling.
      </p>
    </div>

    <div class="form-grid">
      <!-- 1. Input and range -->
      <div class="form-section">
        <h3 class="step">1. Summaries and chapter range</h3>
        <PathField v-model="summariesDir" label="Summaries directory" required resolve-base="campaign"
          help="Shared with the Summary-native page (grounding.yaml). Filenames start with the chapter number." />
        <span v-if="chaptersError" class="field-error">{{ chaptersError }}</span>
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
        <span v-if="rangeInverted" class="field-error">The first chapter is after the last.</span>
        <span v-else-if="!rangeChosen" class="field-help">
          Choose a range explicitly. &ldquo;All chapters&rdquo; fills in the first and last chapter for you.
        </span>
        <span class="field-help">
          Needs a built corpus for this range (Summary-native: Validate, then Build).
        </span>
      </div>

      <!-- 2. Link -->
      <div class="form-section" data-section="link">
        <h3 class="step">2. Link evidence</h3>
        <div class="badges">
          <span v-if="state && state.linked && !warningCount" class="badge ok">linked, nothing withheld</span>
          <span v-if="warningCount" class="badge warn" data-testid="link-warning">
            {{ state?.warnings.ambiguous }} ambiguous, {{ state?.warnings.generic_unruled }} generic (unruled) name forms withheld
          </span>
          <span v-if="state?.link_stale" class="badge bad">link is stale &mdash; run Link with &ldquo;Rewrite&rdquo;</span>
          <span v-if="state && !state.linked" class="badge muted">not linked</span>
        </div>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceLink" /> Rewrite existing evidence (--force)
        </label>
        <RunPanel :endpoint="`${BASE}/run/link`" :params="linkParams" :disabled="!ready" label="Link" @done="onLinkDone" />
        <span v-if="reportNote" class="field-help">{{ reportNote }}</span>
        <table v-if="findings.length" class="grid" data-testid="link-report">
          <thead><tr><th>Finding</th><th>Form / subject</th><th>Ruling</th><th>Message</th></tr></thead>
          <tbody>
            <tr v-for="(f, i) in findings" :key="i">
              <td><code>{{ f.code }}</code></td>
              <td>{{ f.form ?? f.subject }}</td>
              <td>{{ f.ruling ?? '' }}</td>
              <td>{{ f.message }}</td>
            </tr>
          </tbody>
        </table>
        <span v-if="findings.length" class="field-help">
          Withheld forms are never linked. Generic forms are ruled <code>safe</code> or <code>never</code> in canon.yaml,
          by hand; ambiguous forms are fixed in the summaries.
        </span>
      </div>

      <!-- 3. Draft -->
      <div class="form-section" data-section="draft">
        <h3 class="step">3. Draft</h3>
        <fieldset class="choice">
          <legend class="field-label">Which NPCs (required)</legend>
          <label class="checkbox-label">
            <input type="radio" value="all" v-model="draftSelect" name="draft-select" /> Every global NPC with evidence in range (--all)
          </label>
          <label class="checkbox-label">
            <input type="radio" value="narrowed" v-model="draftSelect" name="draft-select" /> Narrowed
          </label>
        </fieldset>
        <div v-if="draftSelect === 'narrowed'" class="narrow-block">
          <div class="field">
            <label class="field-label">Named NPCs</label>
            <textarea class="field-textarea" v-model="draftNames" rows="2"
              placeholder="One name per line. Leave blank to narrow by recent chapters and recurrence only." />
          </div>
          <label v-if="narrowedByName" class="checkbox-label">
            <input type="checkbox" v-model="alsoByThreshold" /> Also draft every NPC that meets the thresholds below
          </label>
          <div v-if="sendThresholds" class="num-grid">
            <div class="field">
              <label class="field-label">Recent chapters</label>
              <input type="number" min="0" class="field-input" v-model.number="recentChapters" />
              <span class="field-help">Seen in the last N chapters of the range; 0 = all.</span>
            </div>
            <div class="field">
              <label class="field-label">Recurring minimum</label>
              <input type="number" min="0" class="field-input" v-model.number="recurringMin" />
              <span class="field-help">At least N entries.</span>
            </div>
          </div>
          <span class="field-help">
            <template v-if="narrowedByName && !alsoByThreshold">Drafts exactly the named NPCs.</template>
            <template v-else-if="narrowedByName">Drafts the named NPCs and every NPC that is recent or recurring.</template>
            <template v-else>Drafts every global NPC that is recent or recurring.</template>
          </span>
        </div>
        <div class="num-grid">
          <div class="field">
            <label class="field-label">Backend</label>
            <select class="field-input" v-model="backend">
              <option v-for="b in BACKENDS" :key="b" :value="b">{{ b }}</option>
            </select>
          </div>
          <div class="field">
            <label class="field-label">Model</label>
            <input class="field-input" v-model="model" />
          </div>
          <div class="field">
            <label class="field-label">Mode</label>
            <select class="field-input" v-model="mode">
              <option v-for="m in MODES" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
          <div class="field">
            <label class="field-label">Chunk size (chars)</label>
            <input type="number" min="1" class="field-input" v-model.number="chunkChars" />
          </div>
          <div class="field">
            <label class="field-label">Max tokens</label>
            <input type="number" min="1" class="field-input" v-model.number="maxTokens" />
          </div>
        </div>
        <span class="field-help">
          Backend, model, mode and sizes start from npc_dossiers.yaml. The sidebar backend does not apply to this page.
          <template v-if="configNote"> {{ configNote }}</template>
        </span>
        <label class="checkbox-label">
          <input type="checkbox" v-model="dumpOnly" /> Dump only &mdash; write the prompts and record, make no model call
        </label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceDraft" /> Re-draft even when unchanged (--force)
        </label>
        <div class="num-grid"><div class="field"><label class="field-label">Workers per endpoint</label><input type="number" min="1" class="field-input" v-model.number="draftParallel" /><span class="field-help">Blank resolves from the selected model.</span></div></div>
        <div class="field"><label class="field-label">DGX endpoints</label><textarea class="field-textarea" v-model="draftEndpointsText" rows="2" placeholder="One URL per line; dgx backend only" /></div>
        <label class="checkbox-label"><input type="checkbox" v-model="draftResume" /> Resume an interrupted draft</label>
        <div v-if="draftResume" class="field"><label class="field-label">Run ID (optional)</label><input class="field-input" v-model="draftResumeId" placeholder="sole compatible run when blank" /></div>
        <span v-if="draftSelect === ''" class="field-help">Choose which NPCs to draft to enable the button.</span>
        <RunPanel :endpoint="`${BASE}/run/draft`" :params="draftParams" :disabled="!draftReady"
          :label="draftResume ? 'Resume draft' : 'Draft'" @done="onDraftDone" />
        <div v-if="draftScheduler?.present" class="field-help">Last draft {{ draftScheduler.run_id }}: {{ draftScheduler.status }} — {{ draftScheduler.counts.completed + draftScheduler.counts.cached }} complete, {{ draftScheduler.counts.unfinished }} unfinished, {{ draftScheduler.counts.failed }} failed.<div v-for="endpoint in draftScheduler.endpoints ?? []" :key="endpoint.id">{{ endpoint.id }}: {{ endpoint.state }} · {{ endpoint.active ?? 0 }}/{{ endpoint.limit ?? '?' }} active <template v-if="endpoint.reason">· {{ endpoint.reason }}</template></div><div v-for="(outcome, item) in draftScheduler.outcomes ?? {}" :key="item" class="bad">{{ item }}: {{ outcome.category }} {{ outcome.code }} {{ outcome.message }}</div></div>
      </div>

      <!-- 4. State table -->
      <div class="form-section" data-section="state">
        <h3 class="step">4. NPCs in this range</h3>
        <span v-if="stateNote" class="field-help">{{ stateNote }}</span>
        <table v-if="npcs.length" class="grid" data-testid="npc-state">
          <thead>
            <tr>
              <th><input type="checkbox" aria-label="Select all"
                :checked="picked.length === npcs.length" @change="togglePickAll(($event.target as HTMLInputElement).checked)" /></th>
              <th>NPC</th><th>Entries</th><th>Scenes</th><th>Moments</th><th>Seen</th>
              <th>Draft</th><th>Verify</th><th>Dropped edits</th><th>Authored</th><th>GM</th><th>Published</th><th>View</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="n in npcs" :key="n.stem" :class="{ dim: !n.global }">
              <td><input type="checkbox" :value="n.stem" v-model="picked" :disabled="!n.global" :aria-label="`Select ${n.subject}`" /></td>
              <td>{{ n.subject }}<span v-if="!n.global" class="field-help"> not global: {{ n.exclusion }}</span></td>
              <td>{{ n.n_entries }}</td><td>{{ n.n_scenes }}</td><td>{{ n.n_moments }}</td>
              <td>{{ n.first_seen }}&ndash;{{ n.last_seen }}</td>
              <td :class="n.draft === 'drafted' ? 'ok' : n.draft === 'none' ? '' : 'warn-text'">{{ n.draft }}</td>
              <td :class="n.verify === 'pass' ? 'ok' : n.verify === 'fail' ? 'bad' : ''">{{ n.verify }}</td>
              <td>
                <span v-if="n.manual_dropped.length" class="bad" :title="n.manual_dropped.map(d => `[manual ${d.n}] ${d.text}`).join('\n')">
                  {{ n.manual_dropped.map(d => d.n).join(', ') }}
                </span>
              </td>
              <td>{{ n.authored ? 'yes' : '' }}</td>
              <td>{{ n.composed ? 'yes' : '' }}</td>
              <td>{{ n.published ? 'yes' : '' }}</td>
              <td class="views">
                <button v-for="[k, l] in VIEW_KINDS" :key="k" class="link-btn" @click="view(n, k, l)">{{ l }}</button>
                <button class="link-btn" @click="viewVerify(n)">Verify</button>
              </td>
            </tr>
          </tbody>
        </table>
        <span v-if="npcs.length" class="field-help">
          Tick NPCs to name them in Verify, Compose and Publish below. Authored files, rulings and drafts are edited
          in files, the CLI or chat, never here.
        </span>
        <span v-if="viewerNote" class="field-error">{{ viewerNote }}</span>
        <div v-if="viewer" class="viewer">
          <div class="viewer-title">{{ viewer.title }} <button class="link-btn" @click="viewer = null">close</button></div>
          <pre>{{ viewer.text }}</pre>
        </div>
      </div>

      <!-- 5. Verify -->
      <div class="form-section" data-section="verify">
        <h3 class="step">5. Verify</h3>
        <span class="field-help">
          Deterministic, no model, edits nothing. {{ pickedSubjects.length ? `Checks ${pickedSubjects.length} ticked NPC(s).` : 'With none ticked, checks every drafted NPC in range.' }}
          A failing draft exits 5.
        </span>
        <div class="num-grid"><div class="field"><label class="field-label">Local workers</label><input type="number" min="1" class="field-input" v-model.number="verifyParallel" /><span class="field-help">Verification is deterministic and local.</span></div></div>
        <label class="checkbox-label"><input type="checkbox" v-model="verifyResume" /> Resume verification</label>
        <div v-if="verifyResume" class="field"><label class="field-label">Run ID (optional)</label><input class="field-input" v-model="verifyResumeId" placeholder="sole compatible run when blank" /></div>
        <RunPanel :endpoint="`${BASE}/run/verify`" :params="verifyParams" :disabled="!ready" :label="verifyResume ? 'Resume verification' : 'Verify'" @done="refresh" />
        <div v-if="verifyScheduler?.present" class="field-help">Last verification {{ verifyScheduler.run_id }}: {{ verifyScheduler.status }} — {{ verifyScheduler.counts.completed + verifyScheduler.counts.cached }} complete, {{ verifyScheduler.counts.unfinished }} unfinished, {{ verifyScheduler.counts.failed }} failed.<div v-for="(outcome, item) in verifyScheduler.outcomes ?? {}" :key="item" class="bad">{{ item }}: {{ outcome.category }} {{ outcome.code }} {{ outcome.message }}</div></div>
      </div>

      <!-- 6. Compose -->
      <div class="form-section" data-section="compose">
        <h3 class="step">6. Compose GM dossiers</h3>
        <span class="field-help">
          Rebuilds the GM edition (draft + Secrets) with no model call; use it after a Secrets-only edit.
          {{ pickedSubjects.length ? `Composes ${pickedSubjects.length} ticked NPC(s).` : 'With none ticked, composes every NPC with a draft or an authored file.' }}
        </span>
        <RunPanel :endpoint="`${BASE}/run/compose`" :params="composeParams" :disabled="!ready" label="Compose" @done="refresh" />
        <span class="field-help">
          Create an empty authored file for each ticked NPC (--init). It refuses per name if one exists and composes
          nothing; you then write it by hand.
        </span>
        <RunPanel :endpoint="`${BASE}/run/compose`" :params="initParams"
          :disabled="!ready || !pickedSubjects.length" label="Create authored file" @done="refresh" />
      </div>

      <!-- 7. Publish -->
      <div class="form-section" data-section="publish">
        <h3 class="step">7. Publish to docs/npcs/</h3>
        <fieldset class="choice">
          <legend class="field-label">What to publish (required)</legend>
          <label class="checkbox-label">
            <input type="radio" value="named" v-model="publishSelect" name="publish-select" />
            The ticked NPCs ({{ pickedSubjects.length }})
          </label>
          <label class="checkbox-label">
            <input type="radio" value="all" v-model="publishSelect" name="publish-select" /> Every NPC with a GM dossier in range (--all)
          </label>
          <label class="checkbox-label">
            <input type="radio" value="authored_all" v-model="publishSelect" name="publish-select" /> Every hand-built dossier (--authored-all)
          </label>
        </fieldset>
        <div class="field">
          <label class="field-label">Source</label>
          <select class="field-input narrow" v-model="publishSource">
            <option value="">(not needed)</option>
            <option v-for="s in SOURCES" :key="s" :value="s">{{ s }}</option>
          </select>
          <span class="field-help">Required only when an NPC has both a GM dossier and a hand-built one.</span>
        </div>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forcePublish" />
          Publish despite a failed verification, a foreign target or a hand-edited target (--force)
        </label>
        <span v-if="publishSelect === ''" class="field-help">Choose what to publish to enable the button.</span>
        <span class="field-help">
          Each refusal and its reason appears in the output below; the NPCs that passed are still published.
        </span>
        <RunPanel :endpoint="`${BASE}/run/publish`" :params="publishParams" :disabled="!publishReady"
          label="Publish" @done="onPublishDone" />
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
.choice { border: none; padding: 0; margin: 0 0 8px; }
.narrow-block { padding-left: 14px; border-left: 2px solid var(--bg-surface1); margin-bottom: 8px; }

.checkbox-label { font-size: 11px; color: var(--text-sub); display: flex; align-items: center; gap: 6px; cursor: pointer; margin-bottom: 8px; }
.checkbox-label input { accent-color: var(--mauve); }

.badges { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: var(--bg-surface0); }
.badge.ok { color: var(--green); }
.badge.warn { color: var(--peach); }
.badge.bad { color: var(--red); }
.badge.muted { color: var(--text-muted); }

.grid { border-collapse: collapse; font-size: 11px; color: var(--text-sub); margin-top: 6px; width: 100%; }
.grid th, .grid td { text-align: left; padding: 3px 12px 3px 0; vertical-align: top; }
.grid th { font-weight: 600; color: var(--text); }
.grid code { font-family: var(--mono); font-size: 10px; }
.dim { opacity: 0.55; }
.views { white-space: nowrap; }
.link-btn { background: none; border: none; color: var(--mauve); cursor: pointer; font-size: 10px; padding: 0 6px 0 0; }
.link-btn:hover { text-decoration: underline; }
.ok { color: var(--green); }
.bad { color: var(--red); }
.warn-text { color: var(--peach); }

.viewer { margin-top: 10px; background: var(--bg-mantle); border-radius: 4px; padding: 8px 10px; }
.viewer-title { font-size: 11px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.viewer pre { font-family: var(--mono); font-size: 10px; color: var(--text-sub); white-space: pre-wrap; word-break: break-word; max-height: 420px; overflow-y: auto; margin: 0; }
</style>
