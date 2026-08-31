<script setup lang="ts">
/**
 * Thread Registry — harvest, rule, maintain (specs/014-thread-registry-ui, #337).
 *
 * The Planning grounding doc cannot assemble until `docs/thread_registry.yaml`
 * exists, and until this page nothing in the UI mentioned that file. This is
 * the surface that creates it.
 *
 * Three things this page deliberately does NOT do:
 *
 *  - **It holds no thread state of its own** (FR-023). Registry, queue and
 *    health are re-fetched from disk on mount and after every successful
 *    write; nothing is cached across a reload.
 *  - **It never rules on a candidate itself** (FR-022, FR-031). Bands,
 *    ordering, search and filters are presentation only. No fuzzy matching,
 *    no clustering, no "did you mean" — deciding two titles are the same
 *    thread is an identity assertion, and it is the GM's.
 *  - **It offers no bulk control** (FR-007, SC-004). One candidate, one
 *    ruling, one act. The absence is the requirement.
 *
 * The harvest run control is this page's own, NOT the shared `RunPanel`
 * (GM ruling, research D19): the harvest is deterministic and spends zero
 * tokens, so a model/backend picker would be meaningless noise above it.
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { apiFetch, apiPost } from '../../api/client'
import { connectSSE } from '../../api/sse'

// ── shapes (mirror contracts/cli.md's --json payloads exactly) ────────────

interface Evidence {
  chapter: number | null
  fact: string
  quote?: string
  source?: string
}
interface Proposal {
  norm: string
  title: string
  all_titles: string[]
  matches: string | null
  chapters: number[]
  status: string
  evidence: Evidence[]
  note?: string
  ruled_thread?: string
}
interface LogRow {
  chapter: number | null
  change: string
  summary: string
  quote?: string
}
interface Thread {
  id: string
  title: string
  status: string
  opened: number | null
  resolved: number | null
  tracker: string | null
  aliases: string[]
  notes: string
  log: LogRow[]
}

const CHANGES = ['opened', 'advanced', 'resolved', 'reopened', 'abandoned']
const STATUSES = ['open', 'dormant', 'resolved', 'abandoned']

// ── state ────────────────────────────────────────────────────────────────

const threads = ref<Thread[]>([])
const proposals = ref<Proposal[]>([])
const problems = ref<string[]>([])
const loading = ref(false)
const loadError = ref('')

const corpus = ref('')
const corpusFiles = ref<{ path: string; size: number }[]>([])
const corpusError = ref('')
const resolving = ref(false)

const harvestOutput = ref('')
const harvestStatus = ref<'idle' | 'running' | 'done' | 'error'>('idle')
let harvestES: EventSource | null = null

const search = ref('')
const chapterFilter = ref('')
const rulingFilter = ref('')

/** Which card has a form open, and which kind. One at a time, by construction. */
const openForm = ref<{ norm: string; kind: 'accept' | 'reject' | 'discuss' } | null>(null)
const formError = ref('')
const busy = ref('')

const plan = ref<{
  id: string; title: string; status: string; opened: number | null
  tracker: string; notes: string; log: LogRow[]
}>({ id: '', title: '', status: 'open', opened: null, tracker: '', notes: '', log: [] })
const ruleNote = ref('')

// maintenance forms, keyed by thread id
const maint = ref<Record<string, any>>({})
const maintError = ref<Record<string, string>>({})

// ── loading (FR-023: everything re-derived from disk) ────────────────────

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const [reg, props, chk] = await Promise.all([
      apiFetch<{ threads: Thread[] }>('/api/projections/threads/registry'),
      apiFetch<{ proposals: Proposal[] }>('/api/projections/threads/proposals'),
      apiFetch<{ threads: number; problems: string[] }>('/api/projections/threads/check'),
    ])
    threads.value = reg.threads || []
    proposals.value = props.proposals || []
    problems.value = chk.problems || []
  } catch (e: any) {
    loadError.value = e?.message || 'Failed to load the thread registry'
  } finally {
    loading.value = false
  }
}
onMounted(loadAll)

// A harvest that outlives the page keeps streaming and then calls loadAll()
// against a component that no longer exists.
onBeforeUnmount(() => {
  harvestES?.close()
  harvestES = null
})

// ── registry region (T025) ───────────────────────────────────────────────

const threadsByStatus = computed(() =>
  STATUSES.map((s) => ({
    status: s,
    items: threads.value.filter((t) => (t.status || 'open') === s),
  })).filter((g) => g.items.length > 0),
)

