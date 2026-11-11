<script setup lang="ts">
/**
 * Source-custody rebase (spec 040, contracts/http.md "UI").
 *
 * A view over files the CLI also writes (Principle IX): the stale list comes from
 * `GET /rebase/inspect`, the review from `GET /rebase/{id}`, and both are re-read after every
 * action. Nothing about a selection, repair or decision is kept in browser storage.
 *
 * Principle X: sources are an explicit list; "Prepare" is disabled until at least one stale source
 * is ticked, and nothing is preselected. Decisions are radios with no preselection, and a decision
 * needs a named reviewer.
 */
import { ref, computed } from 'vue'
import { apiFetch, apiPost } from '../../api/client'
import { DELTA_BASE, streamStage } from '../../api/delta'

interface Provider { provider: string; available: boolean; detail: string }
interface StaleEntry {
  chapter: number; path: string; expected_sha256: string; actual_sha256: string
  pinned_by: string; old_bytes: Provider[]
}
interface Inspect { stale: StaleEntry[]; generation_ref?: string; checked?: number }
interface AffectedLine {
  line_id: string; document: string; line_no: number; citation: string; chapter: number
  entry: string; reason: string; origin: string; state?: string
}
interface SourceDiff { chapter: number; path: string; diff?: string; old_bytes_provider?: string }
interface Show {
  rebase_id?: string; plan_id: string; sources: SourceDiff[]; affected_lines: AffectedLine[]
  unknown_members: { member: string; reason: string; ruling?: unknown }[]
  followup_consumers: { path: string; chapters: number[] }[]
  decisions: unknown[]
}

const SOURCE_DECISIONS = ['adopt-unaffected', 'adopt-with-repairs', 'reject'] as const
const MEMBER_DECISIONS = ['repaired', 'held', 'attested-unaffected'] as const

const rebasePlan = ref('')
const forPlan = ref('')
const inspect = ref<Inspect | null>(null)
const selected = ref<string[]>([])
const oldBytes = ref<Record<string, string>>({})
const show = ref<Show | null>(null)
const output = ref<string[]>([])
const detail = ref<unknown>(null)
const error = ref('')
const busy = ref(false)

const reviewer = ref('')
const reason = ref('')
const sourceDecisions = ref<Record<string, string>>({})
const memberDecisions = ref<Record<string, string>>({})
const repair = ref({ line: '', text: '', reason: '' })
const holdEntry = ref({ entry: '', reason: '' })
const rebindBaseline = ref('')

const unwrap = (r: any) => (r && typeof r === 'object' && 'data' in r ? r.data : r)
const base = `${DELTA_BASE}/rebase`
const planPath = () => `${base}/${encodeURIComponent(rebasePlan.value.trim())}`
const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

async function guard(fn: () => Promise<unknown>) {
  error.value = ''
  busy.value = true
  try { return await fn() } catch (e) { error.value = msg(e) } finally { busy.value = false }
}

const canPrepare = computed(() => selected.value.length > 0 && !busy.value)
const canDecide = computed(() =>
  !!reviewer.value.trim() && !busy.value &&
  (Object.keys(sourceDecisions.value).length + Object.keys(memberDecisions.value).length) > 0)

async function runInspect() {
  await guard(async () => {
    selected.value = []
    const q = forPlan.value.trim() ? `?plan=${encodeURIComponent(forPlan.value.trim())}` : ''
    inspect.value = unwrap(await apiFetch(`${base}/inspect${q}`)) as Inspect
  })
}

async function prepare() {
  if (!selected.value.length) {
    error.value = 'no sources selected; a rebase does not default to every stale chapter.'
    return
  }
  await guard(async () => {
    const body: Record<string, unknown> = { sources: [...selected.value] }
    const ob: Record<string, string> = {}
    for (const e of inspect.value?.stale ?? []) {
      const p = oldBytes.value[String(e.chapter)]?.trim()
      if (p && selected.value.includes(e.path)) ob[String(e.chapter)] = p
    }
    if (Object.keys(ob).length) body.old_bytes = ob
    if (forPlan.value.trim()) body.for_plan = forPlan.value.trim()
    const r = unwrap(await apiPost(base, body)) as { plan_id?: string }
    rebasePlan.value = r.plan_id ?? rebasePlan.value
    await loadShow()
  })
}

async function loadShow() {
  if (!rebasePlan.value.trim()) { show.value = null; return }
  show.value = unwrap(await apiFetch(planPath())) as Show
}

async function reload() { await guard(loadShow) }

async function propose() {
  await guard(async () => {
    output.value = []
    const r = await streamStage(`/rebase/${encodeURIComponent(rebasePlan.value.trim())}/propose`, {},
      l => output.value.push(l))
    output.value.push(`exit ${r.exitCode}`)
    await loadShow()
  })
}

function needReviewer(): boolean {
  if (!reviewer.value.trim()) {
    error.value = 'enter a reviewer name first; a decision is recorded against a named reviewer.'
    return false
  }
  return true
}

