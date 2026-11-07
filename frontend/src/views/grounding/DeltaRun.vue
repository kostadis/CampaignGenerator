<script setup lang="ts">
/**
 * Incremental update run (spec 039, contracts/http.md "Page: DeltaRun.vue").
 *
 * The page is a view over files the CLI also writes (Principle IX): the stage list, member
 * outcomes and banner are re-read from `GET /plans/{id}/status` on load and after every
 * action. Nothing about a decision, plan or selection is kept in browser storage.
 *
 * Principle X: sources are an explicit list. "Select all" ticks every resolved chapter, so the
 * POST body lists each path; there is no "all" flag, glob or implicit default.
 * Decisions have no default: each is one of three buttons (approve / reject / discuss).
 */
import { ref, computed, onMounted } from 'vue'
import {
  DECISIONS, type Decision, type DeltaStatus, type ChapterFile,
  fetchChapters, createPlan, fetchStatus, fetchBaseline, fetchReceipt, fetchReview, reviewHandoff,
  ingestSources, decideAssociation, decideProposal, attestUnchanged, previewGrounding,
  runStage, previewNpcPublish, publishNpcs, applyGrounding, type StreamStageName, type NpcPublishPreview,
} from '../../api/delta'

const planId = ref('')
const summariesDir = ref('')
const files = ref<ChapterFile[]>([])
const selected = ref<string[]>([])
const status = ref<DeltaStatus | null>(null)
const output = ref<string[]>([])
const error = ref('')
const busy = ref(false)
const detail = ref<{ title: string; body: unknown } | null>(null)

const assocId = ref('')
const proposalId = ref('')
const attest = ref({ subject: '', reason: '', publication: '' })
const members = ref<string[]>([])
const memberDraft = ref('')
const previewSha = ref('')
/** The NPC publication the GM has been shown; publish sends exactly this digest and member list. */
const npcPreview = ref<{ sha: string; members: string[]; detail: NpcPublishPreview } | null>(null)

// A decision needs a named reviewer. Remembering the last name is a per-viewer convenience only
// (it is never sent unless the field is filled), so storage failures are ignored.
const REVIEWER_KEY = 'delta-run-reviewer'
function loadReviewer() {
  try { return localStorage.getItem(REVIEWER_KEY) ?? '' } catch { return '' }
}
const reviewer = ref(loadReviewer())
function rememberReviewer() {
  try { localStorage.setItem(REVIEWER_KEY, reviewer.value.trim()) } catch { /* convenience only */ }
}

const bannerStates = ['stale', 'partial', 'recovery_required']
const banner = computed(() => {
  const s = status.value
  if (!s || !bannerStates.includes(s.status)) return null
  const text: Record<string, string> = {
    stale: 'Stale: a bound input changed since this plan was made. Nothing proceeds until it is resolved.',
    partial: 'Partial: some members were held or failed. See the member outcomes below.',
    recovery_required: 'Recovery required: a publish was interrupted.',
  }
  return { state: s.status, text: text[s.status], command: s.recovery_command ?? s.next_action ?? '' }
})

const paths = computed(() => files.value.map(f => sourcePath(f)))
function sourcePath(f: ChapterFile) {
  const dir = summariesDir.value.trim().replace(/\/+$/, '')
  return dir ? `${dir}/${f.path}` : f.path
}
const allSelected = computed(() => paths.value.length > 0 && paths.value.every(p => selected.value.includes(p)))
function selectAll() { selected.value = [...paths.value] }
function clearAll() { selected.value = [] }
const PRODUCTS = ['grounding', 'npc'] as const
const STOPS = ['plan', 'prepare', 'propose', 'verify', 'review', 'preview', 'apply'] as const
const products = ref<string[]>([])
const stop = ref('')
const canCreate = computed(() => selected.value.length > 0 && products.value.length > 0 && !busy.value)

function msg(e: unknown) { return e instanceof Error ? e.message : String(e) }
async function guard(fn: () => Promise<unknown>) {
  error.value = ''
  busy.value = true
  try { return await fn() } catch (e) { error.value = msg(e) } finally { busy.value = false }
}

async function loadChapters() {
  await guard(async () => {
    files.value = []
    selected.value = []
    if (!summariesDir.value.trim()) return
    files.value = (await fetchChapters(summariesDir.value.trim())).files ?? []
  })
}