/** T052 — surface `check` problems on the thread they belong to, not only in
 *  the health region: a broken thread should be visible where it is edited. */
function problemsFor(id: string): string[] {
  return problems.value.filter((p) => p.startsWith(`${id}:`))
}

function sortedLog(t: Thread): LogRow[] {
  return [...(t.log || [])].sort((a, b) => (a.chapter || 0) - (b.chapter || 0))
}

// ── harvest (T027 + T021's own run control) ──────────────────────────────

const corpusPatterns = computed(() =>
  corpus.value.split(/\s+/).map((s) => s.trim()).filter(Boolean),
)

async function resolveCorpus() {
  corpusError.value = ''
  corpusFiles.value = []
  if (!corpusPatterns.value.length) {
    corpusError.value = 'Give at least one corpus glob first.'
    return
  }
  resolving.value = true
  try {
    const qs = corpusPatterns.value
      .map((p) => `pattern=${encodeURIComponent(p)}`)
      .join('&')
    const body = await apiFetch<{ files: { path: string; size: number }[] }>(
      `/api/projections/threads/corpus?${qs}`,
    )
    corpusFiles.value = body.files || []
    if (!corpusFiles.value.length) corpusError.value = 'No files matched.'
  } catch (e: any) {
    corpusError.value = e?.message || 'Could not resolve the corpus'
  } finally {
    resolving.value = false
  }
}

function runHarvest() {
  if (harvestStatus.value === 'running') return
  if (!corpusPatterns.value.length) {
    corpusError.value = 'Give at least one corpus glob first.'
    return
  }
  harvestStatus.value = 'running'
  harvestOutput.value = ''
  const qs = corpusPatterns.value
    .map((p) => `corpus=${encodeURIComponent(p)}`)
    .join('&')
  harvestES = connectSSE(`/api/projections/threads/run/propose?${qs}`, {
    onData: (t) => { harvestOutput.value += t },
    onDone: (rc, error) => {
      harvestES = null
      harvestStatus.value = rc === 0 ? 'done' : 'error'
      if (error && !harvestOutput.value.includes(error)) {
        harvestOutput.value += `\nError: ${error}\n`
      }
      loadAll()
    },
    onError: () => {
      harvestES?.close()
      harvestES = null
      harvestStatus.value = 'error'
      harvestOutput.value += '\n[connection lost — harvest stopped]\n'
    },
  })
}

// ── search + bands (T029, T030, T031) ────────────────────────────────────

/** Free text over the title, EVERY spelling variant, and evidence prose.
 *  Runs in the browser over the whole payload — there is no server-side
 *  query route and none may be added (research D16). */
function matchesSearch(p: Proposal): boolean {
  const q = search.value.trim().toLowerCase()
  if (!q) return true
  const hay = [
    p.title,
    ...(p.all_titles || []),
    ...(p.evidence || []).flatMap((e) => [e.fact, e.quote || '']),
  ].join(' ').toLowerCase()
  return hay.includes(q)
}

function matchesChapter(p: Proposal): boolean {
  const c = chapterFilter.value.trim()
  if (!c) return true
  const n = Number(c)
  if (Number.isNaN(n)) return true
  return (p.chapters || []).includes(n)
}

function matchesRuling(p: Proposal): boolean {
  if (!rulingFilter.value) return true
  return (p.status || 'pending') === rulingFilter.value
}

/** FR-030: search spans candidates that are already ruled, so a rejected one
 *  stays findable — a ruling hides a card from the default view, never from
 *  the GM. */
const filtered = computed(() =>
  proposals.value.filter((p) => matchesSearch(p) && matchesChapter(p) && matchesRuling(p)),
)

const searching = computed(
  () => !!(search.value.trim() || chapterFilter.value.trim() || rulingFilter.value),
)

function mentions(p: Proposal): number {
  return (p.evidence || []).length
}

function bandOf(p: Proposal): 'recurring' | 'repeated' | 'once' {
  const spans = (p.chapters || []).length
  if (spans >= 2) return 'recurring'
  // `< 2`, NOT `== 1`: a candidate with no chapter recorded has ZERO, and
  // must land somewhere visible so the GM can see the chapterless warning
  // (research D20). `== 1` would drop it into the excluded tail.
  if (spans < 2 && mentions(p) >= 2) return 'repeated'
  return 'once'
}