async function submitRepair() {
  if (!needReviewer()) return
  const r = repair.value
  if (!r.line.trim() || !r.text.trim() || !r.reason.trim()) {
    error.value = 'a repair needs a line id, the replacement text and a reason.'
    return
  }
  await guard(async () => {
    detail.value = await apiPost(`${planPath()}/repairs`,
      { line: r.line.trim(), text: r.text, reason: r.reason.trim(), reviewer: reviewer.value.trim() })
    await loadShow()
  })
}

async function submitHold() {
  if (!needReviewer()) return
  const h = holdEntry.value
  if (!h.entry.trim() || !h.reason.trim()) {
    error.value = 'a bulk hold needs an entry (CH/ENTRY) and a reason.'
    return
  }
  await guard(async () => {
    detail.value = await apiPost(`${planPath()}/repairs`,
      { hold_entry: h.entry.trim(), reason: h.reason.trim(), reviewer: reviewer.value.trim() })
    await loadShow()
  })
}

async function submitDecisions() {
  if (!needReviewer()) return
  await guard(async () => {
    const body: Record<string, unknown> = {
      reviewer: reviewer.value.trim(),
      source_decisions: { ...sourceDecisions.value },
      member_decisions: { ...memberDecisions.value },
    }
    if (reason.value.trim()) body.reason = reason.value.trim()
    detail.value = await apiPost(`${planPath()}/decisions`, body)
    await loadShow()
  })
}

async function rebind() {
  if (!forPlan.value.trim()) { error.value = 'enter the pending plan id to rebind.'; return }
  if (!rebindBaseline.value.trim()) { error.value = 'enter the rebase generation id to rebind onto.'; return }
  await guard(async () => {
    const body: Record<string, unknown> = { baseline: rebindBaseline.value.trim() }
    detail.value = await apiPost(`${DELTA_BASE}/plans/${encodeURIComponent(forPlan.value.trim())}/rebind`, body)
  })
}
</script>

