<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useConfigStore } from '../stores/config'

type Num = number | ''

interface Member {
  path?: string
  destination?: string
  document_id?: string
  kind?: string
  sha256?: string | null
  size?: number
  target?: string
}

interface Change {
  path: string
  kind: string
  before_sha256?: string | null
  after_sha256?: string | null
  unified_diff?: string | null
}

// One entry of the engine's `preview.gates` (pipelines/summary_native/promotion/gates.py, preview.py).
// Rendering keys on `gate` ids and `code`s the engine emits, never on message text.
interface Gate {
  gate?: string
  state?: string
  code?: string | null
  message?: string
  relevant_digest?: string | null
}

interface Preview {
  eligible?: boolean
  preview_sha256?: string
  bundle_digest?: string
  live_digest?: string | null
  expected_generation_id?: string | null
  expected_activation_id?: string | null
  destination_edited_since_publication?: boolean | null
  report_analysis_digest?: string | null
  report_resolution_digest?: string | null
  signoff_context_digest?: string | null
  changes?: Change[]
  gates?: Gate[]
  refusal_codes?: string[]
}

interface BundleSelection {
  documents?: Member[]
  timeline?: Member
  references?: Member[]
  retained_records?: Member[]
  dependencies?: Member[]
  alias_identities?: Member[]
}

type Destination = Record<string, unknown> & { edited_since_publication?: boolean | null }

interface Envelope {
  ok: boolean
  code: string
  message: string
  detail?: unknown
  data?: { selection: BundleSelection | null; preview: Preview; destination: Destination | null }
}

// The route's (and the CLI's) request-id bound: 96 characters, this alphabet.
const REQUEST_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/
const SIGNOFF_GATE = 'document-signoffs'
const LAYOUT_GATE = 'managed-layout'
const CUSTODY_GATE = 'bundle-custody'

const props = defineProps<{ since?: number | null; until?: number | null; reviewId?: string; checkReportPath?: string }>()
const emit = defineEmits<{ reviewChanged:[value:string] }>()
const config = useConfigStore()
const since = ref<Num>(props.since ?? '')
const until = ref<Num>(props.until ?? '')
const review = ref(props.reviewId ?? '')
const checkReport = ref(props.checkReportPath ?? '')
// Empty = not sent: the CLI resolves grounding.yaml summary_native.out_root (or its declared default).
const outRoot = ref('')
const configuredOutRoot = computed(() => {
  const value = config.groundingConfig?.summary_native?.out_root
  return typeof value === 'string' ? value : ''
})
const busy = ref(false)
const feedback = ref('')
const error = ref('')
const preview = ref<Preview | null>(null)
const selection = ref<BundleSelection | null>(null)
const destination = ref<Destination | null>(null)
// The exact inputs the shown preview was computed from; commit sends these, never the live fields.
const previewedBody = ref<Record<string, unknown> | null>(null)
// Set when a commit attempt reports the preview no longer matches (the CLI's exit-3 stale class).
const previewStale = ref<{ code: string; message: string } | null>(null)
const requestId = ref('')
const operation = ref('')
const migrationPlan = ref('')
const inspection = ref<Record<string, unknown> | null>(null)
const inspectionCode = ref('')
const consentConsumed = ref(false)

const ready = computed(() => Number.isInteger(since.value) && Number.isInteger(until.value)
  && Number(since.value) <= Number(until.value) && review.value.trim() !== '' && checkReport.value.trim() !== '')
const requestIdValid = computed(() => REQUEST_ID_PATTERN.test(requestId.value.trim()))

const members = computed<Member[]>(() => {
  const manifest = selection.value
  if (!manifest) return []
  return [
    ...(manifest.documents ?? []).map(member => ({ ...member, kind: 'document' })),
    ...(manifest.timeline ? [{ ...manifest.timeline, kind: 'timeline' }] : []),
    ...(manifest.references ?? []).map(member => ({ ...member, kind: 'reference' })),
    ...(manifest.retained_records ?? []).map(member => ({ ...member, kind: 'retained record' })),
    ...(manifest.dependencies ?? []).map(member => ({ ...member, kind: 'dependency' })),
    ...(manifest.alias_identities ?? []).map(member => ({ ...member, destination: member.target, kind: `alias (${member.kind ?? 'link'})` })),
  ]
})
const changes = computed(() => preview.value?.changes ?? [])
const gates = computed(() => preview.value?.gates ?? [])
const blockers = computed(() => gates.value.filter(gate => gate.state !== 'passed'))