function orderBand(items: Proposal[]): Proposal[] {
  return [...items].sort(
    (a, b) =>
      (b.chapters || []).length - (a.chapters || []).length ||
      mentions(b) - mentions(a) ||
      a.title.localeCompare(b.title),
  )
}

const pendingOnly = computed(() => filtered.value.filter((p) => (p.status || 'pending') === 'pending'))
const bandSource = computed(() => (searching.value ? filtered.value : pendingOnly.value))

const recurring = computed(() => orderBand(bandSource.value.filter((p) => bandOf(p) === 'recurring')))
const repeated = computed(() => orderBand(bandSource.value.filter((p) => bandOf(p) === 'repeated')))

/** The once-mentioned tail — rendered ONLY in response to an explicit query.
 *
 *  This is the fix for the defect that shipped in #346: the tail was computed
 *  into a `once` bucket, counted, and then rendered by nothing, so the line
 *  telling the GM to "search or filter by chapter to reach them" was false —
 *  916 of 986 OOTA candidates could not be ruled on from the interface at all
 *  (FR-029/FR-030).
 *
 *  It is NOT a "Show all" control (FR-028): it appears only when the GM has
 *  typed a query or picked a filter, so the page never dumps ~1000 rows on
 *  its own. Search is the affordance; this is what search was always supposed
 *  to reach. */
const otherMatches = computed(() =>
  searching.value ? orderBand(bandSource.value.filter((p) => bandOf(p) === 'once')) : [],
)

/** Hidden, therefore only meaningful when NOT searching — when a query is
 *  active the tail is on screen and hiding nothing. */
const excludedCount = computed(() =>
  searching.value ? 0 : bandSource.value.filter((p) => bandOf(p) === 'once').length,
)

/** The three bands as data, so one card template serves all of them. The
 *  duplication this replaces is why the third band was never added. */
const bands = computed(() => {
  const out = [
    { key: 'recurring', title: 'Recurring', items: recurring.value,
      blurb: 'Appears in two or more chapters.' },
    { key: 'repeated', title: 'Single chapter, repeated', items: repeated.value,
      blurb: 'Mentioned more than once, but so far inside a single chapter — where a '
           + 'thread that opened last session lives before it has had a chance to recur.' },
  ]
  if (searching.value) {
    out.push({
      key: 'once', title: 'Other matches', items: otherMatches.value,
      blurb: 'Mentioned once. Shown because your query reached them; not part of the '
           + 'default view.',
    })
  }
  return out
})

// Every number on this page is derived from the loaded set. A literal here
// is the exact defect this replaced: 916 is right for one corpus and wrong
// for every other (FR-028a).
const ruledCount = computed(() => proposals.value.filter((p) => (p.status || 'pending') !== 'pending').length)

// ── rulings (T042-T046) ──────────────────────────────────────────────────

function evidenceFor(p: Proposal, ch: number): Evidence | undefined {
  return (p.evidence || []).find((e) => e.chapter === ch)
}

/** Pre-fill from the proposal. Every field stays editable and NOTHING is
 *  written until Confirm — there is no "accept as proposed" (FR-008). */
/** Chapters the matched thread has already logged. A matched candidate keeps
 *  its FULL span in the payload (long-standing engine behaviour), so without
 *  this the accept form pre-fills a row for a chapter that is already canon
 *  and Confirm appends it a second time — `check_registry` does not flag a
 *  duplicate chapter, so nothing catches it (review finding, 2026-08-27). */
function alreadyLogged(p: Proposal): number[] {
  if (!p.matches) return []
  const t = threads.value.find((t) => t.id === p.matches)
  if (!t) return []
  return (t.log || []).map((r) => r.chapter).filter((c): c is number => typeof c === 'number')
}

function startAccept(p: Proposal) {
  formError.value = ''
  const logged = alreadyLogged(p)
  const chapters = [...(p.chapters || [])]
    .filter((c) => typeof c === 'number')
    .filter((c) => !logged.includes(c))
    .sort((a, b) => a - b)
  plan.value = {
    id: p.matches || p.norm,
    title: p.title,
    status: 'open',
    opened: chapters.length ? chapters[0] : null,
    tracker: '',
    notes: '',
    log: chapters.map((ch, i) => {
      const ev = evidenceFor(p, ch)
      return {
        chapter: ch,
        change: i === 0 ? 'opened' : 'advanced',
        summary: ev?.fact || '',
        quote: ev?.quote || '',
      }
    }),
  }
  if (!plan.value.log.length) {
    // A chapterless candidate: the GM must supply the chapter (research D4).
    plan.value.log = [{ chapter: null, change: 'opened', summary: '', quote: '' }]
  }
  openForm.value = { norm: p.norm, kind: 'accept' }
}