async function refresh() {
  if (!planId.value.trim()) { status.value = null; return }
  try { status.value = await fetchStatus(planId.value.trim()) } catch (e) { status.value = null; error.value = msg(e) }
}

async function create() {
  // Empty selection is refused here and, if it ever reached the server, by the CLI's own 400.
  if (!selected.value.length) {
    error.value = 'no sources selected; the delta does not default to all chapters.'
    return
  }
  if (!products.value.length) {
    error.value = 'no product selected; choose grounding and/or npc.'
    return
  }
  await guard(async () => {
    const plan = await createPlan([...selected.value], [...products.value], stop.value || undefined) as { plan_id?: string; id?: string }
    planId.value = plan.plan_id ?? plan.id ?? planId.value
    await refresh()
  })
}

async function stage(name: StreamStageName) {
  await guard(async () => {
    output.value = []
    const r = await runStage(planId.value.trim(), name, l => output.value.push(l))
    output.value.push(`exit ${r.exitCode}`)
    await refresh()
  })
}

async function show(title: string, fn: (id: string) => Promise<unknown>) {
  await guard(async () => { detail.value = { title, body: await fn(planId.value.trim()) } })
}

async function decide(kind: 'assoc' | 'proposal', d: Decision) {
  const id = (kind === 'assoc' ? assocId : proposalId).value.trim()
  if (!id) { error.value = 'enter an id first.'; return }
  const who = reviewer.value.trim()
  if (!who) { error.value = 'enter a reviewer name first; a decision is recorded against a named reviewer.'; return }
  rememberReviewer()
  await guard(async () => {
    detail.value = {
      title: `${kind} ${id}: ${d}`,
      body: await (kind === 'assoc' ? decideAssociation : decideProposal)(id, d, who, undefined, planId.value.trim() || undefined),
    }
    await refresh()
  })
}

async function submitAttest() {
  const a = attest.value
  if (!a.subject.trim() || !a.reason.trim() || !a.publication.trim()) {
    error.value = 'attestation needs a subject, a reason and the publication sha.'
    return
  }
  await guard(async () => {
    detail.value = { title: `attest ${a.subject}`, body: await attestUnchanged(planId.value.trim(), a.subject.trim(), a.reason.trim(), a.publication.trim()) }
    await refresh()
  })
}

function addMember() {
  const m = memberDraft.value.trim()
  if (m && !members.value.includes(m)) members.value.push(m)
  memberDraft.value = ''
  npcPreview.value = null
}
/** Select-all writes explicit members: every NPC subject named by the status, never an "all" flag. */
function selectAllMembers() {
  const subjects = (status.value?.members ?? []).map(m => m.subject)
  members.value = [...new Set([...members.value, ...subjects])]
  npcPreview.value = null
}
/** Step 1 of an NPC publication: the CLI's preview, shown to the GM; nothing is written. */
async function previewNpc() {
  if (!members.value.length) { error.value = 'no members selected; npc publish needs an explicit member list.'; return }
  await guard(async () => {
    const chosen = [...members.value]
    const r = await previewNpcPublish(planId.value.trim(), chosen)
    npcPreview.value = { sha: r.preview_sha256, members: chosen, detail: r }
  })
}
/** Step 2: publish exactly the previewed members with the previewed digest. */
async function publish() {
  if (!members.value.length) { error.value = 'no members selected; npc publish needs an explicit member list.'; return }
  const shown = npcPreview.value
  if (!shown || shown.members.join('\n') !== members.value.join('\n')) {
    error.value = 'preview the NPC publication first; publish sends the digest you were shown.'
    return
  }
  await guard(async () => {
    output.value = []
    const r = await publishNpcs(planId.value.trim(), [...shown.members], shown.sha, l => output.value.push(l))
    npcPreview.value = null
    output.value.push(`exit ${r.exitCode}`)
    await refresh()
  })
}

async function preview() {
  await guard(async () => {
    const r = await previewGrounding(planId.value.trim()) as { preview_sha?: string; preview_sha256?: string; sha256?: string }
    previewSha.value = r.preview_sha ?? r.preview_sha256 ?? r.sha256 ?? ''
    detail.value = { title: 'grounding preview', body: r }
  })
}
async function apply() {
  if (!previewSha.value.trim()) { error.value = 'run a preview first; apply needs its sha.'; return }
  await guard(async () => {
    output.value = []
    const r = await applyGrounding(planId.value.trim(), previewSha.value.trim(), l => output.value.push(l))
    output.value.push(`exit ${r.exitCode}`)
    await refresh()
  })
}