// Source approval = the four v2 document sign-offs. The engine's `document-signoffs` gate says
// whether they are absent (PROMOTION_SIGNOFF_REQUIRED) or bound to other bytes/context (…_STALE).
const signoffGate = computed(() => gates.value.find(gate => gate.gate === SIGNOFF_GATE) ?? null)
const signoffState = computed(() => {
  const gate = signoffGate.value
  if (!gate) return 'Unknown'
  if (gate.state === 'passed') return 'Current'
  if (gate.code === 'PROMOTION_SIGNOFF_REQUIRED') return 'Missing'
  if (gate.code === 'PROMOTION_SIGNOFF_STALE') return 'Stale'
  return 'Invalid'
})
// Draft custody = the per-document `document-<id>` gates plus any `bundle-custody` refusal.
const custodyGates = computed(() => gates.value.filter(gate =>
  gate.gate === CUSTODY_GATE || ((gate.gate ?? '').startsWith('document-') && gate.gate !== SIGNOFF_GATE)))
const custodyState = computed(() => {
  if (!custodyGates.value.length) return 'Unknown'
  if (custodyGates.value.every(gate => gate.state === 'passed')) return 'Current'
  if (custodyGates.value.some(gate => gate.code === 'PROMOTION_DEPENDENCY_STALE')) return 'Changed since enumeration'
  return 'Invalid'
})
const custodyProblems = computed(() => custodyGates.value.filter(gate => gate.state !== 'passed'))

// Destination = the live bundle the preview was diffed against (`data.destination` + preview identity).
const layoutGate = computed(() => gates.value.find(gate => gate.gate === LAYOUT_GATE) ?? null)
const liveDigest = computed(() => str(destination.value?.live_digest) || preview.value?.live_digest || '')
const editedLive = computed<boolean | null>(() => {
  const value = destination.value?.edited_since_publication ?? preview.value?.destination_edited_since_publication
  return typeof value === 'boolean' ? value : null
})
const destinationState = computed(() => {
  const layout = layoutGate.value
  if (layout && layout.state !== 'passed') return 'Migration required'
  if (!liveDigest.value) return layout?.state === 'passed' ? 'Absent baseline (first publication)' : 'Unknown'
  if (editedLive.value === true) return 'Hand-edited since last publication'
  if (editedLive.value === false) return 'Matches last publication'
  return 'Unknown'
})
// Every scalar the engine returns about the destination, so richer receipt fields show without a code change.
const destinationFacts = computed(() => {
  const facts: [string, string][] = []
  for (const [key, value] of Object.entries(destination.value ?? {})) {
    if (key === 'edited_since_publication') continue
    if (typeof value === 'string' || typeof value === 'number') facts.push([key, String(value)])
  }
  const expectedActivation = preview.value?.expected_activation_id
  if (expectedActivation && !facts.some(([key]) => key === 'expected_activation_id')) facts.push(['expected_activation_id', expectedActivation])
  return facts
})
const previewFreshness = computed(() => previewStale.value ? 'Stale' : 'Current')
const claims = computed(() => gates.value.find(item => item.gate === 'claims') ?? null)
const operationOutcome = computed(() => {
  const data:any = inspection.value ?? {}
  const raw = data.state ?? data.status ?? data.outcome ?? inspectionCode.value
  return typeof raw === 'string' && raw ? raw.replaceAll('_','-').toLowerCase() : ''
})
const priorIdentity = computed(() => {
  const data:any=inspection.value??{}
  return data.prior_identity ?? data.before_sha256 ?? data.activation?.prior_generation_id ?? data.receipt?.prior_generation_id ?? ''
})
const newIdentity = computed(() => {
  const data:any=inspection.value??{}
  return data.new_identity ?? data.after_sha256 ?? data.activation?.generation_id ?? data.receipt?.generation_id ?? data.activation?.activation_id ?? ''
})