function startRule(p: Proposal, kind: 'reject' | 'discuss') {
  formError.value = ''
  ruleNote.value = ''
  openForm.value = { norm: p.norm, kind }
}

function cancelForm() {
  openForm.value = null
  formError.value = ''
}

function addLogRow() {
  plan.value.log.push({ chapter: null, change: 'advanced', summary: '', quote: '' })
}
function removeLogRow(i: number) {
  plan.value.log.splice(i, 1)
}

async function confirmAccept(p: Proposal) {
  formError.value = ''
  busy.value = p.norm
  try {
    await apiPost('/api/projections/threads/ratify', {
      norm: p.norm,
      id: plan.value.id,
      title: plan.value.title,
      status: plan.value.status,
      opened: plan.value.opened,
      tracker: plan.value.tracker || null,
      notes: plan.value.notes,
      matches: p.matches,
      log: plan.value.log.map((r) => ({
        chapter: r.chapter === null || r.chapter === ('' as any) ? null : Number(r.chapter),
        change: r.change,
        summary: r.summary,
        ...(r.quote ? { quote: r.quote } : {}),
      })),
    })
    openForm.value = null
    await loadAll()
  } catch (e: any) {
    // Verbatim — the engine's own wording, never a paraphrase (FR-021).
    formError.value = e?.message || 'Ratification failed'
  } finally {
    busy.value = ''
  }
}

async function confirmRule(p: Proposal, status: 'rejected' | 'deferred') {
  formError.value = ''
  busy.value = p.norm
  try {
    await apiPost('/api/projections/threads/rule', {
      norm: p.norm, status, note: ruleNote.value || undefined,
    })
    openForm.value = null
    await loadAll()
  } catch (e: any) {
    formError.value = e?.message || 'Ruling failed'
  } finally {
    busy.value = ''
  }
}

// ── maintenance (T051) ───────────────────────────────────────────────────

function blankMaint() {
  return {
    open: '', chapter: '', change: 'advanced', summary: '', quote: '',
    status: 'open', closeChapter: '', alias: '',
  }
}

/** Read-only accessor. It used to create the entry on first call, but it is
 *  called FROM the template — so the first render of every thread mutated
 *  reactive state mid-render, re-triggering the render effect (Vue warns
 *  about this in dev). The map is seeded when threads load instead. */
function maintFor(id: string) {
  return maint.value[id] || blankMaint()
}

/** Seed a form object per thread, preserving any in-progress edit. */
watch(threads, (list) => {
  for (const t of list) if (!maint.value[t.id]) maint.value[t.id] = blankMaint()
}, { immediate: true })

async function post(id: string, path: string, body: any) {
  maintError.value[id] = ''
  busy.value = id
  try {
    await apiPost(path, body)
    maint.value[id].open = ''
    await loadAll()
  } catch (e: any) {
    maintError.value[id] = e?.message || 'Failed'
  } finally {
    busy.value = ''
  }
}

const addLog = (t: Thread) => {
  const m = maintFor(t.id)
  post(t.id, '/api/projections/threads/log', {
    id: t.id, chapter: Number(m.chapter), change: m.change,
    summary: m.summary, quote: m.quote || undefined,
  })
}
const setStatus = (t: Thread) => {
  const m = maintFor(t.id)
  post(t.id, '/api/projections/threads/status', {
    id: t.id, status: m.status,
    chapter: m.closeChapter ? Number(m.closeChapter) : undefined,
  })
}
const addAlias = (t: Thread) => {
  const m = maintFor(t.id)
  post(t.id, '/api/projections/threads/alias', { id: t.id, alias: m.alias })
}
</script>