onMounted(refresh)
</script>

<template>
  <div class="delta-run">
    <h1>Incremental update</h1>

    <div v-if="banner" class="banner" :class="`banner-${banner.state}`" data-testid="status-banner" role="alert">
      <strong>{{ banner.state }}</strong> — {{ banner.text }}
      <code v-if="banner.command"> {{ banner.command }}</code>
    </div>
    <div v-if="error" class="banner banner-error" data-testid="error" role="alert">{{ error }}</div>

    <section>
      <h2>1. Chapters</h2>
      <label>Summaries directory
        <input v-model="summariesDir" data-testid="summaries-dir" @change="loadChapters" />
      </label>
      <div class="row">
        <button type="button" data-testid="select-all" :disabled="!paths.length" @click="selectAll">Select all</button>
        <button type="button" :disabled="!selected.length" @click="clearAll">Clear</button>
        <span>{{ selected.length }} of {{ paths.length }} selected<template v-if="allSelected"> (every chapter, listed explicitly)</template></span>
      </div>
      <ul class="chapters">
        <li v-for="f in files" :key="f.path">
          <label><input v-model="selected" type="checkbox" :value="sourcePath(f)" data-testid="chapter" /> {{ f.chapter }} — {{ f.path }}</label>
        </li>
      </ul>
      <fieldset class="row">
        <legend>Products</legend>
        <label v-for="p in PRODUCTS" :key="p"><input v-model="products" type="checkbox" :value="p" :data-testid="`product-${p}`" /> {{ p }}</label>
        <label>Stop after
          <select v-model="stop" data-testid="stop">
            <option value="">(CLI default)</option>
            <option v-for="o in STOPS" :key="o" :value="o">{{ o }}</option>
          </select>
        </label>
      </fieldset>
      <button type="button" data-testid="create-plan" :disabled="!canCreate" @click="create">Create plan</button>
      <p v-if="!selected.length" class="hint">Select at least one chapter and one product. The update never defaults to all chapters.</p>
    </section>

    <section>
      <h2>2. Plan</h2>
      <label>Plan id <input v-model="planId" data-testid="plan-id" @change="refresh" /></label>
      <button type="button" @click="refresh">Load status</button>
      <p v-if="status" data-testid="run-status">Status: <strong>{{ status.status }}</strong></p>

      <ol v-if="status" class="stepper" data-testid="stepper">
        <li v-for="s in status.stages" :key="s.name" :class="`stage-${s.status}`" data-testid="stage">
          <span class="stage-name">{{ s.name }}</span> <span class="stage-status">{{ s.status }}</span>
          <ul v-if="s.artifacts?.length" class="artifacts">
            <li v-for="a in s.artifacts" :key="a.path"><code>{{ a.path }}</code> <small>{{ a.sha256 }}</small></li>
          </ul>
        </li>
      </ol>
      <ul v-if="status?.members?.length" data-testid="members-outcomes">
        <li v-for="m in status.members" :key="m.subject">{{ m.subject }}: {{ m.outcome }}</li>
      </ul>
    </section>

    <section v-if="planId">
      <h2>3. Stages</h2>
      <div class="row">
        <button type="button" :disabled="busy" @click="guard(async () => { await ingestSources(planId.trim()); await refresh() })">Ingest sources</button>
        <button type="button" :disabled="busy" @click="stage('census')">Census</button>
        <button type="button" :disabled="busy" @click="stage('associations/propose')">Propose associations</button>
        <button type="button" :disabled="busy" @click="stage('npc/draft')">Draft NPCs</button>
        <button type="button" :disabled="busy" @click="stage('npc/verify')">Verify NPCs</button>
        <button type="button" :disabled="busy" @click="stage('grounding/propose')">Propose grounding edits</button>
        <button type="button" :disabled="busy" @click="stage('grounding/check')">Check grounding</button>
        <button type="button" :disabled="busy" data-testid="resume" @click="stage('resume')">Resume</button>
      </div>
      <pre v-if="output.length" class="output" data-testid="output">{{ output.join('\n') }}</pre>
    </section>

    <section v-if="planId">
      <h2>4. Judgments</h2>
      <label>Reviewer <input v-model="reviewer" data-testid="reviewer" placeholder="who is deciding" @change="rememberReviewer" /></label>
      <div class="judgment">
        <label>Association id <input v-model="assocId" data-testid="assoc-id" /></label>
        <button v-for="d in DECISIONS" :key="d" type="button" :data-testid="`assoc-${d}`" @click="decide('assoc', d)">{{ d }}</button>
      </div>
      <div class="judgment">
        <label>Grounding proposal id <input v-model="proposalId" data-testid="proposal-id" /></label>
        <button v-for="d in DECISIONS" :key="d" type="button" :data-testid="`proposal-${d}`" @click="decide('proposal', d)">{{ d }}</button>
      </div>
      <form class="judgment" @submit.prevent="submitAttest">
        <h3>Attest unchanged</h3>
        <label>Subject <input v-model="attest.subject" data-testid="attest-subject" /></label>
        <label>Reason <input v-model="attest.reason" data-testid="attest-reason" required /></label>
        <label>Publication sha <input v-model="attest.publication" data-testid="attest-publication" /></label>
        <button type="submit" data-testid="attest-submit">Record attestation</button>
      </form>
    </section>

    <section v-if="planId">
      <h2>5. Publish</h2>
      <h3>NPC members</h3>
      <div class="row">
        <input v-model="memberDraft" placeholder="subject" data-testid="member-input" @keyup.enter="addMember" />
        <button type="button" @click="addMember">Add</button>
        <button type="button" data-testid="members-select-all" :disabled="!status?.members?.length" @click="selectAllMembers">Select all listed</button>
      </div>
      <ul data-testid="member-list"><li v-for="m in members" :key="m">{{ m }}</li></ul>
      <div class="row">
        <button type="button" data-testid="npc-preview" :disabled="busy" @click="previewNpc">Preview NPC publication</button>
        <button type="button" data-testid="npc-publish" :disabled="busy" @click="publish">Publish previewed NPCs</button>
      </div>
      <div v-if="npcPreview" data-testid="npc-preview-detail">
        <p>Preview <code data-testid="npc-preview-sha">{{ npcPreview.sha }}</code> — nothing has been written. Publishing sends this digest for:</p>
        <ul><li v-for="m in npcPreview.detail.members" :key="m.slug">{{ m.subject }} <small>({{ m.slug }})</small></li></ul>
      </div>

      <h3>Grounding</h3>
      <div class="row">
        <button type="button" :disabled="busy" @click="preview">Preview</button>
        <label>Preview sha <input v-model="previewSha" data-testid="preview-sha" /></label>
        <button type="button" :disabled="busy" @click="apply">Apply</button>
      </div>
    </section>

    <section v-if="planId">
      <h2>6. Review and receipt</h2>
      <div class="row">
        <button type="button" @click="show('baseline', fetchBaseline)">Baseline</button>
        <button type="button" @click="show('review', fetchReview)">Review</button>
        <button type="button" @click="show('review handoff', reviewHandoff)">Review handoff</button>
        <button type="button" @click="show('receipt', fetchReceipt)">Receipt</button>
      </div>
      <div v-if="detail" data-testid="detail"><h3>{{ detail.title }}</h3><pre>{{ JSON.stringify(detail.body, null, 2) }}</pre></div>
    </section>
  </div>
</template>

<style scoped>
.delta-run { padding: 1rem; max-width: 60rem; }
section { margin-bottom: 1.5rem; }
.row { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; margin: 0.5rem 0; }
.banner { padding: 0.6rem 0.9rem; border-radius: 4px; margin-bottom: 1rem; border: 1px solid currentColor; }
.banner-stale, .banner-partial { color: #8a5a00; }
.banner-recovery_required, .banner-error { color: #a12; }
.stepper { padding-left: 1.2rem; }
.stage-complete .stage-status { color: #1a7f37; }
.stage-failed .stage-status { color: #a12; }
.artifacts { font-size: 0.85em; }
.chapters { list-style: none; padding: 0; max-height: 14rem; overflow: auto; }
.output { max-height: 16rem; overflow: auto; background: rgba(128, 128, 128, 0.12); padding: 0.5rem; }
.judgment { margin: 0.75rem 0; display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
.hint { opacity: 0.7; }
</style>