function str(value: unknown) { return typeof value === 'string' ? value : '' }

function clearPreview() {
  preview.value = null
  selection.value = null
  destination.value = null
  previewedBody.value = null
  previewStale.value = null
  consentConsumed.value = false
}

watch(() => props.since, value => { if (typeof value === 'number') since.value = value })
watch(() => props.until, value => { if (typeof value === 'number') until.value = value })
watch(() => props.reviewId, value => { if (value !== undefined && value !== review.value) review.value = value })
watch(() => props.checkReportPath, value => { if (value !== undefined) checkReport.value = value })
// A preview is consent for exactly the inputs it was computed from. Any change drops it, so
// Publish can never send a digest for a range, review, report or out root nobody previewed.
watch([since, until, review, checkReport, outRoot], () => {
  if (!previewedBody.value && !preview.value) return
  clearPreview()
  error.value = ''
  feedback.value = 'Inputs changed after the preview, so it was cleared. Preview again before publishing.'
})

function requestBody() {
  const body: Record<string, unknown> = {
    since: Number(since.value), until: Number(until.value),
    review: review.value.trim(), check_report: checkReport.value.trim(),
  }
  if (outRoot.value.trim()) body.out_root = outRoot.value.trim()
  return body
}

function failureText(envelope: Envelope, status: number) {
  if (envelope.message) return `${envelope.code ? `${envelope.code}: ` : ''}${envelope.message}`
  if (typeof envelope.detail === 'string') return envelope.detail
  if (envelope.detail) return JSON.stringify(envelope.detail)
  return `Request failed (${status})`
}