<template>
  <div class="threads">
    <div class="page-header">
      <h2>Threads</h2>
      <p class="subtitle">
        Harvest narrative threads from the extraction corpus, rule on them one
        at a time, and maintain the registry the Planning document reads.
      </p>
    </div>

    <p v-if="loading" class="loading-box">Loading threads…</p>
    <p v-if="loadError" class="error-box">{{ loadError }}</p>

    <!-- ── health (T026) ────────────────────────────────────────────── -->
    <section class="card">
      <h2>Registry health</h2>
      <p class="health" :class="problems.length ? 'health-error' : 'health-success'">
        <strong>{{ problems.length ? 'Needs attention' : 'Healthy' }}</strong> ·
        <strong>{{ threads.length }}</strong> thread<span v-if="threads.length !== 1">s</span>,
        <strong>{{ problems.length }}</strong> problem<span v-if="problems.length !== 1">s</span>
      </p>
      <ul v-if="problems.length" class="problems">
        <li v-for="p in problems" :key="p">{{ p }}</li>
      </ul>
      <p v-else class="muted">The registry passes every consistency check.</p>
    </section>

    <!-- ── harvest (T027) + its own run control (T021) ──────────────── -->
    <section class="card">
      <h2>Harvest candidates</h2>
      <p class="muted">
        Deterministic and free — this reads extraction output off disk and
        spends no model tokens. Nothing here enters the registry.
      </p>
      <label class="field">
        <span>Corpus (whitespace-separated globs)</span>
        <input
          v-model="corpus"
          class="field-input"
          placeholder="docs/ensemble/per_chapter/*/merged.json"
          spellcheck="false"
        />
      </label>
      <div class="row">
        <button class="btn-neutral btn-sm" :disabled="resolving || !corpusPatterns.length" @click="resolveCorpus">
          {{ resolving ? 'Resolving…' : 'Resolve' }}
        </button>
        <button
          class="btn-primary btn-sm"
          :disabled="harvestStatus === 'running' || !corpusPatterns.length"
          @click="runHarvest"
        >
          {{ harvestStatus === 'running' ? 'Harvesting…' : 'Run harvest' }}
        </button>
        <span class="status-badge" :class="`status-${harvestStatus}`">
          Harvest: {{ harvestStatus }}
        </span>
      </div>
      <p v-if="corpusError" class="error-box">{{ corpusError }}</p>
      <div v-if="corpusFiles.length" class="files">
        <p class="muted">{{ corpusFiles.length }} file(s) matched:</p>
        <ul>
          <li v-for="f in corpusFiles" :key="f.path"><code>{{ f.path }}</code></li>
        </ul>
      </div>
      <pre v-if="harvestOutput" class="output">{{ harvestOutput }}</pre>
    </section>

    <!-- ── the queue (T028-T031, T042-T046) ─────────────────────────── -->
    <section class="card">
      <h2>Candidate queue</h2>

      <div class="filters">
        <input v-model="search" class="field-input" placeholder="Search titles, variants, evidence…" />
        <input v-model="chapterFilter" placeholder="Chapter" class="field-input narrow" />
        <select v-model="rulingFilter" class="field-input">
          <option value="">Any ruling</option>
          <option value="pending">Pending</option>
          <option value="ratified">Ratified</option>
          <option value="rejected">Rejected</option>
          <option value="deferred">Discussed</option>
        </select>
      </div>
      <p v-if="ruledCount" class="muted">
        {{ ruledCount }} candidate(s) already ruled on — search or filter by
        ruling to reach them.
      </p>

      <template v-if="!proposals.length">
        <p class="muted">No candidates yet — run a harvest above.</p>
      </template>

      <template v-else>
        <!-- ONE card template, three bands. The card markup used to be pasted
             once per band, which is how the third band came to be counted and
             never rendered: adding it meant a third copy, so it was not added
             and ~916 of 986 OOTA candidates were unreachable by any means
             (review finding, 2026-08-27). Bands are data now. -->
        <template v-for="band in bands" :key="band.key">
          <h3>{{ band.title }} <span class="count">({{ band.items.length }})</span></h3>
          <p class="muted small">{{ band.blurb }}</p>
          <p v-if="!band.items.length" class="muted">None.</p>

          <div v-for="p in band.items" :key="p.norm" class="candidate">
            <div class="cand-head">
              <strong>{{ p.title }}</strong>
              <span class="status-badge" :class="`status-${p.status || 'pending'}`">
                {{ p.status || 'pending' }}
              </span>
              <span v-if="p.matches" class="status-badge status-info">appends to {{ p.matches }}</span>
            </div>
            <p v-if="(p.all_titles || []).length > 1" class="muted small">
              also recorded as: {{ p.all_titles.join(' · ') }}
            </p>
            <p class="muted small">
              chapters: <span v-if="p.chapters.length">{{ p.chapters.join(', ') }}</span>
              <span v-else class="warn">no chapter recorded; you must supply one to accept</span>
              &middot; {{ mentions(p) }} mention(s)
            </p>
            <ul class="evidence">
              <li v-for="(e, i) in p.evidence" :key="i">
                <span class="ev-ch">ch{{ e.chapter ?? '—' }}</span>
                <span class="ev-fact">{{ e.fact }}</span>
                <q v-if="e.quote" class="ev-quote">{{ e.quote }}</q>
                <span v-if="e.source" class="ev-src">{{ e.source }}</span>
              </li>
            </ul>
            <div class="actions">
              <button class="btn-success btn-sm" @click="startAccept(p)">Accept</button>
              <button class="btn-neutral btn-sm" @click="startRule(p, 'reject')">Reject</button>
              <button class="btn-neutral btn-sm" @click="startRule(p, 'discuss')">Discuss</button>
            </div>

            <div v-if="openForm && openForm.norm === p.norm" class="form">
              <template v-if="openForm.kind === 'accept'">
                <p v-if="p.matches" class="muted small">
                  This candidate matches thread <code>{{ p.matches }}</code> — its
                  identity fields are fixed; only the log rows below are yours to edit.
                </p>
                <p v-if="p.matches && alreadyLogged(p).length" class="muted small">
                  Chapters already logged on that thread are not pre-filled:
                  {{ alreadyLogged(p).join(', ') }}. Add one back only if it really
                  needs a second entry.
                </p>
                <div class="grid">
                  <label><span>id</span>
                    <input v-model="plan.id" class="field-input" :disabled="!!p.matches" /></label>
                  <label><span>title</span>
                    <input v-model="plan.title" class="field-input" :disabled="!!p.matches" /></label>
                  <label><span>status</span>
                    <select v-model="plan.status" class="field-input" :disabled="!!p.matches">
                      <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
                    </select></label>
                  <label><span>opened</span>
                    <input v-model.number="plan.opened" class="field-input" type="number"
                           :disabled="!!p.matches"
                           :required="!p.chapters.length" /></label>
                  <label><span>tracker</span><input v-model="plan.tracker" class="field-input" /></label>
                  <label><span>notes</span><input v-model="plan.notes" class="field-input" /></label>
                </div>
                <h4>Log rows</h4>
                <div v-for="(row, i) in plan.log" :key="i" class="logrow">
                  <input v-model.number="row.chapter" type="number" placeholder="ch" class="field-input narrow" />
                  <select v-model="row.change" class="field-input">
                    <option v-for="c in CHANGES" :key="c" :value="c">{{ c }}</option>
                  </select>
                  <input v-model="row.summary" class="field-input" placeholder="summary" />
                  <input v-model="row.quote" class="field-input" placeholder="quote (verbatim)" />
                  <button class="btn-neutral btn-sm" @click="removeLogRow(i)">remove</button>
                </div>
                <button class="btn-neutral btn-sm" @click="addLogRow">+ add row</button>
                <p v-if="formError" class="error-box">{{ formError }}</p>
                <div class="row">
                  <button class="btn-primary btn-sm" :disabled="busy === p.norm" @click="confirmAccept(p)">
                    {{ busy === p.norm ? 'Writing…' : 'Confirm' }}
                  </button>
                  <button class="btn-neutral btn-sm" @click="cancelForm">Cancel</button>
                </div>
              </template>

              <template v-else>
                <label class="field">
                  <span>Note (optional)</span>
                  <input v-model="ruleNote" class="field-input" />
                </label>
                <p v-if="openForm.kind === 'discuss'" class="muted small">
                  Discussing appends this candidate and its evidence to the
                  adjudication bundle (<code>stores.thread_adjudication</code>,
                  by default <code>docs/ensemble/thread_adjudication.json</code>),
                  which you can hand to a conversation whole. The card stays here
                  and can be ruled on again.
                </p>
                <p v-if="formError" class="error-box">{{ formError }}</p>
                <div class="row">
                  <button
                    class="btn-primary btn-sm"
                    :disabled="busy === p.norm"
                    @click="confirmRule(p, openForm.kind === 'reject' ? 'rejected' : 'deferred')"
                  >Confirm</button>
                  <button class="btn-neutral btn-sm" @click="cancelForm">Cancel</button>
                </div>
              </template>
            </div>
          </div>
        </template>

        <!-- The hidden count, in words, computed from the loaded set. When a
             query is active the tail is RENDERED (third band), so nothing is
             hidden and this line does not appear — it must never claim to be
             hiding candidates the page is in fact showing. -->
        <p v-if="excludedCount" class="excluded">
          {{ excludedCount }} candidate(s) mentioned exactly once are not shown —
          search or filter by chapter to reach them.
        </p>
      </template>
    </section>

    <!-- ── ratified registry (T025, T051, T052) ─────────────────────── -->
    <section class="card">
      <h2>Ratified threads</h2>
      <p v-if="!threads.length" class="muted">No threads yet.</p>
      <div v-for="group in threadsByStatus" :key="group.status" class="group">
        <h3>
          <span class="status-badge" :class="`status-${group.status}`">{{ group.status }}</span>
          <span class="count">({{ group.items.length }})</span>
        </h3>
        <div v-for="t in group.items" :key="t.id" class="thread">
          <div class="cand-head">
            <strong>{{ t.title }}</strong>
            <code>{{ t.id }}</code>
            <span v-if="t.tracker" class="badge">tracker: {{ t.tracker }}</span>
          </div>
          <p class="muted small">
            opened ch{{ t.opened ?? '—' }}
            <span v-if="t.resolved"> &middot; closed ch{{ t.resolved }}</span>
            <span v-if="(t.aliases || []).length"> &middot; also: {{ t.aliases.join(', ') }}</span>
          </p>
          <ul v-if="problemsFor(t.id).length" class="problems">
            <li v-for="p in problemsFor(t.id)" :key="p">{{ p }}</li>
          </ul>
          <ul class="log">
            <li v-for="(r, i) in sortedLog(t)" :key="i">
              <span class="ev-ch">ch{{ r.chapter ?? '—' }}</span>
              <span class="badge">{{ r.change }}</span>
              <span>{{ r.summary }}</span>
              <q v-if="r.quote" class="ev-quote">{{ r.quote }}</q>
            </li>
          </ul>
          <div class="actions">
            <button class="btn-neutral btn-sm" @click="maintFor(t.id).open = maintFor(t.id).open === 'log' ? '' : 'log'">Add log row</button>
            <button class="btn-neutral btn-sm" @click="maintFor(t.id).open = maintFor(t.id).open === 'status' ? '' : 'status'">Change status</button>
            <button class="btn-neutral btn-sm" @click="maintFor(t.id).open = maintFor(t.id).open === 'alias' ? '' : 'alias'">Add alias</button>
          </div>
          <div v-if="maintFor(t.id).open === 'log'" class="form logrow">
            <input v-model="maintFor(t.id).chapter" type="number" placeholder="ch" class="field-input narrow" />
            <select v-model="maintFor(t.id).change" class="field-input">
              <option v-for="c in CHANGES" :key="c" :value="c">{{ c }}</option>
            </select>
            <input v-model="maintFor(t.id).summary" class="field-input" placeholder="summary" />
            <input v-model="maintFor(t.id).quote" class="field-input" placeholder="quote" />
            <button class="btn-primary btn-sm" :disabled="busy === t.id" @click="addLog(t)">Add</button>
          </div>
          <div v-if="maintFor(t.id).open === 'status'" class="form logrow">
            <select v-model="maintFor(t.id).status" class="field-input">
              <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
            </select>
            <input v-model="maintFor(t.id).closeChapter" type="number" class="field-input narrow"
                   placeholder="closing chapter" />
            <button class="btn-primary btn-sm" :disabled="busy === t.id" @click="setStatus(t)">Apply</button>
            <span class="muted small">Resolving or abandoning needs a closing chapter.</span>
          </div>
          <div v-if="maintFor(t.id).open === 'alias'" class="form logrow">
            <input v-model="maintFor(t.id).alias" class="field-input" placeholder="alternate title" />
            <button class="btn-primary btn-sm" :disabled="busy === t.id" @click="addAlias(t)">Add alias</button>
          </div>
          <p v-if="maintError[t.id]" class="error-box">{{ maintError[t.id] }}</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.threads {
  width: 100%;
  min-width: 0;
  height: 100%;
  max-width: 1400px;
  overflow: auto;
  box-sizing: border-box;
  padding: 20px 24px;
  color: var(--text);
  font-family: var(--sans);
  font-size: 12px;
}

