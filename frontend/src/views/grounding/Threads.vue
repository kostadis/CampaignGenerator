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
import { ref, computed, onMounted } from 'vue'
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
const excludedCount = computed(() => bandSource.value.filter((p) => bandOf(p) === 'once').length)

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
function startAccept(p: Proposal) {
  formError.value = ''
  const chapters = [...(p.chapters || [])].filter((c) => typeof c === 'number').sort((a, b) => a - b)
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

function maintFor(id: string) {
  if (!maint.value[id]) {
    maint.value[id] = {
      open: '', chapter: '', change: 'advanced', summary: '', quote: '',
      status: 'open', closeChapter: '', alias: '',
    }
  }
  return maint.value[id]
}

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
    <header class="page-head">
      <h1>Threads</h1>
      <p class="lede">
        Harvest narrative threads from the extraction corpus, rule on them one
        at a time, and maintain the registry the Planning document reads.
      </p>
    </header>

    <p v-if="loadError" class="error-box">{{ loadError }}</p>

    <!-- ── health (T026) ────────────────────────────────────────────── -->
    <section class="card">
      <h2>Registry health</h2>
      <p class="health">
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
          placeholder="docs/ensemble/per_chapter/*/merged.json"
          spellcheck="false"
        />
      </label>
      <div class="row">
        <button :disabled="resolving || !corpusPatterns.length" @click="resolveCorpus">
          {{ resolving ? 'Resolving…' : 'Resolve' }}
        </button>
        <button
          class="primary"
          :disabled="harvestStatus === 'running' || !corpusPatterns.length"
          @click="runHarvest"
        >
          {{ harvestStatus === 'running' ? 'Harvesting…' : 'Run harvest' }}
        </button>
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
        <input v-model="search" placeholder="Search titles, variants, evidence…" />
        <input v-model="chapterFilter" placeholder="Chapter" class="narrow" />
        <select v-model="rulingFilter">
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
        <h3>Recurring <span class="count">({{ recurring.length }})</span></h3>
        <p class="muted small">Appears in two or more chapters.</p>
        <p v-if="!recurring.length" class="muted">None.</p>
        <div v-for="p in recurring" :key="p.norm" class="candidate">
          <!-- card body is shared between bands -->
          <div class="cand-head">
            <strong>{{ p.title }}</strong>
            <span v-if="p.status !== 'pending'" class="badge">{{ p.status }}</span>
            <span v-if="p.matches" class="badge matched">appends to {{ p.matches }}</span>
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
            <button @click="startAccept(p)">Accept</button>
            <button @click="startRule(p, 'reject')">Reject</button>
            <button @click="startRule(p, 'discuss')">Discuss</button>
          </div>

          <div v-if="openForm && openForm.norm === p.norm" class="form">
            <template v-if="openForm.kind === 'accept'">
              <p v-if="p.matches" class="muted small">
                This candidate matches thread <code>{{ p.matches }}</code> — its
                identity fields are fixed; only the log rows below are yours to edit.
              </p>
              <div class="grid">
                <label><span>id</span>
                  <input v-model="plan.id" :disabled="!!p.matches" /></label>
                <label><span>title</span>
                  <input v-model="plan.title" :disabled="!!p.matches" /></label>
                <label><span>status</span>
                  <select v-model="plan.status" :disabled="!!p.matches">
                    <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
                  </select></label>
                <label><span>opened</span>
                  <input v-model.number="plan.opened" type="number"
                         :disabled="!!p.matches"
                         :required="!p.chapters.length" /></label>
                <label><span>tracker</span><input v-model="plan.tracker" /></label>
                <label><span>notes</span><input v-model="plan.notes" /></label>
              </div>
              <h4>Log rows</h4>
              <div v-for="(row, i) in plan.log" :key="i" class="logrow">
                <input v-model.number="row.chapter" type="number" placeholder="ch" class="narrow" />
                <select v-model="row.change">
                  <option v-for="c in CHANGES" :key="c" :value="c">{{ c }}</option>
                </select>
                <input v-model="row.summary" placeholder="summary" />
                <input v-model="row.quote" placeholder="quote (verbatim)" />
                <button class="ghost" @click="removeLogRow(i)">remove</button>
              </div>
              <button class="ghost" @click="addLogRow">+ add row</button>
              <p v-if="formError" class="error-box">{{ formError }}</p>
              <div class="row">
                <button class="primary" :disabled="busy === p.norm" @click="confirmAccept(p)">
                  {{ busy === p.norm ? 'Writing…' : 'Confirm' }}
                </button>
                <button class="ghost" @click="cancelForm">Cancel</button>
              </div>
            </template>

            <template v-else>
              <label class="field">
                <span>Note (optional)</span>
                <input v-model="ruleNote" />
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
                  class="primary"
                  :disabled="busy === p.norm"
                  @click="confirmRule(p, openForm.kind === 'reject' ? 'rejected' : 'deferred')"
                >Confirm</button>
                <button class="ghost" @click="cancelForm">Cancel</button>
              </div>
            </template>
          </div>
        </div>

        <h3>Single chapter, repeated <span class="count">({{ repeated.length }})</span></h3>
        <p class="muted small">
          Mentioned more than once, but so far inside a single chapter — where a
          thread that opened last session lives before it has had a chance to recur.
        </p>
        <p v-if="!repeated.length" class="muted">None.</p>
        <div v-for="p in repeated" :key="p.norm" class="candidate">
          <div class="cand-head">
            <strong>{{ p.title }}</strong>
            <span v-if="p.status !== 'pending'" class="badge">{{ p.status }}</span>
            <span v-if="p.matches" class="badge matched">appends to {{ p.matches }}</span>
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
            <button @click="startAccept(p)">Accept</button>
            <button @click="startRule(p, 'reject')">Reject</button>
            <button @click="startRule(p, 'discuss')">Discuss</button>
          </div>
          <div v-if="openForm && openForm.norm === p.norm" class="form">
            <template v-if="openForm.kind === 'accept'">
              <div class="grid">
                <label><span>id</span><input v-model="plan.id" :disabled="!!p.matches" /></label>
                <label><span>title</span><input v-model="plan.title" :disabled="!!p.matches" /></label>
                <label><span>opened</span>
                  <input v-model.number="plan.opened" type="number" :disabled="!!p.matches" /></label>
                <label><span>tracker</span><input v-model="plan.tracker" /></label>
              </div>
              <h4>Log rows</h4>
              <div v-for="(row, i) in plan.log" :key="i" class="logrow">
                <input v-model.number="row.chapter" type="number" placeholder="ch" class="narrow" />
                <select v-model="row.change">
                  <option v-for="c in CHANGES" :key="c" :value="c">{{ c }}</option>
                </select>
                <input v-model="row.summary" placeholder="summary" />
                <input v-model="row.quote" placeholder="quote (verbatim)" />
                <button class="ghost" @click="removeLogRow(i)">remove</button>
              </div>
              <button class="ghost" @click="addLogRow">+ add row</button>
              <p v-if="formError" class="error-box">{{ formError }}</p>
              <div class="row">
                <button class="primary" :disabled="busy === p.norm" @click="confirmAccept(p)">Confirm</button>
                <button class="ghost" @click="cancelForm">Cancel</button>
              </div>
            </template>
            <template v-else>
              <label class="field"><span>Note (optional)</span><input v-model="ruleNote" /></label>
              <p v-if="formError" class="error-box">{{ formError }}</p>
              <div class="row">
                <button class="primary" :disabled="busy === p.norm"
                        @click="confirmRule(p, openForm.kind === 'reject' ? 'rejected' : 'deferred')">
                  Confirm</button>
                <button class="ghost" @click="cancelForm">Cancel</button>
              </div>
            </template>
          </div>
        </div>

        <!-- T030: the hidden count, in words, computed from the loaded set -->
        <p class="excluded">
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
        <h3>{{ group.status }} <span class="count">({{ group.items.length }})</span></h3>
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
            <button @click="maintFor(t.id).open = maintFor(t.id).open === 'log' ? '' : 'log'">Add log row</button>
            <button @click="maintFor(t.id).open = maintFor(t.id).open === 'status' ? '' : 'status'">Change status</button>
            <button @click="maintFor(t.id).open = maintFor(t.id).open === 'alias' ? '' : 'alias'">Add alias</button>
          </div>
          <div v-if="maintFor(t.id).open === 'log'" class="form logrow">
            <input v-model="maintFor(t.id).chapter" type="number" placeholder="ch" class="narrow" />
            <select v-model="maintFor(t.id).change">
              <option v-for="c in CHANGES" :key="c" :value="c">{{ c }}</option>
            </select>
            <input v-model="maintFor(t.id).summary" placeholder="summary" />
            <input v-model="maintFor(t.id).quote" placeholder="quote" />
            <button class="primary" :disabled="busy === t.id" @click="addLog(t)">Add</button>
          </div>
          <div v-if="maintFor(t.id).open === 'status'" class="form logrow">
            <select v-model="maintFor(t.id).status">
              <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
            </select>
            <input v-model="maintFor(t.id).closeChapter" type="number"
                   placeholder="closing chapter" class="narrow" />
            <button class="primary" :disabled="busy === t.id" @click="setStatus(t)">Apply</button>
            <span class="muted small">Resolving or abandoning needs a closing chapter.</span>
          </div>
          <div v-if="maintFor(t.id).open === 'alias'" class="form logrow">
            <input v-model="maintFor(t.id).alias" placeholder="alternate title" />
            <button class="primary" :disabled="busy === t.id" @click="addAlias(t)">Add alias</button>
          </div>
          <p v-if="maintError[t.id]" class="error-box">{{ maintError[t.id] }}</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.threads { max-width: 60rem; }
.page-head { margin-bottom: 1rem; }
.lede { color: var(--muted, #666); margin: 0.25rem 0 0; }
.card {
  border: 1px solid var(--border, #ddd); border-radius: 6px;
  padding: 1rem; margin-bottom: 1rem;
}
h2 { margin-top: 0; }
h3 { margin-bottom: 0.25rem; }
.count { color: var(--muted, #666); font-weight: normal; }
.muted { color: var(--muted, #666); }
.small { font-size: 0.9em; }
.warn { color: #b45309; font-weight: 600; }
.field { display: block; margin: 0.5rem 0; }
.field span { display: block; font-size: 0.9em; color: var(--muted, #666); }
.field input { width: 100%; }
.row { display: flex; gap: 0.5rem; align-items: center; margin-top: 0.5rem; }
.filters { display: flex; gap: 0.5rem; margin-bottom: 0.5rem; }
.filters input { flex: 1; }
.narrow { width: 6rem; flex: none !important; }
.candidate, .thread {
  border-top: 1px solid var(--border, #eee); padding: 0.75rem 0;
}
.cand-head { display: flex; gap: 0.5rem; align-items: baseline; flex-wrap: wrap; }
.badge {
  font-size: 0.8em; background: var(--chip, #eee); border-radius: 3px;
  padding: 0 0.35rem;
}
.badge.matched { background: #dbeafe; }
.evidence, .log, .problems { margin: 0.4rem 0; padding-left: 1rem; }
.evidence li, .log li { margin-bottom: 0.3rem; }
.ev-ch { font-family: monospace; margin-right: 0.4rem; color: var(--muted, #666); }
.ev-fact { }
/* A quote is the tape's own words — rendered verbatim and visually distinct
   from the paraphrased fact beside it (Constitution IV). */
.ev-quote {
  display: block; margin-left: 1.5rem; font-style: italic;
  border-left: 2px solid var(--border, #ccc); padding-left: 0.5rem;
}
.ev-src { font-size: 0.8em; color: var(--muted, #888); margin-left: 0.4rem; }
.actions { display: flex; gap: 0.5rem; margin-top: 0.4rem; }
.form { margin-top: 0.6rem; padding: 0.6rem; background: var(--panel, #fafafa); border-radius: 4px; }
.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.5rem; }
.grid label span { display: block; font-size: 0.85em; color: var(--muted, #666); }
.grid input, .grid select { width: 100%; }
.logrow { display: flex; gap: 0.4rem; align-items: center; margin-bottom: 0.35rem; flex-wrap: wrap; }
.logrow input:not(.narrow) { flex: 1; }
.excluded { margin-top: 1rem; color: var(--muted, #666); font-style: italic; }
.error-box {
  border: 1px solid #f5c2c7; background: #fff5f5; color: #842029;
  padding: 0.5rem; border-radius: 4px; white-space: pre-wrap;
}
.output {
  background: #111; color: #eee; padding: 0.6rem; border-radius: 4px;
  max-height: 16rem; overflow: auto; white-space: pre-wrap;
}
.files ul { max-height: 10rem; overflow: auto; }
button.ghost { background: none; border: 1px solid var(--border, #ccc); }
</style>