async function runPreview() {
  if (!ready.value) return
  busy.value = true
  feedback.value = 'Requesting an exact read-only preview…'
  error.value = ''
  clearPreview()
  const body = requestBody()
  try {
    const response = await fetch('/api/grounding/summary-native/promotion/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const envelope = await response.json() as Envelope
    if (!envelope.data?.preview) throw new Error(failureText(envelope, response.status))
    selection.value = envelope.data.selection
    preview.value = envelope.data.preview
    destination.value = envelope.data.destination
    previewedBody.value = body
    feedback.value = envelope.message ?? (response.ok ? 'Preview refreshed.' : 'Preview returned blockers.')
    if (!response.ok || envelope.ok === false) error.value = failureText(envelope, response.status)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
    feedback.value = 'Preview request failed.'
  } finally {
    busy.value = false
  }
}

async function invoke(path: string, method = 'POST', body?: Record<string, unknown>) {
  busy.value = true
  error.value = ''
  feedback.value = 'Running installed campaign command…'
  try {
    const response = await fetch(`/api/grounding/summary-native/promotion/${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
    const envelope = await response.json()
    inspection.value = envelope.data ?? null
    inspectionCode.value = envelope.code ?? ''
    feedback.value = envelope.message ?? 'Command completed.'
    if (!response.ok || envelope.ok === false) error.value = `${envelope.code ?? 'COMMAND_FAILED'}: ${envelope.message ?? 'Command failed.'}`
    return envelope
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
    feedback.value = 'Command failed.'
    return null
  } finally {
    busy.value = false
  }
}

async function commit() {
  if (!preview.value?.eligible || !previewedBody.value || consentConsumed.value || !preview.value.preview_sha256 || !requestIdValid.value) return
  consentConsumed.value = true
  const envelope = await invoke('commit', 'POST', {
    ...previewedBody.value, preview_sha256: preview.value.preview_sha256,
    request_id: requestId.value.trim(),
  })
  // The CLI's exit-3 class: the preview, report, review or a dependency changed after it was shown.
  const code = typeof envelope?.code === 'string' ? envelope.code : ''
  if (code.includes('_STALE')) previewStale.value = { code, message: envelope?.message ?? '' }
  const id = envelope?.data?.operation_id ?? envelope?.data?.activation?.operation_id ?? envelope?.data?.receipt?.operation_id
  if (typeof id === 'string') operation.value = id
}

const operationBody = () => ({ operation: operation.value.trim() })

function label(member: Member) {
  return member.document_id ? `${member.kind} · ${member.document_id}` : member.kind ?? 'support'
}
</script>

<template>
  <section class="promotion" aria-labelledby="promotion-title" data-test="grounding-promotion-preview">
    <div class="heading">
      <div><h3 id="promotion-title">Whole-bundle promotion preview</h3>
        <p>Read-only preview of all four reviewed documents, the actual timeline, nested references, retained records, and live changes.</p>
      </div>
      <span class="checkpoint">human checkpoint</span>
    </div>

    <div class="inputs">
      <label>Since chapter <input v-model.number="since" type="number" min="0" data-test="promotion-since"></label>
      <label>Until chapter <input v-model.number="until" type="number" min="0" data-test="promotion-until"></label>
      <label>Review ID <input v-model="review" autocomplete="off" data-test="promotion-review" @input="emit('reviewChanged',review)"></label>
      <label>Check report ID or path <input v-model="checkReport" autocomplete="off" data-test="promotion-report"></label>
      <label>Out root <span class="optional">(optional)</span>
        <input v-model="outRoot" autocomplete="off" data-test="promotion-out-root" :placeholder="configuredOutRoot">
        <span class="hint">Empty uses grounding.yaml summary_native.out_root.</span></label>
    </div>
    <p v-if="!ready" class="hint">Choose an explicit ordered range, review, and check report before previewing.</p>
    <button class="btn-neutral" :disabled="busy || !ready" @click="runPreview">
      {{ busy ? 'Previewing…' : 'Preview complete bundle' }}
    </button>
    <span class="feedback" role="status" aria-live="polite">{{ feedback }}</span>
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <template v-if="preview">
      <div class="summary" :class="preview.eligible ? 'eligible' : 'blocked'">
        <strong>{{ preview.eligible ? 'Eligible preview' : 'Publication blocked' }}</strong>
        <span v-if="preview.preview_sha256">preview <code>{{ preview.preview_sha256 }}</code></span>
        <span v-if="preview.bundle_digest">bundle <code>{{ preview.bundle_digest }}</code></span>
        <span v-if="liveDigest">live <code>{{ liveDigest }}</code></span>
      </div>

      <div class="claims" :class="claims?.state === 'passed' ? 'eligible' : 'blocked'" data-test="promotion-claims">
        <strong>Claims gate: {{ claims?.state ?? 'not_available' }}</strong>
        <code v-if="claims?.code">{{ claims.code }}</code>
        <span>{{ claims?.message || (claims ? '' : 'No claims result was returned. This is not a passing check.') }}</span>
        <span v-if="preview.report_analysis_digest">report basis <code>{{ preview.report_analysis_digest }}</code></span>
      </div>

      <div class="staleness">
        <div data-test="promotion-source-freshness"><strong>Source approval freshness: {{ signoffState }}</strong>
          <span v-if="signoffState === 'Missing'">The four document sign-offs have not been recorded for this review. Sign each document on Shared review.</span>
          <span v-else-if="signoffState === 'Stale'">A sign-off was recorded for different document bytes or check context. Sign the current drafts again.</span>
          <span v-if="signoffGate && signoffGate.state !== 'passed'"><code>{{ signoffGate.code }}</code> {{ signoffGate.message }}</span>
          <span>Draft custody: {{ custodyState }}</span>
          <span v-for="gate in custodyProblems" :key="`${gate.gate}:${gate.code}:${gate.message}`"><code>{{ gate.code }}</code> {{ gate.message }}</span></div>
        <div data-test="promotion-destination-freshness"><strong>Destination preview freshness: {{ previewFreshness }}</strong>
          <span v-if="previewStale"><code>{{ previewStale.code }}</code> {{ previewStale.message }} Refresh the preview; the old digest cannot be published.</span>
          <span v-else>Computed against the live bundle at preview time; publication rechecks it.</span>
          <span>Live destination: {{ destinationState }}</span>
          <span v-if="editedLive === true" class="blocked" data-test="promotion-live-edited">The live documents were edited by hand after they were published. Publishing replaces those edits; they are in the live differences below.</span>
          <span v-if="layoutGate && layoutGate.state !== 'passed'"><code>{{ layoutGate.code }}</code> {{ layoutGate.message }}</span>
          <span v-for="[key, value] in destinationFacts" :key="key">{{ key }} <code>{{ value }}</code></span></div>
      </div>

      <div v-if="blockers.length || preview.refusal_codes?.length" class="result-block">
        <h4>Blocking conditions</h4>
        <ul><li v-for="gate in blockers" :key="`${gate.gate}:${gate.code}:${gate.message}`"><code>{{ gate.code ?? gate.gate }}</code> {{ gate.message }}</li>
          <li v-for="code in preview.refusal_codes ?? []" :key="code"><code>{{ code }}</code></li></ul>
      </div>

      <div class="result-block"><h4>Complete manifest ({{ members.length }})</h4>
        <table v-if="members.length"><thead><tr><th>Class</th><th>Path</th><th>Destination</th><th>Identity</th></tr></thead>
          <tbody><tr v-for="member in members" :key="`${member.path}:${member.destination}`">
            <td>{{ label(member) }}</td><td><code>{{ member.path }}</code></td>
            <td><code>{{ member.destination ?? '—' }}</code></td><td><code>{{ member.sha256 ?? '—' }}</code><span v-if="member.size !== undefined"> · {{ member.size }} B</span></td>
          </tr></tbody></table><p v-else class="hint">The response contained no manifest members.</p>
      </div>

      <div class="result-block"><h4>Live differences ({{ changes.length }})</h4>
        <article v-for="change in changes" :key="change.path" class="change">
          <div><strong>{{ change.kind }}</strong> <code>{{ change.path }}</code></div>
          <div class="digests"><code>{{ change.before_sha256 ?? 'absent' }}</code> → <code>{{ change.after_sha256 ?? 'absent' }}</code></div>
          <pre v-if="change.unified_diff">{{ change.unified_diff }}</pre>
        </article><p v-if="!changes.length" class="hint">No path changes were returned.</p>
      </div>

      <div class="actions">
        <label>Request ID <input v-model="requestId" autocomplete="off" maxlength="96" data-test="promotion-request-id"></label>
        <button class="btn-primary" data-test="promotion-commit" :disabled="busy || consentConsumed || !preview.eligible || !previewedBody || !requestIdValid" @click="commit">Publish exact preview</button>
        <p v-if="requestId.trim() && !requestIdValid" class="error">A request ID is 1–96 characters: letters, digits, dot, underscore or hyphen, starting with a letter or digit.</p>
        <p v-if="consentConsumed" class="hint">This preview consent was consumed by the commit attempt. Refresh the preview before another publication attempt.</p>
      </div>
    </template>

    <div class="result-block controls" data-test="promotion-operations">
      <h4>Publication status, receipts, and recovery</h4>
      <label>Operation ID <input v-model="operation" autocomplete="off" data-test="promotion-operation"></label>
      <div class="button-row">
        <button :disabled="busy" @click="invoke(`status${operation.trim() ? `?operation=${encodeURIComponent(operation.trim())}` : ''}`, 'GET')">Refresh status</button>
        <button :disabled="busy || !operation.trim()" @click="invoke('receipt', 'POST', operationBody())">View receipt</button>
        <button :disabled="busy || !operation.trim()" @click="invoke('recover', 'POST', operationBody())">Recover publication</button>
      </div>
      <h4>Managed bundle migration</h4>
      <label>Plan digest <input v-model="migrationPlan" autocomplete="off" data-test="migration-plan"></label>
      <div class="button-row">
        <button :disabled="busy" @click="invoke('migration/preview')">Preview migration</button>
        <button :disabled="busy || !/^[0-9a-f]{64}$/.test(migrationPlan)" @click="invoke('migration/apply', 'POST', { plan_sha256: migrationPlan })">Apply exact plan</button>
        <button :disabled="busy" @click="invoke('migration/status', 'GET')">Migration status</button>
        <button :disabled="busy" @click="invoke('migration/verify')">Verify migration</button>
        <button :disabled="busy || !operation.trim()" @click="invoke('migration/recover', 'POST', operationBody())">Recover migration</button>
      </div>
      <pre v-if="inspection" data-test="promotion-inspection">{{ JSON.stringify(inspection, null, 2) }}</pre>
      <div v-if="operationOutcome" class="operation-feedback" data-test="promotion-outcome">
        <strong>Current outcome: {{ operationOutcome }}</strong>
        <span v-if="priorIdentity">Prior identity <code>{{ priorIdentity }}</code></span>
        <span v-if="newIdentity">New identity <code>{{ newIdentity }}</code></span>
        <span v-if="operationOutcome.includes('unknown')">The commit result is unknown. Refresh status with this operation ID, then use recovery if the journal remains pending.</span>
        <span v-else-if="operationOutcome.includes('stale')">Live files changed after preparation. Inspect the new destination, then create and approve a new preview.</span>
        <span v-else-if="operationOutcome.includes('blocked')">The operation remains blocked. Resolve the displayed gate and create a new preview.</span>
        <span v-else-if="operationOutcome.includes('committed')">The exact preview was committed. Inspect its receipt for the durable identities.</span>
        <span v-else-if="operationOutcome.includes('saved') || operationOutcome.includes('prepared')">The operation is durable but has not completed publication.</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.promotion{min-width:0;max-width:100%;box-sizing:border-box;padding:14px;border:1px solid var(--bg-surface1);border-radius:6px;background:var(--bg-mantle);font-size:11px;color:var(--text-sub);overflow-wrap:anywhere}
.heading{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px 16px}.heading h3{margin:0;color:var(--text);font-size:12px;font-weight:700}.heading p{margin:4px 0 10px;color:var(--text-muted)}
.optional{font-weight:400;color:var(--text-muted)}.inputs .hint{display:block;margin-top:2px;font-weight:400}
.checkpoint{height:max-content;padding:3px 7px;border-radius:10px;background:var(--yellow);color:var(--bg-base);font-weight:700}.inputs{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(160px,100%),1fr));gap:10px}.inputs label{min-width:0;font-weight:600;color:var(--text-sub)}
input{display:block;width:100%;box-sizing:border-box;margin-top:3px;padding:6px 8px;border:1px solid var(--bg-surface1);border-radius:4px;background:var(--bg-base);color:var(--text);font:11px var(--mono)}
button{margin-top:9px;font-size:11px}button:not([class]){background:var(--bg-surface0);color:var(--text)}.feedback{margin-left:10px;color:var(--text-muted)}.hint{color:var(--text-muted)}.error,.blocked{color:var(--red)}.eligible{color:var(--green)}
.summary,.claims{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;padding:8px;background:var(--bg-base);border-radius:4px}.summary code{overflow-wrap:anywhere}.staleness{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:10px;margin-top:10px}.staleness>div{min-width:0;display:flex;flex-direction:column;gap:3px;padding:8px;background:var(--bg-base);border-radius:4px}.staleness strong,h4{color:var(--text)}
.result-block{min-width:0;margin-top:14px;overflow:hidden}.result-block h4{margin:0 0 6px}.result-block ul{margin:0;padding-left:18px}.result-block code{font:10px var(--mono);overflow-wrap:anywhere}table{display:block;width:100%;max-width:100%;overflow-x:auto;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:5px 8px 5px 0;border-bottom:1px solid var(--bg-surface0)}th{color:var(--text)}
.change{padding:8px 0;border-bottom:1px solid var(--bg-surface0)}.change strong{text-transform:uppercase}.digests{margin-top:4px;color:var(--text-muted);overflow-wrap:anywhere}.change pre{max-height:18rem;overflow:auto;white-space:pre-wrap;padding:8px;background:var(--bg-base);color:var(--text-sub);font:10px var(--mono)}
.actions,.button-row{display:flex;flex-wrap:wrap;align-items:end;gap:8px;margin-top:10px}.actions label,.controls label{min-width:min(280px,100%)}.controls h4:not(:first-child){margin-top:14px}.controls pre{max-height:20rem;overflow:auto;padding:8px;background:var(--bg-base);font:10px var(--mono);white-space:pre-wrap}
.operation-feedback{display:flex;min-width:0;flex-direction:column;gap:4px;margin-top:10px;padding:8px;background:var(--bg-base)}.operation-feedback code{overflow-wrap:anywhere}
</style>