.page-header { margin-bottom: 20px; }
.page-header h2 {
  margin-bottom: 4px;
  color: var(--text);
  font-size: 16px;
  font-weight: 700;
}
.subtitle { color: var(--text-muted); font-size: 12px; line-height: 1.5; }

.card {
  margin-bottom: 16px;
  padding: 14px 16px;
  border: 1px solid var(--bg-surface0);
  border-radius: 6px;
  background: var(--bg-mantle);
}
.card > h2 {
  margin-bottom: 8px;
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
}
h3 { margin: 12px 0 4px; color: var(--text-sub); font-size: 12px; }
h4 { margin: 12px 0 6px; color: var(--text-sub); font-size: 11px; }
.count { color: var(--text-muted); font-weight: 400; }
.muted { color: var(--text-sub); }
.small { font-size: 11px; }
.warn { color: var(--peach); font-weight: 600; }

.health { margin-bottom: 6px; color: var(--text-sub); }
.health-success > strong:first-child { color: var(--green); }
.health-error > strong:first-child { color: var(--red); }

.field { display: block; margin: 8px 0; }
.field > span,
.grid label > span {
  display: block;
  margin-bottom: 3px;
  color: var(--text-sub);
  font-size: 11px;
  font-weight: 600;
}
.field-input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--bg-surface1);
  border-radius: 4px;
  outline: none;
  background: var(--bg-base);
  color: var(--text);
  color-scheme: dark;
  font-family: var(--sans);
  font-size: 12px;
}
.field-input::placeholder { color: var(--text-muted); }
.field-input:hover:not(:disabled) { border-color: var(--bg-overlay0); }
.field-input:focus { border-color: var(--mauve); }
.field-input:disabled {
  border-color: var(--bg-surface0);
  background: var(--bg-mantle);
  color: var(--text-muted);
  cursor: default;
  opacity: 0.7;
}