<template>
  <div class="source-rebase">
    <h1>Source-custody rebase</h1>
    <div v-if="error" class="banner" data-testid="error" role="alert">{{ error }}</div>

    <section>
      <h2>1. Inspect</h2>
      <label>Pending plan (optional) <input v-model="forPlan" data-testid="for-plan" /></label>
      <button type="button" data-testid="inspect" :disabled="busy" @click="runInspect">Inspect stale sources</button>
      <p v-if="inspect && !inspect.stale.length" data-testid="none-stale">No stale sources.</p>
      <table v-if="inspect?.stale.length" data-testid="stale-table">
        <thead><tr><th /><th>Ch</th><th>Path</th><th>Expected</th><th>Actual</th><th>Old bytes</th><th>Old-bytes file</th></tr></thead>
        <tbody>
          <tr v-for="e in inspect.stale" :key="e.path">
            <td><input v-model="selected" type="checkbox" :value="e.path" data-testid="stale-source" /></td>
            <td>{{ e.chapter }}</td>
            <td><code>{{ e.path }}</code></td>
            <td><small>{{ e.expected_sha256 }}</small></td>
            <td><small>{{ e.actual_sha256 }}</small></td>
            <td><span v-for="p in e.old_bytes" :key="p.provider" :class="p.available ? 'ok' : 'no'" :title="p.detail">{{ p.provider }}{{ p.available ? '' : ' (n/a)' }} </span></td>
            <td><input v-model="oldBytes[String(e.chapter)]" placeholder="optional path" /></td>
          </tr>
        </tbody>
      </table>
      <button type="button" data-testid="prepare" :disabled="!canPrepare" @click="prepare">Prepare rebase</button>
      <p v-if="!selected.length" class="hint">Tick at least one stale source. A rebase never defaults to every stale chapter.</p>
    </section>

    <section>
      <h2>2. Review</h2>
      <label>Rebase plan id <input v-model="rebasePlan" data-testid="rebase-plan" @change="reload" /></label>
      <button type="button" :disabled="busy" @click="reload">Load</button>
      <button type="button" data-testid="propose" :disabled="busy || !rebasePlan.trim()" @click="propose">Propose repairs</button>
      <pre v-if="output.length" class="output" data-testid="output">{{ output.join('\n') }}</pre>

      <template v-if="show">
        <div v-for="s in show.sources" :key="s.chapter" class="source" data-testid="source-diff">
          <h3>Chapter {{ s.chapter }} — <code>{{ s.path }}</code></h3>
          <pre class="diff">{{ s.diff || '(no diff)' }}</pre>
        </div>
        <h3>Affected lines ({{ show.affected_lines.length }})</h3>
        <ul data-testid="affected-lines">
          <li v-for="l in show.affected_lines" :key="l.line_id">
            <code>{{ l.line_id }}</code> {{ l.document }}:{{ l.line_no }} {{ l.citation }}
            <small>({{ l.reason }}, {{ l.origin }})</small> <strong>{{ l.state }}</strong>
          </li>
        </ul>
        <h3>Unknown-impact members ({{ show.unknown_members.length }})</h3>
        <ul data-testid="unknown-members">
          <li v-for="m in show.unknown_members" :key="m.member">{{ m.member }} <small>({{ m.reason }})</small></li>
        </ul>
        <p v-if="show.followup_consumers.length" data-testid="followups">
          Follow-ups, not changed by a rebase: <code v-for="f in show.followup_consumers" :key="f.path">{{ f.path }} </code>
        </p>
      </template>

      <form class="row" data-testid="repair-form" @submit.prevent="submitRepair">
        <h3>Repair a line</h3>
        <label>Line id <input v-model="repair.line" data-testid="repair-line" /></label>
        <label>Text <input v-model="repair.text" data-testid="repair-text" /></label>
        <label>Reason <input v-model="repair.reason" data-testid="repair-reason" /></label>
        <button type="submit" :disabled="busy || !rebasePlan.trim()">Record repair</button>
      </form>
      <form class="row" data-testid="hold-form" @submit.prevent="submitHold">
        <h3>Hold every line citing an entry</h3>
        <label>Entry (CH/ENTRY) <input v-model="holdEntry.entry" data-testid="hold-entry" placeholder="3/003.01" /></label>
        <label>Reason <input v-model="holdEntry.reason" data-testid="hold-reason" /></label>
        <button type="submit" :disabled="busy || !rebasePlan.trim()">Hold entry</button>
      </form>
    </section>

    <section>
      <h2>3. Decide</h2>
      <label>Reviewer <input v-model="reviewer" data-testid="reviewer" placeholder="who is deciding" /></label>
      <div v-for="s in show?.sources ?? []" :key="s.chapter" class="row" data-testid="source-decision">
        <span>Chapter {{ s.chapter }}</span>
        <label v-for="d in SOURCE_DECISIONS" :key="d">
          <input v-model="sourceDecisions[String(s.chapter)]" type="radio" :name="`src-${s.chapter}`" :value="d" :data-testid="`src-${s.chapter}-${d}`" /> {{ d }}
        </label>
      </div>
      <div v-for="m in show?.unknown_members ?? []" :key="m.member" class="row" data-testid="member-decision">
        <span>{{ m.member }}</span>
        <label v-for="d in MEMBER_DECISIONS" :key="d">
          <input v-model="memberDecisions[m.member]" type="radio" :name="`mem-${m.member}`" :value="d" :data-testid="`mem-${m.member}-${d}`" /> {{ d }}
        </label>
      </div>
      <label>Reason (required for reject and attested-unaffected) <input v-model="reason" data-testid="decision-reason" /></label>
      <button type="button" data-testid="decide" :disabled="!canDecide" @click="submitDecisions">Record decisions</button>
      <p v-if="!reviewer.trim()" class="hint">A reviewer name is required.</p>
    </section>

    <section v-if="rebasePlan.trim()">
      <h2>4. Publish and rebind</h2>
      <p>Rebase plan <code data-testid="rebase-plan-id">{{ rebasePlan.trim() }}</code> publishes through the existing grounding gates
        (check, preview, apply) on the
        <router-link :to="{ name: 'grounding-delta', query: { plan: rebasePlan.trim() } }" data-testid="delta-link">incremental update page</router-link>
        (the plan id is filled in for you).</p>
      <div class="row">
        <label>Rebase generation (required) <input v-model="rebindBaseline" data-testid="rebind-baseline" /></label>
        <button type="button" data-testid="rebind" :disabled="busy || !forPlan.trim() || !rebindBaseline.trim()" @click="rebind">Rebind pending plan</button>
      </div>
      <p v-if="!forPlan.trim()" class="hint">Rebind needs the pending plan id (step 1).</p>
      <p v-else>Then finish the pending plan on the
        <router-link :to="{ name: 'grounding-delta', query: { plan: forPlan.trim() } }" data-testid="pending-link">incremental update page</router-link>.</p>
    </section>

    <pre v-if="detail" data-testid="detail">{{ JSON.stringify(detail, null, 2) }}</pre>
  </div>
</template>

<style scoped>
.source-rebase { padding: 1rem; max-width: 70rem; }
section { margin-bottom: 1.5rem; }
.row { display: flex; gap: 0.75rem; flex-wrap: wrap; align-items: center; margin: 0.5rem 0; }
.banner { padding: 0.6rem 0.9rem; border: 1px solid currentColor; color: #a12; margin-bottom: 1rem; }
.diff, .output { max-height: 18rem; overflow: auto; background: rgba(128, 128, 128, 0.12); padding: 0.5rem; }
table { border-collapse: collapse; }
td, th { padding: 0.2rem 0.5rem; text-align: left; }
.no { opacity: 0.6; }
.hint { opacity: 0.7; }
</style>