.row { display: flex; gap: 8px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
.filters { display: flex; gap: 8px; margin-bottom: 8px; align-items: center; }
.filters input { flex: 1; }
.filters select { width: auto; min-width: 120px; }
.narrow { width: 6rem; flex: none !important; }

.threads .btn-primary { background: var(--mauve); color: var(--bg-base); }
.threads .btn-success { background: var(--green); color: var(--bg-base); }
.threads .btn-neutral { background: var(--bg-surface0); color: var(--text); }
.threads button:focus-visible { outline: 2px solid var(--mauve); outline-offset: 2px; }

.candidate,
.thread {
  padding: 10px 0;
  border-top: 1px solid var(--bg-surface0);
}
.cand-head { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.badge,
.status-badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 3px;
  background: var(--bg-surface0);
  color: var(--text-sub);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
.status-open,
.status-ratified,
.status-resolved,
.status-done { color: var(--green); }
.status-dormant,
.status-deferred { color: var(--peach); }
.status-rejected,
.status-abandoned,
.status-error { color: var(--red); }
.status-running,
.status-info { color: var(--blue); }
.status-pending,
.status-idle { color: var(--text-muted); }

.evidence,
.log,
.problems { margin: 6px 0; padding-left: 18px; }
.evidence li,
.log li { margin-bottom: 5px; line-height: 1.45; }
.problems { color: var(--red); }
.ev-ch {
  margin-right: 6px;
  color: var(--text-muted);
  font-family: var(--mono);
  font-size: 11px;
}
/* A quote is the tape's own words — rendered verbatim and visually distinct
   from the paraphrased fact beside it (Constitution IV). */
.ev-quote {
  display: block;
  margin: 4px 0 0 18px;
  padding-left: 8px;
  border-left: 2px solid var(--bg-surface1);
  color: var(--text-sub);
  font-style: italic;
}
.ev-src { margin-left: 6px; color: var(--text-muted); font-size: 10px; }
.actions { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
.form {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--bg-surface1);
  border-radius: 4px;
  background: var(--bg-surface0);
}
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.logrow { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
.logrow input:not(.narrow) { flex: 1; }
.excluded { margin-top: 12px; color: var(--text-muted); font-size: 11px; font-style: italic; }
.loading-box,
.error-box {
  margin-bottom: 12px;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
}
.loading-box { background: var(--bg-surface0); color: var(--text-sub); }
.error-box {
  border: 1px solid var(--red);
  background: var(--bg-mantle);
  color: var(--red);
}
.output {
  max-height: 16rem;
  margin-top: 8px;
  padding: 10px;
  overflow: auto;
  border: 1px solid var(--bg-surface0);
  border-radius: 4px;
  background: var(--bg-crust);
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
}
.files { margin-top: 8px; }
.files ul { max-height: 10rem; margin-top: 4px; padding-left: 18px; overflow: auto; }
code {
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--bg-crust);
  color: var(--text-sub);
  font-family: var(--mono);
  font-size: 11px;
}
</style>
